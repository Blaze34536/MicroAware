// Ground station: polls the link API once a second and redraws what Earth received.
const $ = (id) => document.getElementById(id);
const MODE_NAMES = { calm: "Calm, light protection", active: "Active, more protection", storm: "Storm, full protection" };
let shownSig = "";
let latestAlertId = null;

const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);

function drawImage(canvas, pixels) {
  const ctx = canvas.getContext("2d");
  const img = ctx.createImageData(96, 72);
  pixels.forEach((v, i) => img.data.set([v * 0.55 + 30, v * 0.7 + 42, v * 0.75 + 50, 255], i * 4));
  ctx.putImageData(img, 0, 0);
}

function verdict(copy) {
  if (copy.delivered) {
    const rebuilt = copy.rebuilt ? `, ${copy.rebuilt} rebuilt from parity` : "";
    return `<strong class="ok">Arrived intact.</strong> ${copy.loss_pct}% of frames lost${rebuilt}.`;
  }
  return `<strong class="bad">Arrived broken.</strong> ${copy.loss_pct}% of frames lost; ${copy.unrecoverable_blocks ?? "all"} of ${copy.blocks ?? "?"} blocks unreadable.`;
}

function showMessage(m) {
  const sig = m.msg_id + JSON.stringify([m.raw.frames, m.shield.frames]);
  if (sig === shownSig) return;
  shownSig = sig;
  for (const [key, canvas, out] of [["raw", "rawImg", "rawVerdict"], ["shield", "shieldImg", "shieldVerdict"]]) {
    drawImage($(canvas), m[key].image);
    $(canvas).closest("figure").dataset.ok = m[key].delivered;
    $(out).innerHTML = verdict(m[key]);
  }
  const a = m.shield.alert;
  $("decoded").innerHTML = a
    ? `<p><strong>${esc(a.id)}</strong>: Fan A, ${esc(a.label ? a.label.replace("_", " ") : "unknown anomaly")}</p>
       ${a.explanation ? `<p class="spoken">${esc(a.explanation.spoken)}</p><ol>${a.explanation.checks.map((c) => `<li>${esc(c)}</li>`).join("")}</ol>` : ""}`
    : '<p class="bad">The shielded copy could not be decoded.</p>';
  const metrics = [
    ["Frames sent", m.frames_sent.raw + m.frames_sent.shield],
    ["Loss, shielded copy", `${m.shield.loss_pct}%`],
    ["Rebuilt from parity", m.shield.rebuilt ?? 0],
    ["Unreadable blocks", `${m.shield.unrecoverable_blocks ?? "–"} of ${m.shield.blocks ?? "–"}`],
    ["Protection overhead", `${m.overhead_pct}%`],
    ["Airtime", `${m.airtime_s} s`],
  ];
  $("metrics").innerHTML = metrics.map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`).join("");
}

function showStatus(s) {
  $("linkName").textContent = s.link === "simulated" ? "a simulated radio link" : "the ESP-NOW radio link";
  $("mode").textContent = MODE_NAMES[s.mode] || s.mode;
  $("mode").dataset.level = s.mode;
  $("flare").textContent = s.flare ? `${s.flare}% for ${s.flare_left_s} s` : "None";
  const w = s.weather;
  $("kp").textContent = w.kp == null ? "–" : w.kp.toFixed(2);
  const forecast = (w.forecast || []).map(([t, k]) => `${t.slice(11, 16)} UTC Kp ${k}`).join(", ");
  $("weather").innerHTML = w.kp == null
    ? `<p class="quiet">${esc(w.source)}. Protection follows the flare control only.</p>`
    : `<p class="big">Kp ${w.kp.toFixed(2)}, ${w.level}</p>
       <p>${esc(w.source)}, window starting ${w.kp_time.slice(11, 16)} UTC.</p>
       ${forecast ? `<p>Forecast: ${forecast}.</p>` : ""}
       ${w.routine_send_at ? `<p>Routine telemetry: ${esc(w.routine_reason)}.</p>` : ""}`;
}

function showHistory(list) {
  latestAlertId = list[0]?.alert_id ?? null;
  $("resend").disabled = !latestAlertId;
  const mark = (ok) => (ok ? '<span class="ok">Intact</span>' : '<span class="bad">Broken</span>');
  $("history").innerHTML = list.length
    ? list.map((m) => `<tr><td>${m.msg_id}</td><td>${esc(m.alert_id)}</td><td>${m.mode}</td><td>${mark(m.raw.delivered)}</td><td>${mark(m.shield.delivered)}</td></tr>`).join("")
    : '<tr><td colspan="5" class="quiet">No messages yet. Alerts from the habitat appear here automatically.</td></tr>';
}

async function poll() {
  try {
    const [status, list] = await Promise.all([fetch("/api/link/status").then((r) => r.json()), fetch("/api/link/messages").then((r) => r.json())]);
    showStatus(status);
    showHistory(list);
    if (list.length) showMessage(await fetch(`/api/link/messages/${list[0].msg_id}`).then((r) => r.json()));
  } catch {
    $("mode").textContent = "Disconnected";
    $("mode").dataset.level = "storm";
  }
}

async function post(path, body) {
  const res = await fetch(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
  if (!res.ok) $("controlNote").textContent = (await res.json().catch(() => ({}))).detail || `Request failed (${res.status})`;
  poll();
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.flare) post("/api/link/flare", { level: Number(b.dataset.flare), seconds: Number(b.dataset.flare) ? 30 : 1 });
  if (b.id === "resend" && latestAlertId) post(`/api/link/send/${latestAlertId}`);
});

poll();
setInterval(poll, 1000);
