let equityChart = null

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

function buildChart() {
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

function updateChart(equity) {
  if (!equityChart) {
    buildChart()
  }

  equityChart.data.labels = equity.map((x, i) => x.trade_id ?? i + 1)
  equityChart.data.datasets[0].data = equity.map(x => x.cum_r ?? 0)
  equityChart.update("none")
}

async function refreshDashboard() {
  try {
    const summary = await loadJson("summary.json")
    const equity = await loadJson("equity.json")
    const trades = await loadJson("trades.json")
    const signals = await loadJson("signals.json")

    setText("status-pill", summary.status || "ready")
    setText("last-update", "Updated: " + (summary.last_update_utc || "-"))
    setText("metric-market", summary.market || "-")
    setText("metric-trades", summary.total_trades ?? 0)
    setText("metric-winrate", (summary.winrate ?? 0) + "%")
    setText("metric-avg-r", summary.avg_r ?? 0)
    setText("metric-net-r", summary.net_r ?? 0)

    document.getElementById("trades-table").textContent =
      trades && trades.length ? JSON.stringify(trades, null, 2) : "No trades yet"

    document.getElementById("signals-list").textContent =
      signals && signals.length ? JSON.stringify(signals, null, 2) : "No recent signals"

    updateChart(Array.isArray(equity) ? equity : [])
  } catch (err) {
    console.error(err)
    setText("status-pill", "error")
    setText("last-update", "Dashboard data missing or invalid")
  }
}

window.addEventListener("load", async () => {
  buildChart()
  await refreshDashboard()
})
