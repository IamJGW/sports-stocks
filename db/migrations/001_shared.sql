-- Shared by every league: the season, athletes, schedule, stat lines, per-share payouts and fair values.
-- Written only by the nightly robot (the secret key); anyone signed in may read them. Phones never write.

create function private.refuse_change() returns trigger language plpgsql as $$
begin
  raise exception '% are final', tg_table_name;
end $$;

create table public.seasons (
  id text primary key,                          -- e.g. 'nfl-2026'
  sport text not null,
  season int not null,
  rate double precision not null,               -- dividend per fantasy point per share
  economy jsonb not null,                       -- the levers (config/economy.json) the season was set up with
  created_at timestamptz not null default now()
);

create table public.athletes (
  id text primary key,                          -- season id, ':', ESPN id
  season_id text not null references public.seasons,
  espn_id text not null,
  ticker text not null,
  name text not null,
  team text not null,
  pos text not null,
  grp text not null,
  prior_ppg double precision not null,
  prior_ptg double precision not null,
  start_price double precision not null,
  step_shares double precision not null,        -- shares per 1% step of the market maker's price
  fair_value double precision not null,
  unique (season_id, espn_id),
  unique (season_id, ticker)
);

create table public.groups (
  season_id text not null references public.seasons,
  name text not null,
  multiplier double precision not null,
  primary key (season_id, name)
);

create table public.group_checks (
  season_id text not null references public.seasons,
  week int not null,
  grp text not null,
  actual double precision,
  promised double precision,
  ratio double precision,
  multiplier double precision not null,
  primary key (season_id, week, grp)
);

create table public.games (
  id text primary key,                          -- season id, ':', ESPN id
  season_id text not null references public.seasons,
  espn_id text not null,
  week int not null,
  kickoff timestamptz not null,
  day date not null,                            -- the Eastern date of kickoff: record time is its midnight
  home text not null,
  away text not null,
  playoff boolean not null default false,
  status text not null,
  processed_at timestamptz,                     -- set by the overnight update; the market maker steps back in
  set_aside_at timestamptz,                     -- a broken box score set aside by hand, paid later
  set_aside_reason text,
  unique (season_id, espn_id)
);
create index games_by_kickoff on public.games (season_id, kickoff);

create table public.stat_lines (
  game_id text not null references public.games,
  athlete_id text not null references public.athletes,
  team text not null,
  stats jsonb not null,
  points double precision not null,
  primary key (game_id, athlete_id)
);

create table public.payouts (
  game_id text not null,
  athlete_id text not null,
  points double precision not null,
  boost double precision not null,
  per_share double precision not null,
  record_time timestamptz not null,
  paid_at timestamptz not null,
  primary key (game_id, athlete_id),
  foreign key (game_id, athlete_id) references public.stat_lines
);

create table public.fair_values (
  day date not null,
  athlete_id text not null references public.athletes,
  fair_value double precision not null,
  primary key (day, athlete_id)
);

create table public.robot_status (
  season_id text primary key references public.seasons,
  last_day date,                                -- the last day fully paid
  last_run_at timestamptz,
  last_ok_at timestamptz,
  stopped_on date,                              -- the day it is waiting on, if stopped
  stop_reason text
);

create trigger stat_lines_are_final before update or delete on public.stat_lines
  for each row execute function private.refuse_change();
create trigger payouts_are_final before update or delete on public.payouts
  for each row execute function private.refuse_change();

alter table public.seasons enable row level security;
alter table public.athletes enable row level security;
alter table public.groups enable row level security;
alter table public.group_checks enable row level security;
alter table public.games enable row level security;
alter table public.stat_lines enable row level security;
alter table public.payouts enable row level security;
alter table public.fair_values enable row level security;
alter table public.robot_status enable row level security;

create policy "signed in can read" on public.seasons for select to authenticated using (true);
create policy "signed in can read" on public.athletes for select to authenticated using (true);
create policy "signed in can read" on public.groups for select to authenticated using (true);
create policy "signed in can read" on public.group_checks for select to authenticated using (true);
create policy "signed in can read" on public.games for select to authenticated using (true);
create policy "signed in can read" on public.stat_lines for select to authenticated using (true);
create policy "signed in can read" on public.payouts for select to authenticated using (true);
create policy "signed in can read" on public.fair_values for select to authenticated using (true);
create policy "signed in can read" on public.robot_status for select to authenticated using (true);

-- Supabase lets phones write to new tables and call new functions by default. Take that away, here and for
-- everything made later; each later file grants back only what it means to.
alter default privileges in schema public revoke all on tables from anon, authenticated;
alter default privileges in schema public revoke execute on functions from public, anon, authenticated;
revoke all on all tables in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;
revoke execute on all functions in schema private from public, anon, authenticated;
grant select on public.seasons, public.athletes, public.groups, public.group_checks, public.games,
  public.stat_lines, public.payouts, public.fair_values, public.robot_status to authenticated;
grant all on all tables in schema public to service_role;
