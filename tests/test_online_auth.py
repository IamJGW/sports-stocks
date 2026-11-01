"""What a sign-in email actually carries, read from the TEST project's own settings, and that each kind of code works
the way the page uses it. generate_link makes a code without sending any mail. Skipped without the test project's keys."""
import re
import secrets
import subprocess
import sys
import unittest

import online
from engine.online import _request
from tools import auth_setup

KEEP = ("smtp_host", "smtp_port", "smtp_user", "smtp_sender_name", "smtp_admin_email", "rate_limit_email_sent",
        "rate_limit_otp", "mailer_otp_exp", "mailer_autoconfirm", "external_email_enabled", "disable_signup")


class Auth(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.p, cls.m = online.project()
        cls.cfg = auth_setup.read(cls.m)

    def verify(self, email, code):
        return _request("POST", f"{online.PUBLIC['test']['url']}/auth/v1/verify",
                        {"apikey": online.PUBLIC["test"]["publishable_key"]},
                        {"type": "email", "email": email, "token": code})[1]

    def test_both_emails_show_the_code_and_no_link(self):
        for key in ("mailer_templates_magic_link_content", "mailer_templates_confirmation_content"):
            self.assertIn("{{ .Token }}", self.cfg[key], key)
            self.assertNotIn("ConfirmationURL", self.cfg[key], key)
            self.assertNotIn("<a ", self.cfg[key], key)

    def test_length_and_wording_agree(self):
        self.assertEqual(self.cfg["mailer_otp_length"], auth_setup.OTP_LENGTH)
        for key in ("mailer_templates_magic_link_content", "mailer_templates_confirmation_content"):
            self.assertIn(f"{auth_setup.OTP_LENGTH}-digit", self.cfg[key])
        for key in ("mailer_subjects_magic_link", "mailer_subjects_confirmation"):
            self.assertIn("Sports Stocks", self.cfg[key])

    def test_site_url_is_the_public_site(self):
        self.assertEqual(self.cfg["site_url"], auth_setup.SITE)

    def test_a_new_players_code_signs_in(self):
        email = f"newbie-{secrets.token_hex(4)}@example.com"
        got = online._admin("POST", "admin/generate_link", {"type": "signup", "email": email,
                                                            "password": secrets.token_urlsafe(24)})
        try:
            self.assertRegex(got["email_otp"], r"^\d{6}$")
            self.assertEqual(self.verify(email, got["email_otp"])["user"]["email"], email)
        finally:
            online._admin("DELETE", f"admin/users/{got['id']}")

    def test_a_returning_players_code_signs_in(self):
        online.phones(19)
        got = online._admin("POST", "admin/generate_link", {"type": "magiclink", "email": "tester19@example.com"})
        self.assertRegex(got["email_otp"], r"^\d{6}$")
        self.assertEqual(self.verify("tester19@example.com", got["email_otp"])["user"]["email"], "tester19@example.com")

    def test_setup_changes_only_its_own_fields(self):
        before = {k: self.cfg.get(k) for k in KEEP}
        auth_setup.apply(self.m)
        after = auth_setup.read(self.m)
        self.assertEqual({k: after.get(k) for k in KEEP}, before)
        self.assertEqual(auth_setup.differences(after), {})

    def test_setup_wont_touch_live_by_accident(self):
        r = subprocess.run([sys.executable, "tools/auth_setup.py", "live"], cwd=online.ROOT, capture_output=True,
                           text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("--yes-live", r.stderr + r.stdout)


if __name__ == "__main__":
    unittest.main()
