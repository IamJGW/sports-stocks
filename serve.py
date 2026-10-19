#!/usr/bin/env python3
"""Runs Sports Stocks on this computer.

    python3 serve.py                  # open http://localhost:8660 on this Mac
    python3 serve.py --phone          # also lets a phone on the same Wi-Fi open it
    python3 serve.py --save PATH      # use another save file (a copy, to try things without touching the real one)

Press Ctrl+C to stop. The screens only ask questions and place orders; every price and every cent is worked out in
engine/ (Python), never in the web page.
"""
import argparse
import json
import os
import socket
import sys
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, unquote, urlparse

ROOT = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ROOT)
from engine import api, ledger as L  # noqa: E402

PORT = 8660
WEB = os.path.join(ROOT, "web")
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript", ".css": "text/css", ".svg": "image/svg+xml"}


def make_handler(save_path, clock=lambda: datetime.now(timezone.utc)):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, fmt, *args):
            if "404" in (fmt % args) or "500" in (fmt % args):
                super().log_message(fmt, *args)

        def send(self, code, body, ctype):
            data = body if isinstance(body, bytes) else body.encode()
            self.send_response(code)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def json(self, obj, code=200):
            self.send(code, json.dumps(obj), "application/json")

        def conn(self):
            return L.connect(save_path)  # one connection per request

        def do_GET(self):
            url = urlparse(self.path)
            path, qs = url.path, {k: v[0] for k, v in parse_qs(url.query).items()}
            if path.startswith("/api/"):
                return self.api_get(path[5:], qs)
            name = "index.html" if path == "/" else unquote(path).lstrip("/")
            full = os.path.realpath(os.path.join(WEB, name))
            if not full.startswith(WEB + os.sep) or not os.path.isfile(full):
                return self.send(404, "Not found", "text/plain")
            with open(full, "rb") as f:
                self.send(200, f.read(), TYPES.get(os.path.splitext(full)[1], "application/octet-stream"))

        def api_get(self, route, qs):
            conn = self.conn()
            try:
                now = clock()
                if route == "status":
                    return self.json(api.status(conn, now))
                if route == "market":
                    return self.json(api.market(conn, now))
                if route == "athlete":
                    return self.json(api.athlete_page(conn, qs.get("ticker", ""), now))
                if route == "quote":
                    try:
                        shares = int(qs.get("shares", ""))
                    except ValueError:
                        return self.json({"ok": False, "message": "Choose a whole number of shares, at least 1."})
                    return self.json(api.quote(conn, qs.get("ticker", ""), qs.get("side", ""), shares, now))
                if route == "portfolio":
                    return self.json(api.portfolio(conn, now))
                if route == "report":
                    return self.json(api.latest_report(conn))
                return self.json({"ok": False, "message": "Unknown request."}, 404)
            except L.TradeRefused as e:
                return self.json({"ok": False, "message": str(e)}, 404)
            finally:
                conn.close()

        def do_POST(self):
            if urlparse(self.path).path != "/api/trade":
                return self.json({"ok": False, "message": "Unknown request."}, 404)
            try:
                body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
                shares = int(body["shares"])
                expect = body.get("expect_cents")
                expect = None if expect is None else int(expect)
            except (ValueError, KeyError, TypeError):
                return self.json({"ok": False, "message": "That order wasn't understood."}, 400)
            conn = self.conn()
            try:
                return self.json(api.place_trade(conn, str(body.get("ticker", "")), body.get("side"), shares, expect,
                                                 clock()))
            finally:
                conn.close()

    return Handler


def lan_address():
    # Asks the computer which address it would use to reach the internet. Nothing is sent.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("192.168.0.1", 80))
            return s.getsockname()[0]
    except OSError:
        return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phone", action="store_true")
    ap.add_argument("--save", default=os.path.join(ROOT, "save", "game.sqlite"))
    args = ap.parse_args()
    if not os.path.exists(args.save):
        sys.exit("No game yet. Start one with: python3 tools/new_game.py")
    host = "0.0.0.0" if args.phone else "127.0.0.1"
    with ThreadingHTTPServer((host, PORT), make_handler(args.save)) as server:
        print(f"Sports Stocks is running at http://localhost:{PORT}  (Ctrl+C to stop)")
        if args.save != os.path.join(ROOT, "save", "game.sqlite"):
            print(f"Using {args.save}")
        if args.phone:
            ip = lan_address()
            if ip:
                print(f"On a phone on the same Wi-Fi, open http://{ip}:{PORT}")
            print("If your Mac asks whether Python may accept incoming connections, choose Allow.")
        server.serve_forever()


if __name__ == "__main__":
    main()
