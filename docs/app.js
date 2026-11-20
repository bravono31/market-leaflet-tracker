const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));
const yen = (n) => "¥" + Math.round(n).toLocaleString("ja-JP");
const md = (d) => `${+d.slice(5, 7)}/${+d.slice(8, 10)}`;
const period = (a, b) => (a === b ? md(a) : `${md(a)}〜${md(b)}`);
const TAX10 = new Set(["酒", "日用品"]);
// Same order as CATEGORIES in scraper/extract.py.
const CATS = ["野菜・果物", "肉", "魚", "惣菜・弁当", "乳製品・卵", "パン・米・麺",
  "加工食品・調味料", "冷凍食品", "菓子", "飲料", "酒", "日用品", "その他"];

let items = [], leaflets = [], net = {}, status = { stores: {}, store_urls: {}, errors: [] };
const hidden = new Set(), hiddenCats = new Set();
const today = new Date(Date.now() + 9 * 3600e3).toISOString().slice(0, 10); // JST

// Tax-included price; estimated from the tax rate when the leaflet shows only one of them.
function taxIn(it) {
  if (it.price_tax_in != null) return { value: it.price_tax_in, approx: false };
  return { value: Math.floor(it.price * (TAX10.has(it.category) ? 1.1 : 1.08)), approx: true };
}
// Comparable unit: weights/volumes per 100g/100ml, counts per piece.
// "各250g"→250g, "1パック(100g)"→100g, "3点"/"6缶パック"/"1ケース24本"/"10食入"→the last count. "1/4切" stays.
const COUNTER = "袋|パック|本|コ|個|箱|点|缶|切|尾|束|盛|枚|セット|人前|カップ|食|瓶|房|株|ポット|ネット|組|ケース|ホール|玉|匹|杯|粒|丁|貫|カン|台|連|ヶ";
function parseUnit(unit) {
  const u = unit || "";
  const w = u.match(/(?<![\d/.])(\d+(?:\.\d+)?)\s*(kg|g|ml|mL|L|ℓ)(?![a-zA-Z])/);
  if (w) {
    const big = /^(kg|L|ℓ)$/.test(w[2]);
    return { n: (+w[1] * (big ? 1000 : 1)) / 100, unit: /g/.test(w[2]) ? "100g" : "100ml" };
  }
  const counts = [...u.matchAll(new RegExp(`(?<![\\d/.])(\\d+)(${COUNTER})`, "g"))];
  if (!counts.length) return { n: 1, unit: u || "—" };
  const [, n, c] = counts[counts.length - 1];
  return { n: +n, unit: `1${{ コ: "個", ヶ: "個", カン: "貫" }[c] || c}` };
}
function unitPrice(it) {
  const p = taxIn(it), { n, unit } = parseUnit(it.unit);
  return { value: p.value / n, approx: p.approx, unit, total: p.value, converted: n !== 1 };
}
const priceHtml = (it) => {
  const p = unitPrice(it);
  return `${p.approx ? "<small>約</small>" : ""}${yen(p.value)}<small> /${esc(p.unit)}</small>` +
    (p.converted && it.unit ? `<small class="orig">${yen(p.total)} /${esc(it.unit)}</small>` : "");
};
const storeHtml = (s) => `<span class="store"><span class="dot" style="background:var(--${s})"></span>${esc(status.stores[s] || s)}</span>`;
const isActive = (it) => it.start <= today && today <= it.end;

function filtered() {
  const q = $("q").value.trim().toLowerCase();
  const activeOnly = $("active").checked;
  return items.filter((it) =>
    !hidden.has(it.store) && !hiddenCats.has(it.category) && (!activeOnly || isActive(it)) &&
    (!q || (it.name + " " + it.key).toLowerCase().includes(q)));
}

function renderList() {
  const sort = $("sort").value;
  const rows = filtered().sort((a, b) =>
    sort === "price" ? unitPrice(a).value - unitPrice(b).value :
    sort === "name" ? a.key.localeCompare(b.key, "ja") :
    a.end.localeCompare(b.end) || a.key.localeCompare(b.key, "ja"));
  $("count").textContent = `${rows.length}件`;
  $("items").innerHTML = rows.slice(0, 500).map((it) => `
    <li>
      <button class="linklike name" data-key="${esc(it.key)}">${esc(it.name)}</button>
      <span class="price">${priceHtml(it)}</span>
      <span class="meta muted">${storeHtml(it.store)}<span>${period(it.start, it.end)}</span>
        <span>${esc(it.category)}</span>${it.note ? `<span class="tag">${esc(it.note)}</span>` : ""}</span>
    </li>`).join("") || `<li class="empty">該当する商品がありません</li>`;
}

function renderCompare() {
  const stores = Object.keys(status.stores).filter((s) => !hidden.has(s));
  const groups = new Map();
  for (const it of filtered()) {
    const g = groups.get(it.key) || groups.set(it.key, {}).get(it.key);
    // Keep each store's cheapest current offer for the product.
    if (!g[it.store] || unitPrice(it).value < unitPrice(g[it.store]).value) g[it.store] = it;
  }
  const rows = [...groups].map(([key, g]) => ({ key, g, n: Object.keys(g).length }))
    .sort((a, b) => b.n - a.n || a.key.localeCompare(b.key, "ja")).slice(0, 300);
  const head = `<tr><th>商品</th>${stores.map((s) => `<th>${storeHtml(s)}</th>`).join("")}<th>ネット最安</th></tr>`;
  const body = rows.map(({ key, g }) => {
    const offers = Object.values(g);
    const sameUnit = offers.length > 1 && offers.every((o) => unitPrice(o).unit === unitPrice(offers[0]).unit);
    const min = Math.min(...offers.map((o) => unitPrice(o).value));
    const cells = stores.map((s) => {
      const it = g[s];
      if (!it) return "<td>—</td>";
      return `<td class="${sameUnit && unitPrice(it).value === min ? "best" : ""}">${priceHtml(it)}</td>`;
    }).join("");
    const o = net[key]?.offers?.[0];
    const netCell = o ? `<a href="${esc(o.url)}" target="_blank" rel="noopener">${yen(o.price)}</a>` : "—";
    return `<tr><td><button class="linklike" data-key="${esc(key)}">${esc(key)}</button></td>${cells}<td>${netCell}</td></tr>`;
  }).join("");
  $("compareTable").innerHTML = body ? head + body : `<tr><td class="empty">該当する商品がありません</td></tr>`;
}

function renderHistory() {
  const key = $("product").value.trim();
  const rows = items.filter((it) => it.key === key).sort((a, b) => a.start.localeCompare(b.start));
  $("chartWrap").hidden = !rows.length;
  if (!rows.length) return;
  $("chartTitle").textContent = `${key} の税込単価`;
  const stores = [...new Set(rows.map((r) => r.store))];
  $("legend").innerHTML = stores.map(storeHtml).join("");
  drawChart(rows);
  const offers = net[key]?.offers || [];
  $("net").innerHTML = offers.length
    ? `<strong>ネット参考価格</strong>（Yahoo!ショッピング・${esc(net[key].fetched)}時点・送料別の場合あり）<ul>` +
      offers.map((o) => `<li><a href="${esc(o.url)}" target="_blank" rel="noopener">${yen(o.price)}</a> ${esc(o.title)}</li>`).join("") + "</ul>"
    : "";
  $("historyTable").innerHTML = "<tr><th>期間</th><th>店舗</th><th>税込価格</th><th>チラシ表記</th></tr>" +
    [...rows].reverse().map((it) =>
      `<tr><td>${period(it.start, it.end)}</td><td>${storeHtml(it.store)}</td><td>${priceHtml(it)}</td><td style="white-space:normal;text-align:left">${esc(it.name)}</td></tr>`).join("");
}

// One horizontal segment per offer (start→end at its price), so sale periods read as lengths.
function drawChart(rows) {
  const W = 640, H = 260, L = 48, R = 12, T = 12, B = 28;
  const day = (d) => Date.parse(d) / 864e5;
  let x0 = Math.min(...rows.map((r) => day(r.start))), x1 = Math.max(...rows.map((r) => day(r.end)));
  if (x1 - x0 < 6) { x0 -= 3; x1 += 3; }
  const max = Math.max(...rows.map((r) => unitPrice(r).value));
  const step = [1, 2, 5, 10, 20, 50, 100, 200, 500, 1000, 2000, 5000].find((s) => max / s <= 5) || 10000;
  const top = Math.ceil(max / step) * step;
  const x = (d) => L + ((d - x0) / (x1 - x0)) * (W - L - R);
  const y = (v) => T + (1 - v / top) * (H - T - B);
  let svg = "";
  for (let v = 0; v <= top; v += step)
    svg += `<line class="grid" x1="${L}" x2="${W - R}" y1="${y(v)}" y2="${y(v)}"/><text x="${L - 6}" y="${y(v) + 4}" text-anchor="end">${yen(v)}</text>`;
  const ticks = 4;
  for (let i = 0; i <= ticks; i++) {
    const d = x0 + ((x1 - x0) * i) / ticks;
    svg += `<text x="${x(d)}" y="${H - 8}" text-anchor="${i === 0 ? "start" : i === ticks ? "end" : "middle"}">${md(new Date(d * 864e5).toISOString())}</text>`;
  }
  rows.forEach((r, i) => {
    const a = x(day(r.start)), b = Math.max(x(day(r.end)), a), py = y(unitPrice(r).value), c = `var(--${r.store})`;
    svg += `<line x1="${a}" x2="${b}" y1="${py}" y2="${py}" stroke="${c}" stroke-width="2" stroke-linecap="round"/>
      <circle cx="${a}" cy="${py}" r="4" fill="${c}" stroke="var(--surface)" stroke-width="2"/>
      <rect class="hit" data-i="${i}" x="${a - 12}" y="${py - 12}" width="${b - a + 24}" height="24"/>`;
  });
  $("chart").innerHTML = `<svg viewBox="0 0 ${W} ${H}" role="img" aria-label="${esc($("chartTitle").textContent)}の推移。詳細は下の表を参照">${svg}</svg>`;
  const tip = $("tooltip");
  const show = (e) => {
    const r = rows[e.target.dataset?.i];
    if (!r) return (tip.hidden = true);
    tip.innerHTML = `${storeHtml(r.store)}<br><strong>${priceHtml(r)}</strong><br>${period(r.start, r.end)}`;
    tip.hidden = false;
    tip.style.left = Math.min(e.clientX + 12, innerWidth - 250) + "px";
    tip.style.top = e.clientY + 14 + "px";
  };
  $("chart").onpointermove = show;
  $("chart").onpointerdown = show;
  $("chart").onpointerleave = () => (tip.hidden = true);
}

function renderCampaign() {
  const rows = leaflets.filter((l) => !hidden.has(l.store) && (!$("active").checked || (l.start <= today && today <= l.end)))
    .sort((a, b) => b.start.localeCompare(a.start));
  $("leaflets").innerHTML = rows.map((l) => `
    <li>
      <a class="name" href="${esc(l.source_url)}" target="_blank" rel="noopener">${esc(l.title)}</a>
      <span class="muted">${period(l.start, l.end)}</span>
      <span class="meta muted">${storeHtml(l.store)}
        ${(l.campaigns || []).map((c) => `<span class="tag" title="${esc(c.detail || "")}">${esc(c.name)}${c.start ? `（${period(c.start, c.end || c.start)}）` : ""}</span>`).join("")}</span>
    </li>`).join("") || `<li class="empty">該当するチラシがありません</li>`;
}

const renderers = { list: renderList, compare: renderCompare, history: renderHistory, campaign: renderCampaign };
let tab = "list";
function render() { renderers[tab](); }
function showTab(name) {
  tab = name;
  for (const b of $("tabs").children) b.setAttribute("aria-selected", b.dataset.tab === name);
  for (const v of document.querySelectorAll(".view")) v.hidden = v.id !== name;
  render();
}

// Pressed chips are shown; the 全表示/全非表示 buttons press or release every chip in the group.
function chipGroup(box, hiddenSet) {
  box.onclick = (e) => {
    const b = e.target.closest("button");
    if (!b) return;
    const chips = b.dataset.all ? [...box.querySelectorAll("[data-value]")] : [b];
    const on = b.dataset.all ? b.dataset.all === "on" : b.getAttribute("aria-pressed") !== "true";
    for (const c of chips) {
      c.setAttribute("aria-pressed", on);
      on ? hiddenSet.delete(c.dataset.value) : hiddenSet.add(c.dataset.value);
    }
    render();
  };
}

async function init() {
  const get = (f) => fetch(`data/${f}`, { cache: "no-cache" }).then((r) => (r.ok ? r.json() : null)).catch(() => null);
  const [i, l, n, s] = await Promise.all(["items.json", "leaflets.json", "net.json", "status.json"].map(get));
  items = i || []; leaflets = l || []; net = n || {}; status = s || status;

  $("status").innerHTML = (status.updated ? `最終更新 ${esc(status.updated)}・${leaflets.length}チラシ・${items.length}品目` : "まだデータがありません") +
    (status.pending ? `・未処理 ${status.pending}件` : "") +
    (status.errors || []).map((e) => `<span class="err">⚠ ${esc(e)}</span>`).join("");
  $("stores").innerHTML = Object.keys(status.stores).map((s) =>
    `<button class="chip" aria-pressed="true" data-value="${s}"><span class="dot" style="background:var(--${s})"></span>${esc(status.stores[s])}</button>`).join("");
  const cats = [...new Set(items.map((x) => x.category))].sort((a, b) => CATS.indexOf(a) - CATS.indexOf(b));
  $("categories").innerHTML = `<button class="chip all" data-all="on">全表示</button><button class="chip all" data-all="off">全非表示</button>` +
    cats.map((c) => `<button class="chip" aria-pressed="true" data-value="${esc(c)}">${esc(c)}</button>`).join("");
  $("products").innerHTML = [...new Set(items.map((x) => x.key))].sort((a, b) => a.localeCompare(b, "ja")).map((k) => `<option value="${esc(k)}">`).join("");

  $("tabs").onclick = (e) => e.target.dataset.tab && showTab(e.target.dataset.tab);
  chipGroup($("stores"), hidden);
  chipGroup($("categories"), hiddenCats);
  for (const id of ["q", "active", "sort", "product"]) $(id).oninput = render;
  document.querySelector("main").addEventListener("click", (e) => {
    const key = e.target.closest("[data-key]")?.dataset.key;
    if (key) { $("product").value = key; showTab("history"); scrollTo(0, 0); }
  });
  render();
}
init();
