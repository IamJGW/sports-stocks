-- The Market screen's list (MILESTONE_2_PLAN.md, "Screens"): for each athlete of a league, the last trade and the best
-- bid and offer anyone could trade at right now. One call, so the page doesn't ask for 120 books.
--
-- It says what order_book says, with two things left out because they can't be traded at this moment: orders asleep
-- through a game, and the market maker while he is out. best_bid_cents is null when nobody would buy, as when the
-- market maker holds none and no player is bidding. Reads only.

create function public.market_list(p_market uuid) returns jsonb
  language plpgsql stable security definer set search_path = '' as $$
declare
  me public.members := private.me(p_market);
  mk public.markets;
begin
  select * into mk from public.markets where id = p_market;
  return (select coalesce(jsonb_agg(r order by r.athlete_id), '[]') from (
    select a.id as athlete_id, o.out_at is not null as mm_out,
           l.price as last_cents,
           nullif(greatest(coalesce(b.price, 0),
                           case when o.out_at is null and h.held > 0
                                then private.mm_sell_proceeds_cents(a.fair_value, h.held, 1, a.step_shares, mk.mm)
                                else 0 end), 0) as best_bid_cents,
           least(s.price, case when o.out_at is null
                               then private.mm_buy_cost_cents(a.fair_value, h.held, 1, a.step_shares, mk.mm) end)
             as best_ask_cents
      from public.athletes a
      cross join lateral (select private.mm_out(a.id, now()) as out_at) o
      cross join lateral (select private.held(p_market, a.id) as held) h
      left join lateral (select round(t.cents::numeric / t.shares) as price from public.trades t
                          where t.market_id = p_market and t.athlete_id = a.id
                          order by t.at desc, t.id desc limit 1) l on true
      left join lateral (select max(x.limit_cents) as price from public.orders x
                          where x.market_id = p_market and x.athlete_id = a.id and x.side = 'buy' and x.status = 'open'
                            and (o.out_at is null or x.placed_at >= o.out_at)) b on true
      left join lateral (select min(x.limit_cents) as price from public.orders x
                          where x.market_id = p_market and x.athlete_id = a.id and x.side = 'sell' and x.status = 'open'
                            and (o.out_at is null or x.placed_at >= o.out_at)) s on true
     where a.season_id = any (mk.seasons)) r);
end $$;

revoke execute on function public.market_list(uuid) from public, anon, authenticated;
grant execute on function public.market_list(uuid) to authenticated;
