const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" })[c]);
const NAMES = { imbalance: "imbalance", bearing: "a worn bearing", loose_mount: "a loose mount", air_leak: "an air leak" };

function row(group, s) {
  const actions = [];
  if (group.analyze) actions.push(`<button type="button" data-analyze="${s.id}">What does MicroAware hear?</button>`);
  if (group.analyze && s.fault) actions.push(`<button type="button" data-inject="${s.fault}">Try on the live fan</button>`);
  return `<li class="sound" data-condition="${s.condition}">
    <div class="what"><span class="tag">${s.condition === "normal" ? "Fixed" : "Broken"}</span><h3>${esc(s.title)}</h3></div>
    <audio controls preload="none" src="${s.url}"></audio>
    <div class="actions">${actions.join("")}</div>
    <p class="result" id="r-${s.id}" aria-live="polite"></p>
  </li>`;
}

async function load() {
  const groups = await (await fetch("/api/sounds")).json();
  document.getElementById("library").innerHTML = groups
    .map((g) => `<section class="machine">
      <h2>${esc(g.machine)}</h2>
      <ul>${g.sounds.map((s) => row(g, s)).join("")}</ul>
      <p class="credit">${esc(g.credit)}.${g.analyze ? "" : " MicroAware learns one machine at a time: record a baseline of this machine to check it."}</p>
    </section>`)
    .join("");
}

document.addEventListener("click", async (e) => {
  const b = e.target.closest("button");
  if (!b) return;
  if (b.dataset.analyze) {
    const out = document.getElementById(`r-${b.dataset.analyze}`);
    out.textContent = "Listening… the first check trains a model, about 5 seconds.";
    b.disabled = true;
    const r = await fetch(`/api/sounds/${b.dataset.analyze}/analyze`, { method: "POST" });
    const a = await r.json();
    b.disabled = false;
    if (!r.ok) return (out.textContent = a.detail || "Couldn't check this sound.");
    out.dataset.abnormal = a.abnormal;
    out.textContent = !a.abnormal
      ? `Sounds normal: score ${a.score}, alerts above ${a.threshold}.`
      : a.label
        ? `Sounds like ${NAMES[a.label] || a.label} (${Math.round(a.confidence * 100)}% sure): score ${a.score}, alerts above ${a.threshold}.`
        : `Sounds abnormal, cause unknown: score ${a.score}, alerts above ${a.threshold}.`;
  }
  if (b.dataset.inject) {
    const r = await fetch("/api/sim/inject", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ fault: b.dataset.inject, seconds: 10 }) });
    b.textContent = r.ok ? "Mixed into the live fan for 10 s" : "Couldn't reach the live fan";
    setTimeout(() => (b.textContent = "Try on the live fan"), 10000);
  }
});

load();
