"use strict";

const $ = (id) => document.getElementById(id);
const MAX_TABLE_ROWS = 100;
const SHIELD = '<svg viewBox="0 0 16 16" aria-hidden="true"><path d="M8 1.5 2.5 3.5v4c0 3.2 2.3 5.9 5.5 7 3.2-1.1 5.5-3.8 5.5-7v-4z"/></svg>';

const state = {
  privacyMode: "standard",
  privacyLocked: false,
  dataset: null,
  review: null,
  dashboardHtml: "",
};

// ---------- small helpers ----------

function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

/** Minimal, safe Markdown: paragraphs, "- " bullets and **bold**. Everything is escaped first. */
function renderMarkdown(text) {
  const inline = (line) => escapeHtml(line).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
  const html = [];
  let list = [];
  const flush = () => { if (list.length) { html.push(`<ul>${list.join("")}</ul>`); list = []; } };
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    const bullet = line.match(/^[-*•]\s+(.*)$/);
    if (bullet) { list.push(`<li>${inline(bullet[1])}</li>`); continue; }
    flush();
    if (line) html.push(`<p>${inline(line)}</p>`);
  }
  flush();
  return html.join("");
}

const isNumber = (value) => typeof value === "number" && Number.isFinite(value);
const numberFormat = new Intl.NumberFormat(undefined, { maximumFractionDigits: 2 });
/** IDs, years and codes are labels, not quantities: show them without thousands separators. */
const LABEL_COLUMN = /(^|[^a-z])(id|year|code|zip|postcode)$/i;
const formatCell = (value, isLabel) =>
  value === null ? "" : isNumber(value) && !isLabel ? numberFormat.format(value) : String(value);

function buildTable(columns, rows) {
  const numeric = columns.map((_, i) => rows.length > 0 && rows.every((row) => row[i] === null || isNumber(row[i])));
  const label = columns.map((c) => LABEL_COLUMN.test(c));
  const head = columns.map((c, i) => `<th${numeric[i] ? ' class="num"' : ""}>${escapeHtml(c)}</th>`).join("");
  const body = rows.map((row) => `<tr>${row.map((v, i) => `<td${numeric[i] ? ' class="num"' : ""}>${escapeHtml(formatCell(v, label[i]))}</td>`).join("")}</tr>`).join("");
  return `<div class="table-wrap"><table><thead><tr>${head}</tr></thead><tbody>${body}</tbody></table></div>`;
}

function renderAudit(details, calls) {
  details.hidden = false;
  if (!calls.length) {
    details.innerHTML = "<summary>What the AI saw: nothing (no AI call was made)</summary>";
    return;
  }
  const items = calls.map((call, i) => `
    <div class="ai-call">
      <h4>${i + 1}. ${escapeHtml(call.step.replace(/_/g, " "))}</h4>
      <details><summary>Instructions (system prompt)</summary><pre>${escapeHtml(call.system)}</pre></details>
      <pre>${escapeHtml(call.user)}</pre>
    </div>`).join("");
  details.innerHTML = `<summary>What the AI saw (${calls.length} call${calls.length > 1 ? "s" : ""}, exact text)</summary>${items}`;
}

function formatTimings(timings) {
  const parts = Object.entries(timings || {}).map(([step, ms]) => `${step} ${(ms / 1000).toFixed(1)}s`);
  return parts.length ? `Time: ${parts.join(" · ")}` : "";
}

async function api(path, options = {}) {
  const response = await fetch(path, options);
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(body.detail || `Request failed (${response.status})`);
  return body;
}

// ---------- status and privacy ----------

function setServerStatus(connected) {
  const pill = $("server-status");
  pill.classList.toggle("ok", connected);
  pill.classList.toggle("down", !connected);
  pill.querySelector(".label").textContent = connected ? "MCP server connected" : "MCP server not running: start csv-mcp-server";
}

function renderPrivacy() {
  for (const button of document.querySelectorAll(".seg")) {
    const active = button.dataset.mode === state.privacyMode;
    button.classList.toggle("active", active);
    button.setAttribute("aria-pressed", String(active));
    button.disabled = state.privacyLocked && button.dataset.mode !== "strict";
  }
  if (state.privacyLocked) $("server-status").title = "PRIVACY_MODE=strict is set on the server";
}

for (const button of document.querySelectorAll(".seg")) {
  button.addEventListener("click", () => {
    if (state.privacyLocked) return;
    state.privacyMode = button.dataset.mode;
    try { localStorage.setItem("privacyMode", state.privacyMode); } catch { /* storage unavailable */ }
    renderPrivacy();
  });
}

async function refreshStatus() {
  try {
    const status = await api("/api/status");
    setServerStatus(status.mcp_connected);
    state.privacyLocked = status.privacy_mode_locked;
    let saved = null;
    try { saved = localStorage.getItem("privacyMode"); } catch { /* storage unavailable */ }
    state.privacyMode = state.privacyLocked ? "strict" : saved || status.privacy_mode;
    renderPrivacy();
    if (!state.review) showDataset(status.dataset); // never interrupt the PII review step
  } catch {
    setServerStatus(false);
  }
}

// ---------- data panel ----------

function showSection(name) {
  for (const section of ["empty", "review", "loaded"]) $(`data-${section}`).hidden = section !== name;
}

function setInputsEnabled(enabled) {
  for (const id of ["chat-input", "chat-send", "dashboard-input", "dashboard-send"]) $(id).disabled = !enabled;
  $("chat-input").placeholder = enabled ? "Ask a question about your data" : "Upload a CSV to start";
}

function showDataset(profile) {
  state.dataset = profile;
  setInputsEnabled(Boolean(profile));
  if (!profile) {
    if (!state.review) showSection("empty");
    renderSuggestions(null);
    return;
  }
  showSection("loaded");
  $("dataset-name").textContent = profile.source_file || profile.dataset;
  $("dataset-rows").textContent = `${numberFormat.format(profile.row_count)} rows · ${profile.columns.length} columns`;
  $("dataset-columns").innerHTML = profile.columns.map((column) => {
    const badge = column.masked ? '<span class="badge masked">masked</span>' : column.pii ? `<span class="badge">${escapeHtml(column.pii)}</span>` : "";
    return `<li><span>${escapeHtml(column.name)}${badge}</span><span class="dtype">${escapeHtml(column.dtype)}</span></li>`;
  }).join("");
  renderSuggestions(profile);
}

async function uploadFile(file) {
  $("upload-error").hidden = true;
  const form = new FormData();
  form.append("file", file);
  try {
    state.review = await api("/api/upload", { method: "POST", body: form });
    showReview(state.review);
  } catch (error) {
    $("upload-error").textContent = error.message;
    $("upload-error").hidden = false;
  }
}

function showReview(review) {
  showSection("review");
  $("ingest-error").hidden = true;
  $("review-name").textContent = review.filename;
  $("review-rows").textContent = `${numberFormat.format(review.row_count)} rows · ${review.columns.length} columns`;
  const findings = Object.fromEntries(review.pii.map((finding) => [finding.column, finding]));
  const summary = $("pii-summary");
  summary.classList.toggle("warn", review.pii.length > 0);
  summary.textContent = review.pii.length
    ? `Possible personal data in ${review.pii.length} column${review.pii.length > 1 ? "s" : ""}. They are set to be masked; change that below if you need the real values.`
    : "No personal data detected. You can still mask or rename any column.";
  $("review-columns").innerHTML = review.columns.map((column, i) => {
    const finding = findings[column.name];
    const badge = finding ? `<span class="badge" title="${escapeHtml(finding.reason)}">${escapeHtml(finding.kind)}</span>` : "";
    return `<tr>
      <td>${escapeHtml(column.name)}${badge}</td>
      <td><input type="checkbox" data-column="${i}" class="mask" ${finding ? "checked" : ""} aria-label="Mask ${escapeHtml(column.name)}"></td>
      <td><input type="text" data-column="${i}" class="rename" placeholder="keep" aria-label="Rename ${escapeHtml(column.name)}"></td>
    </tr>`;
  }).join("");
  $("review-preview").innerHTML = buildTable(review.columns.map((c) => c.name), review.preview).replace(/^<div class="table-wrap">|<\/div>$/g, "");
}

function collectChoices() {
  const choices = {};
  for (const [i, column] of state.review.columns.entries()) {
    const mask = document.querySelector(`.mask[data-column="${i}"]`).checked;
    const rename = document.querySelector(`.rename[data-column="${i}"]`).value.trim();
    if (mask || rename) choices[column.name] = { mask, rename: rename || null };
  }
  return choices;
}

$("ingest-btn").addEventListener("click", async () => {
  const button = $("ingest-btn");
  button.disabled = true;
  button.textContent = "Converting…";
  try {
    const profile = await api("/api/ingest", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ upload_id: state.review.upload_id, choices: collectChoices() }),
    });
    state.review = null;
    resetConversation();
    showDataset(profile);
  } catch (error) {
    $("ingest-error").textContent = error.message;
    $("ingest-error").hidden = false;
  } finally {
    button.disabled = false;
    button.textContent = "Convert & load";
  }
});

$("cancel-btn").addEventListener("click", () => { state.review = null; showDataset(state.dataset); });

$("remove-btn").addEventListener("click", async () => {
  await api("/api/dataset", { method: "DELETE" });
  resetConversation();
  showDataset(null);
});

const dropzone = $("dropzone");
$("file-input").addEventListener("change", (event) => { if (event.target.files[0]) uploadFile(event.target.files[0]); event.target.value = ""; });
dropzone.addEventListener("dragover", (event) => { event.preventDefault(); dropzone.classList.add("dragging"); });
dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragging"));
dropzone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropzone.classList.remove("dragging");
  if (event.dataTransfer.files[0]) uploadFile(event.dataTransfer.files[0]);
});

// ---------- chat ----------

function renderSuggestions(profile) {
  const box = $("suggestions");
  box.innerHTML = "";
  if (!profile) return;
  const columns = profile.columns.filter((c) => !c.pii);
  const category = columns.find((c) => c.dtype === "String" && c.distinct > 1 && c.distinct <= 30);
  const measure = columns
    .filter((c) => /Int|Float|Decimal/.test(c.dtype) && !LABEL_COLUMN.test(c.name) && c.distinct < profile.row_count)
    .sort((a, b) => (b.max ?? 0) - (a.max ?? 0))[0];
  const date = columns.find((c) => /Date/.test(c.dtype));
  const ideas = [];
  if (category && measure) ideas.push(`Which ${category.name} has the highest total ${measure.name}?`);
  if (date && measure) ideas.push(`How does ${measure.name} change by month?`);
  if (category) ideas.push(`How many rows per ${category.name}?`);
  if (!ideas.length) ideas.push("How many rows are there?");
  for (const idea of ideas) {
    const chip = document.createElement("button");
    chip.type = "button";
    chip.className = "suggestion";
    chip.textContent = idea;
    chip.addEventListener("click", () => ask(idea));
    box.append(chip);
  }
}

function resetConversation() {
  for (const node of [...$("messages").children]) if (node.id !== "chat-empty") node.remove();
  $("chat-empty").hidden = false;
  $("dashboard-result").hidden = true;
  $("dashboard-error").hidden = true;
}

function addUserMessage(text) {
  const node = document.createElement("div");
  node.className = "message user";
  node.textContent = text;
  $("messages").append(node);
}

/** Read server-sent events from a POST response, calling onEvent for each JSON payload. */
async function readEvents(response, onEvent) {
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  for (;;) {
    const { value, done } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    let boundary;
    while ((boundary = buffer.indexOf("\n\n")) !== -1) {
      const chunk = buffer.slice(0, boundary);
      buffer = buffer.slice(boundary + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data: "));
      if (line) onEvent(JSON.parse(line.slice(6)));
    }
  }
}

function assistantView() {
  const node = $("assistant-template").content.firstElementChild.cloneNode(true);
  $("messages").append(node);
  const part = (selector) => node.querySelector(selector);
  let insight = "";
  const scroll = () => { $("messages").scrollTop = $("messages").scrollHeight; };

  return {
    status(text) { part(".status-text").textContent = text; scroll(); },
    handle(event) {
      if (event.type === "sql") {
        part(".sql pre").textContent = event.sql;
        part(".sql").hidden = false;
        const matches = event.filter_matches || [];
        if (matches.length) {
          part(".matches").hidden = false;
          part(".matches").innerHTML = matches.map((m) => m.matched
            ? `<span class="match" title="Matched on this machine">${escapeHtml(m.column)}: '${escapeHtml(m.requested)}' → '${escapeHtml(m.matched)}'</span>`
            : `<span class="match missing">${escapeHtml(m.column)}: no value like '${escapeHtml(m.requested)}'</span>`).join("");
        }
        this.status("Running the query on this machine…");
      } else if (event.type === "table") {
        const shown = event.rows.slice(0, MAX_TABLE_ROWS);
        const note = event.row_count > shown.length || event.truncated
          ? `Showing ${shown.length} of ${numberFormat.format(event.row_count)}${event.truncated ? "+" : ""} rows.`
          : `${numberFormat.format(event.row_count)} row${event.row_count === 1 ? "" : "s"}.`;
        part(".result").innerHTML = event.rows.length ? buildTable(event.columns, shown) + `<div class="result-meta">${note}</div>` : '<p class="muted">The query returned no rows.</p>';
        part(".result").hidden = false;
        this.status("Writing the answer…");
      } else if (event.type === "privacy") {
        part(".privacy-note").innerHTML = `${SHIELD}<span>${escapeHtml(event.reason)}</span>`;
        part(".privacy-note").hidden = false;
      } else if (event.type === "insight") {
        insight += event.text;
        part(".answer-text").innerHTML = renderMarkdown(insight);
        part(".answer-text").hidden = false;
      } else if (event.type === "summary") {
        part(".answer-text").innerHTML = `<span class="source">Written on this machine, without the AI</span>${renderMarkdown(event.text)}`;
        part(".answer-text").hidden = false;
      } else if (event.type === "done" || event.type === "error") {
        part(".status-line").hidden = event.type === "done";
        if (event.type === "error") {
          part(".spinner").remove();
          part(".status-text").textContent = event.message;
          part(".status-line").classList.add("error");
        }
        renderAudit(part(".ai-saw"), event.audit || []);
        const timings = formatTimings(event.timings_ms);
        if (timings) { part(".timings").textContent = timings; part(".timings").hidden = false; }
      }
      scroll();
    },
  };
}

async function ask(question) {
  if (!state.dataset) return;
  $("chat-empty").hidden = true;
  addUserMessage(question);
  const view = assistantView();
  $("chat-send").disabled = true;
  try {
    const response = await fetch("/api/chat", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, privacy_mode: state.privacyMode }),
    });
    if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `Request failed (${response.status})`);
    await readEvents(response, (event) => view.handle(event));
  } catch (error) {
    view.handle({ type: "error", message: error.message, audit: [] });
  } finally {
    $("chat-send").disabled = false;
  }
}

$("chat-form").addEventListener("submit", (event) => {
  event.preventDefault();
  const question = $("chat-input").value.trim();
  if (!question) return;
  $("chat-input").value = "";
  ask(question);
});

// ---------- dashboard ----------

$("dashboard-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const question = $("dashboard-input").value.trim();
  if (!question) return;
  const status = $("dashboard-status");
  status.innerHTML = '<span class="spinner"></span><span>Planning metrics from the schema, then running every query at once…</span>';
  status.hidden = false;
  $("dashboard-error").hidden = true;
  $("dashboard-send").disabled = true;
  try {
    const body = await api("/api/dashboard", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question }),
    });
    state.dashboardHtml = body.html;
    $("dashboard-frame").srcdoc = body.html;
    $("dashboard-timings").textContent = formatTimings(body.timings_ms);
    renderAudit($("dashboard-audit"), body.audit);
    $("dashboard-result").hidden = false;
  } catch (error) {
    $("dashboard-error").textContent = error.message;
    $("dashboard-error").hidden = false;
  } finally {
    status.hidden = true;
    $("dashboard-send").disabled = false;
  }
});

$("dashboard-frame").addEventListener("load", () => {
  const frame = $("dashboard-frame");
  try {
    frame.style.height = `${frame.contentDocument.documentElement.scrollHeight + 4}px`;
  } catch { /* keep the default height */ }
});

$("dashboard-download").addEventListener("click", () => {
  const link = document.createElement("a");
  link.href = URL.createObjectURL(new Blob([state.dashboardHtml], { type: "text/html" }));
  link.download = "dashboard.html";
  link.click();
  URL.revokeObjectURL(link.href);
});

// ---------- tabs ----------

for (const tab of document.querySelectorAll(".tab")) {
  tab.addEventListener("click", () => {
    for (const other of document.querySelectorAll(".tab")) {
      const active = other === tab;
      other.classList.toggle("active", active);
      other.setAttribute("aria-selected", String(active));
      $(`tab-${other.dataset.tab}`).hidden = !active;
    }
  });
}

refreshStatus();
setInterval(refreshStatus, 15000);
