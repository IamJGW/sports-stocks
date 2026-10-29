-- Per league ("market"): members, orders, trades, dividends, reports. Members of a league can read its rows (orders:
-- only their own; the book is shown without names through a function in step 2). Nobody writes directly: placing,
-- matching and cancelling orders and joining leagues are database functions (step 2); dividends come from the robot.

create table public.markets (
  id uuid primary key default gen_random_uuid(),
  name text not null check (length(trim(name)) between 1 and 40),
  join_code text not null unique check (join_code ~ '^[A-HJ-NP-Z2-9]{6}$'),  -- no 0, O, 1 or I
  created_by uuid not null references auth.users,
  created_at timestamptz not null default now(),
  starts_on date not null,
  ends_on date not null,
  seasons text[] not null,                      -- whose athletes trade here, e.g. {nfl-2026}
  max_players int not null default 20 check (max_players between 1 and 20),
  starting_cents bigint not null check (starting_cents > 0),
  mm jsonb not null,                            -- the market maker's levers when the league was made
  closed_at timestamptz,                        -- set when the league ends: no more trades
  check (ends_on >= starts_on)
);

create table public.members (
  id uuid primary key default gen_random_uuid(),
  market_id uuid not null references public.markets,
  user_id uuid not null references auth.users,
  display_name text not null check (length(trim(display_name)) between 1 and 24),
  joined_at timestamptz not null default now(),
  starting_cents bigint not null check (starting_cents > 0),
  unique (market_id, user_id),
  unique (id, market_id)                        -- lets other tables check a member belongs to their league
);
create unique index members_unique_name on public.members (market_id, lower(trim(display_name)));

create table public.orders (
  id bigint generated always as identity primary key,
  market_id uuid not null references public.markets,
  member_id uuid not null,
  athlete_id text not null references public.athletes,
  side text not null check (side in ('buy', 'sell')),
  kind text not null check (kind in ('market', 'limit')),
  shares int not null check (shares > 0),
  limit_cents int not null check (limit_cents > 0),  -- per share; for a market order, the preview's worst price
  remaining int not null check (remaining between 0 and shares),
  status text not null default 'open' check (status in ('open', 'filled', 'cancelled')),
  placed_at timestamptz not null default now(),
  closed_at timestamptz,
  close_reason text,
  foreign key (member_id, market_id) references public.members (id, market_id),
  check ((status = 'open') = (closed_at is null)),
  check (status <> 'open' or remaining > 0),
  check (status <> 'filled' or remaining = 0),
  check (kind = 'limit' or status <> 'open')    -- a market order never waits in the book
);
create index orders_book on public.orders (market_id, athlete_id, side, limit_cents, placed_at, id)
  where status = 'open';
create index orders_by_member on public.orders (member_id, status);

create table public.trades (
  id bigint generated always as identity primary key,
  market_id uuid not null references public.markets,
  athlete_id text not null references public.athletes,
  at timestamptz not null default now(),
  buyer_id uuid,                                -- null: the market maker
  seller_id uuid,                               -- null: the market maker
  shares int not null check (shares > 0),
  cents bigint not null check (cents >= 0),     -- paid by the buyer, received by the seller
  buy_order_id bigint references public.orders,
  sell_order_id bigint references public.orders,
  mm_fair_value double precision,               -- market maker fills only: fair value and the league's holdings before
  mm_held_before int,
  foreign key (buyer_id, market_id) references public.members (id, market_id),
  foreign key (seller_id, market_id) references public.members (id, market_id),
  check (buyer_id is not null or seller_id is not null),
  check (buyer_id is distinct from seller_id),
  check ((buyer_id is null or seller_id is null) = (mm_fair_value is not null and mm_held_before is not null)),
  check (buyer_id is null or buy_order_id is not null),
  check (seller_id is null or sell_order_id is not null)
);
create index trades_by_athlete on public.trades (market_id, athlete_id, at);
create index trades_by_buyer on public.trades (buyer_id, athlete_id, at);
create index trades_by_seller on public.trades (seller_id, athlete_id, at);

create table public.dividends (
  market_id uuid not null references public.markets,
  game_id text not null,
  athlete_id text not null,
  member_id uuid not null,
  shares int not null check (shares > 0),
  cents bigint not null check (cents >= 0),
  primary key (market_id, game_id, athlete_id, member_id),
  foreign key (game_id, athlete_id) references public.payouts,
  foreign key (member_id, market_id) references public.members (id, market_id)
);
create index dividends_by_member on public.dividends (member_id);

create table public.reports (
  market_id uuid not null references public.markets,
  day date not null,
  made_at timestamptz not null,
  body jsonb not null,
  primary key (market_id, day)
);

create trigger trades_are_final before update or delete on public.trades
  for each row execute function private.refuse_change();
create trigger dividends_are_final before update or delete on public.dividends
  for each row execute function private.refuse_change();

-- An order can only be filled down or closed: its other columns never change, its open shares never grow, a closed
-- order never reopens, and orders are never deleted.
create function private.order_guard() returns trigger language plpgsql as $$
begin
  if tg_op = 'DELETE' then
    raise exception 'orders are never deleted; cancel them';
  end if;
  if old.status <> 'open' then
    raise exception 'order % is closed', old.id;
  end if;
  if (new.id, new.market_id, new.member_id, new.athlete_id, new.side, new.kind, new.shares, new.limit_cents,
      new.placed_at) is distinct from
     (old.id, old.market_id, old.member_id, old.athlete_id, old.side, old.kind, old.shares, old.limit_cents,
      old.placed_at) then
    raise exception 'only an order''s open shares and status can change';
  end if;
  if new.remaining > old.remaining then
    raise exception 'an order''s open shares never grow';
  end if;
  return new;
end $$;
create trigger orders_guard before update or delete on public.orders
  for each row execute function private.order_guard();

-- Who may read what.
create function private.is_member(m uuid) returns boolean language sql stable security definer
  set search_path = '' as $$
  select exists (select 1 from public.members where market_id = m and user_id = (select auth.uid()));
$$;

alter table public.markets enable row level security;
alter table public.members enable row level security;
alter table public.orders enable row level security;
alter table public.trades enable row level security;
alter table public.dividends enable row level security;
alter table public.reports enable row level security;

create policy "members read their league" on public.markets for select to authenticated
  using (private.is_member(id));
create policy "members read their league" on public.members for select to authenticated
  using (private.is_member(market_id));
create policy "own orders only" on public.orders for select to authenticated
  using (exists (select 1 from public.members m where m.id = member_id and m.user_id = (select auth.uid())));
create policy "members read their league" on public.trades for select to authenticated
  using (private.is_member(market_id));
create policy "members read their league" on public.dividends for select to authenticated
  using (private.is_member(market_id));
create policy "members read their league" on public.reports for select to authenticated
  using (private.is_member(market_id));

revoke all on all tables in schema public from anon, authenticated;
revoke execute on all functions in schema public from public, anon, authenticated;
revoke execute on all functions in schema private from public, anon, authenticated;
grant usage on schema private to authenticated;
grant execute on function private.is_member(uuid) to authenticated;
grant select on public.seasons, public.athletes, public.groups, public.group_checks, public.games,
  public.stat_lines, public.payouts, public.fair_values, public.robot_status,
  public.markets, public.members, public.orders, public.trades, public.dividends, public.reports to authenticated;
grant all on all tables in schema public to service_role;
