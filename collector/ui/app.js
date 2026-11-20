"use strict";
/*
 * Local egress proof panel.
 *
 * Safety: log text is attacker-controlled, so nothing from the API is ever written with innerHTML. Every value
 * goes in through textContent or a text node (see h() below). The page also runs under a strict CSP.
 */

const state = { selected: null, timer: null, localOnly: null };
// The filter focuses on credentials and personal data. Bare IP addresses are also scrubbed (and highlighted
// when you open a record), but they appear in routine network probes and would bury the interesting ones.
const NOT_SENSITIVE_ENOUGH_TO_LIST = new Set(["ipv4"]);
const hasCredentials = (item) => item.redactions_applied.some((rule) => !NOT_SENSITIVE_ENOUGH_TO_LIST.has(rule));
const $ = (selector) => document.querySelector(selector);

async function getJSON(path) {
  const res = await fetch(path, { cache: "no-store" });
  if (!res.ok) throw new Error(path + " returned HTTP " + res.status);
  return res.json();
}

// Tiny DOM builder. Only a few safe attributes are allowed, and text only ever becomes a text node.
const SAFE_ATTRS = new Set(["class", "title", "type", "id", "role"]);
function h(tag, attrs, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs || {})) {
    if (key === "text") node.textContent = value;
    else if (SAFE_ATTRS.has(key)) node.setAttribute(key, value);
    else if (key.startsWith("data-")) node.setAttribute(key, value);
  }
  for (const child of children) {
    if (child == null) continue;
    node.append(child.nodeType ? child : document.createTextNode(String(child)));
  }
  return node;
}

const state_hold = { held: false };

// POST helper for the two buttons that change delivery. The custom header is what proves the request came from
// this page and not from another site open in the same browser.
async function postLocal(path) {
  const res = await fetch(path, { method: "POST", headers: { "X-Requested-With": "local-ui" } });
  if (!res.ok) throw new Error(path + " returned HTTP " + res.status);
  return res.json();
}

const clock = (epochSeconds) => (epochSeconds ? new Date(epochSeconds * 1000).toLocaleTimeString() : "—");

function summarize(payload) {
  if (payload.metric) return payload.metric.name + " = " + payload.metric.value + " " + payload.metric.unit;
  if (payload.event) return payload.event.category + " × " + payload.event.count + " (" + payload.event.severity + ")";
  return "payload";
}

function showError(message) {
  const box = $("#error");
  box.textContent = message || "";
  box.hidden = !message;
}

// ---------- buffer strip and hold ----------
const plural = (n, word) => n + " " + word + (n === 1 ? "" : "s");

async function loadStrip() {
  try {
    const b = await getJSON("/local/buffer");
    state_hold.held = !!(b.hold && b.hold.held);
    const parts = [];
    parts.push("Link " + b.link);
    parts.push(plural(b.pending, "payload") + " waiting");
    if (b.oldest_pending_age_s != null) parts.push("oldest " + b.oldest_pending_age_s + " s");
    if (state_hold.held) parts.push("HELD, auto-release in " + Math.ceil(b.hold.auto_release_in_s) + " s");
    else if (b.hold && b.hold.last_release) parts.push("last release: " + b.hold.last_release.reason);
    if (b.last_error) parts.push("last error: " + b.last_error);
    $("#strip-text").textContent = parts.join(" · ");
    $("#strip").classList.toggle("held", state_hold.held);
    $("#hold-toggle").textContent = state_hold.held ? "Release" : "Hold sending";
  } catch (err) {
    $("#strip-text").textContent = "Cannot read the buffer: " + err.message;
  }
}

async function toggleHold() {
  try {
    await postLocal(state_hold.held ? "/local/release" : "/local/hold");
    showError("");
  } catch (err) {
    showError("Could not change the hold: " + err.message);
  }
  await loadStrip();
  await loadList();
}

// ---------- pipeline stages ----------
const pairs = (obj) => Object.entries(obj || {}).map(([k, v]) => k + " " + v).join(" · ") || "none";

async function loadStages() {
  try {
    const s = await getJSON("/local/stages");
    const o = s.outbox_now || {};
    const rows = [
      ["Received", s.received, pairs(s.by_format)],
      ["Redacted (records that matched a rule)", Object.values(s.redacted_records_by_rule).reduce((a, b) => a + b, 0), pairs(s.redacted_records_by_rule)],
      ["Dropped", s.dropped.oversize_line + s.dropped.unmapped_or_invalid_record, "oversize line " + s.dropped.oversize_line + " · unmapped or invalid " + s.dropped.unmapped_or_invalid_record],
      ["Aggregated into windows", s.aggregated_into_windows, s.windows_closed + " windows closed"],
      ["Queued to send", s.queued, "failed schema " + s.rejected_before_queue.failed_schema + " · blocked by policy " + s.rejected_before_queue.blocked_by_policy + " · collector events " + s.collector_events],
      ["In the outbox now", Object.values(o).reduce((a, b) => a + b, 0), pairs(o)],
    ];
    const checks = s.checks.map((c) => h("li", { class: c.ok ? "good" : "bad", text: (c.ok ? "✔ " : "✘ ") + c.name + ": " + c.left + " vs " + c.right }));
    $("#stages-body").replaceChildren(
      h("table", { class: "fields" }, h("tbody", {}, ...rows.map((r) => h("tr", {}, h("th", { text: r[0] }), h("td", { class: "mono", text: String(r[1]) }), h("td", { text: r[2] }))))),
      h("ul", { class: "checks-list" }, ...checks),
    );
  } catch (err) {
    $("#stages-body").textContent = "Cannot read the pipeline stages: " + err.message;
  }
}

// ---------- list ----------
async function loadList() {
  try {
    const items = await getJSON("/local/egress?limit=300");
    showError("");
    loadStrip();
    const only = $("#only-secrets").checked;
    const shown = only ? items.filter(hasCredentials) : items;
    renderList(shown, items.length);
    if (!state.selected && shown.length) selectPayload(shown[0].payload_id);
  } catch (err) {
    showError("Cannot reach the collector: " + err.message);
  }
}

function renderList(items, total) {
  const list = $("#list");
  list.replaceChildren();
  for (const item of items) {
    const rules = item.redactions_applied;
    const button = h(
      "button",
      { type: "button", class: "item" + (item.payload_id === state.selected ? " selected" : ""), "data-id": item.payload_id },
      h("span", { class: "item-title", text: summarize(item.payload) }),
      h(
        "span",
        { class: "item-meta" },
        clock(item.created_at) + " · ",
        h("span", { class: "chip " + item.status, text: item.status }),
        rules.length ? h("span", { class: "chip secret", text: rules.length + " secret rule" + (rules.length > 1 ? "s" : "") }) : null,
      ),
    );
    button.addEventListener("click", () => selectPayload(item.payload_id));
    list.append(h("li", {}, button));
  }
  if (!items.length) {
    list.append(
      h("li", { class: "empty", text: $("#only-secrets").checked
        ? "No payload has involved a credential yet. Send one with .\\scripts\\demo.ps1 secret, or untick the filter."
        : "Nothing queued yet." }),
    );
  }
  $("#status").textContent = "Updated " + new Date().toLocaleTimeString() + " · showing " + items.length + " of " + total + " payloads";
}

// ---------- detail ----------
async function selectPayload(id) {
  state.selected = id;
  for (const el of document.querySelectorAll(".item")) el.classList.toggle("selected", el.getAttribute("data-id") === id);
  try {
    const detail = await getJSON("/local/lineage/" + encodeURIComponent(id));
    if (!state.localOnly) state.localOnly = (await getJSON("/local/policy")).local_only;
    renderDetail(detail);
  } catch (err) {
    showError("Cannot load that payload: " + err.message);
  }
}

// Text with the sensitive spans wrapped in <mark>, built from text nodes only.
function highlighted(text, spans) {
  const out = document.createDocumentFragment();
  let pos = 0;
  for (const span of spans) {
    if (span.start > pos) out.append(document.createTextNode(text.slice(pos, span.start)));
    out.append(h("mark", { class: "secret", title: span.rule + ": scrubbed locally and never sent", "data-rule": span.rule, text: text.slice(span.start, span.end) }));
    pos = span.end;
  }
  if (pos < text.length) out.append(document.createTextNode(text.slice(pos)));
  return out;
}

function renderDetail(d) {
  const payloadJson = JSON.stringify(d.payload);

  // The proof: every sensitive value found in the raw records, checked against the exact payload text.
  const findings = [];
  for (const raw of d.raw) {
    for (const span of raw.spans) {
      const value = raw.text.slice(span.start, span.end);
      findings.push({ rule: span.rule, length: value.length, leaked: payloadJson.includes(value), raw: raw.id });
    }
  }
  const leaked = findings.filter((f) => f.leaked).length;

  let verdict;
  if (!findings.length) {
    verdict = h("p", { class: "verdict neutral", text: "No sensitive patterns matched in the raw records behind this payload." });
  } else if (leaked) {
    verdict = h("p", { class: "verdict bad", text: "LEAK: " + leaked + " of " + findings.length + " sensitive value(s) appear in the payload." });
  } else {
    verdict = h("p", { class: "verdict good", text: "✔ " + findings.length + " sensitive value(s) in the raw records. 0 appear in the payload that left." });
  }

  // Left: what stayed.
  const rawCards = d.raw.map((r) =>
    h("article", { class: "raw" },
      h("div", { class: "raw-head", text: "raw record #" + r.id + " · " + clock(r.received_at) }),
      h("pre", { class: "raw-text" }, highlighted(r.text, r.spans)),
    ),
  );
  if (!d.raw.length) rawCards.push(h("p", { class: "muted", text: "These raw records are no longer stored locally (retention)." }));
  if (d.raw_total > d.raw.length) rawCards.push(h("p", { class: "muted", text: "…and " + (d.raw_total - d.raw.length) + " more raw record(s) summarized in this payload." }));

  const left = h("section", { class: "panel local" },
    h("h2", { text: "Stayed local" }),
    h("p", { class: "sub", text: "Raw records. Secrets are visible here only." }),
    ...rawCards,
    h("p", { class: "muted", text: "Never leaves: " + Object.keys(state.localOnly || {}).join(", ") }),
  );

  // Right: what left, field by field with its marking.
  const rows = Object.entries(d.payload).map(([key, value]) =>
    h("tr", {},
      h("th", { text: key }),
      h("td", { class: "mono", text: typeof value === "object" ? JSON.stringify(value) : String(value) }),
      h("td", {}, h("span", { class: "chip mark-" + (d.markings[key] || "none"), text: d.markings[key] || "unlisted" })),
    ),
  );
  const openReceived = h("button", { type: "button", text: "Open this payload on the dashboard" });
  openReceived.addEventListener("click", () => {
    try {
      const target = new URL($("#dashboard-url").value);
      if (!["http:", "https:"].includes(target.protocol) || target.username || target.password) throw new Error("Use an HTTP or HTTPS dashboard URL without credentials.");
      target.hash = "/received?id=" + encodeURIComponent(d.payload.payload_id);
      window.open(target.href, "_blank", "noopener,noreferrer");
    } catch (err) { showError("Invalid dashboard URL: " + err.message); }
  });
  const right = h("section", { class: "panel sent" },
    h("h2", { text: "Left the environment" }),
    h("p", { class: "sub" }, "The exact payload queued to the SaaS · status ", h("strong", { text: d.status }), " · " + d.attempts + " attempt(s)"),
    openReceived,
    h("table", { class: "fields" }, h("tbody", {}, ...rows)),
    h("p", { class: "sub", text: d.status === "sent" ? "Sent at " + clock(d.sent_at) : d.status === "pending" ? "Not sent yet. It leaves only after release (or when the link is back)." : "Closed at " + clock(d.sent_at) }),
    h("p", { class: "sub" }, "SHA-256 of the exact bytes: ", h("code", { class: "mono", text: d.digest })),
    h("details", {}, h("summary", { text: "Raw JSON, byte for byte" }), h("pre", { class: "json", text: JSON.stringify(d.payload, null, 2) })),
  );

  // Leak check table.
  const checks = findings.length
    ? h("section", { class: "panel checks" },
        h("h2", { text: "Leak check" }),
        h("p", { class: "sub", text: "Each sensitive value found in the raw records, searched for in the payload text." }),
        h("table", { class: "fields" },
          h("thead", {}, h("tr", {}, h("th", { text: "Rule" }), h("th", { text: "Value" }), h("th", { text: "Raw record" }), h("th", { text: "Found in payload?" }))),
          h("tbody", {}, ...findings.map((f) =>
            h("tr", {},
              h("td", { text: f.rule }),
              h("td", { class: "mono", text: f.length + " characters (not shown again)" }),
              h("td", { text: "#" + f.raw }),
              h("td", { class: f.leaked ? "bad" : "good", text: f.leaked ? "YES" : "no" }),
            ),
          )),
        ),
      )
    : null;

  $("#detail").replaceChildren(verdict, h("div", { class: "pair" }, left, right), checks);
}

// ---------- wiring ----------
function schedule() {
  clearInterval(state.timer);
  if ($("#auto").checked) state.timer = setInterval(loadList, 3000);
  clearInterval(state.stripTimer);
  state.stripTimer = setInterval(loadStrip, 1000);
  clearInterval(state.stagesTimer);
  state.stagesTimer = setInterval(loadStages, 3000);
}

$("#refresh").addEventListener("click", loadList);
$("#hold-toggle").addEventListener("click", toggleHold);
$("#only-secrets").addEventListener("change", () => { state.selected = null; loadList(); });
$("#auto").addEventListener("change", schedule);
loadList();
loadStages();
schedule();
