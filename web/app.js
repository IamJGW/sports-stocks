// Screens only. Every price, total and balance comes from the Python server; nothing here works out money.
const $ = (s, el = document) => el.querySelector(s);
const view = $("#view");
const money = (n, d = 2) => (n < 0 ? "-" : "") + "$" + Math.abs(n).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d });
const cents = c => money(c / 100);
const esc = s => String(s ?? "").replace(/[&<>"]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const pct = x => x == null ? "–" : (x > 0 ? "+" : "") + (x * 100).toFixed(1) + "%";
const cls = x => x > 0 ? "up" : x < 0 ? "down" : "dim";
const get = async url => (await fetch(url)).json();
const when = iso => iso ? new Date(iso).toLocaleString("en-US", { weekday: "short", hour: "numeric", minute: "2-digit" }) : "–";
const help = sec => `<a class="help" href="#/rules/${sec}" title="How this works">?</a>`;
let token = 0;   // a screen that has been left must not paint over the next one

async function market() {
  const my = ++token;
  const { athletes } = await get("/api/market");
  if (my !== token) return;
  const st = market.state ||= { pos: "All", q: "", sort: "price" };
  view.innerHTML = `
    <div class="bar"><input type="search" id="q" placeholder="Search name, team or ticker" value="${esc(st.q)}"></div>
    <div class="bar" id="pos">${["All", "QB", "RB", "WR", "TE", "Mine"].map(p => `<button class="chip ${p === st.pos ? "on" : ""}" data-p="${p}">${p}</button>`).join("")}
      <select id="sort"><option value="price">Highest price</option><option value="change">Biggest change</option><option value="last">Last game</option><option value="name">Name</option></select></div>
    <div id="list"></div>`;
  $("#sort").value = st.sort;
  const draw = () => {
    const q = st.q.toLowerCase();
    let rows = athletes.filter(a => (st.pos === "All" || (st.pos === "Mine" ? a.mine > 0 : a.pos === st.pos)) &&
      (!q || (a.name + " " + a.team + " " + a.ticker).toLowerCase().includes(q)));
    const key = { price: a => -a.buy, change: a => -(a.change ?? -9), last: a => -(a.last_points ?? -99), name: a => a.name };
    rows.sort((a, b) => key[st.sort](a) > key[st.sort](b) ? 1 : -1);
    $("#list").innerHTML = rows.map(a => `
      <a class="row" href="#/athlete/${a.ticker}">
        <span class="t">${esc(a.name)} <span class="dim small">${a.ticker}</span></span>
        <span class="num">${money(a.buy)}</span><span class="num ${cls(a.change)}">${pct(a.change)}</span>
        <span class="sub">${a.team} · ${a.pos} · sell ${money(a.sell)} · last game ${a.last_points == null ? "–" : a.last_points.toFixed(1) + " pts"} ·
          ${a.in_game ? "<b>in game</b>" : "next " + when(a.next_kickoff)}${a.mine ? ` · <b>you hold ${a.mine}</b>` : ""}</span>
      </a>`).join("") || `<p class="dim">No athletes match.</p>`;
  };
  $("#q").oninput = e => { st.q = e.target.value; draw(); };
  $("#sort").onchange = e => { st.sort = e.target.value; draw(); };
  $("#pos").onclick = e => { const p = e.target.dataset.p; if (!p) return; st.pos = p; [...$("#pos").querySelectorAll(".chip")].forEach(b => b.classList.toggle("on", b.dataset.p === p)); draw(); };
  draw();
}

function spark(canvas, vals) {
  if (vals.length < 2) return;
  const r = devicePixelRatio || 1, w = canvas.width = canvas.clientWidth * r, h = canvas.height = canvas.clientHeight * r;
  const lo = Math.min(...vals), hi = Math.max(...vals), c = canvas.getContext("2d");
  c.strokeStyle = getComputedStyle(document.body).getPropertyValue("--accent") || "#1f6feb";
  c.lineWidth = 2 * r; c.beginPath();
  vals.forEach((v, i) => { const x = i / (vals.length - 1) * w, y = h - 4 * r - (hi === lo ? .5 : (v - lo) / (hi - lo)) * (h - 8 * r); i ? c.lineTo(x, y) : c.moveTo(x, y); });
  c.stroke();
}

async function athlete(ticker) {
  const my = ++token;
  const a = await get("/api/athlete?ticker=" + encodeURIComponent(ticker));
  if (my !== token) return;
  if (a.ok === false) { view.innerHTML = `<a class="back" href="#/market">‹ Market</a><div class="msg">${esc(a.message)}</div>`; return; }
  let side = "buy", seq = 0, preview = null;
  const here = location.hash;
  view.innerHTML = `
    <a class="back" href="#/market">‹ Market</a>
    <div class="card"><div class="big">${esc(a.name)}</div>
      <div class="dim">${a.ticker} · ${a.team} · ${a.pos}</div>
      <div class="kv" style="margin-top:8px"><span>Buy at</span><b class="num">${money(a.buy)}</b>
        <span>Sell at</span><b class="num">${money(a.sell)}</b>
        <span>Fair value ${help("prices")}</span><span class="num">${money(a.fair_value)} <span class="dim small">(started ${money(a.start_price)})</span></span>
        <span>You hold</span><b class="num">${a.mine} shares</b>
        <span>Next game</span><span class="num">${when(a.next_kickoff)}</span></div>
      <canvas id="sp"></canvas></div>
    <div class="card" id="trade">
      ${a.in_game ? `<div class="notice"><b>In a game.</b> ${esc(a.in_game_note)}</div>` : ""}
      <div class="seg"><button class="chip on" data-s="buy">Buy</button><button class="chip" data-s="sell">Sell</button></div>
      <div class="bar"><input type="number" id="n" min="1" step="1" inputmode="numeric" placeholder="Shares" style="flex:1" ${a.in_game ? "disabled" : ""}>
        <button class="chip" id="all"></button></div>
      <div id="pv" class="kv small" style="min-height:70px"></div>
      <div id="out"></div>
      <button class="go" id="go" disabled>Buy</button>
      <div class="helpline dim">Why big orders cost more, and when you can't trade: <a href="#/rules/trading">how buying and selling works</a></div></div>
    <h2>Game log ${help("dividends")}</h2>
    <div class="card">${a.log.length ? `<table><tr><th>Wk</th><th>Opp</th><th class="num">Pts</th><th class="num">Per share</th><th class="num">You got</th></tr>
      ${a.log.map(g => `<tr><td>${g.week}</td><td>${g.away ? "@" : "vs"} ${g.opponent}</td><td class="num">${g.points.toFixed(2)}</td>
        <td class="num">${money(g.per_share, 3)}</td><td class="num">${g.my_shares ? cents(g.my_cents) + ` <span class="dim small">(${g.my_shares})</span>` : "–"}</td></tr>`).join("")}</table>`
      : `<span class="dim">No games yet this season.</span>`}</div>`;
  spark($("#sp"), a.values.map(v => v.fair_value));
  const n = $("#n"), go = $("#go"), pv = $("#pv"), out = $("#out"), all = $("#all");
  const setSide = s => {
    side = s; preview = null; go.textContent = s === "buy" ? "Buy" : "Sell"; go.classList.toggle("sell", s === "sell");
    [...document.querySelectorAll(".seg .chip")].forEach(b => b.classList.toggle("on", b.dataset.s === s));
    all.textContent = s === "buy" ? "All in" : "Sell all"; all.disabled = a.in_game; n.value = ""; out.innerHTML = ""; go.disabled = true; pv.innerHTML = "";
  };
  const refresh = async () => {
    const shares = parseInt(n.value, 10), my2 = ++seq; preview = null; go.disabled = true; out.innerHTML = "";
    if (!(shares > 0)) { pv.innerHTML = ""; return; }
    const q = await get(`/api/quote?ticker=${a.ticker}&side=${side}&shares=${shares}`);
    if (my2 !== seq) return;
    if (!q.ok) { pv.innerHTML = ""; out.innerHTML = `<div class="msg">${esc(q.message)}</div>`; return; }
    preview = q; go.disabled = false;
    pv.innerHTML = `<span>${side === "buy" ? "Total cost" : "You receive"}</span><b class="num">${cents(q.total_cents)}</b>
      <span>Average per share</span><span class="num">${money(q.average)}</span>
      <span>His price after</span><span class="num">${money(q.price_after)}</span>`;
  };
  n.oninput = refresh;
  $(".seg").onclick = e => { if (e.target.dataset.s) setSide(e.target.dataset.s); };
  all.onclick = () => { n.value = side === "buy" ? a.max_buy : a.mine; if (+n.value > 0) refresh(); };
  go.onclick = async () => {
    if (!preview) return; go.disabled = true;
    const r = await (await fetch("/api/trade", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ticker: a.ticker, side, shares: preview.shares, expect_cents: preview.expect_cents }) })).json();
    if (!r.ok) { out.innerHTML = `<div class="msg">${esc(r.message)}</div>`; refresh(); return; }
    if (location.hash !== here) return;   // they have moved on to another screen
    await athlete(ticker);
    $("#out").innerHTML = `<div class="msg ok">${side === "buy" ? "Bought" : "Sold"} ${r.shares} ${r.ticker} for ${cents(r.cents)}.</div>`;
  };
  setSide("buy");
}

async function portfolio() {
  const my = ++token;
  const p = await get("/api/portfolio");
  if (my !== token) return;
  const gain = p.net_worth_cents - p.starting_cents;
  view.innerHTML = `
    <div class="card"><div class="dim small">Net worth (if you sold everything now) ${help("winning")}</div><div class="big">${cents(p.net_worth_cents)}</div>
      <div class="${cls(gain)}">${gain >= 0 ? "+" : ""}${cents(gain)} since the start</div>
      <div class="kv small" style="margin-top:8px"><span>Cash</span><span class="num">${cents(p.cash_cents)}</span>
        <span>Holdings</span><span class="num">${cents(p.holdings_cents)}</span>
        <span>Dividends earned ${help("dividends")}</span><span class="num">${cents(p.dividends_cents)}</span></div></div>
    <h2>Holdings</h2>
    <div class="card">${p.holdings.length ? `<table><tr><th>Athlete</th><th class="num">Shares</th><th class="num">Avg cost</th><th class="num">Worth</th><th class="num">Dividends</th></tr>
      ${p.holdings.map(h => `<tr><td><a href="#/athlete/${h.ticker}">${esc(h.name)}</a><div class="dim small">${h.ticker} · ${h.team}${h.in_game ? " · in game" : ""}</div></td>
        <td class="num">${h.shares}</td><td class="num">${money(h.avg_cost)}</td><td class="num">${cents(h.value_cents)}</td><td class="num">${cents(h.dividend_cents)}</td></tr>`).join("")}</table>`
      : `<span class="dim">Nothing yet. Pick an athlete on the Market screen.</span>`}</div>
    <h2>Activity</h2>
    <div class="card">${p.activity.length ? `<table>${p.activity.map(a => `<tr><td>${new Date(a.at).toLocaleString("en-US", { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" })}</td>
      <td>${a.kind === "trade" ? (a.shares > 0 ? "Bought " : "Sold ") + Math.abs(a.shares) : "Dividend, " + a.shares + " sh"} ${a.ticker}</td>
      <td class="num ${cls(a.cents)}">${cents(a.cents)}</td></tr>`).join("")}</table>` : `<span class="dim">No activity yet.</span>`}</div>`;
}

async function report() {
  const my = ++token;
  const r = await get("/api/report");
  if (my !== token) return;
  view.innerHTML = `<div class="card"><pre>${esc(r.text)}</pre></div>
    <div class="helpline dim">What happens overnight: <a href="#/rules/day">a day in the game</a></div>`;
}

// How it works: the same page as web/rules.html (built from the game's settings), shown inside the app.
async function rules(section) {
  const my = ++token;
  const page = new DOMParser().parseFromString(await (await fetch("/rules.html")).text(), "text/html");
  if (my !== token) return;
  view.innerHTML = `<div class="rules">${page.querySelector("main").innerHTML}</div>`;
  // Its contents links (#trading) would otherwise be read as a change of screen.
  view.querySelectorAll('.rules a[href^="#"]:not([href^="#/"])').forEach(a => {
    a.href = "#/rules/" + a.getAttribute("href").slice(1);
  });
  const target = section && document.getElementById(section);
  if (target) target.scrollIntoView();
}

function route() {
  const [, tab, arg] = (location.hash || "#/market").split("/");
  document.querySelectorAll("nav a").forEach(a => a.classList.toggle("on", a.dataset.tab === (tab === "athlete" ? "market" : tab)));
  window.scrollTo(0, 0);
  const run = tab === "athlete" ? () => athlete(decodeURIComponent(arg)) : tab === "portfolio" ? portfolio :
    tab === "report" ? report : tab === "rules" ? () => rules(arg) : market;
  run().catch(e => { view.innerHTML = `<div class="msg">Couldn't load this screen: ${esc(e.message)}</div>`; });
}
window.addEventListener("hashchange", route);
get("/api/status").then(s => { $("#season").textContent = `${s.season} ${s.sport}` + (s.last_update ? ` · updated through ${s.last_update}` : ""); });
route();
