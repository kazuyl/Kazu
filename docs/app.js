let equityChartInstance = null

async function loadJson(path) {
  const res = await fetch(path, { cache: "no-store" })
  if (!res.ok) throw new Error(`Failed to load ${path}`)
  return res.json()
}

function metric(label, value) {
  return `
    <div class="card">
      <div>${label}</div>
      <div style="font-size: 28px; font-weight: 700;">${value}</div>
    </div>
  `
}

async function main() {
  try {
    const summary = await loadJson("summary.json")
    const equity = await loadJson("equity.json")
    const trades = await loadJson("trades.json")
    const signals = await loadJson("signals.json")

    document.getElementById("status-pill").textContent = summary.status || "ready"
    document.getElementById("last-update").textContent = `Updated: ${summary.last_update_utc || "-"}`

    document.getElementById("metrics").innerHTML =
      metric("Market", summary.market || "-") +
      metric("Trades", summary.total_trades ?? 0) +
      metric("Winrate", `${summary.winrate ?? 0}%`) +
      metric("Avg R", summary.avg_r ?? 0) +
      metric("Net R", summary.net_r ?? 0)

    document.getElementById("models-table").innerHTML = "No model stats yet"

    document.getElementById("trades-table").innerHTML =
      trades.length ? `<pre>${JSON.stringify(trades, null, 2)}</pre>` : "No trades yet"

    document.getElementById("signals-list").innerHTML =
      signals.length ? `<pre>${JSON.stringify(signals, null, 2)}</pre>` : "No recent signals"

    const ctx = document.getElementById("equityChart").getContext("2d")

    if (equityChartInstance) {
      equityChartInstance.destroy()
    }

    equityChartInstance = new Chart(ctx, {
      type: "line",
      data: {
        labels: equity.map(x => x.trade_id),
        datasets: [
          {
            label: "Cum R",
            data: equity.map(x => x.cum_r),
            tension: 0.2
          }
        ]
      },
      options: {
        responsive: true,
        maintainAspectRatio: false
      }
    })
  } catch (err) {
    console.error(err)
    document.getElementById("metrics").innerHTML = `<div class="card">Dashboard data missing</div>`
  }
}

main()
