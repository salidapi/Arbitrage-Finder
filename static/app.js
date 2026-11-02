"use strict";

// No API key or bookmaker credential is written to browser storage.
const $ = (id) => document.getElementById(id);
const state = { settings: {}, sources: [], lastScan: null, busy: false, activeTab: "scanner" };
let notificationTimer;
const TZ = "Europe/Tirane";
const tabTitles = { scanner: "Scanner", sources: "Data sources", history: "Scan history", guides: "Guides & code" };
const settingFields = { minimum_profit: "minimum-profit", bankroll: "bankroll", max_age_seconds: "max-age", source_skew_seconds: "source-skew", currency: "currency", mode: "data-mode", sports_filter: "sports-filter", leagues_filter: "leagues-filter", require_source_timestamps: "require-source-timestamps" };

function el(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = String(text);
  return node;
}

function notify(message, type = "success") {
  clearTimeout(notificationTimer);
  const node = $("notification");
  node.className = `notification ${type === "success" ? "" : type}`;
  node.textContent = message;
  node.hidden = false;
  notificationTimer = setTimeout(() => { node.hidden = true; }, type === "error" ? 14000 : 6000);
}

function errorText(detail) {
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return detail.map((d) => `${(d.loc || []).slice(1).join(".")}: ${d.msg || "Invalid value"}`).join("; ");
  return "The request could not be completed. Check the server log for details.";
}

async function api(path, method = "GET", body) {
  const response = await fetch(path, {
    method,
    credentials: "same-origin",
    headers: body === undefined ? { "Accept": "application/json" } : { "Accept": "application/json", "Content-Type": "application/json" },
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const raw = await response.text();
  let data;
  try { data = raw ? JSON.parse(raw) : {}; } catch (_) { throw new Error(`Server returned an unexpected response (${response.status}).`); }
  if (!response.ok) throw new Error(errorText(data.detail || data.message || `Request failed (${response.status}).`));
  return data;
}

function number(value, digits = 2) {
  const n = Number(value);
  return Number.isFinite(n) ? n.toLocaleString("en-GB", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
}

function money(value, currency) { return `${number(value)} ${currency || "EUR"}`; }
function date(value, options = {}) {
  if (!value || !Number.isFinite(new Date(value).getTime())) return "Time unavailable";
  return new Intl.DateTimeFormat("en-GB", { timeZone: TZ, day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit", ...options }).format(new Date(value));
}

function safeURL(value) {
  if (!value) return null;
  try { const url = new URL(value, location.origin); return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : null; } catch (_) { return null; }
}

function statusTag(status, text) {
  const normalized = String(status || "unconfigured").toLowerCase();
  const kind = ["ok", "ready", "success"].includes(normalized) ? "good" : ["error", "blocked", "failed", "timeout"].includes(normalized) ? "bad" : ["unconfigured", "disabled", "unknown", "not_scanned"].includes(normalized) ? "neutral" : "warning";
  return el("span", `tag ${kind}`, text || normalized.replaceAll("_", " ").toUpperCase());
}

function setTab(name) {
  if (!tabTitles[name]) return;
  state.activeTab = name;
  document.querySelectorAll(".tab-panel").forEach((node) => { node.hidden = node.id !== `panel-${name}`; });
  document.querySelectorAll("[data-tab]").forEach((node) => {
    const active = node.dataset.tab === name;
    node.classList.toggle("active", active);
    if (active) node.setAttribute("aria-current", "page"); else node.removeAttribute("aria-current");
  });
  $("page-crumb").textContent = tabTitles[name];
  if (name === "history") loadHistory();
  if (name === "guides") loadDocuments();
  window.scrollTo({ top: 0, behavior: "auto" });
}

function applySettings(settings) {
  state.settings = settings || {};
  for (const [key, id] of Object.entries(settingFields)) {
    if (settings[key] === undefined || settings[key] === null) continue;
    if ($(id).type === "checkbox") $(id).checked = Boolean(settings[key]);
    else $(id).value = settings[key];
  }
  $("stake-currency").textContent = $("currency").value;
  renderModeBanner();
}

function readSettings() {
  return {
    minimum_profit: Number($("minimum-profit").value), bankroll: Number($("bankroll").value),
    max_age_seconds: Number($("max-age").value), source_skew_seconds: Number($("source-skew").value),
    currency: $("currency").value, mode: $("data-mode").value,
    sports_filter: $("sports-filter").value.trim(), leagues_filter: $("leagues-filter").value.trim(),
    require_source_timestamps: $("require-source-timestamps").checked,
  };
}

async function saveSettings(showMessage = true) {
  if (!$("settings-form").reportValidity()) throw new Error("Please correct the highlighted scan preferences.");
  const settings = readSettings();
  await api("/api/settings", "PUT", settings);
  state.settings = settings;
  renderModeBanner();
  if (showMessage) notify("Scan preferences saved.");
}

function renderModeBanner(scanMode) {
  const selectedMode = $("data-mode").value;
  const mode = scanMode || state.lastScan?.mode || selectedMode;
  const banner = $("mode-banner");
  banner.classList.toggle("demo", mode === "demo" || mode === "import");
  let message = mode === "demo"
    ? "Demo mode · Every price and opportunity below is sample data. Switch to Live sources for real data."
    : mode === "import"
    ? "Imported data · These results came from your JSON import. Their source, prices, and settlement rules require your verification."
    : "Live mode · Only configured sources are queried when you scan. Availability and coverage depend on each connector.";
  if (state.lastScan && selectedMode !== mode) message += ` Your next scan is set to ${selectedMode === "demo" ? "Demo" : "Live sources"}.`;
  $("mode-banner-text").textContent = message;
}

function setBusy(busy) {
  state.busy = busy;
  document.querySelectorAll(".scan-trigger").forEach((node) => { node.disabled = busy; });
  $("scan-button").querySelector(".scan-label").textContent = busy ? "Scanning…" : "Scan for arbitrage";
  $("scan-progress").hidden = !busy;
  $("import-form").querySelector("button[type=submit]").disabled = busy;
}

async function scan() {
  if (state.busy) return;
  try {
    await saveSettings(false);
    setBusy(true);
    $("scan-warnings").hidden = true;
    const result = await api("/api/scan", "POST", {});
    renderScan(result);
    await refreshSources(false);
    const warning = !result.quote_count || (result.sources || []).some((s) => ["error", "blocked"].includes(s.status));
    notify(result.quote_count ? `Scan finished. ${result.quote_count} quotes analyzed; ${(result.opportunities || []).length} opportunities found.` : "Scan finished without usable quotes. Check source health and configuration.", warning ? "warning" : "success");
  } catch (error) {
    notify(error.message, "error");
    renderWarnings([`The latest scan failed: ${error.message}`, ...(state.lastScan ? ["Any opportunities still displayed belong to the previous scan. Recheck their timestamps."] : [])]);
    $("result-mode-label").className = "tag bad";
    $("result-mode-label").textContent = state.lastScan ? "PREVIOUS SCAN" : "SCAN FAILED";
  } finally { setBusy(false); }
}

function renderWarnings(warnings) {
  const target = $("scan-warnings");
  target.replaceChildren();
  const usable = Array.isArray(warnings) ? warnings.filter(Boolean) : [];
  target.hidden = !usable.length;
  if (!usable.length) return;
  const list = el("div", "warning-list");
  usable.forEach((warning) => list.append(el("p", "", typeof warning === "string" ? warning : JSON.stringify(warning))));
  target.append(list);
}

function renderScan(result) {
  state.lastScan = result;
  const opportunities = result.opportunities || [];
  $("stat-opportunities").textContent = opportunities.length;
  $("result-count").textContent = opportunities.length;
  const isDemo = result.mode === "demo";
  $("stat-opportunities-note").textContent = isDemo ? "Sample data · not live opportunities" : result.mode === "import" ? "From imported quotes" : "Meeting your scan preferences";
  $("stat-return").textContent = opportunities.length ? `${number(Math.max(...opportunities.map((o) => Number(o.roi_percent))))}%` : "—";
  $("stat-quotes").textContent = number(result.quote_count || 0, 0);
  const sources = result.sources || [];
  $("stat-sources-note").textContent = isDemo ? "Synthetic sample dataset only" : result.mode === "import" ? "User-supplied imported dataset" : `${sources.filter((s) => s.status === "ok").length} of ${sources.length} sources returned data`;
  $("stat-last-scan").textContent = result.completed_at ? date(result.completed_at, { day: undefined, month: undefined, hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";
  $("stat-scan-note").textContent = result.completed_at ? `${date(result.completed_at, { hour: undefined, minute: undefined })} · ${TZ}` : "Manual scans only";
  const label = $("result-mode-label");
  label.className = `tag ${isDemo || result.mode === "import" ? "warning" : "neutral"}`;
  label.textContent = isDemo ? "DEMO · SAMPLE ODDS" : result.mode === "import" ? "IMPORTED QUOTES" : "LIVE SOURCE RESULTS";
  renderModeBanner(result.mode);
  const warnings = [...(result.warnings || [])];
  if (result.rejected && Object.keys(result.rejected).length) {
    const rejected = Object.entries(result.rejected).filter(([, count]) => Number(count) > 0).map(([reason, count]) => `${reason.replaceAll("_", " ")}: ${count}`);
    if (rejected.length) warnings.push(`Excluded by validation: ${rejected.join(" · ")}.`);
  }
  renderWarnings(warnings);
  const target = $("opportunities");
  target.replaceChildren();
  if (!opportunities.length) {
    const hasQuotes = Number(result.quote_count) > 0;
    const failed = !hasQuotes && sources.some((s) => ["error", "blocked", "unconfigured"].includes(s.status));
    const empty = el("div", `empty-state${failed ? " error-state" : ""}`);
    empty.append(el("div", "empty-icon", failed ? "!" : "⌕"));
    empty.append(el("h3", "", hasQuotes ? "No matching opportunities in this scan." : "No usable quotes returned."));
    empty.append(el("p", "", hasQuotes ? "No complete, equivalent market met your profit and freshness requirements. Another scan may produce a different result." : "Review the source status below. Configure at least two compatible bookmaker feeds, or use Demo to explore sample results."));
    target.append(empty);
  } else opportunities.forEach((opportunity) => target.append(opportunityCard(opportunity, result.mode)));
  renderHealth(sources);
  renderQuotePreview(result);
}

function renderQuotePreview(result) {
  const quotes = Array.isArray(result.quote_samples) ? result.quote_samples.slice(0, 100) : [];
  $("quote-preview-count").textContent = quotes.length;
  const preview = $("quote-preview-json");
  preview.hidden = !quotes.length;
  preview.textContent = quotes.length ? JSON.stringify(quotes, null, 2) : "";
  if (!quotes.length) {
    $("quote-preview-note").textContent = Number(result.quote_count) > 0
      ? "This saved scan does not contain a quote preview. Run a new scan to record extracted prices, timestamps, and settlement contracts."
      : "No usable quotes were extracted in this scan. Review source health and connector configuration above.";
    return;
  }
  const modeNote = result.mode === "demo" ? "Demo · synthetic samples only. " : result.mode === "import" ? "Imported data · user-supplied quotes. " : "Live source extraction. ";
  $("quote-preview-note").textContent = `${modeNote}Showing ${quotes.length} of ${Number(result.quote_count) || quotes.length} quotes (maximum preview: 100). Compare these prices, source update times, outcomes, and settlement rules with the bookmaker before using the results. A missing source update time is not proof of a fresh price.`;
}

function outcomeName(outcome, opportunity) {
  const names = { home: opportunity.home || "Home", away: opportunity.away || "Away", draw: "Draw", over: "Over", under: "Under" };
  return names[outcome] || String(outcome || "Unknown outcome");
}

function opportunityCard(opportunity, mode) {
  const card = el("article", "opportunity-card");
  const header = el("div", "opportunity-header");
  const event = el("div");
  event.append(el("div", "event-kicker", `${opportunity.sport || "Sport"} / ${opportunity.league || "League not supplied"}`));
  event.append(el("div", "event-title", typeof opportunity.event === "string" ? opportunity.event : `${opportunity.home || "Home"} vs ${opportunity.away || "Away"}`));
  const meta = el("div", "event-meta");
  const marketNames = { h2h_2way: "Two-way winner", h2h_3way: "Three-way winner", totals: "Totals", spreads: "Handicap" };
  const line = opportunity.line === null || opportunity.line === undefined ? "" : ` ${opportunity.line}`;
  meta.append(el("span", "market-pill", `${marketNames[opportunity.market] || opportunity.market || "Market"}${line}`));
  meta.append(el("span", "", `${opportunity.period || "full_time"} · ${opportunity.rules || "regulation"}`.replaceAll("_", " ")));
  meta.append(el("span", "", `${date(opportunity.starts_at)} · Tirana`));
  if (mode === "demo") meta.append(statusTag("warning", "SAMPLE"));
  event.append(meta);
  const roi = el("div", "roi-block");
  roi.append(el("strong", "", `${number(opportunity.roi_percent)}%`), el("span", "", "CALCULATED RETURN"));
  header.append(event, roi);
  card.append(header);
  const tableWrap = el("div", "legs-wrap");
  const table = el("table", "legs-table");
  const thead = el("thead");
  const headings = el("tr");
  ["BOOKMAKER", "OUTCOME", "ODDS", "STAKE", "GROSS PAYOUT", "PRICE AGE"].forEach((heading) => headings.append(el("th", "", heading)));
  thead.append(headings);
  const tbody = el("tbody");
  (opportunity.legs || []).forEach((leg) => {
    const row = el("tr");
    const bookmaker = el("td", "bookmaker-name");
    bookmaker.append(el("span", "", leg.bookmaker));
    const href = safeURL(leg.url);
    if (href) {
      const link = el("a", "mini-link", " →");
      link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer";
      link.setAttribute("aria-label", `Open ${leg.bookmaker} source page`);
      bookmaker.append(link);
    }
    row.append(bookmaker, el("td", "", outcomeName(leg.outcome, opportunity)), el("td", "odds-value", number(leg.odds, 3)), el("td", "stake-value", money(leg.stake, opportunity.currency)), el("td", "", money(leg.payout, opportunity.currency)));
    const ageCell = el("td");
    const timestamp = leg.source_updated_at || leg.observed_at;
    const age = timestamp ? Math.floor((Date.now() - new Date(timestamp).getTime()) / 1000) : NaN;
    const stale = Number.isFinite(age) && age > Number(state.settings.max_age_seconds || 120);
    const ageLabel = el("span", `quote-age${stale ? " stale" : ""}`, Number.isFinite(age) ? `${Math.max(0, age)}s${stale ? " · STALE" : ""}` : "Unknown");
    if (timestamp) ageLabel.dataset.timestamp = timestamp;
    ageLabel.title = `${leg.source_updated_at ? "Source updated" : "Observed (source time unavailable)"}: ${date(timestamp, { second: "2-digit" })} · ${TZ}`;
    ageCell.append(ageLabel); row.append(ageCell); tbody.append(row);
  });
  table.append(thead, tbody); tableWrap.append(table); card.append(tableWrap);
  const footer = el("div", "opportunity-footer");
  const stake = el("span", "", "Total stake "); stake.append(el("strong", "", money(opportunity.total_stake, opportunity.currency)));
  const profit = el("span", "", "Worst-case calculated profit "); profit.append(el("strong", "", money(opportunity.worst_profit, opportunity.currency)));
  footer.append(stake, profit); card.append(footer);
  const warnings = opportunity.warnings || [];
  if (warnings.length) card.append(el("div", "opportunity-warning", warnings.join(" · ")));
  return card;
}

function renderHealth(scanSources) {
  const overrides = new Map((scanSources || []).map((s) => [s.id, s]));
  const sources = state.sources.map((s) => ({ ...s, ...(overrides.get(s.id) || {}) }));
  for (const source of scanSources || []) if (!sources.some((s) => s.id === source.id)) sources.push(source);
  const target = $("source-health"); target.replaceChildren();
  if (!sources.length) { target.append(el("p", "subtle", "No data sources are configured.")); return; }
  sources.forEach((source) => {
    const item = el("article", "health-item");
    const top = el("div", "health-top");
    top.append(el("span", "health-name", source.name || source.id), statusTag(source.status || (source.enabled ? "not_scanned" : "disabled")));
    item.append(top, el("p", "", source.message || (source.enabled ? "Enabled · not yet scanned" : "Disabled · enable in Data sources")));
    if (source.quote_count !== undefined) item.append(el("p", "", `${number(source.quote_count, 0)} quotes returned`));
    target.append(item);
  });
}

function renderSources() {
  $("source-nav-count").textContent = state.sources.filter((s) => s.enabled).length;
  const target = $("source-configs"); target.replaceChildren();
  state.sources.forEach((source) => {
    const card = el("section", "card source-card");
    const heading = el("div", "card-heading");
    const name = el("div"); name.append(el("h2", "", source.name || source.id), el("div", "source-id", source.id));
    const toggleLabel = el("label", "source-toggle");
    const toggle = el("input"); toggle.type = "checkbox"; toggle.checked = Boolean(source.enabled); toggle.setAttribute("aria-label", `Enable ${source.name || source.id}`);
    toggleLabel.append(toggle, el("span", "", "Enabled")); heading.append(name, toggleLabel);
    card.append(heading);
    const isAPI = ["the_odds_api", "odds_api", "odds-api"].includes(source.id);
    card.append(el("p", "source-description", source.description || (isAPI ? "Optional API connector. Select only the sports and markets needed to conserve your free request quota. Provider coverage must include your bookmakers." : "No-login public scraper. Regional pages and market mappings require verification. An unconfigured profile does not supply live odds.")));
    const configLabel = el("label", "", "Connector configuration · JSON");
    const textarea = el("textarea"); textarea.rows = 9; textarea.spellcheck = false; textarea.value = JSON.stringify(source.config || {}, null, 2); textarea.setAttribute("aria-label", `${source.name || source.id} connector configuration`);
    configLabel.append(textarea, el("small", "", isAPI ? "Enter your API key in the dedicated field above. Keep API quotas and bookmaker coverage in mind." : "Use your scraper PDF for the configuration schema. Do not paste passwords, API keys, cookies, or session tokens here."));
    card.append(configLabel);
    const footer = el("div", "source-card-footer");
    const badge = statusTag(source.status || (source.enabled ? "not_scanned" : "disabled"));
    const save = el("button", "button secondary small", "Save source"); save.type = "button";
    save.addEventListener("click", async () => {
      let config;
      try { config = JSON.parse(textarea.value); if (typeof config !== "object" || !config || Array.isArray(config)) throw new Error("Configuration must be a JSON object."); }
      catch (error) { notify(`Invalid ${source.name || source.id} configuration: ${error.message}`, "error"); return; }
      save.disabled = true;
      try {
        await api(`/api/sources/${encodeURIComponent(source.id)}`, "PUT", { enabled: toggle.checked, config });
        source.enabled = toggle.checked; source.config = config;
        await refreshSources(true); notify(`${source.name || source.id} configuration saved.`);
      } catch (error) { notify(error.message, "error"); }
      finally { save.disabled = false; }
    });
    footer.append(badge, save); card.append(footer);
    if (source.message) card.append(el("p", "subtle source-message", source.message));
    target.append(card);
  });
}

function setAPIKeyStatus(present) {
  $("api-key-status").textContent = present ? "KEY SAVED" : "NO KEY";
  $("api-key-status").className = `tag ${present ? "good" : "neutral"}`;
  $("api-key").placeholder = present ? "Saved key is hidden · enter a replacement" : "Enter your API key";
  $("delete-key").disabled = !present;
  $("load-sports").disabled = !present;
}

async function loadSportsCatalog() {
  const button = $("load-sports");
  const target = $("sports-catalog");
  button.disabled = true;
  button.textContent = "Loading catalog…";
  target.replaceChildren(el("p", "subtle", "Requesting the current sports catalog…"));
  try {
    const result = await api("/api/catalog/sports", "POST", {});
    target.replaceChildren();
    if (result.message) target.append(el("p", result.status === "ok" ? "subtle" : "subtle load-error", result.message));
    if (result.quota !== undefined && result.quota !== null) {
      const quota = typeof result.quota === "object" ? Object.entries(result.quota).map(([key, value]) => `${key}: ${value ?? "unknown"}`).join(" · ") : String(result.quota);
      target.append(el("p", "catalog-quota", `Provider quota · ${quota}`));
    }
    const sports = Array.isArray(result.sports) ? result.sports : [];
    if (!sports.length) {
      target.append(el("p", "subtle", "No sport keys were returned. Check the API key, provider response, and network access."));
      return;
    }
    const wrap = el("div", "history-table-wrap catalog-table-wrap");
    const table = el("table", "history-table catalog-table");
    const head = el("thead"); const headings = el("tr");
    ["SPORT KEY · COPY INTO CONFIGURATION", "SPORT / LEAGUE", "GROUP", "STATUS"].forEach((text) => headings.append(el("th", "", text)));
    head.append(headings);
    const body = el("tbody");
    sports.forEach((sport) => {
      const row = el("tr");
      const keyCell = el("td");
      const key = el("code", "catalog-key", sport.key || "");
      key.tabIndex = 0;
      const copy = el("button", "text-button catalog-copy", "Copy"); copy.type = "button";
      copy.setAttribute("aria-label", `Copy sport key ${sport.key || ""}`);
      copy.addEventListener("click", async () => {
        try { await navigator.clipboard.writeText(String(sport.key || "")); notify("Sport key copied. Add it to the connector's sports JSON list."); }
        catch (_) { const range = document.createRange(); range.selectNodeContents(key); const selection = window.getSelection(); selection.removeAllRanges(); selection.addRange(range); notify("Sport key selected. Use your browser's Copy command."); }
      });
      keyCell.append(key, copy);
      const title = el("td", "", sport.title || sport.key || "Unnamed sport");
      if (sport.description) title.title = sport.description;
      const status = el("td"); status.append(statusTag(sport.active ? "ok" : "unknown", sport.active ? "ACTIVE" : "INACTIVE"));
      row.append(keyCell, title, el("td", "", sport.group || "—"), status); body.append(row);
    });
    table.append(head, body); wrap.append(table); target.append(wrap);
    target.append(el("p", "subtle", `${sports.length} sport keys returned. Active sports may still lack your chosen bookmakers or markets. Edit and save the connector configuration before scanning.`));
  } catch (error) {
    target.replaceChildren(el("p", "subtle load-error", `Could not load the sports catalog: ${error.message}`));
    notify(error.message, "error");
  } finally {
    button.textContent = "Load available sports";
    button.disabled = $("api-key-status").textContent !== "KEY SAVED";
  }
}

async function refreshSources(rebuildForms = false) {
  const data = await api("/api/state");
  state.sources = data.sources || [];
  setAPIKeyStatus(Boolean(data.api_key_present));
  if (rebuildForms) renderSources();
  $("source-nav-count").textContent = state.sources.filter((s) => s.enabled).length;
  renderHealth(state.lastScan?.sources);
}

async function loadHistory() {
  const target = $("history-list");
  try {
    const data = await api("/api/history");
    const scans = data.scans || [];
    target.replaceChildren();
    if (!scans.length) { target.append(el("h2", "", "Your first scan starts the story."), el("p", "subtle history-summary", "Manual scans will appear here with their timestamps, mode, and results.")); return; }
    const wrap = el("div", "history-table-wrap"); const table = el("table", "history-table");
    const head = el("thead"); const headings = el("tr");
    ["COMPLETED · TIRANA", "MODE", "QUOTES", "OPPORTUNITIES", "SOURCE STATUS"].forEach((text) => headings.append(el("th", "", text)));
    head.append(headings); const body = el("tbody");
    scans.forEach((scan) => {
      const row = el("tr"); row.append(el("td", "", date(scan.completed_at || scan.started_at, { second: "2-digit" })));
      const mode = el("td"); mode.append(statusTag(scan.mode === "live" ? "unknown" : "warning", String(scan.mode || "unknown").toUpperCase()));
      const count = scan.opportunity_count ?? (scan.opportunities || []).length;
      const summary = (scan.sources || []).map((s) => `${s.name || s.id}: ${s.status}`).join("; ") || scan.status || "See scan record";
      row.append(mode, el("td", "", number(scan.quote_count || 0, 0)), el("td", "", number(count, 0)), el("td", "history-detail", summary)); body.append(row);
    });
    table.append(head, body); wrap.append(table); target.append(wrap, el("p", "history-summary", "Historical prices are not current opportunities. Start a new scan before considering any bets."));
  } catch (error) { target.replaceChildren(el("p", "subtle load-error", `Could not load history: ${error.message}`)); }
}

async function loadDocuments() {
  const target = $("documents-list");
  try {
    const data = await api("/api/documents");
    const documents = data.documents || [];
    target.replaceChildren();
    if (!documents.length) { const card = el("div", "card"); card.append(el("h2", "", "Documentation is being prepared."), el("p", "subtle history-summary", "Generated PDFs will appear here. Source Markdown and the documentation builder are also included in the repository.")); target.append(card); return; }
    documents.forEach((document) => {
      const href = safeURL(document.url); if (!href) return;
      const card = el("article", "card document-card");
      card.append(el("div", "document-icon", "▤"), el("h2", "", document.name || "Documentation"));
      card.append(el("p", "", document.description || "English PDF · Includes supported behavior, limitations, and step-by-step instructions."));
      const link = el("a", "button secondary", "Open PDF →"); link.href = href; link.target = "_blank"; link.rel = "noopener noreferrer";
      card.append(link); target.append(card);
    });
  } catch (error) { target.replaceChildren(el("p", "subtle load-error", `Could not load documents: ${error.message}`)); }
}

function bindEvents() {
  document.querySelectorAll("[data-tab]").forEach((node) => node.addEventListener("click", () => setTab(node.dataset.tab)));
  document.querySelectorAll("[data-go-tab]").forEach((node) => node.addEventListener("click", () => setTab(node.dataset.goTab)));
  $("scan-button").addEventListener("click", scan);
  $("settings-form").addEventListener("submit", async (event) => { event.preventDefault(); try { await saveSettings(); } catch (error) { notify(error.message, "error"); } });
  $("data-mode").addEventListener("change", () => renderModeBanner());
  $("currency").addEventListener("change", () => { $("stake-currency").textContent = $("currency").value; });
  $("refresh-history").addEventListener("click", loadHistory);
  $("load-sports").addEventListener("click", loadSportsCatalog);
  $("api-key-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const key = $("api-key").value.trim();
    if (!key) { notify("Enter an API key to save.", "error"); return; }
    const save = $("api-key-form").querySelector("button[type=submit]"); save.disabled = true;
    try { await api("/api/credentials/odds-api", "PUT", { api_key: key }); $("api-key").value = ""; setAPIKeyStatus(true); notify("API key saved locally. The saved value stays hidden."); }
    catch (error) { notify(error.message, "error"); }
    finally { save.disabled = false; }
  });
  $("delete-key").addEventListener("click", async () => {
    try { await api("/api/credentials/odds-api", "DELETE"); $("api-key").value = ""; setAPIKeyStatus(false); notify("Saved API key removed."); }
    catch (error) { notify(error.message, "error"); }
  });
  $("import-file").addEventListener("change", async (event) => {
    const file = event.target.files[0]; if (!file) return;
    if (file.size > 5 * 1024 * 1024) { notify("Choose a JSON file smaller than 5 MB.", "error"); return; }
    try { $("import-json").value = await file.text(); } catch (_) { notify("The selected file could not be read.", "error"); }
  });
  $("import-form").addEventListener("submit", async (event) => {
    event.preventDefault(); if (state.busy) return;
    try {
      let payload = JSON.parse($("import-json").value);
      if (Array.isArray(payload)) payload = { quotes: payload };
      if (!payload || !Array.isArray(payload.quotes)) throw new Error("Import a JSON object with a quotes array, or an array of normalized quotes.");
      await saveSettings(false); setBusy(true);
      const result = await api("/api/import", "POST", payload);
      renderScan(result); setTab("scanner"); notify(`Imported ${result.quote_count || 0} quotes. Results are labeled as imported data.`);
    } catch (error) { notify(error.message, "error"); }
    finally { setBusy(false); }
  });
}

async function initialize() {
  bindEvents();
  try {
    const data = await api("/api/state");
    state.sources = data.sources || [];
    applySettings(data.settings || {});
    renderSources(); setAPIKeyStatus(Boolean(data.api_key_present));
    if (data.last_scan) renderScan(data.last_scan); else renderHealth();
  } catch (error) {
    notify(`Dashboard connection failed: ${error.message}`, "error");
    $("source-health").replaceChildren(el("p", "subtle load-error", "Cannot reach the local backend. Check that the server is running and reload this page."));
  }
}

// Only the elapsed age changes here. This timer never requests new odds.
setInterval(() => {
  document.querySelectorAll(".quote-age[data-timestamp]").forEach((node) => {
    const age = Math.floor((Date.now() - new Date(node.dataset.timestamp).getTime()) / 1000);
    if (!Number.isFinite(age)) return;
    const stale = age > Number(state.settings.max_age_seconds || 120);
    node.textContent = `${Math.max(0, age)}s${stale ? " · STALE" : ""}`;
    node.classList.toggle("stale", stale);
  });
}, 1000);

initialize();
