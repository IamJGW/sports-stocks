// Screens only. Every price, fill and balance comes from the database; nothing here works out money.
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const sb = supabase.createClient(SS.url, SS.key, { auth: { persistSession: true, autoRefreshToken: true } });
const money = (n, d = 2) => (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const cents = c => money(c / 100);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const cls = x => x > 0 ? "up" : x < 0 ? "down" : "dim";
const help = sec => `<a class="help" href="#/rules/${sec}" title="How this works">?</a>`;
const store = { get: k => { try { return localStorage.getItem(k); } catch (e) { return null; } }, set: (k, v) => { try { localStorage.setItem(k, v); } catch (e) {} } };
let token = 0, pollTimer = null, user = null, league = null;   // league: the market row being viewed
const names = {};   // member id -> display name, per league

const rpc = async (fn, args) => { const { data, error } = await sb.rpc(fn, args); if (error) throw new Error(error.message); return data; };
const q = async req => { const { data, error } = await req; if (error) throw new Error(error.message); return data; };
const fail = e => `<div class="msg">${esc(e.message)}</div>`;
const day = iso => new Date(iso + (iso.length === 10 ? "T12:00:00" : "")).toLocaleDateString("en-US", { month: "short", day: "numeric" });
const easternToday = () => new Intl.DateTimeFormat("en-CA", { timeZone: "America/New_York" }).format(new Date());   // the database's day

let athletes = null;
async function loadAthletes() {
  if (!athletes) athletes = await q(sb.from("athletes").select("id,ticker,name,team,pos,fair_value").eq("season_id", SS.season).order("name"));
  return athletes;
}
const byTicker = async t => (await loadAthletes()).find(a => a.ticker === t);

async function loadLeague() {
  const mine = await q(sb.from("markets").select("*").order("created_at"));
  const id = store.get("league");
  league = mine.find(m => m.id === id) || mine[0] || null;
  $("#league").textContent = league ? league.name : "";
  if (league) {
    store.set("league", league.id);
    const ms = await q(sb.from("members").select("id,display_name,joined_at").eq("market_id", league.id));
    ms.forEach(m => names[m.id] = m);
  }
  return mine;
}
const needLeague = () => `<div class="card">Join or create a league first. <a href="#/leagues">Leagues</a></div>`;

// ---- Sign in
function signin() {
  view.innerHTML = `<div class="card"><h2 style="margin-top:0">Sign in</h2>
    <p class="dim small">Enter your email. We'll email you a sign-in code.</p>
    <input type="email" id="em" placeholder="you@example.com" autocomplete="email" inputmode="email">
    <button class="go" id="send">Send code</button><div id="out"></div></div>`;
  $("#send").onclick = async () => {
    const email = $("#em").value.trim(); if (!email) return;
    $("#send").disabled = true;
    const { error } = await sb.auth.signInWithOtp({ email, options: { shouldCreateUser: true } });
    if (error) { $("#out").innerHTML = fail(error); $("#send").disabled = false; return; }
    view.innerHTML = `<div class="card"><h2 style="margin-top:0">Check your email</h2>
      <p class="dim small">We sent a code to ${esc(email)}.</p>
      <input type="text" id="code" inputmode="numeric" autocomplete="one-time-code" maxlength="8" placeholder="6-digit code from the email">
      <button class="go" id="ok">Sign in</button><button class="link" id="back">Use a different email</button><div id="out"></div></div>`;
    $("#back").onclick = signin;
    $("#ok").onclick = async () => {
      $("#ok").disabled = true;
      const { data, error } = await sb.auth.verifyOtp({ email, token: $("#code").value.replace(/\D/g, ""), type: "email" });
      if (error) { $("#out").innerHTML = fail({ message: "That code didn't work. Check the numbers, or go back and send a new one." }); $("#ok").disabled = false; return; }
      user = data.user; location.hash = "#/market"; start();
    };
  };
}

// ---- Leagues
async function leagues() {
  const my = ++token;
  const mine = await loadLeague(); if (my !== token) return;
  const joinCode = new URLSearchParams(location.search).get("join") || "";
  const today = easternToday();
  view.innerHTML = `
    <h2>Your leagues</h2>
    ${mine.map(m => `<div class="card"><b>${esc(m.name)}</b> ${league && m.id === league.id ? '<span class="dim small">(showing)</span>' : ""}
      <div class="dim small">${day(m.starts_on)} to ${day(m.ends_on)} · code <b>${m.join_code}</b></div>
      <div class="bar"><button class="chip on" data-open="${m.id}">Open</button>
        ${m.created_by === user.id ? `<button class="chip" data-edit="${m.id}">Dates</button><button class="chip" data-code="${m.id}">New code</button>
        <button class="chip" data-share="${m.id}">Share link</button>` : ""}</div></div>`).join("") || `<p class="dim">No leagues yet.</p>`}
    <div id="out"></div>
    <h2>Join with a code</h2>
    <div class="card"><input type="text" id="jc" placeholder="Code" maxlength="6" value="${esc(joinCode)}" style="text-transform:uppercase">
      <input type="text" id="jn" placeholder="Your display name" maxlength="24"><button class="go" id="join">Join</button></div>
    <h2>Create a league</h2>
    <div class="card"><input type="text" id="cn" placeholder="League name" maxlength="40">
      <input type="text" id="cd" placeholder="Your display name" maxlength="24">
      <label class="dim small">Starts</label><input type="date" id="cs" value="${today}" min="${today}">
      <label class="dim small">Ends</label><input type="date" id="ce">
      <button class="go" id="create">Create</button></div>
    <p><button class="link" id="so">Sign out (${esc(user.email)})</button></p>`;
  const leagues2 = async msg => { await leagues(); if (msg) $("#out").innerHTML = `<div class="msg ok">${esc(msg)}</div>`; };
  const run = async (fn, ok) => { try { await fn(); await leagues2(ok); } catch (e) { $("#out").innerHTML = fail(e); } };
  view.onclick = async e => {
    const d = e.target.dataset;
    if (d.open) { store.set("league", d.open); await loadLeague(); location.hash = "#/market"; }
    if (d.code) run(async () => { await rpc("new_join_code", { p_market: d.code }); }, "New code made.");
    if (d.share) { const m = mine.find(x => x.id === d.share); const url = `${location.origin}${location.pathname}?join=${m.join_code}`;
      try { await navigator.clipboard.writeText(url); $("#out").innerHTML = `<div class="msg ok">Link copied: ${esc(url)}</div>`; } catch (_) { $("#out").innerHTML = `<div class="notice">${esc(url)}</div>`; } }
    if (d.edit) {
      const m = mine.find(x => x.id === d.edit); const s = prompt("Start date (YYYY-MM-DD)", m.starts_on); if (!s) return;
      const en = prompt("End date (YYYY-MM-DD)", m.ends_on); if (!en) return;
      run(() => rpc("update_league", { p_market: m.id, p_name: m.name, p_starts_on: s, p_ends_on: en }), "Dates changed.");
    }
  };
  $("#join").onclick = () => run(async () => { const r = await rpc("join_league", { p_code: $("#jc").value, p_display_name: $("#jn").value }); store.set("league", r.market_id); history.replaceState(null, "", location.pathname + "#/leagues"); }, "Joined.");
  $("#create").onclick = () => run(async () => { const r = await rpc("create_league", { p_name: $("#cn").value, p_season: SS.season, p_starts_on: $("#cs").value, p_ends_on: $("#ce").value, p_display_name: $("#cd").value }); store.set("league", r.market_id); }, "League created.");
  $("#so").onclick = async () => { await sb.auth.signOut(); user = null; league = null; location.hash = "#/signin"; route(); };
}

// ---- Market
async function market() {
  const my = ++token;
  await loadLeague(); if (!league) { view.innerHTML = needLeague(); return; }
  const [list, acct, rows] = await Promise.all([loadAthletes(), rpc("my_account", { p_market: league.id }), rpc("market_list", { p_market: league.id })]);
  if (my !== token) return;
  const mine = Object.fromEntries(acct.holdings.map(h => [h.athlete_id, h.shares]));
  const quote = Object.fromEntries(rows.map(r => [r.athlete_id, r]));
  const price = c => c == null ? "none" : cents(c);
  const quoted = a => { const r = quote[a.id]; return r ? `<span class="sub">Bid ${price(r.best_bid_cents)} · Offer ${price(r.best_ask_cents)} · Last ${price(r.last_cents)}${r.mm_out ? " · market maker out" : ""}</span>` : ""; };
  const st = market.state ||= { pos: "All", q: "" };
  view.innerHTML = `
    <div class="bar"><input type="search" id="q" placeholder="Search name, team or ticker" value="${esc(st.q)}"></div>
    <div class="bar" id="pos">${["All", "QB", "RB", "WR", "TE", "Mine"].map(p => `<button class="chip ${p === st.pos ? "on" : ""}" data-p="${p}">${p}</button>`).join("")}</div>
    <div id="list"></div>`;
  const draw = () => {
    const s = st.q.toLowerCase();
    $("#list").innerHTML = list.filter(a => (st.pos === "All" || (st.pos === "Mine" ? mine[a.id] : a.pos === st.pos)) &&
      (!s || (a.name + " " + a.team + " " + a.ticker).toLowerCase().includes(s))).sort((a, b) => b.fair_value - a.fair_value).map(a => `
      <a class="row" href="#/athlete/${a.ticker}"><span class="t">${esc(a.name)} <span class="dim small">${a.ticker}</span></span>
        <span class="num">${money(a.fair_value)}</span><span></span>
        <span class="sub">${a.team} · ${a.pos} · fair value${mine[a.id] ? ` · <b>you hold ${mine[a.id]}</b>` : ""}</span>${quoted(a)}</a>`).join("") || `<p class="dim">No athletes match.</p>`;
  };
  $("#q").oninput = e => { st.q = e.target.value; draw(); };
  $("#pos").onclick = e => { const p = e.target.dataset.p; if (!p) return; st.pos = p; [...$("#pos").children].forEach(b => b.classList.toggle("on", b.dataset.p === p)); draw(); };
  draw();
}

// ---- Athlete: book, order box, my open orders, recent trades
async function athlete(ticker) {
  const my = ++token;
  await loadLeague(); if (!league) { view.innerHTML = needLeague(); return; }
  const a = await byTicker(ticker); if (!a) { view.innerHTML = `<a class="back" href="#/market">‹ Market</a><div class="msg">No such athlete.</div>`; return; }
  let side = "buy", kind = "market", seq = 0, preview = null;
  view.innerHTML = `
    <a class="back" href="#/market">‹ Market</a>
    <div class="card"><div class="big">${esc(a.name)}</div><div class="dim">${a.ticker} · ${a.team} · ${a.pos}</div>
      <div id="mm" class="small" style="margin-top:8px"></div><div id="last" class="small dim"></div></div>
    <div class="card"><b>Order book</b> ${help("trading")}<div id="book" class="book small" style="margin-top:6px"></div></div>
    <div class="card" id="trade">
      <div class="seg"><button class="chip on" data-s="buy">Buy</button><button class="chip" data-s="sell">Sell</button></div>
      <div class="seg"><button class="chip on" data-k="market">Market</button><button class="chip" data-k="limit">Limit</button></div>
      <div class="bar"><input type="number" id="n" min="1" step="1" inputmode="numeric" placeholder="Shares" style="flex:1">
        <input type="number" id="lp" min="0.01" step="0.01" inputmode="decimal" placeholder="Limit price $" style="flex:1;display:none"></div>
      <div id="pv" class="kv small" style="min-height:60px"></div><div id="out"></div>
      <button class="go" id="go" disabled>Buy</button></div>
    <h2>Your open orders here</h2><div class="card" id="mine"></div>
    <h2>Recent trades</h2><div class="card" id="trades"></div>`;
  const n = $("#n"), lp = $("#lp"), go = $("#go"), pv = $("#pv"), out = $("#out");
  const loadBook = async () => {
    const b = await rpc("order_book", { p_market: league.id, p_athlete: a.id }); if (my !== token) return;
    const lines = (arr, c) => arr.map(l => `<div class="${c}">${cents(l.price)} × ${l.shares}${l.asleep > 0 ? ` <span class="dim">(${l.asleep} asleep)</span>` : ""}</div>`).join("") || `<div class="dim">none</div>`;
    $("#book").innerHTML = `<div><div class="dim">Bids (buyers)</div>${lines(b.bids, "bid")}</div><div><div class="dim">Offers (sellers)</div>${lines(b.asks, "ask")}</div>`;
    const m = b.market_maker;
    $("#mm").innerHTML = m.out ? `Market maker: <b>out while his team plays</b>. Fair value ${money(m.fair_value)}.` :
      `Market maker: sells from <b>${cents(m.sells_from_cents)}</b>${m.buys_from_cents != null ? `, buys from <b>${cents(m.buys_from_cents)}</b>` : ", has none to sell back"}.`;
    $("#last").textContent = b.last ? `Last trade ${cents(b.last.price_cents)} (${b.last.shares} sh)` : "No trades here yet.";
  };
  const loadMine = async () => {
    const os = (await q(sb.from("orders").select("*").eq("market_id", league.id).eq("athlete_id", a.id).eq("status", "open").order("placed_at", { ascending: false }))); if (my !== token) return;
    $("#mine").innerHTML = os.map(o => `<div class="kv small"><span>${o.side === "buy" ? "Buy" : "Sell"} ${o.remaining} at ${cents(o.limit_cents)}</span><button class="chip small" data-c="${o.id}">Cancel</button></div>`).join("") || `<span class="dim">None.</span>`;
  };
  const loadTrades = async () => {
    const ts = await q(sb.from("trades").select("at,shares,cents,buyer_id,seller_id").eq("market_id", league.id).eq("athlete_id", a.id).order("at", { ascending: false }).limit(8)); if (my !== token) return;
    if (ts.some(t => [t.buyer_id, t.seller_id].some(id => id && !names[id]))) { await loadLeague(); if (my !== token) return; }   // someone joined since
    const nm = id => id ? esc(names[id]?.display_name || "?") : "Market maker";
    $("#trades").innerHTML = ts.map(t => `<div class="small">${new Date(t.at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}: ${nm(t.buyer_id)} bought ${t.shares} from ${nm(t.seller_id)} for ${cents(t.cents)}</div>`).join("") || `<span class="dim">None yet.</span>`;
  };
  const refreshAll = () => Promise.all([loadBook(), loadMine(), loadTrades()]).catch(e => { out.innerHTML = fail(e); });
  const refresh = async () => {
    const shares = parseInt(n.value, 10), s2 = ++seq; preview = null; go.disabled = true; out.innerHTML = "";
    if (!(shares > 0) || (kind === "limit" && !(parseFloat(lp.value) > 0))) { pv.innerHTML = ""; return; }
    try {
      const r = await rpc("place_order", { p_market: league.id, p_athlete: a.id, p_side: side, p_kind: kind, p_shares: shares,
        p_limit_cents: kind === "limit" ? Math.round(parseFloat(lp.value) * 100) : null, p_preview: true });
      if (s2 !== seq) return;
      preview = r; go.disabled = false;
      pv.innerHTML = r.filled > 0 ? `<span>${side === "buy" ? "Would cost" : "Would bring"}</span><b class="num">${cents(r.cents)}</b>
          <span>Fills now</span><span class="num">${r.filled} of ${r.shares}</span>
          <span>Average per share</span><span class="num">${cents(r.cents / r.filled)}</span>` : `<span class="dim">Nothing fills right now.</span><span></span>`;
      pv.innerHTML += kind === "limit" && r.waiting > 0 ? `<span>Waits in the book</span><span class="num">${r.waiting}</span>` : "";
      if (kind === "market" && r.dropped > 0) pv.innerHTML += `<span>Not ordered</span><span class="num">${r.dropped}</span>`;
      if (r.market_maker_out) pv.innerHTML += `<span class="dim">Market maker is out.</span><span></span>`;
    } catch (e) { if (s2 === seq) { pv.innerHTML = ""; out.innerHTML = fail(e); } }
  };
  go.onclick = async () => {
    if (!preview) return; go.disabled = true; const shares = parseInt(n.value, 10);
    try {
      const r = await rpc("place_order", { p_market: league.id, p_athlete: a.id, p_side: side, p_kind: kind, p_shares: shares,
        p_limit_cents: kind === "limit" ? Math.round(parseFloat(lp.value) * 100) : preview.worst_cents, p_preview: false });
      n.value = ""; pv.innerHTML = ""; preview = null;
      out.innerHTML = `<div class="msg ok">` + (r.filled ? `${side === "buy" ? "Bought" : "Sold"} ${r.filled} of ${r.shares} ${r.ticker} for ${cents(r.cents)}` : `Order placed: ${r.shares} ${r.ticker}`) +
        (r.waiting ? `; ${r.waiting} waiting in the book` : "") + (r.dropped ? `; ${r.dropped} not ordered` : "") + `.</div>`;
      refreshAll();
    } catch (e) { out.innerHTML = fail(e); refresh(); }
  };
  n.oninput = lp.oninput = refresh;
  $("#trade").onclick = e => {
    const d = e.target.dataset;
    if (d.s || d.k) {
      side = d.s || side; kind = d.k || kind; go.textContent = side === "buy" ? "Buy" : "Sell"; go.classList.toggle("sell", side === "sell");
      $("#trade").querySelectorAll("[data-s]").forEach(b => b.classList.toggle("on", b.dataset.s === side));
      $("#trade").querySelectorAll("[data-k]").forEach(b => b.classList.toggle("on", b.dataset.k === kind));
      lp.style.display = kind === "limit" ? "" : "none"; refresh();
    }
  };
  $("#mine").onclick = async e => { const c = e.target.dataset.c; if (!c) return; try { await rpc("cancel_order", { p_order: +c }); refreshAll(); } catch (err) { out.innerHTML = fail(err); } };
  await refreshAll();
  pollTimer = setInterval(() => { if (!document.hidden && my === token) Promise.all([loadBook(), loadMine(), loadTrades()]).catch(() => {}); }, 5000);
}

// ---- Portfolio
async function portfolio() {
  const my = ++token;
  await loadLeague(); if (!league) { view.innerHTML = needLeague(); return; }
  const [acct, list, lb] = await Promise.all([rpc("my_account", { p_market: league.id }), loadAthletes(), rpc("leaderboard", { p_market: league.id })]);
  if (my !== token) return;
  const by = Object.fromEntries(list.map(a => [a.id, a]));
  const me = lb.find(r => r.member_id === acct.member_id), worth = me ? me.net_worth_cents : acct.cash_cents;
  const gain = worth - league.starting_cents;
  view.innerHTML = `
    <div class="card"><div class="dim small">Net worth (if you sold everything now) ${help("winning")}</div><div class="big">${cents(worth)}</div>
      <div class="${cls(gain)}">${gain >= 0 ? "+" : ""}${cents(gain)} since the start</div>
      <div class="kv small" style="margin-top:8px"><span>Cash</span><span class="num">${cents(acct.cash_cents)}</span>
        <span>Set aside for waiting orders</span><span class="num">${cents(acct.set_aside_cents)}</span>
        <span>Free to spend</span><span class="num">${cents(acct.free_cents)}</span></div></div>
    <h2>Holdings</h2><div class="card">${acct.holdings.length ? `<table><tr><th>Athlete</th><th class="num">Shares</th><th class="num">Worth</th></tr>
      ${acct.holdings.map(h => { const a = by[h.athlete_id]; return `<tr><td><a href="#/athlete/${a.ticker}">${esc(a.name)}</a><div class="dim small">${a.ticker} · ${a.team}</div></td>
        <td class="num">${h.shares}${h.set_aside ? `<div class="dim small">${h.set_aside} for sale</div>` : ""}</td><td class="num">${cents(h.value_cents)}</td></tr>`; }).join("")}</table>` : `<span class="dim">Nothing yet. Pick an athlete on the Market screen.</span>`}</div>
    <h2>Open orders</h2><div id="oo" class="card">${acct.open_orders.map(o => { const a = by[o.athlete_id]; return `<div class="kv small"><span>${o.side === "buy" ? "Buy" : "Sell"} ${o.remaining} <a href="#/athlete/${a.ticker}">${a.ticker}</a> at ${cents(o.limit_cents)}</span><button class="chip small" data-c="${o.id}">Cancel</button></div>`; }).join("") || `<span class="dim">None.</span>`}</div><div id="out"></div>`;
  $("#oo").onclick = async e => { const c = e.target.dataset.c; if (!c) return; try { await rpc("cancel_order", { p_order: +c }); portfolio(); } catch (err) { $("#out").innerHTML = fail(err); } };
}

// ---- League: leaderboard, tap a player for holdings
async function leaguePage(arg) {
  const my = ++token;
  await loadLeague(); if (!league) { view.innerHTML = needLeague(); return; }
  if (arg) return player(decodeURIComponent(arg), my);
  const lb = await rpc("leaderboard", { p_market: league.id }); if (my !== token) return;
  const week = iso => Math.max(1, Math.ceil((new Date(iso) - new Date(league.starts_on + "T00:00:00")) / 6048e5));
  view.innerHTML = `<div class="dim small">${esc(league.name)} · ${day(league.starts_on)} to ${day(league.ends_on)} · code ${league.join_code}</div>
    <div class="card"><table><tr><th>#</th><th>Player</th><th class="num">Net worth</th></tr>
    ${lb.map((r, i) => `<tr><td>${i + 1}</td><td><a href="#/league/${r.member_id}">${esc(r.display_name)}</a>${week(r.joined_at) > 1 ? `<div class="dim small">joined week ${week(r.joined_at)}</div>` : ""}</td>
      <td class="num">${cents(r.net_worth_cents)}<div class="dim small ${cls(r.net_worth_cents - league.starting_cents)}">${r.net_worth_cents >= league.starting_cents ? "+" : ""}${cents(r.net_worth_cents - league.starting_cents)}</div></td></tr>`).join("")}</table></div>`;
}
async function player(id, my) {
  const [ts, list] = await Promise.all([q(sb.from("trades").select("athlete_id,shares,buyer_id,seller_id,at,cents").eq("market_id", league.id).or(`buyer_id.eq.${id},seller_id.eq.${id}`).order("at", { ascending: false })), loadAthletes()]);
  if (my !== token) return;
  const by = Object.fromEntries(list.map(a => [a.id, a])), held = {};
  ts.forEach(t => held[t.athlete_id] = (held[t.athlete_id] || 0) + (t.buyer_id === id ? t.shares : -t.shares));
  view.innerHTML = `<a class="back" href="#/league">‹ League</a><h2 style="margin-top:0">${esc(names[id]?.display_name || "Player")}</h2>
    <div class="card"><b>Holdings</b>${Object.entries(held).filter(([, s]) => s > 0).map(([a, s]) => `<div class="kv small"><span>${esc(by[a].name)} <span class="dim">${by[a].ticker}</span></span><span class="num">${s} sh</span></div>`).join("") || `<div class="dim">None.</div>`}</div>
    <div class="card"><b>Recent trades</b>${ts.slice(0, 15).map(t => `<div class="small">${new Date(t.at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}: ${t.buyer_id === id ? "bought" : "sold"} ${t.shares} ${by[t.athlete_id].ticker} for ${cents(t.cents)}</div>`).join("") || `<div class="dim">None.</div>`}</div>`;
}

// ---- Morning report
async function report() {
  const my = ++token;
  await loadLeague(); if (!league) { view.innerHTML = needLeague(); return; }
  const rows = await q(sb.from("reports").select("day,body").eq("market_id", league.id).order("day", { ascending: false }).limit(1)); if (my !== token) return;
  if (!rows.length) { view.innerHTML = `<div class="card dim">No report yet. The first one arrives the morning after the first games.</div>`; return; }
  const { day: d, body: r } = rows[0], list = await loadAthletes(); if (my !== token) return;
  const by = Object.fromEntries(list.map(a => [a.id, a]));
  const mover = m => `<tr><td>${esc(m.name)} <span class="dim small">${m.ticker}</span></td><td class="num">${money(m.before)} → ${money(m.after)}</td><td class="num ${cls(m.change)}">${m.change > 0 ? "+" : ""}${(m.change * 100).toFixed(1)}%</td></tr>`;
  view.innerHTML = `<h2 style="margin-top:0">Report for games on ${day(d)}</h2>
    ${r.games?.length ? `<div class="card small">${r.games.map(esc).join("<br>")}</div>` : ""}
    <div class="card"><b>Players</b><table>${(r.players || []).map(p => `<tr><td>${esc(p.display_name)}</td><td class="num dim">+${cents(p.dividend_cents)} dividends</td><td class="num">${cents(p.net_worth_cents)}</td></tr>`).join("")}</table></div>
    ${(r.overnight_fills || []).length ? `<div class="card"><b>Filled overnight</b>${r.overnight_fills.map(f => `<div class="small">${esc(f.display_name)}'s ${f.side === "buy" ? "buy" : "sale"} of ${f.shares} ${esc(f.ticker)}${f.kind === "limit" ? ` at ${cents(f.limit_cents)}` : ""} filled at ${cents(f.cents / f.shares)} overnight</div>`).join("")}</div>` : ""}
    ${(r.top_dividends || []).length ? `<div class="card"><b>Biggest dividends</b><table>${r.top_dividends.map(t => `<tr><td>${esc(t.name)} <span class="dim small">${t.ticker}</span></td><td class="num">${t.points.toFixed(2)} pts</td><td class="num">${money(t.per_share, 3)}/sh</td></tr>`).join("")}</table></div>` : ""}
    ${(r.gainers || []).length ? `<div class="card"><b>Biggest rises</b><table>${r.gainers.map(mover).join("")}</table></div><div class="card"><b>Biggest falls</b><table>${(r.losers || []).map(mover).join("")}</table></div>` : ""}
    ${(r.busiest || []).length ? `<div class="card"><b>Busiest stocks</b>${r.busiest.map(b => `<div class="small">${esc(b.name)} ${b.ticker}: ${b.shares} shares in ${b.trades} trades</div>`).join("")}</div>` : ""}
    ${(r.group_checks || []).length ? `<div class="card"><b>Weekly group re-check</b>${r.group_checks.map(c => `<div class="small">${esc(c.group)}: paid ${c.ratio == null ? "n/a" : Math.round(c.ratio * 100) + "%"} of promise</div>`).join("")}</div>` : ""}
    <div class="helpline dim">What happens overnight: <a href="#/rules/day">a day in the game</a></div>`;
}

// ---- How it works (same page as web/rules.html)
async function rules(section) {
  const my = ++token;
  const page = new DOMParser().parseFromString(await (await fetch("rules.html")).text(), "text/html");
  if (my !== token) return;
  view.innerHTML = `<div class="rules">${page.querySelector("main").innerHTML}</div>`;
  view.querySelectorAll('.rules a[href^="#"]:not([href^="#/"])').forEach(a => { a.href = "#/rules/" + a.getAttribute("href").slice(1); });
  const target = section && document.getElementById(section);
  if (target) target.scrollIntoView();
}

// ---- Banner: a day before today (Eastern) still has an unprocessed game after 10 a.m. Eastern
async function banner() {
  try {
    const f = (o) => new Intl.DateTimeFormat("en-US", { timeZone: "America/New_York", ...o });
    const today = easternToday();
    const hour = +f({ hour: "numeric", hour12: false }).format(new Date()) % 24;
    const [late, st] = await Promise.all([
      q(sb.from("games").select("id,status").eq("season_id", SS.season).lt("day", today).is("processed_at", null)),
      q(sb.from("robot_status").select("stop_reason").eq("season_id", SS.season))]);
    const pending = late.filter(g => !["postponed", "cancelled", "canceled"].includes(String(g.status).toLowerCase()));
    $("#banner").innerHTML = pending.length && hour >= 10 ?
      `<div class="warn"><b>Overnight update delayed.</b> ${esc(st[0]?.stop_reason || "The overnight update hasn't run yet")}. Prices and dividends will catch up when it does.</div>` : "";
  } catch (e) { $("#banner").innerHTML = ""; }
}

function route() {
  clearInterval(pollTimer);
  if (!user) { document.querySelectorAll("nav a").forEach(a => a.classList.remove("on")); return signin(); }
  const [, tab, arg] = (location.hash || "#/market").split("/");
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.tab === (tab === "athlete" ? "market" : tab)));
  window.scrollTo(0, 0);
  const run = tab === "athlete" ? () => athlete(decodeURIComponent(arg)) : tab === "portfolio" ? portfolio : tab === "league" ? () => leaguePage(arg) :
    tab === "leagues" ? leagues : tab === "report" ? report : tab === "rules" ? () => rules(arg) : market;
  run().catch(e => { view.innerHTML = fail(e); });
}
async function start() {
  const { data } = await sb.auth.getSession();
  user = data.session?.user || null;
  $("#season").textContent = SS.season;
  if (user) { await loadLeague().catch(() => {}); banner();
    if (new URLSearchParams(location.search).get("join")) location.hash = "#/leagues"; }
  route();
}
window.addEventListener("hashchange", route);
start();
