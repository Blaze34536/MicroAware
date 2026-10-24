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
const SOURCES = { mic: "Microphone", synth: "Simulated fan", none: "Nothing" };

const scores = [];
let rawRange = { lo: -60, hi: 0 };
let alertSig = "";
let bandsSig = "";

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
  const sig = alerts.map((a) => a.id + a.state).join();
  if (sig === alertSig) return;
  alertSig = sig;
  const ol = $("alerts");
  if (!alerts.length) {
    ol.innerHTML = '<li class="quiet">No alerts yet.</li>';
    return;
  }
  ol.innerHTML = alerts
    .map((a) => {
      const what = a.label ? a.label : "unknown anomaly";
      const band = a.evidence.top_bands[0];
      const where = band ? ` Loudest change at ${band.band_hz.replace("-", "–")} Hz, ${band.delta_db > 0 ? "+" : ""}${band.delta_db} dB.` : "";
      const time = a.t.slice(11, 19);
      const ack = a.state === "active" ? `<button type="button" data-ack="${a.id}">Acknowledge</button>` : `<span class="when">${a.state === "acknowledged" ? "Acknowledged" : "Cleared"}</span>`;
      return `<li class="alert" data-state="${a.state}">
        <h3>Fan A: ${what}</h3>
        <p class="when">${a.id} at ${time} UTC</p>
        <p>Score ${fmt(a.evidence.score)}, threshold ${fmt(a.evidence.threshold)}.${where}</p>
        ${ack}
      </li>`;
    })
    .join("");
}

function render(t) {
  const [label, level] = STATES[t.state] || [t.state, "none"];
  $("state").textContent = t.state === "recording" ? `${label} ${Math.round((t.record_progress || 0) * 100)}%` : label;
  $("state").dataset.level = level;
  document.body.dataset.level = level;
  $("source").textContent = SOURCES[t.source] || t.source;

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

  renderBands(t.top_bands, t.state === "abnormal");
  renderAlerts(t.alerts);
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
  if (!res.ok) alert(`Request failed: ${(await res.json()).detail || res.status}`);
}

document.addEventListener("click", (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.action === "record") api("POST", "/api/baseline", { seconds: Number($("recSeconds").value) || 90 });
  if (b.dataset.fault) api("POST", "/api/sim/inject", { fault: b.dataset.fault, seconds: 10 });
  if (b.dataset.ack) api("POST", `/api/alerts/${b.dataset.ack}/ack`);
});
$("scale").addEventListener("change", (e) => api("PUT", "/api/config", { threshold_scale: Number(e.target.value) }));
$("scale").addEventListener("input", (e) => ($("scaleOut").textContent = `${Number(e.target.value).toFixed(1)}×`));
setInterval(() => ($("clock").textContent = new Date().toISOString().slice(11, 19)), 1000);

connect();
