"""Checks on the online database's SQL files that need no internet: every table is locked down, money rows are final,
and the season uploader's rows fit the tables. (tools/db.py status runs the same safety check on a live project.)"""
import os
import re
import unittest

from helpers import ROOT, new_market
from tools import upload_season

MIGRATIONS = os.path.join(ROOT, "db", "migrations")
SQL = "\n".join(open(os.path.join(MIGRATIONS, f)).read() for f in sorted(os.listdir(MIGRATIONS)) if f.endswith(".sql"))
NOT_COLUMNS = {"primary", "foreign", "unique", "check", "constraint"}


def tables():
    """{table: [columns]} for every table made in the public schema."""
    out = {}
    for name, body in re.findall(r"create table public\.(\w+) \((.*?)\n\);", SQL, re.S):
        cols = []
        for line in body.split("\n"):
            m = re.match(r"\s+(\w+)\s", line)
            if m and m.group(1) not in NOT_COLUMNS:
                cols.append(m.group(1))
        out[name] = cols
    return out


class Migrations(unittest.TestCase):
    def test_files_are_numbered_in_order(self):
        names = sorted(f for f in os.listdir(MIGRATIONS) if f.endswith(".sql"))
        self.assertEqual([int(n[:3]) for n in names], list(range(1, len(names) + 1)))

    def test_every_table_has_row_level_security(self):
        for t in tables():
            self.assertIn(f"alter table public.{t} enable row level security;", SQL, t)

    def test_phones_are_never_granted_writes(self):
        for grant in re.findall(r"grant ([^;]+?) to ([^;]+);", SQL):
            what, who = grant
            if "anon" in who or "authenticated" in who:
                self.assertNotRegex(what.lower(), r"\b(insert|update|delete|truncate|all)\b", grant)

    def test_default_privileges_are_taken_away(self):
        self.assertIn("alter default privileges in schema public revoke all on tables from anon, authenticated;", SQL)
        self.assertIn("alter default privileges in schema public revoke execute on functions from public, anon, "
                      "authenticated;", SQL)

    def test_money_rows_are_final(self):
        for t in ("trades", "dividends", "payouts", "stat_lines"):
            self.assertRegex(SQL, rf"create trigger \w+ before update or delete on public\.{t}\s+for each row "
                                  rf"execute function private\.refuse_change\(\);", t)
        self.assertIn("before update or delete on public.orders", SQL)

    def test_public_functions_are_listed_and_pinned(self):
        allowed = {line.split("#")[0].strip() for line in open(os.path.join(ROOT, "db", "phone_functions.txt"))}
        allowed.discard("")
        made = set(re.findall(r"create (?:or replace )?function public\.(\w+)", SQL))
        self.assertLessEqual(allowed, made, "phone_functions.txt names a function no migration makes")
        for body in re.findall(r"create (?:or replace )?function public\.\w+.*?\$\$", SQL, re.S):
            self.assertIn("security definer", body)
            self.assertIn("set search_path = ''", body)

    def test_uploader_rows_fit_the_tables(self):
        sid, rows = upload_season.season_rows(new_market())
        self.assertEqual(sid, "nfl-2026")
        schema = tables()
        for table, sent in rows.items():
            if sent:
                self.assertLessEqual(set(sent[0]), set(schema[table]), table)
        self.assertEqual({t for t, _, _ in upload_season.PLAN}, set(rows))


if __name__ == "__main__":
    unittest.main()
