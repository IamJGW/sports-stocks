"""The sign-in emails, set the same way on each project.

  python3 tools/auth_setup.py test              set them and read them back
  python3 tools/auth_setup.py test --check      only say what differs
  python3 tools/auth_setup.py live --yes-live   the same on the real project (Justin's OK first)

Supabase sends two different emails. A returning player gets the "magic link" template. A brand-new player gets the
"confirmation" template, which is a link-only email until it is changed here, so both must show the code. Only the
fields in SETTINGS are touched: the mail server, its password and the rate limits stay as typed into Supabase's
settings page (the SMTP password can't be set from here and shouldn't be).

Needs the access token (tools/set_key.py token).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.online import Management, OnlineError, Project  # noqa: E402

OTP_LENGTH = 6
SITE = "https://iamjgw.github.io/sports-stocks/"
SUBJECT = "Your Sports Stocks sign-in code"
BODY = (f"<h2>Your Sports Stocks code</h2>\n<p>Enter this {OTP_LENGTH}-digit code: <b>{{{{ .Token }}}}</b></p>\n"
        "<p>It works for one hour. If you didn't ask for it, you can ignore this email.</p>")
SETTINGS = {
    "mailer_otp_length": OTP_LENGTH,
    "site_url": SITE,
    "mailer_subjects_magic_link": SUBJECT,
    "mailer_subjects_confirmation": SUBJECT,
    "mailer_templates_magic_link_content": BODY,
    "mailer_templates_confirmation_content": BODY,
}


def read(m):
    return m.auth_config()


def differences(cfg):
    return {k: cfg.get(k) for k, v in SETTINGS.items() if cfg.get(k) != v}


def apply(m):
    m.update_auth_config(SETTINGS)


def main():
    args = sys.argv[1:]
    if not args or args[0] not in ("test", "live"):
        sys.exit(__doc__)
    target = args[0]
    if target == "live" and "--yes-live" not in args:
        sys.exit("This changes the real project. Run it again with --yes-live, once Justin has said so.")
    try:
        m = Management(Project(target).ref)
        if "--check" not in args:
            apply(m)
        left = differences(read(m))
    except OnlineError as e:
        sys.exit(f"Supabase said: {e}")
    if left:
        sys.exit(f"Differs on {target}: {', '.join(left)}")
    print(f"Sign-in emails on {target} are as they should be: {OTP_LENGTH}-digit code in both, no links.")


if __name__ == "__main__":
    main()
