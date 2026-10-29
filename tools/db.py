"""Database changes for the online game: the numbered SQL files in db/migrations/.

  python3 tools/db.py test status   which files the test project has had, which are waiting, and a safety check
  python3 tools/db.py test push     apply the waiting files, in order, each all or nothing
  python3 tools/db.py test reset    TEST ONLY: remove every table and function we made, then push everything again
  (use live instead of test for the real project; reset refuses live)

Needs the project's keys (tools/set_key.py test|live) and the access token (tools/set_key.py token).
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from engine.online import Management, OnlineError, Project  # noqa: E402

MIGRATIONS = os.path.join(ROOT, "db", "migrations")

BOOTSTRAP = """
create schema if not exists private;
revoke all on schema private from public, anon, authenticated;
create table if not exists private.schema_migrations (name text primary key, applied_at timestamptz not null default now());
"""

# Tables in public without row-level security, and functions anyone signed in (or not) may call. The second list
# must hold only the functions a phone is meant to call.
SAFETY = """
select 'no row-level security' as problem, c.relname as name from pg_class c join pg_namespace n on n.oid = c.relnamespace
 where n.nspname = 'public' and c.relkind = 'r' and not c.relrowsecurity
union all
select 'phones can write', table_name from information_schema.role_table_grants
 where table_schema = 'public' and grantee in ('anon', 'authenticated')
   and privilege_type in ('INSERT', 'UPDATE', 'DELETE', 'TRUNCATE')
union all
select 'callable by phones', p.proname from pg_proc p join pg_namespace n on n.oid = p.pronamespace
 where n.nspname = 'public' and (has_function_privilege('anon', p.oid, 'execute')
                                  or has_function_privilege('authenticated', p.oid, 'execute'))
order by 1, 2;
"""

RESET = """
do $$
declare r record;
begin
  for r in select tablename from pg_tables where schemaname = 'public' loop
    execute format('drop table if exists public.%I cascade', r.tablename);
  end loop;
  for r in select p.oid::regprocedure as f from pg_proc p join pg_namespace n on n.oid = p.pronamespace
           where n.nspname = 'public' loop
    execute format('drop function if exists %s cascade', r.f);
  end loop;
end $$;
drop schema if exists private cascade;
"""


def files():
    return sorted(f for f in os.listdir(MIGRATIONS) if f.endswith(".sql"))


def applied(m):
    m.sql(BOOTSTRAP)
    return {r["name"] for r in m.sql("select name from private.schema_migrations")}


def push(m):
    done = applied(m)
    waiting = [f for f in files() if f not in done]
    if not waiting:
        print("Nothing waiting.")
    for f in waiting:
        with open(os.path.join(MIGRATIONS, f)) as fh:
            body = fh.read()
        name = f.replace("'", "''")
        try:
            m.sql(f"begin;\n{body}\n;insert into private.schema_migrations (name) values ('{name}');\ncommit;")
        except OnlineError as e:
            sys.exit(f"{f} failed and was not applied (nothing after it was tried):\n  {e}")
        print(f"applied {f}")


def status(m):
    done = applied(m)
    for f in files():
        print(("  done     " if f in done else "  WAITING  ") + f)
    problems = m.sql(SAFETY)
    allowed = phone_functions()
    problems = [p for p in problems if not (p["problem"] == "callable by phones" and p["name"] in allowed)]
    if problems:
        print("Safety check FAILED:")
        for p in problems:
            print(f"  {p['problem']}: {p['name']}")
        return False
    print("Safety check passed: every table has row-level security, phones can't write to any table, and phones "
          "can call only the functions listed in db/phone_functions.txt.")
    return True


def phone_functions():
    path = os.path.join(ROOT, "db", "phone_functions.txt")
    with open(path) as f:
        return {line.split("#")[0].strip() for line in f if line.split("#")[0].strip()}


def main():
    if len(sys.argv) != 3 or sys.argv[1] not in ("test", "live") or sys.argv[2] not in ("status", "push", "reset"):
        sys.exit(__doc__)
    target, cmd = sys.argv[1:]
    try:
        m = Management(Project(target).ref)
        if cmd == "reset":
            if target != "test":
                sys.exit("reset only works on the test project.")
            m.sql(RESET)
            print("Test project emptied.")
            cmd = "push"
        if cmd == "push":
            push(m)
            cmd = "status"
        if cmd == "status":
            sys.exit(0 if status(m) else 1)
    except OnlineError as e:
        sys.exit(f"Supabase said: {e}")


if __name__ == "__main__":
    main()
