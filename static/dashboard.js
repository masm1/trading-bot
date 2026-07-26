const bodies = {
  watchlist: document.getElementById("watchlistBody"),
  positions: document.getElementById("positionsBody"),
  closedPositions: document.getElementById("closedPositionsBody"),
  paperTrades: document.getElementById("paperTradesBody"),
  demoOrders: document.getElementById("demoOrdersBody"),
  tradeLog: document.getElementById("tradeLogBody"),
};

const positionCount = document.getElementById("positionCount");
const openPositionPill = document.getElementById("openPositionPill");
const plSummary = document.getElementById("plSummary");
const refreshButton = document.getElementById("refreshButton");
const lastUpdateEl = document.getElementById("lastUpdate");
const tradeLogCountEl = document.getElementById("tradeLogCount");
const paperTradeCountEl = document.getElementById("paperTradeCount");
const demoOrderCountEl = document.getElementById("demoOrderCount");
const watchlistCountEl = document.getElementById("watchlistCount");
const watchlistPill = document.getElementById("watchlistPill");
const watchlistScroll = document.getElementById("watchlistScroll");
const watchlistModeEl = document.getElementById("watchlistMode");
const watchlistEyebrowEl = document.getElementById("watchlistEyebrow");
const stageFlowTitleEl = document.getElementById("stageFlowTitle");
const watchTimeHeaderEl = document.getElementById("watchTimeHeader");
const botStatusTimeEl = document.getElementById("botStatusTime");
const botStatusMessageEl = document.getElementById("botStatusMessage");
const serviceStatusEl = document.getElementById("serviceStatus");
const netPlEl = document.getElementById("netPl");
const winRateEl = document.getElementById("winRate");
const stageFlowEl = document.getElementById("stageFlow");
const priceTickerEl = document.getElementById("priceTicker");
const liveMarketsGridEl = document.getElementById("liveMarketsGrid");
const liveMarketsPillEl = document.getElementById("liveMarketsPill");
let plChart;
let watchlistScrollFrame;
let watchlistScrollPaused = false;
let currentData = window.initialData || {};
const tableFilters = {
  watchlist: "all",
  activity: "all",
};

function text(value) {
  if (value === null || value === undefined || value === "") {
    return "-";
  }
  return String(value);
}

function number(value) {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
}

function money(value) {
  return `$${number(value).toFixed(2)}`;
}

function signedPercent(value) {
  const parsed = number(value);
  if (parsed === 0) return "0.00%";
  return `${parsed > 0 ? "+" : ""}${parsed.toFixed(2)}%`;
}

function signedMinutes(value) {
  const parsed = number(value);
  if (parsed === 0) return "Now";
  if (parsed > 0) return `+${parsed}m`;
  return `${parsed}m`;
}

function moneyClass(value) {
  const parsed = Number(value);
  if (Number.isNaN(parsed)) return "";
  if (parsed > 0) return "profit";
  if (parsed < 0) return "loss";
  return "warn";
}

function badgeClass(value) {
  return text(value).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_|_$/g, "");
}

function badge(value) {
  const pill = document.createElement("span");
  pill.className = `badge ${badgeClass(value)}`;
  pill.textContent = text(value);
  return pill;
}

function readableEvent(value) {
  const raw = text(value);
  const labels = {
    AUTO_SIGNAL_DEMO_ORDER_SIGNAL_SENT: "Signal Order Sent",
    AUTO_SIGNAL_DEMO_ORDER_SIGNAL_FAILED: "Signal Order Failed",
    DEMO_AUTO_CLOSE_TAKE_PROFIT_SENT: "Take Profit Closed",
    DEMO_AUTO_CLOSE_TAKE_PROFIT_FAILED: "Take Profit Failed",
    DEMO_AUTO_CLOSE_STOP_LOSS_SENT: "Stop Loss Closed",
    DEMO_AUTO_CLOSE_STOP_LOSS_FAILED: "Stop Loss Failed",
    DEMO_ORDER_SENT: "Demo Order Sent",
    DEMO_ORDER_FAILED: "Demo Order Failed",
    SIGNAL_CHECK: "Signal Check",
    BASE_PRICE_SAVED: "Base Saved",
  };
  return labels[raw] || raw.replaceAll("_", " ").toLowerCase().replace(/\b\w/g, (char) => char.toUpperCase());
}

function eventBadge(value) {
  const pill = badge(value);
  pill.textContent = readableEvent(value);
  return pill;
}

function renderPaperTradeAction(value, item) {
  const symbol = text(item.symbol);
  const signal = text(item.signal).toUpperCase();
  const changePercent = number(item.change_percent);
  const eligible = symbol && (signal === "STRONG_RALLY" || changePercent > 0);

  if (!eligible) {
    const empty = document.createElement("span");
    empty.textContent = "-";
    return empty;
  }

  const button = document.createElement("button");
  button.type = "button";
  button.className = "refresh-button";
  button.textContent = "Buy";
  button.dataset.symbol = symbol;

  button.addEventListener("click", async () => {
    button.disabled = true;
    const originalText = button.textContent;
    button.textContent = "Buying...";
    const success = await manualBuy(symbol);
    button.textContent = success ? "Bought" : originalText;
    if (!success) {
      button.disabled = false;
    }
  });

  return button;
}

async function manualBuy(symbol) {
  try {
    const response = await fetch("/api/manual-buy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ symbol }),
    });
    const data = await response.json();
    if (!response.ok || !data.success) {
      alert(`Buy failed: ${data.message || "Unknown error"}`);
      return false;
    }
    refresh();
    return true;
  } catch (error) {
    alert(`Buy request failed: ${error}`);
    return false;
  }
}

function setRows(body, rows, columns, emptyText) {
  body.replaceChildren();

  if (!rows || rows.length === 0) {
    const row = document.createElement("tr");
    const cell = document.createElement("td");
    cell.colSpan = columns.length;
    cell.className = "empty";
    cell.textContent = emptyText;
    row.appendChild(cell);
    body.appendChild(row);
    return;
  }

  rows.forEach((item) => {
    const row = document.createElement("tr");
    columns.forEach((column) => {
      const cell = document.createElement("td");
      const value = item[column.key];

      if (column.render) {
        cell.appendChild(column.render(value, item));
      } else {
        cell.textContent = column.format ? column.format(value, item) : text(value);
      }

      if (column.className) {
        cell.className = column.className(value, item);
      }

      row.appendChild(cell);
    });
    body.appendChild(row);
  });
}

function updateMetricCard(element, value) {
  if (!element) return;
  const card = element.closest(".metric-card");
  if (!card) return;
  card.classList.remove("profit", "loss");
  if (number(value) > 0) card.classList.add("profit");
  if (number(value) < 0) card.classList.add("loss");
}

function renderSummary(data) {
  if (!plSummary) return;

  const metrics = [
    ["Total Profit", money(data.total_profit)],
    ["Total Loss", money(data.total_loss)],
    ["Sharpe", number(data.sharpe_ratio).toFixed(2)],
    ["Drawdown", money(data.max_drawdown)],
    ["Winning", text(data.winning_trades)],
    ["Losing", text(data.losing_trades)],
    ["Avg Profit", money(data.avg_profit)],
    ["Avg Loss", money(data.avg_loss)],
  ];

  plSummary.replaceChildren();
  metrics.forEach(([label, value]) => {
    const item = document.createElement("div");
    const labelEl = document.createElement("span");
    const valueEl = document.createElement("strong");
    labelEl.textContent = label;
    valueEl.textContent = value;
    item.append(labelEl, valueEl);
    plSummary.appendChild(item);
  });
}

function renderStageFlow(summary) {
  if (!stageFlowEl) return;
  stageFlowEl.replaceChildren();

  (summary || []).forEach((item) => {
    const node = document.createElement("div");
    node.className = `stage-step ${item.count > 0 ? "active" : ""}`;

    const count = document.createElement("strong");
    const label = document.createElement("span");
    count.textContent = item.count;
    label.textContent = item.label;
    node.append(count, label);
    stageFlowEl.appendChild(node);
  });
}

function renderPriceTicker(rows) {
  if (!priceTickerEl) return;
  priceTickerEl.replaceChildren();

  const tickerRows = rows && rows.length > 0 ? rows : [{
    symbol: "WAITING",
    price: "",
    change_percent: "",
    direction: "flat",
    status: "No price data yet",
  }];

  [...tickerRows, ...tickerRows].forEach((item) => {
    const node = document.createElement("div");
    node.className = `ticker-item ${item.direction || "flat"}`;

    const symbol = document.createElement("strong");
    const price = document.createElement("span");
    const change = document.createElement("span");
    const status = document.createElement("small");

    symbol.textContent = item.symbol || "-";
    price.textContent = item.price === "" || item.price === null || item.price === undefined
      ? "Price pending"
      : `$${Number(item.price).toFixed(2)}`;
    change.textContent = item.change_percent === "" || item.change_percent === null || item.change_percent === undefined
      ? "-"
      : signedPercent(item.change_percent);
    change.className = "ticker-change";
    status.textContent = readableEvent(item.status || "");

    node.append(symbol, price, change, status);
    priceTickerEl.appendChild(node);
  });
}

function renderLiveMarkets(rows) {
  if (!liveMarketsGridEl) return;
  liveMarketsGridEl.replaceChildren();

  const marketRows = rows || [];
  if (liveMarketsPillEl) liveMarketsPillEl.textContent = marketRows.length;

  if (marketRows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "live-market-empty";
    empty.textContent = "No live markets configured yet.";
    liveMarketsGridEl.appendChild(empty);
    return;
  }

  marketRows.forEach((item) => {
    const card = document.createElement("article");
    card.className = `live-market-card ${item.direction || "flat"}`;

    const header = document.createElement("div");
    header.className = "live-market-header";

    const titleWrap = document.createElement("div");
    const symbol = document.createElement("strong");
    const label = document.createElement("span");
    symbol.textContent = item.symbol || "-";
    label.textContent = item.label || item.symbol || "-";
    titleWrap.append(symbol, label);

    const change = document.createElement("span");
    change.className = "live-market-change";
    change.textContent = item.change_percent === "" || item.change_percent === null || item.change_percent === undefined
      ? "-"
      : signedPercent(item.change_percent);

    header.append(titleWrap, change);

    const price = document.createElement("div");
    price.className = "live-market-price";
    price.textContent = item.price === "" || item.price === null || item.price === undefined
      ? "Price pending"
      : `$${Number(item.price).toFixed(2)}`;

    const move = document.createElement("small");
    move.textContent = item.change === "" || item.change === null || item.change === undefined
      ? "Awaiting quote"
      : `${number(item.change) > 0 ? "+" : ""}${number(item.change).toFixed(2)} today`;

    card.append(header, price, move);
    liveMarketsGridEl.appendChild(card);
  });
}

function filterWatchlistRows(rows) {
  const filter = tableFilters.watchlist;
  if (filter === "all") return rows;
  if (filter === "CHECK") {
    return rows.filter((row) => text(row.stage).startsWith("CHECK"));
  }
  if (filter === "EVENT_COMPLETE") {
    return rows.filter((row) => ["EVENT_COMPLETE", "MARKET_OPEN_WINDOW_COMPLETE", "MARKET_CLOSED_WEEKEND"].includes(row.stage));
  }
  return rows.filter((row) => row.stage === filter);
}

function filterActivityRows(rows) {
  const filter = tableFilters.activity;
  if (filter === "all") return rows;
  return rows.filter((row) => text(row.event).includes(filter));
}

function renderChart(data) {
  const ctx = document.getElementById("plChart");
  if (!ctx || !window.Chart) return;

  const chartData = data.chart_data || [];
  const lineColor = number(chartData[chartData.length - 1]) < 0 ? "#ff6b6b" : "#50d47d";

  if (plChart) {
    plChart.destroy();
  }

  plChart = new Chart(ctx, {
    type: "line",
    data: {
      labels: data.chart_labels || [],
      datasets: [{
        label: "Cumulative P/L",
        data: chartData,
        borderColor: lineColor,
        backgroundColor: "rgba(80, 212, 125, 0.12)",
        borderWidth: 3,
        pointRadius: 2,
        pointHoverRadius: 5,
        tension: 0.28,
        fill: true,
      }],
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (context) => `P/L: ${money(context.parsed.y)}`,
          },
        },
      },
      scales: {
        x: {
          grid: { color: "rgba(156, 168, 179, 0.08)" },
          ticks: { color: "#9ca8b3", maxTicksLimit: 6 },
        },
        y: {
          grid: { color: "rgba(156, 168, 179, 0.12)" },
          ticks: {
            color: "#9ca8b3",
            callback: (value) => money(value),
          },
        },
      },
    },
  });
}

function render(data) {
  currentData = data;
  const openCount = data.positions?.length || 0;

  if (positionCount) positionCount.textContent = openCount;
  if (openPositionPill) openPositionPill.textContent = openCount;
  if (lastUpdateEl) lastUpdateEl.textContent = data.last_update || "-";
  if (tradeLogCountEl) tradeLogCountEl.textContent = `${data.trade_log_count ?? 0} log rows`;
  if (paperTradeCountEl) paperTradeCountEl.textContent = data.paper_trade_count ?? 0;
  if (demoOrderCountEl) demoOrderCountEl.textContent = data.demo_order_count ?? 0;
  if (watchlistCountEl) watchlistCountEl.textContent = data.watchlist_count ?? 0;
  if (watchlistPill) watchlistPill.textContent = data.watchlist_count ?? 0;
  if (watchlistModeEl) watchlistModeEl.textContent = `${data.watchlist_mode || "Watchlist"} names`;
  if (watchlistEyebrowEl) watchlistEyebrowEl.textContent = `${data.watchlist_mode || "Watchlist"} Queue`;
  if (stageFlowTitleEl) stageFlowTitleEl.textContent = `${data.watchlist_mode || "Watchlist"} Stage Flow`;
  if (watchTimeHeaderEl) watchTimeHeaderEl.textContent = data.watchlist_time_label || "Watch Time";
  if (botStatusTimeEl) botStatusTimeEl.textContent = data.bot_status?.timestamp || "-";
  if (botStatusMessageEl) botStatusMessageEl.textContent = data.bot_status?.message || "No bot heartbeat yet.";
  if (botStatusTimeEl) {
    const card = botStatusTimeEl.closest(".metric-card");
    card?.classList.remove("status-fresh", "status-stale", "status-unknown");
    card?.classList.add(`status-${data.bot_status?.state || "unknown"}`);
  }
  if (netPlEl) netPlEl.textContent = money(data.net_pl);
  if (winRateEl) winRateEl.textContent = `${number(data.win_rate).toFixed(1)}% win rate`;
  updateMetricCard(netPlEl, data.net_pl);

  renderSummary(data);
  renderStageFlow(data.watchlist_stage_summary);
  renderPriceTicker(data.price_ticker);
  renderLiveMarkets(data.live_markets);
  renderChart(data);

  setRows(
    bodies.watchlist,
    filterWatchlistRows(data.watchlist || []),
    [
      { key: "symbol" },
      { key: "watch_time" },
      { key: "stage", render: badge },
      { key: "minutes_from_event", format: signedMinutes },
      { key: "notes" },
    ],
    "No active watchlist symbols yet."
  );

  setRows(
    bodies.positions,
    data.positions,
    [
      { key: "timestamp" },
      { key: "instrument" },
      { key: "direction", render: badge },
      { key: "size" },
      { key: "open_level" },
      { key: "current_price" },
      { key: "profit_loss", format: money, className: moneyClass },
      { key: "currency" },
    ],
    "No open position snapshots yet."
  );

  setRows(
    bodies.closedPositions,
    data.closed_positions,
    [
      { key: "timestamp" },
      { key: "instrument" },
      { key: "direction", render: badge },
      { key: "size" },
      { key: "open_level" },
      { key: "current_price" },
      { key: "profit_loss", format: money, className: moneyClass },
      { key: "currency" },
    ],
    "No closed demo positions yet."
  );

  setRows(
    bodies.paperTrades,
    data.paper_trades,
    [
      { key: "timestamp" },
      { key: "symbol" },
      { key: "signal", render: badge },
      { key: "paper_action" },
      { key: "change_percent", format: signedPercent, className: moneyClass },
      { key: "action", render: renderPaperTradeAction },
    ],
    "No active watchlist windows available for CALL/PUT ideas yet."
  );

  setRows(
    bodies.demoOrders,
    data.demo_orders,
    [
      { key: "timestamp" },
      { key: "symbol" },
      { key: "direction", render: badge },
      { key: "size" },
      { key: "status", render: badge },
    ],
    "No demo orders yet."
  );

  if (serviceStatusEl) {
    if (data.ig_status) {
      serviceStatusEl.textContent = data.ig_status;
      serviceStatusEl.style.display = "block";
    } else {
      serviceStatusEl.textContent = "";
      serviceStatusEl.style.display = "none";
    }
  }

  setRows(
    bodies.tradeLog,
    filterActivityRows(data.trade_log || []),
    [
      { key: "timestamp" },
      { key: "symbol" },
      { key: "event", render: eventBadge },
      { key: "signal", render: badge },
      { key: "current_price" },
      { key: "notes" },
    ],
    "No recent trading activity yet."
  );
}

document.querySelectorAll("[data-filter-target]").forEach((button) => {
  button.addEventListener("click", () => {
    const target = button.dataset.filterTarget;
    const value = button.dataset.filterValue;
    tableFilters[target] = value;

    document.querySelectorAll(`[data-filter-target="${target}"]`).forEach((item) => {
      item.classList.toggle("active", item === button);
    });

    render(currentData);
  });
});

function startWatchlistAutoScroll() {
  if (!watchlistScroll || watchlistScrollFrame) return;

  const step = () => {
    const maxScroll = watchlistScroll.scrollHeight - watchlistScroll.clientHeight;

    if (!watchlistScrollPaused && maxScroll > 0) {
      if (watchlistScroll.scrollTop >= maxScroll - 1) {
        watchlistScroll.scrollTop = 0;
      } else {
        watchlistScroll.scrollTop += 0.35;
      }
    }

    watchlistScrollFrame = requestAnimationFrame(step);
  };

  watchlistScrollFrame = requestAnimationFrame(step);
}

if (watchlistScroll) {
  watchlistScroll.addEventListener("mouseenter", () => {
    watchlistScrollPaused = true;
  });
  watchlistScroll.addEventListener("mouseleave", () => {
    watchlistScrollPaused = false;
  });
  watchlistScroll.addEventListener("focusin", () => {
    watchlistScrollPaused = true;
  });
  watchlistScroll.addEventListener("focusout", () => {
    watchlistScrollPaused = false;
  });
}

async function refresh() {
  try {
    refreshButton.disabled = true;
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    const data = await response.json();
    render(data);
  } finally {
    refreshButton.disabled = false;
  }
}

refreshButton.addEventListener("click", refresh);
render(window.initialData);
startWatchlistAutoScroll();
refresh();
setInterval(refresh, 10000);
