"""Driving real Chrome from Python's standard library, so the browser flows need nothing installed.

Chrome runs on its own throwaway or named profile, never the everyday one, and is talked to over its debugging socket.
Clicks and taps are real input events at the button's position, so a button hidden behind something fails instead of
passing the way an element.click() would.
"""
import base64
import json
import os
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import threading
import time

CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"
IPHONE_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_5 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) "
             "Version/18.5 Mobile/15E148 Safari/604.1")
VIEWPORTS = {
    "desktop": {"width": 1280, "height": 800, "scale": 1, "mobile": False},
    "iphone": {"width": 390, "height": 844, "scale": 3, "mobile": True},
}


class Failed(Exception):
    """A browser step didn't do what the flow expected."""


class _Socket:
    """Just enough WebSocket for Chrome's debugging port: text frames, pings, closing."""

    def __init__(self, port, path):
        self.s = socket.create_connection(("127.0.0.1", port))
        key = base64.b64encode(secrets.token_bytes(16)).decode()
        self.s.sendall((f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
                        f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        head = b""
        while b"\r\n\r\n" not in head:
            head += self.s.recv(1)
        if b" 101 " not in head.split(b"\r\n")[0]:
            raise Failed(f"Chrome refused the socket: {head[:80]!r}")
        self.lock = threading.Lock()

    def _exact(self, n):
        out = b""
        while len(out) < n:
            got = self.s.recv(n - len(out))
            if not got:
                raise ConnectionError("closed")
            out += got
        return out

    def _frame(self, opcode, data):
        mask = secrets.token_bytes(4)
        n = len(data)
        head = bytes([0x80 | opcode])
        if n < 126:
            head += bytes([0x80 | n])
        elif n < 65536:
            head += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            head += bytes([0x80 | 127]) + struct.pack(">Q", n)
        body = bytes(b ^ mask[i % 4] for i, b in enumerate(data))
        with self.lock:
            self.s.sendall(head + mask + body)

    def send(self, text):
        self._frame(1, text.encode())

    def recv(self):
        parts = []
        while True:
            b0, b1 = self._exact(2)
            n = b1 & 0x7f
            if n == 126:
                n = struct.unpack(">H", self._exact(2))[0]
            elif n == 127:
                n = struct.unpack(">Q", self._exact(8))[0]
            data = self._exact(n)
            opcode = b0 & 0x0f
            if opcode == 8:
                raise ConnectionError("closed")
            if opcode == 9:
                self._frame(10, data)
                continue
            if opcode in (0, 1):
                parts.append(data)
                if b0 & 0x80:
                    return b"".join(parts).decode()


class Chrome:
    def __init__(self, headless=True, profile=None):
        self.temp = None if profile else tempfile.mkdtemp(prefix="sports-stocks-chrome-")
        self.profile = profile or self.temp
        os.makedirs(self.profile, exist_ok=True)
        port_file = os.path.join(self.profile, "DevToolsActivePort")
        if os.path.exists(port_file):
            os.remove(port_file)
        args = [CHROME, f"--user-data-dir={self.profile}", "--remote-debugging-port=0", "--no-first-run",
                "--no-default-browser-check", "--disable-extensions", "--disable-sync", "--window-size=1280,900",
                "--disable-features=PasswordManagerOnboarding,AutofillServerCommunication", "about:blank"]
        if headless:
            args.insert(1, "--headless=new")
        self.proc = subprocess.Popen(args, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        for _ in range(200):
            if os.path.exists(port_file) and os.path.getsize(port_file) > 0:
                break
            time.sleep(0.05)
        else:
            raise Failed("Chrome didn't open its debugging port.")
        port, path = open(port_file).read().split()[:2]
        self.ws = _Socket(int(port), path)
        self.next_id = 0
        self.pending = {}
        self.tabs = {}
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                m = json.loads(self.ws.recv())
                if "id" in m:
                    box = self.pending.pop(m["id"], None)
                    if box:
                        box["reply"] = m
                        box["done"].set()
                elif m.get("sessionId") in self.tabs:
                    self.tabs[m["sessionId"]]._event(m["method"], m.get("params", {}))
        except (ConnectionError, OSError):
            for box in list(self.pending.values()):
                box["done"].set()

    def send(self, method, params=None, session=None, timeout=60):
        self.next_id += 1
        box = {"done": threading.Event(), "reply": None}
        self.pending[self.next_id] = box
        m = {"id": self.next_id, "method": method, "params": params or {}}
        if session:
            m["sessionId"] = session
        self.ws.send(json.dumps(m))
        if not box["done"].wait(timeout) or box["reply"] is None:
            raise Failed(f"Chrome didn't answer {method}.")
        if "error" in box["reply"]:
            raise Failed(f"{method}: {box['reply']['error'].get('message')}")
        return box["reply"].get("result", {})

    def tab(self, viewport):
        target = self.send("Target.createTarget", {"url": "about:blank"})["targetId"]
        session = self.send("Target.attachToTarget", {"targetId": target, "flatten": True})["sessionId"]
        t = Tab(self, session, viewport)
        self.tabs[session] = t
        t.setup()
        return t

    def close(self):
        try:
            self.send("Browser.close", timeout=5)
        except (Failed, OSError):
            pass
        try:
            self.proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            self.proc.kill()
        if self.temp:
            shutil.rmtree(self.temp, ignore_errors=True)


class Tab:
    def __init__(self, chrome, session, viewport):
        self.chrome, self.session, self.name = chrome, session, viewport
        self.vp = VIEWPORTS[viewport]
        self.problems = []   # page errors and failed requests since the last take_problems()
        self.requests = []   # (url, status, mime type)
        self.allowed = []    # text that marks a problem as expected
        self.scripts = []    # scripts run before each page, added by before_page()

    def send(self, method, params=None, timeout=60):
        return self.chrome.send(method, params, self.session, timeout)

    def setup(self):
        for domain in ("Page", "Runtime", "Network", "Log"):
            self.send(f"{domain}.enable")
        v = self.vp
        self.send("Emulation.setDeviceMetricsOverride", {"width": v["width"], "height": v["height"],
                                                         "deviceScaleFactor": v["scale"], "mobile": v["mobile"]})
        if v["mobile"]:
            self.send("Emulation.setTouchEmulationEnabled", {"enabled": True, "maxTouchPoints": 5})
            self.send("Network.setUserAgentOverride", {"userAgent": IPHONE_UA, "platform": "iPhone"})

    def _event(self, method, p):
        if method == "Runtime.exceptionThrown":
            d = p["exceptionDetails"]
            self.problems.append("page error: " + (d.get("exception", {}).get("description") or d.get("text", "")))
        elif method == "Runtime.consoleAPICalled" and p["type"] == "error":
            self.problems.append("console: " + " ".join(str(a.get("value", a.get("description", ""))) for a in p["args"]))
        elif method == "Log.entryAdded" and p["entry"]["level"] == "error":
            self.problems.append(f"log: {p['entry']['text']} {p['entry'].get('url', '')}")
        elif method == "Network.responseReceived":
            r = p["response"]
            self.requests.append((r["url"], r["status"], r.get("mimeType")))
        elif method == "Network.loadingFailed" and not p.get("canceled"):
            self.problems.append(f"request failed: {p.get('errorText')}")

    def take_problems(self):
        out = [p for p in self.problems if not any(a in p for a in self.allowed)]
        self.problems = []
        return out

    # ---- Pages

    def goto(self, url):
        self.send("Page.navigate", {"url": url})
        self.wait("document.readyState === 'complete'", 30, f"{url} to load")

    def reload(self):
        self.send("Page.reload")
        time.sleep(0.2)
        self.wait("document.readyState === 'complete'", 30, "the page to reload")

    def hash(self, h):
        self.eval(f"location.hash = {json.dumps(h)}")

    def before_page(self, script):
        """Run a script before every page load, until forget_scripts()."""
        self.scripts.append(self.send("Page.addScriptToEvaluateOnNewDocument", {"source": script})["identifier"])

    def forget_scripts(self):
        for s in self.scripts:
            self.send("Page.removeScriptToEvaluateOnNewDocument", {"identifier": s})
        self.scripts = []

    def eval(self, js, await_promise=True):
        r = self.send("Runtime.evaluate", {"expression": js, "returnByValue": True, "awaitPromise": await_promise,
                                           "userGesture": True})
        if "exceptionDetails" in r:
            d = r["exceptionDetails"]
            raise Failed(f"Script failed: {d.get('exception', {}).get('description') or d.get('text')}")
        return r["result"].get("value")

    def wait(self, js, timeout=20, what=None):
        """Wait until a script's answer is truthy; returns it."""
        end = time.time() + timeout
        while True:
            got = self.eval(js)
            if got:
                return got
            if time.time() > end:
                raise Failed(f"Waited {timeout}s for {what or js}. Screen says: {self.screen()[:300]!r}")
            time.sleep(0.15)

    def screen(self):
        try:
            return self.eval("document.body ? document.body.innerText : ''") or ""
        except Failed:
            return ""

    def text(self, sel):
        return self.eval(f"document.querySelector({json.dumps(sel)})?.innerText ?? null")

    def has(self, sel):
        return bool(self.eval(f"!!document.querySelector({json.dumps(sel)})"))

    def wait_for(self, sel, timeout=20):
        return self.wait(f"!!document.querySelector({json.dumps(sel)})", timeout, sel)

    def wait_text(self, sel, text, timeout=20):
        return self.wait(f"(document.querySelector({json.dumps(sel)})?.innerText || '').includes({json.dumps(text)})",
                         timeout, f"{text!r} in {sel}")

    # ---- Input

    def click(self, sel):
        self.wait_for(sel)
        spot = self.eval(f"""(() => {{
          const e = document.querySelector({json.dumps(sel)});
          e.scrollIntoView({{ block: 'center', inline: 'center' }});
          const r = e.getBoundingClientRect(), x = r.left + r.width / 2, y = r.top + r.height / 2;
          const top = document.elementFromPoint(x, y);
          return {{ x, y, hit: !!top && (top === e || e.contains(top) || top.contains(e)), disabled: !!e.disabled,
                    top: top ? top.tagName + '.' + top.className : null }};
        }})()""")
        if spot["disabled"]:
            raise Failed(f"{sel} is disabled.")
        if not spot["hit"]:
            raise Failed(f"{sel} is covered by {spot['top']}.")
        x, y = spot["x"], spot["y"]
        if self.vp["mobile"]:
            self.send("Input.synthesizeTapGesture", {"x": x, "y": y, "duration": 50, "tapCount": 1})
            return
        self.send("Input.dispatchMouseEvent", {"type": "mouseMoved", "x": x, "y": y})
        for kind in ("mousePressed", "mouseReleased"):
            self.send("Input.dispatchMouseEvent", {"type": kind, "x": x, "y": y, "button": "left", "clickCount": 1})

    def fill(self, sel, text):
        """Type into a box the way a keyboard does: focus, clear, then the text, firing the page's input handler."""
        self.wait_for(sel)
        self.eval(f"""(() => {{ const e = document.querySelector({json.dumps(sel)}); e.focus(); e.select?.();
          e.value = ''; e.dispatchEvent(new Event('input', {{ bubbles: true }})); }})()""")
        if text:
            self.send("Input.insertText", {"text": text})

    def set_value(self, sel, value):
        """For a date box, whose picker can't be typed into the same way on each phone."""
        self.wait_for(sel)
        self.eval(f"""(() => {{ const e = document.querySelector({json.dumps(sel)}); e.value = {json.dumps(value)};
          e.dispatchEvent(new Event('input', {{ bubbles: true }})); e.dispatchEvent(new Event('change', {{ bubbles: true }})); }})()""")

    def shot(self, path, full=True):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = self.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": full})["data"]
        with open(path, "wb") as f:
            f.write(base64.b64decode(data))
        return path
