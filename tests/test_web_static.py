"""The site's own files: what a phone needs to add it to the home screen, and paths that work under /sports-stocks/."""
import json
import os
import re
import struct
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB = os.path.join(ROOT, "web")


def read(name):
    with open(os.path.join(WEB, name), encoding="utf-8") as f:
        return f.read()


def png_size(path):
    with open(path, "rb") as f:
        head = f.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n", f"{path} isn't a PNG"
    return struct.unpack(">II", head[16:24])


class Site(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = read("index.html")

    def manifest(self):
        return json.loads(read("manifest.webmanifest"))

    def test_manifest_says_what_a_home_screen_needs(self):
        m = self.manifest()
        self.assertEqual(m["display"], "standalone")
        self.assertTrue(m["name"] and m["short_name"])
        self.assertLessEqual(len(m["short_name"]), 12)  # longer is cut off under the icon
        for key in ("start_url", "scope"):
            self.assertFalse(m[key].startswith(("/", "http")), key)
        self.assertEqual({i["sizes"] for i in m["icons"]}, {"192x192", "512x512"})

    def test_icons_are_the_size_they_claim(self):
        for i in self.manifest()["icons"]:
            w, h = i["sizes"].split("x")
            self.assertEqual(png_size(os.path.join(WEB, i["src"])), (int(w), int(h)))
        touch = re.search(r'<link rel="apple-touch-icon" href="([^"]+)"', self.index).group(1)
        self.assertEqual(png_size(os.path.join(WEB, touch)), (180, 180))

    def test_index_links_the_manifest_and_a_favicon(self):
        self.assertRegex(self.index, r'<link rel="manifest" href="manifest\.webmanifest">')
        self.assertRegex(self.index, r'<link rel="icon" [^>]*href="[^"]+\.png"')
        self.assertIn('name="apple-mobile-web-app-capable" content="yes"', self.index)
        self.assertIn('name="theme-color"', self.index)

    def test_every_local_path_exists_and_is_relative(self):
        paths = re.findall(r'(?:href|src)="([^"#][^"]*)"', self.index)
        self.assertTrue(paths)
        for p in paths:
            self.assertFalse(p.startswith("/"), f"{p} would miss the /sports-stocks/ folder")
            if not p.startswith("http"):
                self.assertTrue(os.path.exists(os.path.join(WEB, p)), p)

    def test_no_secret_in_the_site(self):
        for folder, _, names in os.walk(WEB):
            for n in names:
                if n.endswith((".js", ".html", ".css", ".webmanifest")) and "vendor" not in folder:
                    with open(os.path.join(folder, n), encoding="utf-8") as f:
                        text = f.read()
                    self.assertNotRegex(text, r"sb_secret_|service_role|sbp_[0-9a-f]{20}", n)

    def test_config_still_points_at_the_test_project(self):
        online = json.load(open(os.path.join(ROOT, "config", "online.json")))
        config = read("config.js")
        self.assertIn(online["test"]["url"], config)
        self.assertNotIn(online["live"]["url"], config)

    def test_code_box_fits_supabases_code(self):
        from tools.auth_setup import OTP_LENGTH
        box = re.search(r'id="code"[^>]*maxlength="(\d+)"', read("app.js"))
        self.assertGreaterEqual(int(box.group(1)), OTP_LENGTH + 1)  # room for a pasted space
        self.assertRegex(read("app.js"), r'verifyOtp\(\{[^}]*type: "email"')


if __name__ == "__main__":
    unittest.main()
