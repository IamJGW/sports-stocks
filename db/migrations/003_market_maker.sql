-- The market maker's prices in SQL, the same arithmetic as engine/market_maker.py down to the cent (tests/
-- test_online_trading.py checks thousands of cases and every real trade). Each share is priced on its own: buying share
-- number h+1 when the league holds h costs mid(h) x (1 + spread/2); selling one when it holds h pays
-- mid(h - 1) x (1 - spread/2). Block totals round against the player: buys up to the next cent, sales down.
-- mm is a league's lever set: {"spread": 0.04, "lean_per_step": 0.01}.

create function private.mm_q(mm jsonb, step_shares double precision) returns double precision
  language sql immutable set search_path = '' as $$
  select power(1 + (mm->>'lean_per_step')::double precision, 1 / step_shares);
$$;

-- sum of q^(start + i) for i in 0..n-1, in the same order of operations as Python
create function private.mm_geometric(q double precision, start bigint, n bigint) returns double precision
  language sql immutable set search_path = '' as $$
  select case when n <= 0 then 0::double precision
              when abs(q - 1) < 1e-15 then n::double precision
              else power(q, start) * (power(q, n) - 1) / (q - 1) end;
$$;

-- Python's round(x, 6): the float's shortest exact digits, then 6 decimals, so 1234.0000000001 isn't an extra cent.
create function private.round6(x double precision) returns numeric
  language sql immutable set search_path = '' set extra_float_digits = 1 as $$
  select round(x::text::numeric, 6);
$$;

create function private.mm_buy_cost_cents(fair_value double precision, held bigint, n bigint,
                                          step_shares double precision, mm jsonb) returns bigint
  language sql immutable set search_path = '' as $$
  select ceil(private.round6(fair_value * (1 + (mm->>'spread')::double precision / 2)
                             * private.mm_geometric(private.mm_q(mm, step_shares), held, n) * 100))::bigint;
$$;

create function private.mm_sell_proceeds_cents(fair_value double precision, held bigint, n bigint,
                                               step_shares double precision, mm jsonb) returns bigint
  language sql immutable set search_path = '' as $$
  select floor(private.round6(fair_value * (1 - (mm->>'spread')::double precision / 2)
                              * private.mm_geometric(private.mm_q(mm, step_shares), held - n, n) * 100))::bigint;
$$;

-- One share's exact price in cents (not rounded): the k-th share of a block bought when the league holds `held`,
-- or the k-th share of a block sold.
create function private.mm_buy_share_cents(fair_value double precision, held bigint, k bigint,
                                           step_shares double precision, mm jsonb) returns double precision
  language sql immutable set search_path = '' as $$
  select fair_value * power(private.mm_q(mm, step_shares), held + k - 1)
         * (1 + (mm->>'spread')::double precision / 2) * 100;
$$;

create function private.mm_sell_share_cents(fair_value double precision, held bigint, k bigint,
                                            step_shares double precision, mm jsonb) returns double precision
  language sql immutable set search_path = '' as $$
  select fair_value * power(private.mm_q(mm, step_shares), held - k)
         * (1 - (mm->>'spread')::double precision / 2) * 100;
$$;

-- How many shares the market maker trades with one order before something stops it: the order's price limit
-- (cap, whole cents; null for none), a player's order at a price he can't beat (rival, whole cents: the market maker
-- must be a whole cent better, since players go first at the same price, judged in cents as the buyer pays them;
-- Justin, 2026-10-29), the shares wanted, and the buyer's cash.
-- A share's price is compared at 6 decimals, like the block totals and the preview's worst price, so a share the
-- preview showed at $51.00 still fills when the order is guarded at $51.00.
create function private.mm_buy_ok(fair_value double precision, held bigint, k bigint, step_shares double precision,
                                  mm jsonb, cap bigint, rival bigint, cash bigint) returns boolean
  language plpgsql immutable set search_path = '' as $$
declare p numeric := private.round6(private.mm_buy_share_cents(fair_value, held, k, step_shares, mm));
begin
  return (cap is null or p <= cap) and (rival is null or ceil(p) < rival)
     and (cash is null or private.round6(fair_value * (1 + (mm->>'spread')::double precision / 2)
                                         * private.mm_geometric(private.mm_q(mm, step_shares), held, k) * 100) <= cash);
end $$;

-- Doubling first, then halving, so no share far past the answer is priced: the millionth share's price can be too
-- big for a number (a cash-limited preview of 1,000,000 shares used to fail).
create function private.mm_buy_count(fair_value double precision, held bigint, step_shares double precision, mm jsonb,
                                     want bigint, cap bigint, rival bigint, cash bigint) returns bigint
  language plpgsql immutable set search_path = '' as $$
declare lo bigint := 1; hi bigint := 2; mid bigint;
begin
  if want < 1 or not private.mm_buy_ok(fair_value, held, 1, step_shares, mm, cap, rival, cash) then
    return 0;
  end if;
  while hi <= want and private.mm_buy_ok(fair_value, held, hi, step_shares, mm, cap, rival, cash) loop
    lo := hi;
    hi := hi * 2;
  end loop;
  hi := least(hi - 1, want);
  while lo < hi loop
    mid := (lo + hi + 1) / 2;
    if private.mm_buy_ok(fair_value, held, mid, step_shares, mm, cap, rival, cash) then
      lo := mid;
    else
      hi := mid - 1;
    end if;
  end loop;
  return lo;
end $$;

create function private.mm_sell_count(fair_value double precision, held bigint, step_shares double precision, mm jsonb,
                                      want bigint, floor_cents bigint, rival bigint) returns bigint
  language plpgsql immutable set search_path = '' as $$
declare lo bigint := 0; hi bigint := least(want, held); mid bigint; p numeric;
begin
  while lo < hi loop
    mid := (lo + hi + 1) / 2;
    p := private.round6(private.mm_sell_share_cents(fair_value, held, mid, step_shares, mm));
    if (floor_cents is null or p >= floor_cents) and (rival is null or floor(p) > rival) then
      lo := mid;
    else
      hi := mid - 1;
    end if;
  end loop;
  return lo;
end $$;

revoke execute on all functions in schema private from public, anon, authenticated;
grant execute on function private.is_member(uuid) to authenticated;
