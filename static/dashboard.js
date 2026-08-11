const bodies = {
  watchlist: document.getElementById("watchlistBody"),
  positions: document.getElementById("positionsBody"),
  closedPositions: document.getElementById("closedPositionsBody"),
  demoOrders: document.getElementById("demoOrdersBody"),
  tradeLog: document.getElementById("tradeLogBody"),
};

const positionCount = document.getElementById("positionCount");
const openPositionPill = document.getElementById("openPositionPill");
const plSummary = document.getElementById("plSummary");
const refreshButton = document.getElementById("refreshButton");
const modeButtons = Array.from(document.querySelectorAll("[data-market-mode]"));
const lastUpdateEl = document.getElementById("lastUpdate");
const tradeLogCountEl = document.getElementById("tradeLogCount");
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
const commandCenterEl = document.getElementById("commandCenter");
const commandStatusDotEl = document.getElementById("commandStatusDot");
const commandHeadlineEl = document.getElementById("commandHeadline");
const commandBotStateEl = document.getElementById("commandBotState");
const commandModeEl = document.getElementById("commandMode");
const commandMarketEl = document.getElementById("commandMarket");
const commandNextEl = document.getElementById("commandNext");
const commandLastCycleEl = document.getElementById("commandLastCycle");
const discoveryStatusEl = document.getElementById("discoveryStatus");
const discoveryCountEl = document.getElementById("discoveryCount");
const discoverySummaryEl = document.getElementById("discoverySummary");
const discoveryListEl = document.getElementById("discoveryList");
const autoBuyReadinessEl = document.getElementById("autoBuyReadiness");
const autoBuyStatusGridEl = document.getElementById("autoBuyStatusGrid");
const candidateListEl = document.getElementById("candidateList");
const candidateCountEl = document.getElementById("candidateCount");
const manualWatchlistOrdersEl = document.getElementById("manualWatchlistOrders");
const manualWatchlistCountEl = document.getElementById("manualWatchlistCount");
const manualWatchlistNotionalEl = document.getElementById("manualWatchlistNotional");
const positionCardsEl = document.getElementById("positionCards");
const closedPositionCardsEl = document.getElementById("closedPositionCards");
const demoOrderCardsEl = document.getElementById("demoOrderCards");
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

function hasNumber(value) {
  return value !== "" && value !== null && value !== undefined && Number.isFinite(Number(value));
}

function money(value) {
  return `$${number(value).toFixed(2)}`;
}

function sizeFromNotional(price, notional) {
  const parsedPrice = Number(price);
  const parsedNotional = Number(notional);
  if (!Number.isFinite(parsedPrice) || parsedPrice <= 0 || !Number.isFinite(parsedNotional) || parsedNotional <= 0) {
    return "-";
  }
  return Math.max(parsedNotional / parsedPrice, 0.00001).toFixed(5);
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

function setModeButtons(data) {
  const enabled = Boolean(data.config_status?.market_open_auto_mode);
  modeButtons.forEach((button) => {
    const selected = button.dataset.marketMode === String(enabled);
    button.classList.toggle("active", selected);
    button.setAttribute("aria-pressed", selected ? "true" : "false");
  });
}

async function updateWatchlistMode(enabled) {
  try {
    modeButtons.forEach((button) => {
      button.disabled = true;
    });
    const response = await fetch("/api/watchlist-mode", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ market_open_auto_mode: enabled }),
    });
    const payload = await response.json().catch(() => ({}));
    if (!response.ok || !payload.success) {
      throw new Error(payload.message || `Mode update failed with ${response.status}`);
    }
    render(payload.data);
  } catch (error) {
    if (serviceStatusEl) {
      serviceStatusEl.textContent = `Watchlist mode update failed: ${error.message || error}`;
      serviceStatusEl.style.display = "block";
    }
  } finally {
    modeButtons.forEach((button) => {
      button.disabled = false;
    });
  }
}

function toneBadge(value, tone) {
  const pill = badge(value);
  if (tone) pill.classList.add(`tone_${tone}`);
  return pill;
}

function readableEvent(value) {
  const raw = text(value);
  const labels = {
    AUTO_SIGNAL_DEMO_ORDER_SIGNAL_SENT: "Signal Order Sent",
    AUTO_SIGNAL_DEMO_ORDER_SIGNAL_FAILED: "Signal Order Failed",
    AUTO_SIGNAL_DEMO_ORDER_SIGNAL_PENDING: "Signal Order Pending",
    AUTO_TREND_BUY_ORDER_TREND_BUY_SENT: "Trend Buy Sent",
    AUTO_TREND_BUY_ORDER_TREND_BUY_FAILED: "Trend Buy Failed",
    AUTO_TREND_BUY_ORDER_TREND_BUY_PENDING: "Trend Buy Pending",
    DEMO_AUTO_CLOSE_TAKE_PROFIT_SENT: "Take Profit Closed",
    DEMO_AUTO_CLOSE_TAKE_PROFIT_FAILED: "Take Profit Failed",
    DEMO_AUTO_CLOSE_TAKE_PROFIT_PENDING_CONFIRMATION: "Take Profit Pending",
    DEMO_AUTO_CLOSE_STOP_LOSS_SENT: "Stop Loss Closed",
    DEMO_AUTO_CLOSE_STOP_LOSS_FAILED: "Stop Loss Failed",
    DEMO_AUTO_CLOSE_STOP_LOSS_PENDING_CONFIRMATION: "Stop Loss Pending",
    DEMO_ORDER_SENT: "Demo Order Sent",
    DEMO_ORDER_FAILED: "Demo Order Failed",
    DEMO_ORDER_PENDING_CONFIRMATION: "Demo Order Pending",
    MANUAL_BUY_MANUAL_BUY_SENT: "Manual Buy Sent",
    MANUAL_BUY_MANUAL_BUY_FAILED: "Manual Buy Failed",
    MANUAL_BUY_MANUAL_BUY_PENDING: "Manual Buy Pending",
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

async function manualBuy(symbol) {
  try {
    const notionalInput = manualWatchlistNotionalEl;
    const notional = notionalInput ? Number(notionalInput.value) : undefined;
    const payload = { symbol, confirm: true };
    if (notional) payload.notional_usd = notional;

    const response = await fetch("/api/manual-buy", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (data.pending_confirmation) {
      alert(`Buy pending IG confirmation: ${data.message || "Check open positions shortly."}`);
      refresh();
      return true;
    }
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

async function manualBuyWithNotional(symbol, notional) {
  const watchInput = manualWatchlistNotionalEl;
  const previousWatch = watchInput ? watchInput.value : null;

  if (watchInput) watchInput.value = notional;

  try {
    return await manualBuy(symbol);
  } finally {
    if (watchInput && previousWatch !== null) watchInput.value = previousWatch;
  }
}

function confirmManualBuy(item, status) {
  const modal = document.getElementById("buyConfirmModal");
  const body = document.getElementById("buyConfirmBody");
  const cancelBtn = document.getElementById("buyCancelBtn");
  const confirmBtn = document.getElementById("buyConfirmBtn");
  const details = status || {};
  const notional = manualWatchlistNotionalEl ? Number(manualWatchlistNotionalEl.value) || 500 : 500;

  if (!modal || !body || !cancelBtn || !confirmBtn) {
    return manualBuyWithNotional(item.symbol, notional);
  }

  const price = item.price || item.current_price || "";
  const estimatedSize = sizeFromNotional(price, notional);
  const rows = [
    ["Symbol", item.symbol || "-"],
    ["Latest Price", hasNumber(price) ? formatPriceText(price) : "Unavailable"],
    ["Notional", money(notional)],
    ["Estimated Size", estimatedSize],
    ["Route", text(item.tradable_hint)],
    ["Signal", text(item.signal)],
    ["Stage", readableEvent(item.stage || "-")],
    ["Manual Buy", details.manual_buy_enabled ? "Enabled" : "Disabled"],
  ];

  body.replaceChildren();
  const summary = document.createElement("div");
  summary.className = "confirm-summary";
  rows.forEach(([label, value]) => {
    const row = document.createElement("div");
    const labelEl = document.createElement("span");
    const valueEl = document.createElement("strong");
    labelEl.textContent = label;
    valueEl.textContent = value;
    row.append(labelEl, valueEl);
    summary.appendChild(row);
  });

  const note = document.createElement("p");
  note.className = "confirm-note";
  note.textContent = details.manual_buy_enabled
    ? "This sends a protected IG demo BUY request using your server allowlist and rate limit."
    : "Manual buy is disabled on the server. Enable PAPER_TRADING, ALLOW_MANUAL_BUY, and MANUAL_BUY_ALLOWLIST.";
  body.append(summary, note);

  modal.style.display = "flex";
  confirmBtn.disabled = !details.manual_buy_enabled;

  const cleanup = () => {
    modal.style.display = "none";
    cancelBtn.removeEventListener("click", onCancel);
    confirmBtn.removeEventListener("click", onConfirm);
  };

  const onCancel = () => cleanup();
  const onConfirm = async () => {
    confirmBtn.disabled = true;
    confirmBtn.textContent = "Sending...";
    try {
      const success = await manualBuyWithNotional(item.symbol, notional);
      if (success) cleanup();
    } finally {
      confirmBtn.textContent = "Confirm Buy";
      confirmBtn.disabled = !details.manual_buy_enabled;
    }
  };

  cancelBtn.addEventListener("click", onCancel);
  confirmBtn.addEventListener("click", onConfirm);
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

function formatPriceText(value) {
  if (!hasNumber(value)) {
    return "Waiting for quote";
  }

  return `$${Number(value).toFixed(2)}`;
}

function formatMoveText(value) {
  if (!hasNumber(value)) {
    return "No change data";
  }

  const numberValue = Number(value);
  return `${numberValue > 0 ? "+" : ""}${numberValue.toFixed(2)} today`;
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
    if (!hasNumber(item.price)) node.classList.add("no-quote");

    const symbol = document.createElement("strong");
    const price = document.createElement("span");
    const change = document.createElement("span");
    const status = document.createElement("small");

    symbol.textContent = item.symbol || "-";
    price.textContent = formatPriceText(item.price);
    change.textContent = item.change_percent === "" || item.change_percent === null || item.change_percent === undefined
      ? "-"
      : signedPercent(item.change_percent);
    change.className = "ticker-change";
    status.textContent = item.quote_source
      ? `${readableEvent(item.status || "")} | ${item.quote_source}`
      : readableEvent(item.status || item.quote_message || "");

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
    if (!hasNumber(item.price)) card.classList.add("no-quote");

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
    price.textContent = formatPriceText(item.price);

    const move = document.createElement("small");
    move.textContent = item.quote_source
      ? `${formatMoveText(item.change)} | ${item.quote_source}`
      : item.quote_message || "No change data";

    card.append(header, price, move);
    liveMarketsGridEl.appendChild(card);
  });
}

function renderAutoBuyStatus(status) {
  if (!autoBuyStatusGridEl) return;
  const details = status || {};
  autoBuyStatusGridEl.replaceChildren();

  if (autoBuyReadinessEl) {
    autoBuyReadinessEl.textContent = details.readiness || "Unknown";
    autoBuyReadinessEl.className = `badge tone_${details.tone || "info"}`;
  }

  const items = [
    ["Mode", details.mode || "Off", details.armed ? "good" : "danger"],
    ["Market", details.market_mode || "-"],
    ["Stage", readableEvent(details.stage || "-"), details.tone || "info"],
    ["Bot", readableEvent(details.bot_state || "unknown"), details.bot_state === "fresh" ? "good" : "warn"],
    ["Max Notional", money(details.max_notional_usd)],
    ["Min Quality", number(details.min_quality).toFixed(2)],
    ["Trend Trigger", `${number(details.trend_buy_min_change_percent).toFixed(2)}%`],
    ["Signal Window", details.signal_window || "-"],
    ["Once Per Day", details.once_per_symbol_per_day ? "On" : "Off", details.once_per_symbol_per_day ? "good" : "warn"],
    ["Manual Buy", details.manual_buy_enabled ? "Enabled" : "Disabled", details.manual_buy_enabled ? "good" : "warn"],
  ];

  items.forEach(([label, value, tone]) => {
    const item = document.createElement("div");
    item.className = "status-item";
    const labelEl = document.createElement("span");
    const valueEl = document.createElement("strong");
    labelEl.textContent = label;
    valueEl.textContent = text(value);
    if (tone) valueEl.className = `tone-${tone}`;
    item.append(labelEl, valueEl);
    autoBuyStatusGridEl.appendChild(item);
  });
}

function renderCommandCenter(data) {
  if (!commandCenterEl) return;
  const status = data.auto_buy_status || {};
  const bot = data.bot_status || {};
  const tone = status.tone || "info";

  commandCenterEl.classList.remove("tone-good", "tone-warn", "tone-danger", "tone-info");
  commandCenterEl.classList.add(`tone-${tone}`);
  if (commandStatusDotEl) commandStatusDotEl.className = `status-dot tone-${tone}`;
  if (commandHeadlineEl) commandHeadlineEl.textContent = status.readiness || "Unknown";
  if (commandBotStateEl) commandBotStateEl.textContent = readableEvent(bot.state || "unknown");
  if (commandModeEl) commandModeEl.textContent = status.mode || "Off";
  if (commandMarketEl) commandMarketEl.textContent = status.market_mode || "-";
  if (commandNextEl) commandNextEl.textContent = status.next_action || "-";
  if (commandLastCycleEl) {
    const age = Number(bot.age_seconds);
    commandLastCycleEl.textContent = Number.isFinite(age) ? `${age}s ago` : (bot.timestamp || "-");
  }
}

function renderDiscovery(discovery) {
  if (!discoverySummaryEl || !discoveryListEl) return;
  const details = discovery || {};
  const rows = details.rows || [];
  const enabled = Boolean(details.enabled);

  if (discoveryStatusEl) {
    discoveryStatusEl.textContent = enabled ? "Enabled" : "Disabled";
    discoveryStatusEl.className = `badge tone_${enabled ? "good" : "warn"}`;
  }
  if (discoveryCountEl) discoveryCountEl.textContent = details.active_count ?? 0;

  const summaryItems = [
    ["Active", details.active_count ?? 0, "good"],
    ["Skipped", details.skipped_count ?? 0, "warn"],
    ["Max", details.max_symbols ?? "-"],
    ["IPO Cap", details.max_ipo_symbols ?? "-"],
    ["Min Price", money(details.min_price)],
    ["Next Refresh", details.next_refresh || "-"],
  ];

  discoverySummaryEl.replaceChildren();
  summaryItems.forEach(([label, value, tone]) => {
    const item = document.createElement("div");
    const labelEl = document.createElement("span");
    const valueEl = document.createElement("strong");
    labelEl.textContent = label;
    valueEl.textContent = text(value);
    if (tone) valueEl.className = `tone-${tone}`;
    item.append(labelEl, valueEl);
    discoverySummaryEl.appendChild(item);
  });

  discoveryListEl.replaceChildren();
  if (rows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "discovery-empty";
    empty.textContent = details.message || "No discovery rows yet.";
    discoveryListEl.appendChild(empty);
    return;
  }

  rows.slice(0, 20).forEach((item) => {
    const active = ["yes", "true", "1", "active"].includes(text(item.active).toLowerCase());
    const row = document.createElement("article");
    row.className = `discovery-row ${active ? "active" : "skipped"}`;

    const symbol = document.createElement("strong");
    symbol.textContent = item.symbol || "-";

    const meta = document.createElement("div");
    meta.className = "discovery-meta";
    meta.append(
      toneBadge(active ? "Active" : "Skipped", active ? "good" : "warn"),
      badge(item.source || "-"),
      badge(item.category || "-"),
      document.createTextNode(`Score ${text(item.score)}`),
      document.createTextNode(`Price ${hasNumber(item.price) ? formatPriceText(item.price) : "-"}`)
    );

    const reason = document.createElement("small");
    const ipoBits = [item.ipo_status, item.ipo_date, item.exchange].filter(Boolean).join(" | ");
    reason.textContent = `${item.reason || item.notes || "-"}${ipoBits ? ` (${ipoBits})` : ""}`;

    row.append(symbol, meta, reason);
    discoveryListEl.appendChild(row);
  });
}

function renderCandidates(rows) {
  if (!candidateListEl) return;
  candidateListEl.replaceChildren();
  const candidates = rows || [];
  if (candidateCountEl) candidateCountEl.textContent = candidates.length;

  if (candidates.length === 0) {
    const empty = document.createElement("div");
    empty.className = "candidate-empty";
    empty.textContent = "No symbols in the current auto-buy watchlist.";
    candidateListEl.appendChild(empty);
    return;
  }

  candidates.forEach((item) => {
    const node = document.createElement("article");
    node.className = `candidate-row ${item.eligible ? "eligible" : "skipped"}`;

    const rank = document.createElement("strong");
    rank.className = "candidate-rank";
    rank.textContent = `#${item.rank || "-"}`;

    const main = document.createElement("div");
    main.className = "candidate-main";
    const title = document.createElement("div");
    title.className = "candidate-title";
    const symbol = document.createElement("strong");
    symbol.textContent = item.symbol || "-";
    const state = toneBadge(item.eligible ? "Ready" : "Skipped", item.eligible ? "good" : "warn");
    title.append(symbol, state);

    const meta = document.createElement("div");
    meta.className = "candidate-meta";
    meta.append(
      badge(item.signal || "WAITING"),
      document.createTextNode(`Change ${item.change_percent === "" ? "-" : signedPercent(item.change_percent)}`),
      document.createTextNode(`Quality ${item.quality === "" ? "-" : number(item.quality).toFixed(2)}`),
      document.createTextNode(`Route ${text(item.tradable_hint)}`)
    );

    const reason = document.createElement("small");
    reason.textContent = item.reason || "-";
    const diagnostics = document.createElement("ul");
    diagnostics.className = "candidate-diagnostics";
    (item.diagnostics || []).slice(0, 5).forEach((detail) => {
      const node = document.createElement("li");
      node.textContent = detail;
      diagnostics.appendChild(node);
    });

    main.append(title, meta, reason, diagnostics);
    node.append(rank, main);
    candidateListEl.appendChild(node);
  });
}

function renderManualWatchlistOrders(rows, status) {
  if (!manualWatchlistOrdersEl) return;
  manualWatchlistOrdersEl.replaceChildren();
  const candidates = rows || [];
  const details = status || {};
  if (manualWatchlistCountEl) manualWatchlistCountEl.textContent = candidates.length;

  if (candidates.length === 0) {
    const empty = document.createElement("div");
    empty.className = "manual-order-empty";
    empty.textContent = "No watchlist symbols available.";
    manualWatchlistOrdersEl.appendChild(empty);
    return;
  }

  candidates.forEach((item) => {
    const card = document.createElement("article");
    card.className = "manual-order-card";

    const header = document.createElement("div");
    header.className = "manual-order-header";
    const symbol = document.createElement("strong");
    symbol.textContent = item.symbol || "-";
    const state = toneBadge(details.manual_buy_enabled ? "Manual Ready" : "Manual Disabled", details.manual_buy_enabled ? "good" : "warn");
    header.append(symbol, state);

    const meta = document.createElement("div");
    meta.className = "manual-order-meta";
    meta.append(
      document.createTextNode(`Price ${formatPriceText(item.price)}`),
      document.createTextNode(`Stage ${readableEvent(item.stage || "-")}`),
      document.createTextNode(`Route ${text(item.tradable_hint)}`)
    );

    const reason = document.createElement("small");
    reason.textContent = details.manual_buy_enabled
      ? "Manual buy uses the server allowlist and rate limit."
      : "Enable PAPER_TRADING, ALLOW_MANUAL_BUY, and your IP allowlist on the server.";

    const action = document.createElement("button");
    action.type = "button";
    action.className = "refresh-button manual-buy-button";
    action.textContent = `Buy ${item.symbol || ""}`.trim();
    action.disabled = !details.manual_buy_enabled;
    action.addEventListener("click", () => confirmManualBuy(item, details));

    card.append(header, meta, reason, action);
    manualWatchlistOrdersEl.appendChild(card);
  });
}

function mobileField(label, value, className) {
  const field = document.createElement("div");
  const labelEl = document.createElement("span");
  const valueEl = document.createElement("strong");
  labelEl.textContent = label;
  valueEl.textContent = text(value);
  if (className) valueEl.className = className;
  field.append(labelEl, valueEl);
  return field;
}

function renderMobileCards(container, rows, options) {
  if (!container) return;
  container.replaceChildren();
  const dataRows = rows || [];
  if (dataRows.length === 0) {
    const empty = document.createElement("div");
    empty.className = "mobile-empty";
    empty.textContent = options.emptyText;
    container.appendChild(empty);
    return;
  }

  dataRows.forEach((item) => {
    const card = document.createElement("article");
    card.className = "mobile-data-card";
    const header = document.createElement("div");
    header.className = "mobile-card-header";
    const title = document.createElement("strong");
    title.textContent = options.title(item);
    header.appendChild(title);
    const headerBadge = options.badge ? options.badge(item) : null;
    if (headerBadge) header.appendChild(headerBadge);

    const grid = document.createElement("div");
    grid.className = "mobile-card-grid";
    options.fields.forEach((field) => {
      grid.appendChild(mobileField(field.label, field.value(item), field.className ? field.className(item) : ""));
    });

    card.append(header, grid);
    container.appendChild(card);
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
  setModeButtons(data);

  renderCommandCenter(data);
  renderDiscovery(data.market_discovery);
  renderSummary(data);
  renderStageFlow(data.watchlist_stage_summary);
  renderPriceTicker(data.price_ticker);
  renderLiveMarkets(data.live_markets);
  renderAutoBuyStatus(data.auto_buy_status);
  renderCandidates(data.auto_buy_candidates);
  renderManualWatchlistOrders(data.auto_buy_candidates, data.auto_buy_status);
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
  renderMobileCards(positionCardsEl, data.positions, {
    emptyText: "No open demo positions.",
    title: (item) => item.instrument || "Unknown position",
    badge: (item) => badge(item.direction || "-"),
    fields: [
      { label: "Time", value: (item) => item.timestamp },
      { label: "Size", value: (item) => item.size },
      { label: "Open", value: (item) => item.open_level },
      { label: "Current", value: (item) => item.current_price },
      { label: "P/L", value: (item) => money(item.profit_loss), className: (item) => moneyClass(item.profit_loss) },
      { label: "Currency", value: (item) => item.currency },
    ],
  });

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
  renderMobileCards(closedPositionCardsEl, data.closed_positions, {
    emptyText: "No closed demo positions.",
    title: (item) => item.instrument || "Closed position",
    badge: (item) => badge(item.direction || "-"),
    fields: [
      { label: "Time", value: (item) => item.timestamp },
      { label: "Size", value: (item) => item.size },
      { label: "Open", value: (item) => item.open_level },
      { label: "Close", value: (item) => item.current_price },
      { label: "Final P/L", value: (item) => money(item.profit_loss), className: (item) => moneyClass(item.profit_loss) },
      { label: "Currency", value: (item) => item.currency },
    ],
  });

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
  renderMobileCards(demoOrderCardsEl, data.demo_orders, {
    emptyText: "No demo orders yet.",
    title: (item) => item.symbol || "Order",
    badge: (item) => badge(item.status || "-"),
    fields: [
      { label: "Time", value: (item) => item.timestamp },
      { label: "Direction", value: (item) => item.direction },
      { label: "Size", value: (item) => item.size },
      { label: "Status", value: (item) => readableEvent(item.status || "-") },
    ],
  });

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
    if (refreshButton) refreshButton.disabled = true;
    const response = await fetch("/api/dashboard", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Dashboard API returned ${response.status}`);
    }
    const data = await response.json();
    render(data);
  } catch (error) {
    if (serviceStatusEl) {
      serviceStatusEl.textContent = `Dashboard refresh failed: ${error.message || error}`;
      serviceStatusEl.style.display = "block";
    }
  } finally {
    if (refreshButton) refreshButton.disabled = false;
  }
}

if (refreshButton) refreshButton.addEventListener("click", refresh);
modeButtons.forEach((button) => {
  button.addEventListener("click", () => {
    updateWatchlistMode(button.dataset.marketMode === "true");
  });
});
try {
  render(window.initialData || {});
} catch (error) {
  if (serviceStatusEl) {
    serviceStatusEl.textContent = `Dashboard render failed: ${error.message || error}`;
    serviceStatusEl.style.display = "block";
  }
}
startWatchlistAutoScroll();
refresh();
setInterval(refresh, 10000);
