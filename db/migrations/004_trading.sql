-- Trading: leagues and joining, orders, matching, cancelling, the sweep, and what a phone reads (the book without
-- names, its own account, the leaderboard). The rules are the plan's "The order book's rules" (MILESTONE_2_PLAN.md).
--
-- Everything that changes a league takes the league's lock first (private.lock_league), so a league handles one
-- order, cancel or sweep at a time. Times are the database clock read after the lock, so they follow the lock order.
-- Cash and holdings aren't stored: they're added up from trades and dividends, which are final.

-- ---- Small pieces

create function private.lock_league(m uuid) returns void language sql set search_path = '' as $$
  select pg_advisory_xact_lock(hashtextextended('league:' || m::text, 0));
$$;

create function private.eastern_day(t timestamptz) returns date language sql immutable set search_path = '' as $$
  select (t at time zone 'America/New_York')::date;
$$;

create function private.money(cents bigint) returns text language sql immutable set search_path = '' as $$
  select '$' || to_char(cents / 100.0, 'FM999,999,999,990.00');
$$;

-- Shares of an athlete the league's players hold together: what the market maker has sold them, net.
create function private.held(m uuid, a text) returns bigint language sql stable set search_path = '' as $$
  select coalesce(sum(case when seller_id is null then shares else -shares end), 0)::bigint
  from public.trades where market_id = m and athlete_id = a and (buyer_id is null or seller_id is null);
$$;

create function private.cash(member uuid) returns bigint language sql stable set search_path = '' as $$
  select (select starting_cents from public.members where id = member)
       + coalesce((select sum(case when seller_id = member then cents else -cents end) from public.trades
                   where buyer_id = member or seller_id = member), 0)::bigint
       + coalesce((select sum(cents) from public.dividends where member_id = member), 0)::bigint;
$$;

create function private.shares(member uuid, a text) returns bigint language sql stable set search_path = '' as $$
  select coalesce(sum(case when buyer_id = member then shares else -shares end), 0)::bigint
  from public.trades where (buyer_id = member or seller_id = member) and athlete_id = a;
$$;

-- Set aside for waiting orders: a buy holds back shares x limit price of cash, a sell holds back its shares.
create function private.cash_set_aside(member uuid) returns bigint language sql stable set search_path = '' as $$
  select coalesce(sum(remaining::bigint * limit_cents), 0)::bigint from public.orders
  where member_id = member and side = 'buy' and status = 'open';
$$;

create function private.shares_set_aside(member uuid, a text) returns bigint language sql stable
  set search_path = '' as $$
  select coalesce(sum(remaining), 0)::bigint from public.orders
  where member_id = member and athlete_id = a and side = 'sell' and status = 'open';
$$;

-- The market maker is out of an athlete from his team's kickoff until the overnight update processes the game
-- (set-aside games included: they wait for a good box score). Returns the latest such kickoff, or null when he's in.
-- Waiting orders placed before it are asleep: they can't fill until the update.
create function private.mm_out(a text, t timestamptz) returns timestamptz language sql stable set search_path = '' as $$
  select max(g.kickoff) from public.games g join public.athletes x on x.id = a
  where g.season_id = x.season_id and x.team in (g.home, g.away) and g.kickoff <= t and g.processed_at is null
    and g.status not in ('STATUS_POSTPONED', 'STATUS_CANCELED');
$$;

create function private.me(m uuid) returns public.members language plpgsql stable set search_path = '' as $$
declare r public.members;
begin
  select * into r from public.members where market_id = m and user_id = (select auth.uid());
  if r.id is null then
    raise exception 'You aren''t in this league.';
  end if;
  return r;
end $$;

-- Trading is open from the league's start date to its end date (Eastern) until it is closed.
create function private.check_open(mk public.markets, t timestamptz) returns void language plpgsql stable
  set search_path = '' as $$
begin
  if mk.closed_at is not null or private.eastern_day(t) > mk.ends_on then
    raise exception 'This league is over.';
  end if;
  if private.eastern_day(t) < mk.starts_on then
    raise exception 'Trading starts on %.', to_char(mk.starts_on, 'FMDay, FMMonth FMDD');
  end if;
end $$;

-- ---- Matching

-- Fills an order (the taker) against the book and the market maker, best price first, players before the market
-- maker at the same price, older orders first. Updates the waiting orders it fills and returns the pieces; the
-- caller records the trades (private.record_fills) and the taker's own order.
--   side: the taker's side. cap: its limit in cents (a buy's ceiling, a sale's floor), null for none.
--   want: shares. cash: a buy's spending limit, null when its cash is already set aside.
--   taker: the taker's order id when it is already waiting (the sweep), null for a new order.
-- Player to player, the price is the older order's (for a new order, always the waiting one's). Against the market
-- maker, his own price, each share on its own, rounded against the player once per piece; he goes first only when
-- strictly better than the price the player piece would actually be paid at.
create function private.player_price(t public.orders, o public.orders, has boolean) returns bigint
  language sql immutable set search_path = '' as $$
  select case when not has then null
              when t.id is not null and (t.placed_at, t.id) < (o.placed_at, o.id) then t.limit_cents
              else o.limit_cents end;
$$;

create function private.match(p_market uuid, p_athlete text, p_member uuid, p_side text, p_cap bigint,
                              p_want bigint, p_cash bigint, p_taker bigint, p_now timestamptz) returns jsonb
  language plpgsql set search_path = '' set extra_float_digits = 1 as $$
declare
  a public.athletes;
  v_mm jsonb;
  v_out timestamptz := private.mm_out(p_athlete, p_now);
  v_held bigint := private.held(p_market, p_athlete);
  v_left bigint := p_want;
  v_cash bigint := p_cash;
  t public.orders;
  o public.orders;
  v_has boolean;
  v_n bigint;
  v_cents bigint;
  v_price bigint;
  v_pieces jsonb := '[]';
begin
  select * into a from public.athletes where id = p_athlete;
  select mm into v_mm from public.markets where id = p_market;
  if p_taker is not null then
    select * into t from public.orders where id = p_taker;
  end if;
  while v_left > 0 loop
    if p_side = 'buy' then
      select * into o from public.orders
       where market_id = p_market and athlete_id = p_athlete and side = 'sell' and status = 'open'
         and member_id <> p_member and (v_out is null or placed_at >= v_out)
         and (p_cap is null or limit_cents <= p_cap)
       order by limit_cents, placed_at, id limit 1 for update;
      v_has := found;
      v_price := private.player_price(t, o, v_has);
      v_n := 0;
      if v_out is null then
        v_n := private.mm_buy_count(a.fair_value, v_held, a.step_shares, v_mm, v_left, p_cap, v_price, v_cash);
      end if;
      if v_n > 0 then
        v_cents := private.mm_buy_cost_cents(a.fair_value, v_held, v_n, a.step_shares, v_mm);
        v_pieces := v_pieces || jsonb_build_object('order_id', null, 'member_id', null, 'shares', v_n,
          'cents', v_cents, 'held', v_held, 'fv', a.fair_value,
          'worst', ceil(private.round6(private.mm_buy_share_cents(a.fair_value, v_held, v_n, a.step_shares, v_mm))));
        v_held := v_held + v_n;
        v_left := v_left - v_n;
        v_cash := v_cash - v_cents;
        continue;
      end if;
    else
      select * into o from public.orders
       where market_id = p_market and athlete_id = p_athlete and side = 'buy' and status = 'open'
         and member_id <> p_member and (v_out is null or placed_at >= v_out)
         and (p_cap is null or limit_cents >= p_cap)
       order by limit_cents desc, placed_at, id limit 1 for update;
      v_has := found;
      v_price := private.player_price(t, o, v_has);
      v_n := 0;
      if v_out is null then
        v_n := private.mm_sell_count(a.fair_value, v_held, a.step_shares, v_mm, v_left, p_cap, v_price);
      end if;
      if v_n > 0 then
        v_cents := private.mm_sell_proceeds_cents(a.fair_value, v_held, v_n, a.step_shares, v_mm);
        v_pieces := v_pieces || jsonb_build_object('order_id', null, 'member_id', null, 'shares', v_n,
          'cents', v_cents, 'held', v_held, 'fv', a.fair_value,
          'worst', floor(private.round6(private.mm_sell_share_cents(a.fair_value, v_held, v_n, a.step_shares, v_mm))));
        v_held := v_held - v_n;
        v_left := v_left - v_n;
        continue;
      end if;
    end if;
    exit when not v_has;
    v_n := least(v_left, o.remaining, coalesce(v_cash / v_price, v_left));
    exit when v_n = 0;
    update public.orders set remaining = remaining - v_n,
           status = case when remaining = v_n then 'filled' else 'open' end,
           closed_at = case when remaining = v_n then p_now end,
           close_reason = case when remaining = v_n then 'filled' end
     where id = o.id;
    v_pieces := v_pieces || jsonb_build_object('order_id', o.id, 'member_id', o.member_id, 'shares', v_n,
      'cents', v_n * v_price, 'held', null, 'worst', v_price);
    v_left := v_left - v_n;
    v_cash := v_cash - v_n * v_price;
  end loop;
  return v_pieces;
end $$;

-- One trade row per piece. A market maker piece records the fair value it was priced at and the league's holdings
-- before it.
create function private.record_fills(p_market uuid, p_athlete text, p_side text, p_member uuid, p_order bigint,
                                     p_pieces jsonb, p_now timestamptz) returns void
  language plpgsql set search_path = '' as $$
declare x record;
begin
  for x in select * from jsonb_to_recordset(p_pieces)
                  as r(order_id bigint, member_id uuid, shares int, cents bigint, held bigint,
                       fv double precision) loop
    insert into public.trades (market_id, athlete_id, at, buyer_id, seller_id, shares, cents, buy_order_id,
                               sell_order_id, mm_fair_value, mm_held_before)
    values (p_market, p_athlete, p_now,
            case when p_side = 'buy' then p_member else x.member_id end,
            case when p_side = 'buy' then x.member_id else p_member end,
            x.shares, x.cents,
            case when p_side = 'buy' then p_order else x.order_id end,
            case when p_side = 'buy' then x.order_id else p_order end,
            x.fv, x.held);
  end loop;
end $$;

-- Fill waiting orders that cross: after a trade with the market maker (his prices moved) and after the overnight
-- update (fair values moved, sleeping orders woke). The best waiting buy goes first, then the best waiting sale,
-- until neither can fill. Returns the fills, for the morning report. The caller holds the league's lock.
create function private.sweep(p_market uuid, p_athlete text, p_now timestamptz) returns jsonb
  language plpgsql set search_path = '' as $$
declare
  v_out timestamptz;
  w public.orders;
  v_side text;
  v_pieces jsonb;
  v_n bigint;
  v_fills jsonb := '[]';
begin
  loop
    v_out := private.mm_out(p_athlete, p_now);
    v_pieces := '[]';
    foreach v_side in array array['buy', 'sell'] loop
      select * into w from public.orders
       where market_id = p_market and athlete_id = p_athlete and side = v_side and status = 'open'
         and (v_out is null or placed_at >= v_out)
       order by case when v_side = 'buy' then -limit_cents else limit_cents end, placed_at, id limit 1 for update;
      continue when not found;
      v_pieces := private.match(p_market, p_athlete, w.member_id, w.side, w.limit_cents, w.remaining, null, w.id,
                                p_now);
      exit when jsonb_array_length(v_pieces) > 0;
    end loop;
    exit when jsonb_array_length(v_pieces) = 0;
    perform private.record_fills(p_market, p_athlete, w.side, w.member_id, w.id, v_pieces, p_now);
    select sum((x->>'shares')::bigint) into v_n from jsonb_array_elements(v_pieces) x;
    update public.orders set remaining = remaining - v_n,
           status = case when remaining = v_n then 'filled' else 'open' end,
           closed_at = case when remaining = v_n then p_now end,
           close_reason = case when remaining = v_n then 'filled' end
     where id = w.id;
    v_fills := v_fills || jsonb_build_object('order_id', w.id, 'member_id', w.member_id, 'side', w.side,
      'shares', v_n, 'cents', (select sum((x->>'cents')::bigint) from jsonb_array_elements(v_pieces) x));
  end loop;
  return v_fills;
end $$;

-- ---- Orders

-- The real thing; place_order wraps it so a preview can run it and throw the result away.
create function private.place(p_market uuid, p_athlete text, p_side text, p_kind text, p_shares int,
                              p_limit_cents int, p_preview boolean) returns jsonb
  language plpgsql set search_path = '' as $$
declare
  me public.members;
  mk public.markets;
  a public.athletes;
  v_now timestamptz;
  v_free bigint;
  v_cash bigint;
  v_own bigint;
  v_pieces jsonb;
  v_filled bigint;
  v_cents bigint;
  v_worst bigint;
  v_status text;
  v_order bigint;
  v_out timestamptz;
  v_cap bigint;
  v_self text;
begin
  perform private.lock_league(p_market);
  v_now := clock_timestamp();
  me := private.me(p_market);
  select * into mk from public.markets where id = p_market;
  perform private.check_open(mk, v_now);
  select * into a from public.athletes where id = p_athlete;
  if a.id is null or not a.season_id = any (mk.seasons) then
    raise exception 'That athlete doesn''t trade in this league.';
  end if;
  if p_side is null or p_side not in ('buy', 'sell') then
    raise exception 'Choose buy or sell.';
  end if;
  if p_kind is null or p_kind not in ('market', 'limit') then
    raise exception 'Choose a market order or a limit order.';
  end if;
  if p_shares is null or p_shares < 1 or p_shares > 1000000 then
    raise exception 'Choose a whole number of shares, from 1 to 1,000,000.';
  end if;
  if p_limit_cents is not null and (p_limit_cents < 1 or p_limit_cents > 100000000) then
    raise exception 'Choose a price from $0.01 to $1,000,000.00 a share.';
  end if;
  if p_kind = 'limit' and p_limit_cents is null then
    raise exception 'A limit order needs a price.';
  end if;
  if p_kind = 'market' and p_limit_cents is null and not p_preview then
    raise exception 'A market order needs the price from its preview.';
  end if;

  -- You can't trade with yourself: a limit order that would meet your own waiting order is refused. A market order
  -- stops a cent short of it instead, and is refused only if that leaves it nothing.
  v_cap := p_limit_cents;
  if p_side = 'buy' then
    select min(limit_cents) into v_own from public.orders where member_id = me.id and athlete_id = p_athlete
       and side = 'sell' and status = 'open';
    if v_own is not null and v_own <= coalesce(v_cap, v_own) then
      v_cap := v_own - 1;
      v_self := format('You have a sell waiting at %s. Cancel it first.', private.money(v_own));
    end if;
  else
    select max(limit_cents) into v_own from public.orders where member_id = me.id and athlete_id = p_athlete
       and side = 'buy' and status = 'open';
    if v_own is not null and v_own >= coalesce(v_cap, v_own) then
      v_cap := v_own + 1;
      v_self := format('You have a buy waiting at %s. Cancel it first.', private.money(v_own));
    end if;
  end if;
  if p_kind = 'limit' and v_self is not null then
    raise exception '%', v_self;
  end if;

  -- Money and shares can't be promised twice.
  if p_side = 'buy' then
    v_free := private.cash(me.id) - private.cash_set_aside(me.id);
    if p_kind = 'limit' and p_shares::bigint * p_limit_cents > v_free then
      raise exception 'Not enough free cash: % at % sets aside %, and you have % free.', p_shares,
        private.money(p_limit_cents), private.money(p_shares::bigint * p_limit_cents), private.money(v_free);
    end if;
    if p_kind = 'market' and v_free <= 0 then
      raise exception 'You have no free cash.';
    end if;
    v_cash := case when p_kind = 'market' then v_free end;
  else
    v_free := private.shares(me.id, p_athlete) - private.shares_set_aside(me.id, p_athlete);
    if p_shares > v_free then
      raise exception 'You have % % free to sell, so you can''t sell %.', v_free, a.ticker, p_shares;
    end if;
  end if;

  v_pieces := private.match(p_market, p_athlete, me.id, p_side, v_cap, p_shares, v_cash, null, v_now);
  select coalesce(sum((x->>'shares')::bigint), 0), coalesce(sum((x->>'cents')::bigint), 0),
         case when p_side = 'buy' then max((x->>'worst')::bigint) else min((x->>'worst')::bigint) end
    into v_filled, v_cents, v_worst from jsonb_array_elements(v_pieces) x;
  v_out := private.mm_out(p_athlete, v_now);

  if v_filled = 0 and v_self is not null then
    raise exception '%', v_self;
  end if;
  if p_kind = 'market' and v_filled = 0 and not p_preview then
    raise exception '%', case when v_out is not null
      then format('No %s shares are on offer at that price, and the market maker is out while %s plays.',
                  a.ticker, a.name)
      else format('No %s shares are on offer at that price.', a.ticker) end;
  end if;
  v_status := case when v_filled = p_shares then 'filled' when p_kind = 'limit' then 'open' else 'cancelled' end;
  insert into public.orders (market_id, member_id, athlete_id, side, kind, shares, limit_cents, remaining, status,
                             placed_at, closed_at, close_reason)
  values (p_market, me.id, p_athlete, p_side, p_kind, p_shares,
          coalesce(p_limit_cents, v_worst, 1), p_shares - v_filled, v_status, v_now,
          case when v_status <> 'open' then v_now end,
          case v_status when 'filled' then 'filled' when 'cancelled' then 'rest not on offer' end)
  returning id into v_order;
  perform private.record_fills(p_market, p_athlete, p_side, me.id, v_order, v_pieces, v_now);
  if not p_preview then
    perform private.sweep(p_market, p_athlete, v_now);
  end if;
  return jsonb_build_object(
    'order_id', case when p_preview then null else v_order end,
    'status', v_status, 'side', p_side, 'kind', p_kind, 'ticker', a.ticker,
    'shares', p_shares, 'filled', v_filled, 'waiting', case when v_status = 'open' then p_shares - v_filled else 0 end,
    'dropped', case when v_status = 'cancelled' then p_shares - v_filled else 0 end,
    'cents', v_cents, 'worst_cents', v_worst,
    'from_players', coalesce((select sum((x->>'shares')::bigint) from jsonb_array_elements(v_pieces) x
                               where x->>'order_id' is not null), 0),
    'market_maker_out', v_out is not null,
    'pieces', jsonb_array_length(v_pieces));
end $$;

-- Place an order, or (p_preview) see exactly what it would do: the same code runs and its writes are rolled back.
-- A market order's p_limit_cents is the preview's worst_cents, so no share fills at a worse price than the preview
-- showed (the book may have moved: then fewer shares fill).
create function public.place_order(p_market uuid, p_athlete text, p_side text, p_kind text, p_shares int,
                                   p_limit_cents int default null, p_preview boolean default false) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare v_result jsonb;
begin
  if not coalesce(p_preview, false) then
    return private.place(p_market, p_athlete, p_side, p_kind, p_shares, p_limit_cents, false);
  end if;
  begin
    v_result := private.place(p_market, p_athlete, p_side, p_kind, p_shares, p_limit_cents, true);
    raise exception using errcode = 'SSPRV';
  exception when sqlstate 'SSPRV' then
    null;
  end;
  return v_result || '{"preview": true}';
end $$;

create function public.cancel_order(p_order bigint) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare o public.orders; v_now timestamptz;
begin
  select * into o from public.orders where id = p_order;
  if o.id is null then
    raise exception 'No such order.';
  end if;
  perform private.lock_league(o.market_id);
  v_now := clock_timestamp();
  select * into o from public.orders where id = p_order for update;
  if not exists (select 1 from public.members where id = o.member_id and user_id = (select auth.uid())) then
    raise exception 'That isn''t your order.';
  end if;
  if o.status <> 'open' then
    raise exception 'That order is already %.', o.status;
  end if;
  update public.orders set status = 'cancelled', closed_at = v_now, close_reason = 'cancelled' where id = o.id;
  return jsonb_build_object('order_id', o.id, 'status', 'cancelled', 'released', o.remaining);
end $$;

-- ---- Leagues

create function private.new_code() returns text language plpgsql volatile set search_path = '' as $$
declare
  letters constant text := 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789';  -- no 0, O, 1 or I
  b bytea;
  c text;
begin
  loop
    b := uuid_send(gen_random_uuid());
    c := '';
    for i in 0..5 loop
      c := c || substr(letters, get_byte(b, i) % 32 + 1, 1);
    end loop;
    exit when not exists (select 1 from public.markets where join_code = c);
  end loop;
  return c;
end $$;

create function private.add_member(mk public.markets, p_display_name text) returns public.members
  language plpgsql set search_path = '' as $$
declare r public.members;
begin
  if p_display_name is null or length(trim(p_display_name)) not between 1 and 24 then
    raise exception 'Choose a display name of 1 to 24 characters.';
  end if;
  if (select count(*) from public.members where market_id = mk.id) >= mk.max_players then
    raise exception 'This league is full (% players).', mk.max_players;
  end if;
  begin
    insert into public.members (market_id, user_id, display_name, starting_cents)
    values (mk.id, (select auth.uid()), trim(p_display_name), mk.starting_cents) returning * into r;
  exception when unique_violation then
    raise exception 'Someone in this league already uses the name %.', trim(p_display_name);
  end;
  return r;
end $$;

create function public.create_league(p_name text, p_season text, p_starts_on date, p_ends_on date,
                                     p_display_name text) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare s public.seasons; mk public.markets; r public.members;
begin
  if (select auth.uid()) is null then
    raise exception 'Sign in first.';
  end if;
  if p_name is null or length(trim(p_name)) not between 1 and 40 then
    raise exception 'Choose a league name of 1 to 40 characters.';
  end if;
  select * into s from public.seasons where id = p_season;
  if s.id is null then
    raise exception 'No such season.';
  end if;
  if p_starts_on is null or p_starts_on < private.eastern_day(now()) then
    raise exception 'The start date must be today or later.';
  end if;
  if p_ends_on is null or p_ends_on < p_starts_on then
    raise exception 'The end date must be on or after the start date.';
  end if;
  insert into public.markets (name, join_code, created_by, starts_on, ends_on, seasons, starting_cents, mm)
  values (trim(p_name), private.new_code(), (select auth.uid()), p_starts_on, p_ends_on, array[s.id],
          round((s.economy->>'starting_cash')::numeric * 100)::bigint, s.economy->'market_maker')
  returning * into mk;
  r := private.add_member(mk, p_display_name);
  return jsonb_build_object('market_id', mk.id, 'join_code', mk.join_code, 'member_id', r.id);
end $$;

create function public.join_league(p_code text, p_display_name text) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare mk public.markets; r public.members;
begin
  if (select auth.uid()) is null then
    raise exception 'Sign in first.';
  end if;
  select * into mk from public.markets where join_code = upper(trim(p_code));
  if mk.id is null then
    raise exception 'No league has the code %.', upper(trim(p_code));
  end if;
  perform private.lock_league(mk.id);
  select * into r from public.members where market_id = mk.id and user_id = (select auth.uid());
  if r.id is null then
    if mk.closed_at is not null or private.eastern_day(clock_timestamp()) > mk.ends_on then
      raise exception 'This league is over.';
    end if;
    r := private.add_member(mk, p_display_name);
  end if;
  return jsonb_build_object('market_id', mk.id, 'member_id', r.id, 'name', mk.name);
end $$;

-- The creator can change the name and dates before the start, and make a new code at any time.
create function public.update_league(p_market uuid, p_name text, p_starts_on date, p_ends_on date) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare mk public.markets;
begin
  perform private.lock_league(p_market);
  select * into mk from public.markets where id = p_market;
  if mk.id is null or mk.created_by is distinct from (select auth.uid()) then
    raise exception 'Only the person who made this league can change it.';
  end if;
  if private.eastern_day(now()) >= mk.starts_on then
    raise exception 'This league has started, so its dates are fixed.';
  end if;
  if p_name is null or length(trim(p_name)) not between 1 and 40 then
    raise exception 'Choose a league name of 1 to 40 characters.';
  end if;
  if p_starts_on is null or p_starts_on < private.eastern_day(now()) then
    raise exception 'The start date must be today or later.';
  end if;
  if p_ends_on is null or p_ends_on < p_starts_on then
    raise exception 'The end date must be on or after the start date.';
  end if;
  update public.markets set name = trim(p_name), starts_on = p_starts_on, ends_on = p_ends_on where id = p_market;
  return jsonb_build_object('market_id', p_market);
end $$;

create function public.new_join_code(p_market uuid) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare v_code text;
begin
  perform private.lock_league(p_market);
  if not exists (select 1 from public.markets where id = p_market and created_by = (select auth.uid())) then
    raise exception 'Only the person who made this league can change its code.';
  end if;
  v_code := private.new_code();
  update public.markets set join_code = v_code where id = p_market;
  return jsonb_build_object('join_code', v_code);
end $$;

-- ---- What a phone reads

-- The book for one athlete: the top five prices each side with share counts (no names), the market maker's line,
-- and the last trade. Asleep: shares at that price waiting out a game.
create function public.order_book(p_market uuid, p_athlete text) returns jsonb
  language plpgsql stable security definer set search_path = '' as $$
declare
  me public.members := private.me(p_market);
  a public.athletes;
  v_mm jsonb;
  v_held bigint := private.held(p_market, p_athlete);
  v_out timestamptz := private.mm_out(p_athlete, now());
  v_last public.trades;
begin
  select * into a from public.athletes where id = p_athlete;
  select mm into v_mm from public.markets where id = p_market;
  select * into v_last from public.trades where market_id = p_market and athlete_id = p_athlete
   order by at desc, id desc limit 1;
  return jsonb_build_object(
    'bids', coalesce((select jsonb_agg(l order by l.price desc) from (
        select limit_cents as price, sum(remaining) as shares,
               sum(case when v_out is not null and placed_at < v_out then remaining else 0 end) as asleep
          from public.orders where market_id = p_market and athlete_id = p_athlete and side = 'buy'
           and status = 'open' group by limit_cents order by limit_cents desc limit 5) l), '[]'),
    'asks', coalesce((select jsonb_agg(l order by l.price) from (
        select limit_cents as price, sum(remaining) as shares,
               sum(case when v_out is not null and placed_at < v_out then remaining else 0 end) as asleep
          from public.orders where market_id = p_market and athlete_id = p_athlete and side = 'sell'
           and status = 'open' group by limit_cents order by limit_cents limit 5) l), '[]'),
    'market_maker', jsonb_build_object(
        'out', v_out is not null, 'held', v_held, 'fair_value', a.fair_value,
        'sells_from_cents', private.mm_buy_cost_cents(a.fair_value, v_held, 1, a.step_shares, v_mm),
        'buys_from_cents', case when v_held > 0
          then private.mm_sell_proceeds_cents(a.fair_value, v_held, 1, a.step_shares, v_mm) end),
    'last', case when v_last.id is not null then jsonb_build_object(
        'price_cents', round(v_last.cents::numeric / v_last.shares), 'shares', v_last.shares, 'at', v_last.at) end);
end $$;

-- A member's value: cash plus what selling each holding to the market maker would bring right now (walking his price
-- down from the league's holdings), even while he is out. Players' bids don't count.
create function private.holdings(p_member uuid) returns table (athlete_id text, shares bigint, value_cents bigint)
  language sql stable set search_path = '' as $$
  select h.athlete_id, h.shares,
         private.mm_sell_proceeds_cents(a.fair_value, private.held(m.market_id, h.athlete_id), h.shares,
                                        a.step_shares, mk.mm)
  from (select t.athlete_id, sum(case when t.buyer_id = p_member then t.shares else -t.shares end)::bigint as shares
          from public.trades t where t.buyer_id = p_member or t.seller_id = p_member group by t.athlete_id) h
  join public.athletes a on a.id = h.athlete_id
  join public.members m on m.id = p_member
  join public.markets mk on mk.id = m.market_id
  where h.shares > 0;
$$;

create function public.my_account(p_market uuid) returns jsonb
  language plpgsql stable security definer set search_path = '' as $$
declare me public.members := private.me(p_market); v_cash bigint := private.cash(me.id);
begin
  return jsonb_build_object(
    'member_id', me.id, 'display_name', me.display_name,
    'cash_cents', v_cash, 'set_aside_cents', private.cash_set_aside(me.id),
    'free_cents', v_cash - private.cash_set_aside(me.id),
    'holdings', coalesce((select jsonb_agg(jsonb_build_object('athlete_id', h.athlete_id, 'shares', h.shares,
        'set_aside', private.shares_set_aside(me.id, h.athlete_id), 'value_cents', h.value_cents)
        order by h.value_cents desc) from private.holdings(me.id) h), '[]'),
    'open_orders', coalesce((select jsonb_agg(to_jsonb(o) order by o.placed_at desc) from public.orders o
        where o.member_id = me.id and o.status = 'open'), '[]'));
end $$;

create function public.leaderboard(p_market uuid) returns jsonb
  language plpgsql stable security definer set search_path = '' as $$
declare me public.members := private.me(p_market);
begin
  return (select jsonb_agg(r order by r.net_worth_cents desc, r.display_name) from (
    select m.id as member_id, m.display_name, m.joined_at, private.cash(m.id) as cash_cents,
           coalesce((select sum(h.value_cents) from private.holdings(m.id) h), 0)::bigint as holdings_cents,
           private.cash(m.id) + coalesce((select sum(h.value_cents) from private.holdings(m.id) h), 0)::bigint
             as net_worth_cents
      from public.members m where m.market_id = p_market) r);
end $$;

-- ---- For the robot (secret key only)

-- After the overnight update: sweep every athlete with waiting orders in one league against the new prices. Once the
-- league's end date has passed nothing fills, even before end_leagues cancels what's left.
create function public.sweep_league(p_market uuid) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare v_now timestamptz; a text; v_fills jsonb := '[]';
begin
  perform private.lock_league(p_market);
  v_now := clock_timestamp();
  if exists (select 1 from public.markets where id = p_market
             and (closed_at is not null or private.eastern_day(v_now) > ends_on)) then
    return v_fills;
  end if;
  for a in select distinct athlete_id from public.orders where market_id = p_market and status = 'open'
           order by athlete_id loop
    v_fills := v_fills || private.sweep(p_market, a, v_now);
  end loop;
  return v_fills;
end $$;

-- Close leagues whose end date has passed: every waiting order is cancelled, "league over", and trading stops.
create function public.end_leagues(p_today date) returns jsonb
  language plpgsql security definer set search_path = '' as $$
declare m uuid; v_now timestamptz; v_ended jsonb := '[]';
begin
  for m in select id from public.markets where closed_at is null and ends_on < p_today order by id loop
    perform private.lock_league(m);
    v_now := clock_timestamp();
    update public.orders set status = 'cancelled', closed_at = v_now, close_reason = 'league over'
     where market_id = m and status = 'open';
    update public.markets set closed_at = v_now where id = m;
    v_ended := v_ended || to_jsonb(m);
  end loop;
  return v_ended;
end $$;

-- The books add up: nobody's cash or shares below zero or promised twice, every order's open shares equal its shares
-- minus its fills, the market maker holds exactly what the players hold between them, each of his fills is his
-- formula's price for the holdings before it, no fill broke a price limit, and nothing awake is left crossed (two
-- players' orders, or an order and his price). Returns the problems (none: an empty list). The robot runs it daily
-- after the sweep; the tests run it after every case.
create function public.check_league(p_market uuid) returns jsonb
  language sql stable security definer set search_path = '' as $$
  with m as (select * from public.members where market_id = p_market),
       t as (select * from public.trades where market_id = p_market),
       o as (select * from public.orders where market_id = p_market),
       a as (select distinct athlete_id from t union select distinct athlete_id from o),
       p (problem, detail) as (
    select 'negative cash', m.display_name from m where private.cash(m.id) < 0
    union all
    select 'cash promised twice', m.display_name from m where private.cash(m.id) < private.cash_set_aside(m.id)
    union all
    select 'shares promised twice', m.display_name || ' ' || a.athlete_id from m cross join a
     where private.shares(m.id, a.athlete_id) < private.shares_set_aside(m.id, a.athlete_id)
    union all
    select 'fills do not match the order', o.id::text from o
     where o.shares - o.remaining <> coalesce((select sum(shares) from t where t.buy_order_id = o.id
                                               or t.sell_order_id = o.id), 0)
    union all
    select 'market maker holdings', a.athlete_id from a
     where private.held(p_market, a.athlete_id)
           <> (select coalesce(sum(private.shares(m.id, a.athlete_id)), 0) from m)
    union all
    select 'market maker holdings before', t.id::text from t
     where t.mm_held_before is not null
       and t.mm_held_before <> (select coalesce(sum(case when u.seller_id is null then u.shares else -u.shares end), 0)
                                  from t u where u.athlete_id = t.athlete_id and u.mm_held_before is not null
                                   and u.id < t.id)
    union all
    select 'market maker price', t.id::text from t join public.athletes x on x.id = t.athlete_id
      join public.markets k on k.id = p_market
     where t.mm_fair_value is not null
       and t.cents <> case when t.seller_id is null
             then private.mm_buy_cost_cents(t.mm_fair_value, t.mm_held_before, t.shares, x.step_shares, k.mm)
             else private.mm_sell_proceeds_cents(t.mm_fair_value, t.mm_held_before, t.shares, x.step_shares, k.mm) end
    union all
    select 'book crossed', b.id::text || ' ' || s.id::text
      from o b join o s on s.athlete_id = b.athlete_id and s.side = 'sell' and s.status = 'open'
                       and s.member_id <> b.member_id and s.limit_cents <= b.limit_cents
     where b.side = 'buy' and b.status = 'open'
       and coalesce(least(b.placed_at, s.placed_at) >= private.mm_out(b.athlete_id, now()), true)
    union all
    select 'book crossed', o.id::text from o join public.athletes x on x.id = o.athlete_id
      join public.markets k on k.id = p_market
     where o.status = 'open' and private.mm_out(o.athlete_id, now()) is null
       and case when o.side = 'buy'
             then private.round6(private.mm_buy_share_cents(x.fair_value, private.held(p_market, o.athlete_id), 1,
                                                            x.step_shares, k.mm)) <= o.limit_cents
             else private.held(p_market, o.athlete_id) > 0
                  and private.round6(private.mm_sell_share_cents(x.fair_value, private.held(p_market, o.athlete_id),
                                                                 1, x.step_shares, k.mm)) >= o.limit_cents end
    union all
    select 'paid above a buy limit', t.id::text from t join o on o.id = t.buy_order_id
     where t.cents > t.shares::bigint * o.limit_cents
    union all
    select 'sold below a sell limit', t.id::text from t join o on o.id = t.sell_order_id
     where t.cents < t.shares::bigint * o.limit_cents
    union all
    select 'player price not a waiting price', t.id::text from t join o b on b.id = t.buy_order_id
      join o s on s.id = t.sell_order_id
     where t.cents not in (t.shares::bigint * b.limit_cents, t.shares::bigint * s.limit_cents)
    union all
    select 'open order in a closed league', o.id::text from o join public.markets k on k.id = o.market_id
     where o.status = 'open' and k.closed_at is not null)
  select coalesce(jsonb_agg(jsonb_build_object('problem', problem, 'detail', detail) order by problem, detail),
                  '[]') from p;
$$;

-- Phones may call only the functions in db/phone_functions.txt; the robot's three are for the secret key.
revoke execute on all functions in schema public from public, anon, authenticated;
revoke execute on all functions in schema private from public, anon, authenticated;
grant execute on function private.is_member(uuid) to authenticated;
grant execute on function public.place_order(uuid, text, text, text, int, int, boolean),
  public.cancel_order(bigint), public.create_league(text, text, date, date, text), public.join_league(text, text),
  public.update_league(uuid, text, date, date), public.new_join_code(uuid), public.order_book(uuid, text),
  public.my_account(uuid), public.leaderboard(uuid) to authenticated;
grant execute on function public.sweep_league(uuid), public.end_leagues(date), public.check_league(uuid)
  to service_role;
