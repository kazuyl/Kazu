let equityChart = null
let priceChart = null

async function loadJson(path) {
  const res = await fetch(path + "?t=" + Date.now(), { cache: "no-store" })
  if (!res.ok) {
    throw new Error("Failed to load " + path)
  }
  return await res.json()
}

function setText(id, value) {
  const el = document.getElementById(id)
  if (el) el.textContent = value
}

function kv(label, value) {
  return `
    <div class="info-label">${label}</div>
    <div>${value ?? "-"}</div>
  `
}

function pill(value) {
  const v = (value || "").toLowerCase()
  const cls = v.includes("bull")
    ? "pill pill-bull"
    : v.includes("bear")
    ? "pill pill-bear"
    : "pill pill-chop"
  return `<span class="${cls}">${value}</span>`
}

function buildEquityChart() {
  const canvas = document.getElementById("equityChart")
  const ctx = canvas.getContext("2d")

  if (equityChart) {
    equityChart.destroy()
  }

  equityChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Cum R",
          data: [],
          tension: 0.2
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      animation: false
    }
  })
}

function updateEquityChart(equity) {
  if (!equityChart) {
    buildEquityChart()
  }

  equityChart.data.labels = equity.map((x, i) => x.trade_id ?? i + 1)
  equityChart.data.datasets[0].data = equity.map(x => x.cum_r ?? 0)
  equityChart.update("none")
}

function buildPriceChart() {
  const canvas = document.getElementById("priceChart")
  const ctx = canvas.getContext("2d")

  if (priceChart) {
    priceChart.destroy()
  }

  priceChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: [],
      datasets: [
        {
          label: "Close",
          data: [],
          tension: 0.15
        },
        {
          label: "EMA9",
          data: [],
          tension: 0.15
        },
        {
          label: "EMA21",
          data: [],
          tension: 0.15
        }
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
  if (!priceChart) {
    buildPriceChart()
  }

  priceChart.data.labels = rows.map(x => (x.time || "").slice(11, 16))
  priceChart.data.datasets[0].data = rows.map(x => x.close)
  priceChart.data.datasets[1].data = rows.map(x => x.ema9)
  priceChart.data.datasets[2].data = rows.map(x => x.ema21)
  priceChart.update("none")
}

function renderContext(context) {
  document.getElementById("context-grid").innerHTML =
    kv("Symbol", context.symbol) +
    kv("Price", context.price) +
    kv("Session", context.session) +
    kv("Market State", pill(context.market_state)) +
    kv("RSI", context.rsi) +
    kv("ATR", context.atr) +
    kv("EMA 9", context.ema9) +
    kv("EMA 21", context.ema21) +
    kv("EMA 50", context.ema50) +
    kv("Close vs EMA21 ATR", context.close_vs_ema21_atr) +
    kv("Range % ATR", context.range_pct_atr) +
    kv("Active Models", (context.active_models || []).join(", "))
}

function renderRegimes(context) {
  document.getElementById("regime-grid").innerHTML =
    kv("5m", `${context.regime_5m} (${context.confidence_5m})`) +
    kv("1h", `${context.regime_1h} (${context.confidence_1h})`) +
    kv("4h", `${context.regime_4h} (${context.confidence_4h})`)
}

function renderScenario(scenario) {
  document.getElementById("scenario-grid").innerHTML =
    kv("Status", scenario.status) +
    kv("Model", scenario.entry_model) +
    kv("Side", scenario.side) +
    kv("Playbook", scenario.playbook) +
    kv("Entry", scenario.entry) +
    kv("Stop", scenario.stop) +
    kv("TP", scenario.tp) +
    kv("RR", scenario.rr) +
    kv("Invalidation", scenario.invalidation) +
    kv("Confirmation", scenario.confirmation)
}

function renderOpenTrade(openTrade) {
  if (!openTrade || !openTrade.has_open_trade) {
    document.getElementById("open-trade-grid").innerHTML = kv("Status", "No open trade")
    return
  }

  document.getElementById("open-trade-grid").innerHTML =
    kv("Model", openTrade.model) +
    kv("Side", openTrade.side) +
    kv("Entry", openTrade.entry) +
    kv("Stop", openTrade.stop) +
    kv("TP", openTrade.tp) +
    kv("RR", openTrade.rr) +
    kv("Current Price", openTrade.current_price) +
    kv("Unrealized R", openTrade.unrealized_r) +
    kv("Bars Held", openTrade.bars_held) +
    kv("Opened At", openTrade.opened_at)
}

async function refreshDashboard() {
  try {
    const summary = await loadJson("summary.json")
    const equity = await loadJson("equity.json")
    const trades = await loadJson("trades.json")
    const signals = await loadJson("signals.json")
    const context = await loadJson("context.json")
    const scenario = await loadJson("scenario.json")
    const openTrade = await loadJson("open_trade.json")
    const priceRows = await loadJson("price_chart.json")
    const models = await loadJson("models.json")

    setText("status-pill", summary.status || "ready")
    setText("last-update", "Updated: " + (summary.last_update_utc || "-"))
    setText("metric-market", context.symbol || summary.market || "-")
    setText("metric-trades", summary.total_trades ?? 0)
    setText("metric-winrate", (summary.winrate ?? 0) + "%")
    setText("metric-avg-r", summary.avg_r ?? 0)
    setText("metric-net-r", summary.net_r ?? 0)

    document.getElementById("trades-table").textContent =
      trades && trades.length ? JSON.stringify(trades, null, 2) : "No trades yet"

    document.getElementById("signals-list").textContent =
      signals && signals.length ? JSON.stringify(signals, null, 2) : "No recent signals"

    document.getElementById("models-table").textContent =
      models && models.length ? JSON.stringify(models, null, 2) : "No model stats yet"

    renderContext(context)
    renderRegimes(context)
    renderScenario(scenario)
    renderOpenTrade(openTrade)
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
