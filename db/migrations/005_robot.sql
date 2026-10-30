-- The nightly robot's side of the database (secret key only): the schedule, holdings at record time, one call per
-- day that puts the whole overnight update in (MILESTONE_2_PLAN.md, "The overnight update and the order book"), and
-- the status row the banner reads. The robot works out scores, payouts, dividends and fair values in Python (the
-- Milestone 1 code that matches the hand check); these functions check what it sends and put it in.
--
-- Locks: robot_day updates athletes (a "no key update" row lock, which doesn't block the key-share locks phones take
-- when they insert orders and trades) and then takes each league's lock to sweep it. Phones take a league's lock and
-- only read athletes, so the two never wait on each other in a circle. Nothing holding a league lock may ever
-- update athletes.

-- Midnight Eastern at the start of a day: who held shares then is paid for that day's games.
create function private.record_time(d date) returns timestamptz language sql stable set search_path = '' as $$
  select d::timestamp at time zone 'America/New_York';
$$;

-- The season's shared rows, for the robot's in-memory copy, with every double as exact text: the web API sends
-- doubles back with only 15 significant digits, and a copy built from those would drift from the Mac's save.
create function public.robot_season(p_season text) returns jsonb
  language sql stable security definer set search_path = '' set extra_float_digits = 3 as $$
  select jsonb_build_object(
    'season', (select jsonb_build_object('id', id, 'sport', sport, 'season', season, 'rate', rate::text,
                                         'economy', economy, 'created_at', created_at)
                 from public.seasons where id = p_season),
    'athletes', (select coalesce(jsonb_agg(jsonb_build_object('espn_id', espn_id, 'ticker', ticker, 'name', name,
                   'team', team, 'pos', pos, 'grp', grp, 'prior_ppg', prior_ppg::text, 'prior_ptg', prior_ptg::text,
                   'start_price', start_price::text, 'step_shares', step_shares::text,
                   'fair_value', fair_value::text) order by id), '[]')
                 from public.athletes where season_id = p_season),
    'groups', (select coalesce(jsonb_agg(jsonb_build_object('name', name, 'multiplier', multiplier::text)
                                         order by name), '[]')
                 from public.groups where season_id = p_season),
    'group_checks', (select coalesce(jsonb_agg(jsonb_build_object('week', week, 'grp', grp, 'actual', actual::text,
                       'promised', promised::text, 'ratio', ratio::text, 'multiplier', multiplier::text)
                       order by week, grp), '[]')
                     from public.group_checks where season_id = p_season),
    'games', (select coalesce(jsonb_agg(jsonb_build_object('espn_id', espn_id, 'week', week, 'kickoff', kickoff,
                'day', day, 'home', home, 'away', away, 'playoff', playoff, 'status', status,
                'processed_at', processed_at, 'set_aside_at', set_aside_at) order by kickoff, id), '[]')
              from public.games where season_id = p_season),
    'stat_lines', (select coalesce(jsonb_agg(jsonb_build_object('game_id', g.espn_id, 'athlete_id', a.espn_id,
                     'team', s.team, 'stats', s.stats, 'points', s.points::text) order by s.game_id, s.athlete_id),
                     '[]')
                   from public.stat_lines s join public.games g on g.id = s.game_id
                   join public.athletes a on a.id = s.athlete_id
                   where g.season_id = p_season));
$$;

-- Holdings at a day's record time, per league that pays for that day (its start date to its end date, closed or
-- not), for the season's athletes. Only players: the market maker isn't paid.
create function private.holders_at(p_season text, p_day date)
  returns table (market_id uuid, member_id uuid, athlete_id text, shares bigint)
  language sql stable set search_path = '' as $$
  select t.market_id, x.member_id, t.athlete_id, sum(x.shares)::bigint
  from public.markets k
  join public.trades t on t.market_id = k.id
  join public.athletes a on a.id = t.athlete_id and a.season_id = p_season
  cross join lateral (values (t.buyer_id, t.shares::bigint), (t.seller_id, -t.shares::bigint)) x (member_id, shares)
  where p_season = any (k.seasons) and p_day between k.starts_on and k.ends_on
    and t.at < private.record_time(p_day) and x.member_id is not null
  group by t.market_id, x.member_id, t.athlete_id
  having sum(x.shares) > 0;
$$;

create function public.robot_holders(p_season text, p_day date) returns jsonb
  language sql stable security definer set search_path = '' as $$
  select coalesce(jsonb_agg(to_jsonb(h) order by h.market_id, h.athlete_id, h.member_id), '[]')
  from private.holders_at(p_season, p_day) h;
$$;

-- The schedule: new games are added; a game not yet processed takes the feed's kickoff, teams and status. Returns
-- how many rows changed.
create function public.robot_sync_games(p_season text, p_games jsonb) returns int
  language plpgsql security definer set search_path = '' as $$
declare n int;
begin
  insert into public.games (id, season_id, espn_id, week, kickoff, day, home, away, status)
  select p_season || ':' || r.espn_id, p_season, r.espn_id, r.week, r.kickoff, r.day, r.home, r.away, r.status
  from jsonb_to_recordset(p_games) r (espn_id text, week int, kickoff timestamptz, day date, home text, away text,
                                      status text)
  on conflict (id) do update set week = excluded.week, kickoff = excluded.kickoff, day = excluded.day,
         home = excluded.home, away = excluded.away, status = excluded.status
   where games.processed_at is null and games.season_id = excluded.season_id
     and (games.week, games.kickoff, games.day, games.home, games.away, games.status)
         is distinct from (excluded.week, excluded.kickoff, excluded.day, excluded.home, excluded.away, excluded.status);
  get diagnostics n = row_count;
  return n;
end $$;

-- A broken box score set aside by hand (nightly.py --online --set-aside): the day's other games pay without it, and
-- it pays later, at its own record time, when a good box score arrives. The market maker stays out of its teams.
create function public.robot_set_aside(p_game text, p_reason text) returns void
  language plpgsql security definer set search_path = '' as $$
begin
  if coalesce(trim(p_reason), '') = '' then
    raise exception 'Give a reason for setting the game aside.';
  end if;
  update public.games set set_aside_at = now(), set_aside_reason = p_reason
   where id = p_game and processed_at is null;
  if not found then
    raise exception 'No unprocessed game %.', p_game;
  end if;
end $$;

-- One day's overnight update, all or nothing, in the plan's order:
--   1. the day's stat lines and per-share payouts (shared);
--   2. each league's dividends, after checking them against this function's own count of holdings at record time:
--      every holder paid, nobody else, the right shares, and cents within half a cent of shares x per share;
--   3. fair values, groups and their re-checks (shared); the day's games marked processed (the market maker is back);
--   4. every open league's book swept against the new prices;
--   5. a report per league that pays for the day: the robot's shared report plus the league's own dividends, net
--      worths, busiest stocks and overnight fills.
-- p: {games: [ids], stat_lines, payouts, dividends, athletes: [{id, team, fair_value}], groups, group_checks,
--     fair_values: [{athlete_id, fair_value}], report: {...}}. A day already in is skipped, so running twice changes
-- nothing; two robots at once take turns on the season's lock.
create function public.robot_day(p_season text, p_day date, p jsonb) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare
  v_games text[];
  v_done int;
  v_now timestamptz;
  v_rec timestamptz := private.record_time(p_day);
  v_bad text;
  m uuid;
  v_fills jsonb;
  v_all_fills int := 0;
  v_leagues int := 0;
begin
  perform pg_advisory_xact_lock(hashtextextended('robot:' || p_season, 0));
  v_now := clock_timestamp();
  select array_agg(x order by x) into v_games from jsonb_array_elements_text(p -> 'games') x;
  if v_games is null then
    raise exception 'No games sent for %.', p_day;
  end if;
  if (select count(*) from public.games where id = any (v_games) and season_id = p_season and day = p_day)
     <> cardinality(v_games) then
    raise exception 'The games sent aren''t all % games on %.', p_season, p_day;
  end if;
  select count(*) into v_done from public.games where id = any (v_games) and processed_at is not null;
  if v_done = cardinality(v_games) then
    return jsonb_build_object('day', p_day, 'skipped', true);
  elsif v_done > 0 then
    raise exception 'Some of the games sent for % are already processed.', p_day;
  end if;

  -- 1. Stat lines and per-share payouts.
  if exists (select 1 from jsonb_to_recordset(p -> 'stat_lines') r (game_id text, athlete_id text)
              left join public.athletes a on a.id = r.athlete_id and a.season_id = p_season
             where not r.game_id = any (v_games) or a.id is null) then
    raise exception 'A stat line isn''t for one of the day''s games and the season''s athletes.';
  end if;
  insert into public.stat_lines (game_id, athlete_id, team, stats, points)
  select r.game_id, r.athlete_id, r.team, r.stats, r.points
  from jsonb_to_recordset(p -> 'stat_lines') r (game_id text, athlete_id text, team text, stats jsonb,
                                                points double precision);
  insert into public.payouts (game_id, athlete_id, points, boost, per_share, record_time, paid_at)
  select r.game_id, r.athlete_id, r.points, r.boost, r.per_share, v_rec, v_now
  from jsonb_to_recordset(p -> 'payouts') r (game_id text, athlete_id text, points double precision,
                                             boost double precision, per_share double precision);
  if exists (select 1 from public.payouts where game_id = any (v_games) and per_share < 0) then
    raise exception 'A per-share payout is below zero.';
  end if;

  -- 2. Dividends, checked against our own count first.
  with sent as (
    select * from jsonb_to_recordset(p -> 'dividends')
      r (market_id uuid, game_id text, athlete_id text, member_id uuid, shares bigint, cents bigint)),
  want as (
    select h.market_id, pay.game_id, h.athlete_id, h.member_id, h.shares, pay.per_share
    from private.holders_at(p_season, p_day) h
    join public.payouts pay on pay.athlete_id = h.athlete_id and pay.game_id = any (v_games)),
  bad as (
    select coalesce(w.member_id, s.member_id)::text || ' ' || coalesce(w.athlete_id, s.athlete_id) || ' '
           || coalesce(w.game_id, s.game_id) || ': ' ||
           case when s.member_id is null then 'holder not paid'
                when w.member_id is null then 'not a holder at record time'
                when s.shares <> w.shares then 'sent ' || s.shares || ' shares, held ' || w.shares
                else 'sent ' || s.cents || ' cents for ' || w.shares * w.per_share * 100 end as what
    from want w full join sent s using (market_id, game_id, athlete_id, member_id)
    where s.member_id is null or w.member_id is null or s.shares <> w.shares
       or abs(s.cents - w.shares * w.per_share * 100) > 0.5 + 1e-6)
  select string_agg(what, '; ' order by what) into v_bad from (select what from bad limit 10) b;
  if v_bad is not null then
    raise exception 'Dividends don''t match the holdings at record time: %', v_bad;
  end if;
  insert into public.dividends (market_id, game_id, athlete_id, member_id, shares, cents)
  select r.market_id, r.game_id, r.athlete_id, r.member_id, r.shares, r.cents
  from jsonb_to_recordset(p -> 'dividends')
    r (market_id uuid, game_id text, athlete_id text, member_id uuid, shares int, cents bigint);

  -- 3. Fair values, groups, re-checks; the games are processed.
  update public.athletes a set team = r.team, fair_value = r.fair_value
    from jsonb_to_recordset(p -> 'athletes') r (id text, team text, fair_value double precision)
   where a.id = r.id and a.season_id = p_season;
  if exists (select 1 from public.athletes where season_id = p_season and not fair_value > 0) then
    raise exception 'A fair value isn''t above zero.';
  end if;
  update public.groups g set multiplier = r.multiplier
    from jsonb_to_recordset(p -> 'groups') r (name text, multiplier double precision)
   where g.season_id = p_season and g.name = r.name;
  insert into public.group_checks (season_id, week, grp, actual, promised, ratio, multiplier)
  select p_season, r.week, r.grp, r.actual, r.promised, r.ratio, r.multiplier
  from jsonb_to_recordset(p -> 'group_checks') r (week int, grp text, actual double precision,
                                                  promised double precision, ratio double precision,
                                                  multiplier double precision);
  insert into public.fair_values (day, athlete_id, fair_value)
  select p_day, r.athlete_id, r.fair_value
  from jsonb_to_recordset(p -> 'fair_values') r (athlete_id text, fair_value double precision)
  join public.athletes a on a.id = r.athlete_id and a.season_id = p_season
  on conflict (day, athlete_id) do update set fair_value = excluded.fair_value;
  update public.games set processed_at = v_now where id = any (v_games);

  -- 4 and 5. Sweep every open league; report to every league that pays for the day.
  for m in select id from public.markets
            where p_season = any (seasons) and (closed_at is null or p_day between starts_on and ends_on)
            order by id loop
    v_fills := public.sweep_league(m);
    v_all_fills := v_all_fills + jsonb_array_length(v_fills);
    continue when not exists (select 1 from public.markets where id = m and p_day between starts_on and ends_on);
    v_leagues := v_leagues + 1;
    insert into public.reports (market_id, day, made_at, body)
    values (m, p_day, v_now, coalesce(p -> 'report', '{}') || jsonb_build_object(
      'players', (select coalesce(jsonb_agg(r order by r.net_worth_cents desc, r.display_name), '[]') from (
          select mb.id as member_id, mb.display_name,
                 coalesce((select sum(d.cents) from public.dividends d
                            where d.member_id = mb.id and d.game_id = any (v_games)), 0)::bigint as dividend_cents,
                 private.cash(mb.id) as cash_cents,
                 private.cash(mb.id) + coalesce((select sum(h.value_cents) from private.holdings(mb.id) h), 0)::bigint
                   as net_worth_cents
          from public.members mb where mb.market_id = m) r),
      'busiest', (select coalesce(jsonb_agg(b order by b.shares desc, b.ticker), '[]') from (
          select a.ticker, a.name, sum(t.shares)::bigint as shares, count(*) as trades
          from public.trades t join public.athletes a on a.id = t.athlete_id
          where t.market_id = m and private.eastern_day(t.at) = p_day
          group by a.ticker, a.name order by sum(t.shares) desc, a.ticker limit 5) b),
      'overnight_fills', (select coalesce(jsonb_agg(f.x || jsonb_build_object(
            'athlete_id', o.athlete_id, 'ticker', a.ticker, 'display_name', mb.display_name, 'kind', o.kind,
            'limit_cents', o.limit_cents) order by f.n), '[]')
          from jsonb_array_elements(v_fills) with ordinality f (x, n)
          join public.orders o on o.id = (f.x ->> 'order_id')::bigint
          join public.athletes a on a.id = o.athlete_id
          join public.members mb on mb.id = o.member_id)))
    on conflict (market_id, day) do update set made_at = excluded.made_at, body = excluded.body;
  end loop;

  insert into public.robot_status (season_id, last_day) values (p_season, p_day)
  on conflict (season_id) do update set last_day = greatest(robot_status.last_day, excluded.last_day);

  return jsonb_build_object('day', p_day, 'games', cardinality(v_games),
    'stat_lines', (select count(*) from public.stat_lines where game_id = any (v_games)),
    'dividends', (select count(*) from public.dividends where game_id = any (v_games)),
    'dividend_cents', (select coalesce(sum(cents), 0) from public.dividends where game_id = any (v_games)),
    'fills', v_all_fills, 'reports', v_leagues);
end $$;

-- The end of every run, stopped or not: what the banner reads. A stop gives the day it's waiting on (if any) and why.
create function public.robot_finish(p_season text, p_stopped_on date, p_reason text) returns void
  language sql security definer set search_path = '' as $$
  insert into public.robot_status (season_id, last_run_at, last_ok_at, stopped_on, stop_reason)
  values (p_season, now(), case when p_reason is null then now() end, p_stopped_on, p_reason)
  on conflict (season_id) do update set last_run_at = excluded.last_run_at,
         last_ok_at = coalesce(excluded.last_ok_at, robot_status.last_ok_at),
         stopped_on = excluded.stopped_on, stop_reason = excluded.stop_reason;
$$;

revoke execute on all functions in schema public from public, anon, authenticated;
revoke execute on all functions in schema private from public, anon, authenticated;
grant execute on function private.is_member(uuid) to authenticated;
grant execute on function public.place_order(uuid, text, text, text, int, int, boolean),
  public.cancel_order(bigint), public.create_league(text, text, date, date, text), public.join_league(text, text),
  public.update_league(uuid, text, date, date), public.new_join_code(uuid), public.order_book(uuid, text),
  public.my_account(uuid), public.leaderboard(uuid) to authenticated;
grant execute on function public.robot_season(text), public.robot_holders(text, date), public.robot_sync_games(text, jsonb),
  public.robot_set_aside(text, text), public.robot_day(text, date, jsonb), public.robot_finish(text, date, text)
  to service_role;
