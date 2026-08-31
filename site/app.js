/*
  CRC Market Monitor visual reference: user-authorized market-monitor screenshots.
  Keep compact ledger tables, breadth heat cells, symmetric pulse bars and navy industry tracks.
  This front end consumes only the generated daily aggregate at site/data/latest.json.
*/
const $ = selector => document.querySelector(selector);
const number = value => value === null || value === undefined || Number.isNaN(value) ? "—" : new Intl.NumberFormat("en-US", { maximumFractionDigits: 0 }).format(value);
const decimal = (value, digits = 1) => value === null || value === undefined || Number.isNaN(value) ? "—" : Number(value).toFixed(digits);
const signed = (value, digits = 2) => value === null || value === undefined || Number.isNaN(value) ? "—" : `${value >= 0 ? "+" : ""}${Number(value).toFixed(digits)}`;
const percentage = (value, digits = 1) => value === null || value === undefined || Number.isNaN(value) ? "—" : `${Number(value).toFixed(digits)}%`;
const heatClass = (value, direction) => {
  if (value === null || value === undefined) return "";
  const strong = value >= 300;
  return direction === "up" ? (strong ? "heat-up-strong" : "heat-up-soft") : (strong ? "heat-down-strong" : "heat-down-soft");
};
const reverseHeat = (value, upper, lower) => value === null || value === undefined ? "" : value <= lower ? "heat-up-strong" : value >= upper ? "heat-down-strong" : "";

function metric(label, value, detail, tone = "") {
  return `<article class="kpi"><p class="metric-label">${label}</p><div class="metric-value ${tone}">${value}</div><p class="metric-detail">${detail}</p></article>`;
}

function renderKpis(summary) {
  const breadthTone = summary.up4 >= summary.down4 ? "up" : "down";
  $("#kpis").innerHTML = `
    <article class="kpi"><p class="metric-label">UP 4% ／ DOWN 4%</p><div class="dual-metric"><div><div class="metric-value ${breadthTone === "up" ? "up" : ""}">${number(summary.up4)}</div><p class="metric-detail">強勢升幅</p></div><div><div class="metric-value ${breadthTone === "down" ? "down" : ""}">${number(summary.down4)}</div><p class="metric-detail">弱勢跌幅</p></div></div></article>
    ${metric("% 企穩 20 日線", percentage(summary.sma20Pct), `分母 ${number(summary.sma20N)} 隻`, summary.sma20Pct <= 10 ? "up" : summary.sma20Pct >= 90 ? "down" : "")}
    ${metric("% 企穩 50 日線", percentage(summary.sma50Pct), `分母 ${number(summary.sma50N)} 隻`, summary.sma50Pct <= 20 ? "up" : summary.sma50Pct >= 80 ? "down" : "")}
    ${metric("SPY 距 50 日 EMA", signed(summary.spyAtr), "單位：14 日 ATR", summary.spyAtr >= 5 ? "down" : summary.spyAtr <= -5 ? "up" : "")}
    ${metric("QQQ 距 50 日 EMA", signed(summary.qqqAtr), "單位：14 日 ATR", summary.qqqAtr >= 5 ? "down" : summary.qqqAtr <= -5 ? "up" : "")}
    ${metric("領導股 MLI", percentage(summary.mliReturn, 2), `${number(summary.mliN)} 隻／${percentage(summary.mliUpPct)} 上升`, summary.mliReturn >= 0 ? "up" : "down")}`;
}

function renderHistory(history) {
  $("#history-body").innerHTML = history.map(row => `<tr>
    <td>${row.date}</td><td class="${heatClass(row.up4, "up")}">${number(row.up4)}</td><td class="${heatClass(row.down4, "down")}">${number(row.down4)}</td>
    <td class="${reverseHeat(row.sma20Pct, 90, 10)}">${decimal(row.sma20Pct)}</td><td class="${reverseHeat(row.sma50Pct, 80, 20)}">${decimal(row.sma50Pct)}</td>
    <td>${signed(row.spyAtr)}</td><td>${signed(row.qqqAtr)}</td><td class="${row.mliReturn >= 0 ? "value-up" : "value-down"}">${signed(row.mliReturn)}</td>
    <td>${decimal(row.mliUpPct)}</td><td>${number(row.mliN)}</td><td>${number(row.universeN)}</td><td>${row.sp500Close ? Number(row.sp500Close).toLocaleString("en-US", {minimumFractionDigits:2, maximumFractionDigits:2}) : "—"}</td>
  </tr>`).join("");
}

function renderPulse(history) {
  const max = Math.max(800, ...history.flatMap(item => [item.up4 || 0, item.down4 || 0]));
  $("#pulse-chart").innerHTML = [...history].reverse().map(item => {
    const up = Math.max(2, ((item.up4 || 0) / max) * 100);
    const down = Math.max(2, ((item.down4 || 0) / max) * 100);
    const upColor = item.up4 >= 300 ? "var(--green)" : "#5fb397";
    const downColor = item.down4 >= 300 ? "var(--red)" : "#d4786e";
    return `<div class="pulse-item" data-tooltip="${item.date} · UP ${number(item.up4)} / DN ${number(item.down4)}"><div class="pulse-up" style="height:${up}px;background:${upColor}"></div><div class="pulse-down" style="height:${down}px;background:${downColor}"></div></div>`;
  }).join("");
}

function renderLeaderKpis(summary) {
  const analysisN = summary.analysisN || summary.universeN;
  const leaderShare = analysisN ? summary.mliN / analysisN * 100 : null;
  $("#leader-kpis").innerHTML = `
    <article class="leader-kpi"><p class="metric-label">領導股數目</p><div class="metric-value">${number(summary.mliN)}</div><p class="metric-detail">前一日 ${summary.mliN ? "已計算" : "—"}</p></article>
    <article class="leader-kpi"><p class="metric-label">佔總分析股票比率</p><div class="metric-value">${percentage(leaderShare)}</div><p class="metric-detail">分母 ${number(analysisN)} 隻</p></article>
    <article class="leader-kpi"><p class="metric-label">領導股當日升幅</p><div class="metric-value ${summary.mliReturn >= 0 ? "up" : "down"}">${percentage(summary.mliReturn, 2)}</div><p class="metric-detail">等權平均日回報</p></article>
    <article class="leader-kpi"><p class="metric-label">上升比例</p><div class="metric-value">${percentage(summary.mliUpPct)}</div><p class="metric-detail">領導股之內的升股比例</p></article>`;
}

function renderIndustry(rows) {
  const max = Math.max(1, ...rows.map(row => row.leaderShare || 0));
  $("#industry-body").innerHTML = rows.map(row => {
    const fill = Math.max(2, row.leaderShare / max * 100);
    const tick = Math.min(100, row.poolShare / max * 100);
    return `<div class="industry-row" role="row"><span><strong>${row.name}</strong></span><span><span class="share-track"><span class="share-fill" style="width:${fill}%"></span><span class="share-tick" style="left:${tick}%"></span></span></span><span>${number(row.leaderN)}</span><span>${percentage(row.leaderShare)}</span><span>${percentage(row.poolShare)}</span><span>${percentage(row.penetration)}</span><span class="${row.excess >= 0 ? "positive" : "negative"}">${signed(row.excess, 1)}</span></div>`;
  }).join("");
}

function renderTrend(values) {
  const svg = $("#leader-trend");
  if (!values.length) { svg.innerHTML = ""; return; }
  const width = 700, height = 230, left = 40, right = 46, top = 14, bottom = 30;
  const max = Math.max(45, ...values.map(value => value + 5));
  const min = 0;
  const x = index => left + index * (width - left - right) / Math.max(values.length - 1, 1);
  const y = value => top + (max - value) * (height - top - bottom) / (max - min);
  const path = values.map((value,index) => `${index ? "L" : "M"}${x(index).toFixed(1)},${y(value).toFixed(1)}`).join(" ");
  const area = `${path} L ${x(values.length - 1)},${height-bottom} L ${x(0)},${height-bottom} Z`;
  const ticks = [0, 11, 23, 34, 45];
  const last = values.at(-1);
  svg.innerHTML = `${ticks.map(tick => `<g><line class="gridline" x1="${left}" y1="${y(tick)}" x2="${width-right}" y2="${y(tick)}"></line><text class="svg-label" x="0" y="${y(tick)+4}">${tick}%</text></g>`).join("")}<path class="area" d="${area}"></path><path class="trendline" d="${path}"></path><circle class="last-dot" cx="${x(values.length-1)}" cy="${y(last)}" r="4"></circle><text class="svg-value" x="${x(values.length-1)+8}" y="${y(last)+4}">${percentage(last)}</text><text class="svg-label" x="${left}" y="${height-7}">較早</text><text class="svg-label" text-anchor="end" x="${width-right}" y="${height-7}">最新</text>`;
}

async function loadDashboard() {
  try {
    const response = await fetch("data/latest.json", { cache: "no-store" });
    if (!response.ok) throw new Error("找不到每日資料檔案");
    const data = await response.json();
    document.title = `CRC Market Monitor · ${data.asOf || "Setup"}`;
    $("#breadth-date").textContent = data.asOf || "尚未更新";
    $("#header-meta").textContent = `收市 ${data.asOf || "—"}　｜　總分析股票 ${number(data.summary?.universeN)} 隻　｜　${data.source || "未設定資料來源"}`;
    if (data.status !== "live") { const box = $("#data-status"); box.classList.add("visible"); box.textContent = data.message || "目前尚未載入已驗證的市場資料。"; }
    renderKpis(data.summary || {}); renderHistory(data.history || []); renderPulse(data.history || []); renderLeaderKpis(data.summary || {}); renderIndustry(data.industry || []); renderTrend(data.leaderTrend || []);
  } catch (error) { $("#data-status").classList.add("visible"); $("#data-status").textContent = `無法載入每日資料：${error.message}`; }
}
loadDashboard();
