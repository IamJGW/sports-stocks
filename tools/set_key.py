"""Save a Supabase key on this Mac without it appearing on screen, in chat or in the project folder.

  python3 tools/set_key.py live    the real project: its URL, then its secret key (hidden as you paste)
  python3 tools/set_key.py test    the test project, the same way
  python3 tools/set_key.py token   your Supabase personal access token (hidden), for database changes

Each is written to ~/.config/sports-stocks/<name>.env, readable only by you. Run it again to replace a key.
"""
import getpass
import os
import sys

DIR = os.path.expanduser("~/.config/sports-stocks")


def write(name, values):
    os.makedirs(DIR, mode=0o700, exist_ok=True)
    path = os.path.join(DIR, f"{name}.env")
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        for k, v in values.items():
            f.write(f"{k}={v}\n")
    os.chmod(path, 0o600)
    return path


def main():
    if len(sys.argv) != 2 or sys.argv[1] not in ("live", "test", "token"):
        sys.exit(__doc__)
    name = sys.argv[1]
    if name == "token":
        token = getpass.getpass("Paste the personal access token (it won't show), then Return: ").strip()
        if not token.startswith("sbp_"):
            sys.exit("That doesn't look like a Supabase access token (they start with sbp_). Nothing saved.")
        path = write(name, {"SUPABASE_ACCESS_TOKEN": token})
    else:
        url = input(f"The {name} project's URL (https://....supabase.co): ").strip().rstrip("/")
        if not (url.startswith("https://") and url.endswith(".supabase.co")):
            sys.exit("That doesn't look like a project URL (https://<something>.supabase.co). Nothing saved.")
        secret = getpass.getpass("Paste its secret key (it won't show), then Return: ").strip()
        if len(secret) < 30:
            sys.exit("That key looks too short. Nothing saved.")
        path = write(name, {"SUPABASE_URL": url, "SUPABASE_SECRET_KEY": secret})
    print(f"Saved in {path} (only you can read it).")


if __name__ == "__main__":
    main()
