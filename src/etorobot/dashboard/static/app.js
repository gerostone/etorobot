// Minimal dashboard client: token handling, fetch, SSE live updates.
function getToken() {
  let t = localStorage.getItem("dashboard_token");
  if (t === null) {
    t = window.prompt("Dashboard token (dejar vacío si no hay):") || "";
    localStorage.setItem("dashboard_token", t);
  }
  return t;
}
const TOKEN = getToken();
const authHeaders = TOKEN ? { Authorization: "Bearer " + TOKEN } : {};
const tokenQuery = TOKEN ? "?token=" + encodeURIComponent(TOKEN) : "";

async function apiGet(path) {
  const r = await fetch(path, { headers: authHeaders });
  if (r.status === 401) {
    localStorage.removeItem("dashboard_token");
    throw new Error("unauthorized");
  }
  if (!r.ok) throw new Error("HTTP " + r.status);
  return r.json();
}

function td(v) { const c = document.createElement("td"); c.textContent = v; return c; }

function badge(status, stale) {
  const span = document.createElement("span");
  const kind = stale ? "stale" : status;
  span.className = "badge " + kind;
  span.textContent = stale ? "stale" : status;
  return span;
}

async function renderList() {
  const runs = await apiGet("/api/runs");
  const tbody = document.querySelector("#runs tbody");
  tbody.innerHTML = "";
  for (const r of runs) {
    const tr = document.createElement("tr");
    const idCell = document.createElement("td");
    const link = document.createElement("a");
    link.href = "/run.html?id=" + r.id; link.textContent = r.id;
    idCell.appendChild(link); tr.appendChild(idCell);
    tr.appendChild(td(r.mode));
    tr.appendChild(td(r.strategy));
    tr.appendChild(td(r.instruments));
    const st = document.createElement("td");
    st.appendChild(badge(r.status, r.stale)); tr.appendChild(st);
    tr.appendChild(td(r.num_trades));
    tr.appendChild(td((r.total_return * 100).toFixed(2) + "%"));
    tr.appendChild(td(r.started_at || ""));
    tbody.appendChild(tr);
  }
}

let chart = null;
function ensureChart() {
  if (chart) return chart;
  const ctx = document.getElementById("equityChart").getContext("2d");
  chart = new Chart(ctx, {
    type: "line",
    data: { labels: [], datasets: [{ label: "Equity", data: [],
            borderColor: "#5aa9ff", tension: 0.1 }] },
    options: { animation: false, scales: { x: { display: false } } },
  });
  return chart;
}
function pushEquity(rows) {
  const c = ensureChart();
  for (const e of rows) { c.data.labels.push(e.timestamp); c.data.datasets[0].data.push(e.equity); }
  c.update();
}

function renderMetrics(m) {
  const wrap = document.getElementById("metrics");
  wrap.innerHTML = "";
  const items = [
    ["Total return", (m.total_return * 100).toFixed(2) + "%"],
    ["Max drawdown", (m.max_drawdown * 100).toFixed(2) + "%"],
    ["Sharpe", m.sharpe.toFixed(2)],
    ["Trades", m.num_trades],
    ["Win rate", (m.win_rate * 100).toFixed(1) + "%"],
  ];
  for (const [label, value] of items) {
    const d = document.createElement("div"); d.className = "metric";
    d.innerHTML = '<div>' + label + '</div><div class="value">' + value + '</div>';
    wrap.appendChild(d);
  }
}

function appendFill(f) {
  const tbody = document.querySelector("#fills tbody");
  const tr = document.createElement("tr");
  [f.id, f.action, f.symbol, f.price, f.units, f.amount, f.commission,
   f.position_id, f.timestamp].forEach((v) => tr.appendChild(td(v)));
  tbody.appendChild(tr);
}
function appendSignal(s) {
  const tbody = document.querySelector("#signals tbody");
  const tr = document.createElement("tr");
  [s.id, s.direction, s.symbol, s.accepted, s.reason || "",
   s.timestamp].forEach((v) => tr.appendChild(td(v)));
  tbody.appendChild(tr);
}

async function renderRun() {
  const id = new URLSearchParams(location.search).get("id");
  document.getElementById("runId").textContent = id;
  const rep = await apiGet("/api/runs/" + id);
  document.getElementById("statusBadge").appendChild(
    badge(rep.run.status, rep.run.stale));
  renderMetrics(rep.metrics);
  pushEquity(rep.equity);
  rep.fills.forEach(appendFill);
  rep.signals.forEach(appendSignal);
  if (rep.run.status === "running") openStream(id);
}

function openStream(id) {
  const es = new EventSource("/api/runs/" + id + "/stream" + tokenQuery);
  es.addEventListener("fill", (e) => appendFill(JSON.parse(e.data)));
  es.addEventListener("signal", (e) => appendSignal(JSON.parse(e.data)));
  es.addEventListener("equity", (e) => pushEquity([JSON.parse(e.data)]));
  es.addEventListener("run_status", (e) => {
    es.close();
    const s = JSON.parse(e.data).status;
    const badgeEl = document.getElementById("statusBadge");
    badgeEl.innerHTML = ""; badgeEl.appendChild(badge(s, false));
  });
}

if (window.VIEW === "list") renderList().catch((e) => alert(e.message));
else if (window.VIEW === "run") renderRun().catch((e) => alert(e.message));
