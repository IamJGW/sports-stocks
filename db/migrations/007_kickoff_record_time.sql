-- Record time moves from midnight Eastern at the start of game day to each game's kickoff (owner's call, 7 Nov 2026):
-- whoever held an athlete's shares when his game kicked off is paid for that game. A buy on game day before kickoff
-- now counts; a sale before kickoff gives the dividend up. The market maker already steps out at kickoff
-- (004_trading.sql), so the two now line up. Games already paid keep the record time they were paid at.

-- Holdings at a moment, per league that pays for that day (its start date to its end date, closed or not), for the
-- season's athletes. Only players: the market maker isn't paid.
create function private.holders_at_time(p_season text, p_day date, p_at timestamptz)
  returns table (market_id uuid, member_id uuid, athlete_id text, shares bigint)
  language sql stable set search_path = '' as $$
  select t.market_id, x.member_id, t.athlete_id, sum(x.shares)::bigint
  from public.markets k
  join public.trades t on t.market_id = k.id
  join public.athletes a on a.id = t.athlete_id and a.season_id = p_season
  cross join lateral (values (t.buyer_id, t.shares::bigint), (t.seller_id, -t.shares::bigint)) x (member_id, shares)
  where p_season = any (k.seasons) and p_day between k.starts_on and k.ends_on
    and t.at < p_at and x.member_id is not null
  group by t.market_id, x.member_id, t.athlete_id
  having sum(x.shares) > 0;
$$;

-- For the robot: each of the day's games with its kickoff, and the holdings at every distinct kickoff that day.
-- The robot pays a game's payouts to the holders listed under that game's kickoff.
create function public.robot_game_holders(p_season text, p_day date) returns jsonb
  language sql stable security definer set search_path = '' as $$
  select jsonb_build_object(
    'games', (select coalesce(jsonb_object_agg(g.id, g.kickoff), '{}')
                from public.games g where g.season_id = p_season and g.day = p_day),
    'holders', (select coalesce(jsonb_agg(jsonb_build_object('kickoff', k.kickoff) || to_jsonb(h)
                                          order by k.kickoff, h.market_id, h.athlete_id, h.member_id), '[]')
                  from (select distinct kickoff from public.games where season_id = p_season and day = p_day) k
                  cross join lateral private.holders_at_time(p_season, p_day, k.kickoff) h));
$$;

-- One day's overnight update, all or nothing, in the plan's order:
--   1. the day's stat lines and per-share payouts (shared);
--   2. each league's dividends, after checking them against this function's own count of holdings at each game's
--      kickoff (its record time):
--      every holder paid, nobody else, the right shares, and cents within half a cent of shares x per share;
--   3. fair values, groups and their re-checks (shared); the day's games marked processed (the market maker is back);
--   4. every open league's book swept against the new prices;
--   5. a report per league that pays for the day: the robot's shared report plus the league's own dividends, net
--      worths, busiest stocks and overnight fills.
-- p: {games: [ids], stat_lines, payouts, dividends, athletes: [{id, team, fair_value}], groups, group_checks,
--     fair_values: [{athlete_id, fair_value}], report: {...}}. A day already in is skipped, so running twice changes
-- nothing; two robots at once take turns on the season's lock.
create or replace function public.robot_day(p_season text, p_day date, p jsonb) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare
  v_games text[];
  v_done int;
  v_now timestamptz;
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
  select r.game_id, r.athlete_id, r.points, r.boost, r.per_share, g.kickoff, v_now
  from jsonb_to_recordset(p -> 'payouts') r (game_id text, athlete_id text, points double precision,
                                             boost double precision, per_share double precision)
  join public.games g on g.id = r.game_id;
  if exists (select 1 from public.payouts where game_id = any (v_games) and per_share < 0) then
    raise exception 'A per-share payout is below zero.';
  end if;

  -- 2. Dividends, checked against our own count first.
  with sent as (
    select * from jsonb_to_recordset(p -> 'dividends')
      r (market_id uuid, game_id text, athlete_id text, member_id uuid, shares bigint, cents bigint)),
  kicks as (
    select distinct g.kickoff from public.games g where g.id = any (v_games)),
  held as (
    select k.kickoff, h.* from kicks k cross join lateral private.holders_at_time(p_season, p_day, k.kickoff) h),
  want as (
    select h.market_id, pay.game_id, h.athlete_id, h.member_id, h.shares, pay.per_share
    from public.payouts pay
    join public.games g on g.id = pay.game_id
    join held h on h.kickoff = g.kickoff and h.athlete_id = pay.athlete_id
    where pay.game_id = any (v_games)),
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

-- The midnight versions are gone, so an out-of-date robot stops with a clear error instead of paying the old way.
drop function public.robot_holders(text, date);
drop function private.holders_at(text, date);
drop function private.record_time(date);

revoke execute on function public.robot_game_holders(text, date), private.holders_at_time(text, date, timestamptz)
  from public, anon, authenticated;
grant execute on function public.robot_game_holders(text, date) to service_role;
