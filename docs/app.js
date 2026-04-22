let equityChart = null
let priceChart = null

async function loadJson(path) {
  const res = await fetch(path + "?t=" + Date.now(), { cache: "no-store" })
  if (!res.ok) throw new Error("Failed to load " + path)
  return await res.json()
}

function setText(id, value) {
  const el = document.getElementById(id)
  if (el) el.textContent = value
}

function fmt(v) {
  if (v === null || v === undefined || v === "" || Number.isNaN(v)) return "-"
  return v
}

function num(v, digits = 2) {
  if (v === null || v === undefined || v === "" || Number.isNaN(Number(v))) return "-"
  return Number(v).toFixed(digits)
}

function kv(label, value) {
  return `<div class="info-label">${label}</div><div>${value}</div>`
}

function pill(value) {
  const v = String(value || "").toLowerCase()
  const cls = v.includes("bull")
    ? "pill pill-bull"
    : v.includes("bear")
    ? "pill pill-bear"
    : "pill pill-chop"
  return `<span class="${cls}">${value}</span>`
}

function pnlClass(v) {
  const n = Number(v)
  if (Number.isNaN(n)) return ""
  if (n > 0) return "text-green"
  if (n < 0) return "text-red"
  return "text-muted"
}

function buildEquityChart() {
  const ctx = document.getElementById("equityChart").getContext("2d")
  if (equityChart) equityChart.destroy()

  equityChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [{ label: "Cum R", data: [], tension: 0.2 }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false
    }
  })
}

function updateEquityChart(rows) {
  if (!equityChart) buildEquityChart()
  equityChart.data.labels = rows.map((x, i) => x.trade_id ?? i + 1)
  equityChart.data.datasets[0].data = rows.map(x => x.cum_r ?? 0)
  equityChart.update("none")
}

function buildPriceChart() {
  const ctx = document.getElementById("priceChart").getContext("2d")
  if (priceChart) priceChart.destroy()

  priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        { label: "Close", data: [], tension: 0.15 },
        { label: "EMA9", data: [], tension: 0.15 },
        { label: "EMA21", data: [], tension: 0.15 }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false
    }
  })
}

function updatePriceChart(rows) {
  if (!priceChart) buildPriceChart()
  priceChart.data.labels = rows.map(x => (x.time || "").slice(11, 16))
  priceChart.data.datasets[0].data = rows.map(x => x.close)
  priceChart.data.datasets[1].data = rows.map(x => x.ema9)
  priceChart.data.datasets[2].data = rows.map(x => x.ema21)
  priceChart.update("none")
}

function renderContext(context) {
  document.getElementById("context-grid").innerHTML =
    kv("Symbol", fmt(context.symbol)) +
    kv("Price", num(context.price)) +
    kv("Session", fmt(context.session)) +
    kv("Market State", pill(context.market_state || "unknown")) +
    kv("RSI", num(context.rsi)) +
    kv("ATR", num(context.atr)) +
    kv("EMA 9", num(context.ema9)) +
    kv("EMA 21", num(context.ema21)) +
    kv("EMA 50", num(context.ema50)) +
    kv("Active Models", (context.active_models || []).join(", ") || "-")
}

function renderRegimes(context) {
  document.getElementById("regime-grid").innerHTML =
    kv("5m", `${fmt(context.regime_5m)} (${fmt(context.confidence_5m)})`) +
    kv("1h", `${fmt(context.regime_1h)} (${fmt(context.confidence_1h)})`) +
    kv("4h", `${fmt(context.regime_4h)} (${fmt(context.confidence_4h)})`)
}

function renderScenario(scenario) {
  document.getElementById("scenario-grid").innerHTML =
    kv("Status", fmt(scenario.status)) +
    kv("Model", fmt(scenario.entry_model)) +
    kv("Side", fmt(scenario.side)) +
    kv("Playbook", fmt(scenario.playbook)) +
    kv("Entry", num(scenario.entry)) +
    kv("Stop", num(scenario.stop)) +
    kv("TP", num(scenario.tp)) +
    kv("RR", num(scenario.rr)) +
    kv("Invalidation", fmt(scenario.invalidation)) +
    kv("Confirmation", fmt(scenario.confirmation))
}

function renderOpenTrade(openTrade) {
  const target = document.getElementById("open-trade-grid")
  if (!openTrade || !openTrade.has_open_trade) {
    target.innerHTML = `<div class="empty-state">No open trade</div>`
    return
  }

  target.innerHTML =
    kv("Model", fmt(openTrade.model)) +
    kv("Side", fmt(openTrade.side)) +
    kv("Entry", num(openTrade.entry)) +
    kv("Stop", num(openTrade.stop)) +
    kv("TP", num(openTrade.tp)) +
    kv("RR", num(openTrade.rr)) +
    kv("Current Price", num(openTrade.current_price)) +
    kv("Unrealized R", `<span class="${pnlClass(openTrade.unrealized_r)}">${num(openTrade.unrealized_r)}</span>`) +
    kv("Bars Held", fmt(openTrade.bars_held)) +
    kv("Opened At", fmt(openTrade.opened_at))
}

function renderModels(models) {
  const target = document.getElementById("models-table")
  if (!models || !models.length) {
    target.innerHTML = `<div class="empty-state">No model stats yet</div>`
    return
  }

  target.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>Model</th>
          <th>Trades</th>
          <th>WR</th>
          <th>Avg R</th>
          <th>Net R</th>
        </tr>
      </thead>
      <tbody>
        ${models.map(m => `
          <tr>
            <td>${fmt(m.model)}</td>
            <td>${fmt(m.trades)}</td>
            <td>${num(m.winrate, 2)}%</td>
            <td class="${pnlClass(m.avg_r)}">${num(m.avg_r, 3)}</td>
            <td class="${pnlClass(m.net_r)}">${num(m.net_r, 2)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `
}

function renderSignals(signals) {
  const target = document.getElementById("signals-list")
  if (!signals || !signals.length) {
    target.innerHTML = `<div class="empty-state">No recent signals</div>`
    return
  }

  target.innerHTML = signals.slice(0, 8).map(s => `
    <div class="signal-card">
      <div class="signal-top">
        <div class="signal-model">${fmt(s.model)}</div>
        <div class="signal-status">${fmt(s.status)}</div>
      </div>
      <div class="signal-meta">
        <span>${fmt(s.side)}</span>
        <span>${fmt(s.market_state)}</span>
        <span>${fmt(s.time)}</span>
      </div>
    </div>
  `).join("")
}

function renderTrades(trades) {
  const target = document.getElementById("trades-table")
  if (!trades || !trades.length) {
    target.innerHTML = `<div class="empty-state">No trades yet</div>`
    return
  }

  target.innerHTML = `
    <table class="data-table">
      <thead>
        <tr>
          <th>Time</th>
          <th>Model</th>
          <th>Side</th>
          <th>Entry</th>
          <th>Exit</th>
          <th>R</th>
          <th>Reason</th>
        </tr>
      </thead>
      <tbody>
        ${trades.slice().reverse().slice(0, 25).map(t => `
          <tr>
            <td>${fmt(t.closed_at || t.opened_at)}</td>
            <td>${fmt(t.model)}</td>
            <td>${fmt(t.side)}</td>
            <td>${num(t.entry)}</td>
            <td>${num(t.exit_price)}</td>
            <td class="${pnlClass(t.result_r)}">${num(t.result_r, 3)}</td>
            <td>${fmt(t.close_reason)}</td>
          </tr>
        `).join("")}
      </tbody>
    </table>
  `
}

async function refreshDashboard() {
  try {
    const summary = await loadJson("summary.json")
    const equity = await loadJson("equity.json")
    const trades = await loadJson("trades.json")
    const signals = await loadJson("signals.json")
    const models = await loadJson("models.json")
    const context = await loadJson("context.json")
    const scenario = await loadJson("scenario.json")
    const openTrade = await loadJson("open_trade.json")
    const priceRows = await loadJson("price_chart.json")

    setText("status-pill", summary.status || "ready")
    setText("last-update", "Updated: " + (summary.last_update_utc || "-"))
    setText("metric-market", context.symbol || summary.market || "-")
    setText("metric-trades", summary.total_trades ?? 0)
    setText("metric-winrate", (summary.winrate ?? 0) + "%")
    setText("metric-avg-r", summary.avg_r ?? 0)
    setText("metric-net-r", summary.net_r ?? 0)
    setText("metric-max-dd", summary.max_dd_r ?? 0)

    renderContext(context)
    renderRegimes(context)
    renderScenario(scenario)
    renderOpenTrade(openTrade)
    renderModels(models)
    renderSignals(signals)
    renderTrades(trades)
    updateEquityChart(Array.isArray(equity) ? equity : [])
    updatePriceChart(Array.isArray(priceRows) ? priceRows : [])
  } catch (err) {
    console.error(err)
    setText("status-pill", "error")
    setText("last-update", "Dashboard data missing or invalid")
  }
}

window.addEventListener("load", async () => {
  buildEquityChart()
  buildPriceChart()
  await refreshDashboard()
})
