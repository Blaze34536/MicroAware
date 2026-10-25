// MicroAware dashboard: renders the 4 Hz tick from /ws; all commands go over REST.
const $ = (id) => document.getElementById(id);
const COL = 3; // px per tick in the spectrograms
const HISTORY = 480; // score points kept: 2 min at 4 Hz
const NOISE_DB = 4; // residual this small is normal wobble; keep it dark

const STATES = {
  no_baseline: ["Not trained", "none"],
  recording: ["Recording", "none"],
  training: ["Learning the fan", "none"],
  nominal: ["Nominal", "nominal"],
  abnormal: ["Fault detected", "abnormal"],
};
const SOURCES = { mic: "Microphone", synth: "Simulated fan", file: "Recorded run", none: "Nothing" };

const scores = [];
let rawRange = { lo: -60, hi: 0 };
let alertSig = "";
let bandsSig = "";
let soundOn = false;
let lastAlerts = [];
let spoken = null; // alert ids already spoken; null until the first tick so old alerts stay quiet

// Color ramps as [stop, r, g, b]; inputs are clamped to 0..1.
const RAW_RAMP = [[0, 30, 42, 50], [0.55, 61, 110, 143], [1, 230, 234, 236]];
const HOT_RAMP = [[0, 30, 42, 50], [0.35, 232, 163, 23], [0.75, 198, 47, 27], [1, 255, 240, 220]];
const COLD_RAMP = [[0, 30, 42, 50], [1, 61, 110, 143]];

function ramp(stops, v) {
  v = Math.min(1, Math.max(0, v));
  for (let i = 1; i < stops.length; i++) {
    const [b, ...hi] = stops[i];
    const [a, ...lo] = stops[i - 1];
    if (v <= b) {
      const f = (v - a) / (b - a);
      return `rgb(${lo.map((c, j) => Math.round(c + f * (hi[j] - c))).join(",")})`;
    }
  }
}

function sizeCanvas(c) {
  const r = c.getBoundingClientRect();
  if (c.width !== Math.round(r.width) || c.height !== Math.round(r.height)) {
    c.width = Math.round(r.width);
    c.height = Math.round(r.height);
  }
}

// Scroll the waterfall left and paint the newest column on the right; low bands at the bottom.
function pushColumn(canvas, values, color) {
  const ctx = canvas.getContext("2d");
  const { width: w, height: h } = canvas;
  ctx.drawImage(canvas, -COL, 0);
  if (!values) {
    ctx.fillStyle = "#1E2A32";
    ctx.fillRect(w - COL, 0, COL, h);
    return;
  }
  const bh = h / values.length;
  values.forEach((v, i) => {
    ctx.fillStyle = color(v);
    ctx.fillRect(w - COL, h - (i + 1) * bh, COL, Math.ceil(bh));
  });
}

function drawScore(threshold) {
  const c = $("scoreChart");
  sizeCanvas(c);
  const ctx = c.getContext("2d");
  const { width: w, height: h } = c;
  ctx.clearRect(0, 0, w, h);
  if (!threshold) return;
  // Log scale so a fault 50x over threshold doesn't flatten normal running.
  const lo = Math.log(threshold / 10);
  const hi = Math.log(Math.max(threshold * 20, ...scores.filter(Boolean)));
  const y = (s) => h - ((Math.log(Math.max(s, threshold / 10)) - lo) / (hi - lo)) * h;
  ctx.setLineDash([6, 4]);
  ctx.strokeStyle = "#E8A317";
  ctx.lineWidth = 2;
  ctx.beginPath();
  ctx.moveTo(0, y(threshold));
  ctx.lineTo(w, y(threshold));
  ctx.stroke();
  ctx.setLineDash([]);
  ctx.strokeStyle = "#1E2A32";
  ctx.beginPath();
  const step = w / (HISTORY - 1);
  scores.forEach((s, i) => {
    if (s == null) return;
    const x = w - (scores.length - 1 - i) * step;
    i && scores[i - 1] != null ? ctx.lineTo(x, y(s)) : ctx.moveTo(x, y(s));
  });
  ctx.stroke();
}

function fmt(n) {
  if (n == null) return "–";
  return n >= 100 ? n.toFixed(0) : n >= 10 ? n.toFixed(1) : n.toFixed(2);
}

function renderBands(bands, abnormal) {
  bands = bands.filter((b) => b.delta_db >= NOISE_DB);
  const sig = abnormal + JSON.stringify(bands);
  if (sig === bandsSig) return;
  bandsSig = sig;
  const ul = $("bands");
  if (!abnormal || !bands.length) {
    ul.innerHTML = '<li class="quiet">Nothing unusual right now.</li>';
    return;
  }
  ul.innerHTML = bands
    .map((b) => `<li><span>${b.band_hz.replace("-", "–")} Hz</span><span class="db">${b.delta_db > 0 ? "+" : ""}${b.delta_db} dB</span></li>`)
    .join("");
}

function renderAlerts(alerts) {
  const sig = alerts.map((a) => a.id + a.state + !!a.explanation).join();
  if (sig === alertSig) return;
  alertSig = sig;
  const ol = $("alerts");
  if (!alerts.length) {
    ol.innerHTML = '<li class="quiet">No alerts yet.</li>';
    return;
  }
  ol.innerHTML = alerts
    .map((a) => {
      const what = a.label ? `${a.label.replace("_", " ")} (${Math.round(a.label_conf * 100)}% sure)` : "unknown anomaly";
      const band = a.evidence.top_bands[0];
      const where = band ? ` Loudest change at ${band.band_hz.replace("-", "–")} Hz, ${band.delta_db > 0 ? "+" : ""}${band.delta_db} dB.` : "";
      const time = a.t.slice(11, 19);
      const ack = a.state === "active" ? `<button type="button" data-ack="${a.id}">Acknowledge</button>` : `<span class="when">${a.state === "acknowledged" ? "Acknowledged" : "Cleared"}</span>`;
      return `<li class="alert" data-state="${a.state}">
        <h3>Fan A: ${what}</h3>
        <p class="when">${a.id} at ${time} UTC</p>
        ${a.explanation ? `<p class="spoken">${esc(a.explanation.spoken)}</p>
        <ol class="checks">${a.explanation.checks.map((c) => `<li>${esc(c)}</li>`).join("")}</ol>` : '<p class="when">Explaining…</p>'}
        <p class="evidence">Score ${fmt(a.evidence.score)}, threshold ${fmt(a.evidence.threshold)}.${where}</p>
        <div class="actions">${ack}${a.explanation ? `<button type="button" data-replay="${a.id}">Play again</button>` : ""}</div>
      </li>`;
    })
    .join("");
}

function esc(s) {
  return String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
}

// Plays an alert's explanation, telling the server so our own voice isn't scored as a fault.
function speak(a) {
  if (!soundOn || !a.explanation) return;
  const done = () => api("POST", "/api/guard", { playing: false });
  api("POST", "/api/guard", { playing: true, seconds: 30 });
  if (a.audio) {
    const audio = new Audio(a.audio);
    audio.onended = audio.onerror = done;
    audio.play().catch(done);
  } else {
    const u = new SpeechSynthesisUtterance(a.explanation.spoken);
    u.onend = u.onerror = done;
    speechSynthesis.speak(u);
  }
}

function speakNew(alerts) {
  if (spoken === null) {
    spoken = new Set(alerts.map((a) => a.id));
    return;
  }
  for (const a of alerts) {
    if (a.explanation && a.state === "active" && !spoken.has(a.id)) {
      spoken.add(a.id);
      speak(a);
    }
  }
}

function render(t) {
  const [label, level] = STATES[t.state] || [t.state, "none"];
  const what = t.record_label ? ` ${t.record_label.replace("_", " ")}` : "";
  $("state").textContent = t.state === "recording" ? `${label}${what} ${Math.round((t.record_progress || 0) * 100)}%` : label;
  $("state").dataset.level = level;
  document.body.dataset.level = level;
  $("source").textContent = SOURCES[t.source] || t.source;
  $("pause").textContent = t.guarded ? "Paused, speaking" : t.talking && t.ignore_talking ? "Paused, talking" : "Live";
  $("pause").dataset.paused = t.guarded || (t.talking && t.ignore_talking);
  if (document.activeElement !== $("ignoreTalking")) $("ignoreTalking").checked = t.ignore_talking;
  if (t.link) {
    const sent = t.link.last_minute;
    const mode = t.link.mode[0].toUpperCase() + t.link.mode.slice(1);
    $("link").textContent = sent.messages ? `${mode}, ${sent.shield_delivered} of ${sent.messages} arrived` : mode;
  }

  const waiting = ["no_baseline", "recording", "training"].includes(t.state);
  $("empty").hidden = t.state !== "no_baseline";
  $("recProgress").hidden = t.state !== "recording";
  $("recProgress").value = t.record_progress || 0;
  document.querySelectorAll('[data-action="record"]').forEach((b) => (b.disabled = t.state === "recording" || t.state === "training"));

  if (t.mel) {
    const max = Math.max(...t.mel);
    rawRange.hi = Math.max(max, rawRange.hi - 0.05); // slow decay keeps colors stable
    rawRange.lo = rawRange.hi - 70;
  }
  ["raw", "residual"].forEach((id) => sizeCanvas($(id)));
  pushColumn($("raw"), t.mel, (v) => ramp(RAW_RAMP, (v - rawRange.lo) / (rawRange.hi - rawRange.lo)));
  pushColumn($("residual"), waiting ? null : t.residual, (v) => (v >= 0 ? ramp(HOT_RAMP, (v - NOISE_DB) / 12) : ramp(COLD_RAMP, (-v - NOISE_DB) / 24)));

  scores.push(t.score);
  if (scores.length > HISTORY) scores.shift();
  drawScore(t.threshold);
  $("scoreNow").textContent = fmt(t.score);
  $("thrNow").textContent = fmt(t.threshold);
  if (document.activeElement !== $("scale")) {
    $("scale").value = t.threshold_scale;
    $("scaleOut").textContent = `${Number(t.threshold_scale).toFixed(1)}×`;
  }

  const counts = Object.entries(t.labels || {});
  $("labelStatus").textContent =
    (counts.length ? `Clips: ${counts.map(([k, n]) => `${k.replace("_", " ")} ${n}`).join(", ")}.` : "No clips recorded yet.") +
    (t.labeler ? ` Trained on: ${t.labeler.map((l) => l.replace("_", " ")).join(", ")}.` : "");

  renderBands(t.top_bands, t.state === "abnormal");
  renderAlerts(t.alerts);
  speakNew(t.alerts);
  lastAlerts = t.alerts;
}

function connect() {
  const ws = new WebSocket(`${location.protocol === "https:" ? "wss" : "ws"}://${location.host}/ws`);
  ws.onmessage = (e) => render(JSON.parse(e.data));
  ws.onclose = () => {
    $("state").textContent = "Disconnected";
    $("state").dataset.level = "offline";
    setTimeout(connect, 1000);
  };
}

async function api(method, path, body) {
  const res = await fetch(path, {
    method,
    headers: body ? { "Content-Type": "application/json" } : {},
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!res.ok) {
    const detail = (await res.json().catch(() => ({}))).detail;
    alert(typeof detail === "string" ? detail : `Request failed (${res.status})`);
  }
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.action === "record") api("POST", "/api/baseline", { seconds: Number($("recSeconds").value) || 90 });
  if (b.dataset.action === "record-label") api("POST", "/api/labels/record", { label: $("faultLabel").value, seconds: 15 });
  if (b.dataset.action === "train") api("POST", "/api/labeler/train");
  if (b.dataset.fault) api("POST", "/api/sim/inject", { fault: b.dataset.fault, seconds: 10 });
  if (b.dataset.ack) api("POST", `/api/alerts/${b.dataset.ack}/ack`);
  if (b.dataset.replay) {
    const was = soundOn;
    soundOn = true;
    speak(lastAlerts.find((a) => a.id === b.dataset.replay));
    soundOn = was;
  }
  if (b.id === "sound") {
    soundOn = !soundOn;
    b.textContent = soundOn ? "On" : "Turn on";
    b.setAttribute("aria-pressed", soundOn);
  }
});
$("scale").addEventListener("change", (e) => api("PUT", "/api/config", { threshold_scale: Number(e.target.value) }));
$("ignoreTalking").addEventListener("change", (e) => api("PUT", "/api/config", { ignore_talking: e.target.checked }));
$("scale").addEventListener("input", (e) => ($("scaleOut").textContent = `${Number(e.target.value).toFixed(1)}×`));
setInterval(() => ($("clock").textContent = new Date().toISOString().slice(11, 19)), 1000);

// Voice assistant: tools run here in the browser and read the local API, so no tunnel is needed.
const getJSON = async (path, opts) => JSON.stringify(await (await fetch(path, opts)).json());
const TOOLS = {
  get_status: () => getJSON("/api/status"),
  get_history: ({ minutes } = {}) => getJSON(`/api/history?minutes=${Number(minutes) || 10}`),
  get_alert: ({ id } = {}) =>
    !id || id === "latest"
      ? getJSON("/api/alerts").then((all) => JSON.stringify(JSON.parse(all)[0] || { error: "No alerts yet" }))
      : getJSON(`/api/alerts/${encodeURIComponent(id)}`),
  acknowledge_alert: ({ id } = {}) => getJSON(`/api/alerts/${encodeURIComponent(id)}/ack`, { method: "POST" }),
};
let session = null;
let lines = [];

function showLine(who, text) {
  lines = [...lines, [who, text]].slice(-4);
  $("transcript").innerHTML = lines.map(([w, t]) => `<dt>${w}</dt><dd>${esc(t)}</dd>`).join("");
}

function setTalking(on, status) {
  $("talk").setAttribute("aria-pressed", on);
  $("talk").textContent = on ? "Stop talking" : "Start talking";
  $("voiceStatus").textContent = status;
}

async function toggleTalk() {
  if (session) {
    await session.endSession();
    return;
  }
  const { agent_id } = await (await fetch("/api/voice/config")).json();
  if (!agent_id) {
    setTalking(false, "Voice assistant isn't set up: add ELEVENLABS_AGENT_ID to .env and restart.");
    return;
  }
  setTalking(true, "Connecting…");
  api("POST", "/api/guard", { playing: true, seconds: 600 }); // the conversation is loud; don't score it as a fault
  try {
    session = await ElevenLabsClient.Conversation.startSession({
      agentId: agent_id,
      clientTools: TOOLS,
      onConnect: () => setTalking(true, "Listening. Ask a question."),
      onModeChange: ({ mode }) => setTalking(true, mode === "speaking" ? "Answering…" : "Listening. Ask a question."),
      onMessage: (m) => showLine((m.role || m.source) === "user" ? "You" : "Assistant", m.message),
      onError: (e) => setTalking(true, `Voice error: ${e}`),
      onDisconnect: () => {
        session = null;
        setTalking(false, "Session ended.");
        api("POST", "/api/guard", { playing: false });
      },
    });
  } catch (e) {
    session = null;
    setTalking(false, `Couldn't start the voice session: ${e.message || e}`);
    api("POST", "/api/guard", { playing: false });
  }
}
$("talk").addEventListener("click", toggleTalk);

connect();
