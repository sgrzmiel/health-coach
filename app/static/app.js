/* health-coach frontend */
"use strict";

// ---------------------------------------------------------------------------
// Utils
// ---------------------------------------------------------------------------
const $ = id => document.getElementById(id);
const fmt = (v, dec = 0) => v == null ? "—" : Number(v).toFixed(dec);
const fmtDate = s => s ? s.slice(0, 10) : "—";
const sportLabel = s => ({ running:"Bieganie", cycling:"Rower", walking:"Marsz", hiking:"Marsz", strength_training:"Siłownia", swimming:"Pływanie" }[s] || s || "—");
const sportCss = s => `sport-pill sport-${(s || "").replace(/\s/g, "_")}`;
const scoreClass = n => n >= 7 ? "score-high" : n >= 4 ? "score-mid" : "score-low";

async function api(method, path, body, timeoutMs = 600000) {
  const opts = { method, headers: { "Content-Type": "application/json" }, signal: AbortSignal.timeout(timeoutMs) };
  if (body !== undefined) opts.body = JSON.stringify(body);
  const r = await fetch(path, opts);
  if (!r.ok) {
    const err = await r.json().catch(() => ({ detail: r.statusText }));
    throw new Error(err.detail || r.statusText);
  }
  return r.json();
}

// ---------------------------------------------------------------------------
// UI helpers
// ---------------------------------------------------------------------------

function toast(msg, ok = true) {
  // remove existing toasts
  document.querySelectorAll(".hc-toast").forEach(t => t.remove());
  const el = document.createElement("div");
  el.className = "hc-toast";
  el.style.cssText = [
    "position:fixed", "bottom:24px", "right:24px",
    `background:${ok ? "#14532d" : "#450a0a"}`,
    `color:${ok ? "#4ade80" : "#f87171"}`,
    "border:1px solid currentColor",
    "padding:12px 18px", "border-radius:8px",
    "font-size:14px", "z-index:9999",
    "max-width:420px", "line-height:1.5",
    "box-shadow:0 4px 20px rgba(0,0,0,0.5)",
    "animation:fadeIn 0.15s ease",
  ].join(";");
  el.innerHTML = `<span style="margin-right:8px">${ok ? "✓" : "✕"}</span>${msg}`;
  document.body.appendChild(el);
  setTimeout(() => el.remove(), ok ? 4000 : 7000);
}

// Status element next to a button: show message, optionally auto-clear
// persistent=true skips the 3s auto-clear (use for connection state labels)
function setStatus(elOrId, msg, type = "ok", persistent = false) {
  const el = typeof elOrId === "string" ? $(elOrId) : elOrId;
  if (!el) return;
  const colors = { ok: "#4ade80", err: "#f87171", info: "#6ea8fe", warn: "#f59e0b" };
  el.textContent = msg;
  el.style.color = colors[type] || colors.ok;
  el.style.display = msg ? "inline" : "none";
  if (type === "ok" && msg && !persistent) setTimeout(() => { if (el.textContent === msg) { el.textContent = ""; el.style.display = "none"; } }, 3000);
}

// Make a button show loading spinner while async fn runs
async function withBtn(btn, loadingLabel, fn) {
  const original = btn.innerHTML;
  const originalDisabled = btn.disabled;
  btn.disabled = true;
  btn.innerHTML = `<span class="spinner"></span>${loadingLabel}`;
  try {
    return await fn();
  } finally {
    btn.innerHTML = original;
    btn.disabled = originalDisabled;
  }
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------
let _authenticated = false;

async function checkAuth() {
  const d = await api("GET", "/api/auth/status");
  _authenticated = d.authenticated;
  $("auth-status").textContent = _authenticated ? (d.mode === "open" ? "tryb otwarty" : "zalogowany") : "niezalogowany";
  $("login-btn").classList.toggle("hidden", _authenticated);
  $("logout-btn").classList.toggle("hidden", !_authenticated);
}

$("login-btn").onclick = () => { $("login-modal").classList.remove("hidden"); $("login-password").focus(); };
$("login-cancel").onclick = () => $("login-modal").classList.add("hidden");
$("login-submit").onclick = async () => {
  const btn = $("login-submit");
  const pw = $("login-password").value;
  await withBtn(btn, "Loguję...", async () => {
    try {
      await api("POST", "/api/auth/login", { password: pw });
      $("login-modal").classList.add("hidden");
      $("login-password").value = "";
      $("login-error").classList.add("hidden");
      await checkAuth();
      toast("Zalogowano.");
    } catch (e) {
      $("login-error").textContent = e.message;
      $("login-error").classList.remove("hidden");
    }
  });
};
$("login-password").addEventListener("keydown", e => { if (e.key === "Enter") $("login-submit").click(); });
$("logout-btn").onclick = async () => { await api("POST", "/api/auth/logout"); await checkAuth(); toast("Wylogowano."); };

// ---------------------------------------------------------------------------
// Tabs
// ---------------------------------------------------------------------------
document.querySelectorAll(".tab").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll(".tab").forEach(t => t.classList.remove("active"));
    document.querySelectorAll(".tab-panel").forEach(p => p.classList.add("hidden"));
    btn.classList.add("active");
    $("tab-" + btn.dataset.tab).classList.remove("hidden");
    history.replaceState(null, "", "#" + btn.dataset.tab);
    if (btn.dataset.tab === "dashboard") loadDashboard();
    if (btn.dataset.tab === "weight") loadWeight();
    if (btn.dataset.tab === "activities") loadActivities();
    if (btn.dataset.tab === "gym") loadGymSessions();
    if (btn.dataset.tab === "nutrition") loadNutrition();
    if (btn.dataset.tab === "settings") loadSettings();
    if (btn.dataset.tab === "equipment") loadEquipment();
  };
});

function initFromHash() {
  const tab = location.hash.slice(1) || "dashboard";
  const btn = document.querySelector(`[data-tab="${tab}"]`);
  (btn || document.querySelector('[data-tab="dashboard"]')).click();
}

// Coach sub-tabs
document.querySelectorAll(".coach-tab").forEach(btn => {
  btn.onclick = () => {
    document.querySelectorAll(".coach-tab").forEach(t => t.classList.remove("active"));
    btn.classList.add("active");
    document.querySelectorAll("[id^=coach-][id$=-panel]").forEach(p => p.classList.add("hidden"));
    const map = { plan: "plan", "gym-session": "gym-session", eval: "eval", recovery: "recovery", "nutrition-analysis": "nutrition" };
    const key = map[btn.dataset.coach];
    if (key) { const p = $("coach-" + key + "-panel"); if (p) p.classList.remove("hidden"); }
    if (btn.dataset.coach === "eval") loadEvalSelects();
    if (btn.dataset.coach === "plan") loadPlanHistory();
  };
});

// ---------------------------------------------------------------------------
// Sync all
// ---------------------------------------------------------------------------
$("sync-all-btn").onclick = () => withBtn($("sync-all-btn"), "Synchronizuję...", async () => {
  const st = $("sync-all-status");
  setStatus(st, "Garmin / Withings / Fitatu...", "info", true);
  const steps = [
    { label: "Garmin",   fn: () => api("POST", "/api/garmin/sync", {}) },
    { label: "Withings", fn: () => api("POST", "/api/withings/sync") },
    { label: "Fitatu",   fn: () => api("POST", "/api/fitatu/sync", { days: 30 }) },
  ];
  const settled = await Promise.allSettled(steps.map(s => s.fn()));
  const results = steps.map((s, i) =>
    settled[i].status === "fulfilled" ? `✓ ${s.label}` : `✕ ${s.label}: ${settled[i].reason?.message || "błąd"}`
  );
  setStatus(st, results.join("  "), "ok", true);
  await loadDashboard();
});

// ---------------------------------------------------------------------------
// Dashboard
// ---------------------------------------------------------------------------
async function loadDashboard() {
  $("dash-date").textContent = new Date().toLocaleDateString("pl-PL", { weekday: "long", day: "numeric", month: "long" });
  $("dash-today").innerHTML = '<div class="muted loading-pulse">Ładuję...</div>';
  $("dash-nutrition").innerHTML = '<div class="muted loading-pulse">Ładuję...</div>';
  $("dash-weight").innerHTML = '<div class="muted loading-pulse">Ładuję...</div>';
  $("dash-recent-act").innerHTML = '<div class="muted loading-pulse">Ładuję...</div>';
  $("dash-daily-table").innerHTML = '<div class="muted loading-pulse">Ładuję...</div>';

  const [daily, nutr, acts, daily14] = await Promise.allSettled([
    api("GET", "/api/garmin/daily?limit=1"),
    api("GET", "/api/fitatu/today"),
    api("GET", "/api/garmin/activities?limit=7"),
    api("GET", "/api/garmin/daily?limit=14"),
  ]);

  renderTodayStats(daily.status === "fulfilled" ? daily.value.items[0] : null);
  renderNutritionToday(nutr.status === "fulfilled" ? nutr.value.item : null);
  renderRecentActivities(acts.status === "fulfilled" ? acts.value.items : []);
  renderDailyTable(daily14.status === "fulfilled" ? daily14.value.items : []);

  try {
    const wdata = await api("GET", "/api/withings/weights?limit=14");
    renderWeightCard(wdata.items || []);
  } catch (e) {
    $("dash-weight").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
  }
}

function renderSleepDetail(d) {
  const deep  = d.sleep_deep_s  || 0;
  const rem   = d.sleep_rem_s   || 0;
  const light = d.sleep_light_s || 0;
  const awake = d.sleep_awake_s || 0;
  const total = deep + rem + light + awake;
  if (!total) return "";

  const hm  = s => { const h = Math.floor(s/3600), m = Math.floor((s%3600)/60); return h ? `${h}h ${m}m` : `${m}m`; };
  const pct = s => Math.round(s / total * 100);

  const feedbackMap = {
    POSITIVE_OPTIMAL_STRUCTURE: "Optymalna struktura",
    NEGATIVE_SUBOPTIMAL_STRUCTURE: "Nieoptymalny rozkład",
    POSITIVE_SHORT_BUT_SOLID: "Krótki, ale solidny",
  };
  const fb = d.sleep_score_feedback ? (feedbackMap[d.sleep_score_feedback] || d.sleep_score_feedback.replace(/_/g," ")) : "";

  const stack = [
    { flex: deep,  color: "#3b82f6" },
    { flex: rem,   color: "#a78bfa" },
    { flex: light, color: "#7dd3fc" },
    { flex: awake, color: "#374151" },
  ].filter(s => s.flex > 0).map(s =>
    `<div class="sleep-stack-seg" style="flex:${s.flex};background:${s.color}"></div>`
  ).join("");

  const phases = [
    { cls:"deep",  label:"Głęboki", s: deep  },
    { cls:"rem",   label:"REM",     s: rem   },
    { cls:"light", label:"Lekki",   s: light },
    { cls:"awake", label:"Czuwan.", s: awake },
  ];

  const metrics = [
    d.sleep_spo2_avg   != null ? `SpO2 <strong>${d.sleep_spo2_avg.toFixed(0)}%</strong>` : null,
    d.sleep_respiration_avg != null ? `Oddech <strong>${d.sleep_respiration_avg.toFixed(0)}/min</strong>` : null,
    d.sleep_stress_avg != null ? `Stres <strong>${d.sleep_stress_avg.toFixed(0)}</strong>` : null,
  ].filter(Boolean);

  return `<div class="sleep-detail">
    ${fb ? `<div class="sleep-feedback">${fb}</div>` : ""}
    <div class="sleep-stack">${stack}</div>
    <div class="sleep-phases">${phases.map(p => `<div class="sleep-phase">
      <div class="sleep-ph-label ${p.cls}">${p.label}</div>
      <div class="sleep-ph-val">${hm(p.s)}</div>
      <div class="sleep-ph-pct">${pct(p.s)}%</div>
    </div>`).join("")}</div>
    ${metrics.length ? `<div class="sleep-metrics">${metrics.map(m => `<span class="sleep-metric">${m}</span>`).join("")}</div>` : ""}
  </div>`;
}

function renderTodayStats(d) {
  if (!d) { $("dash-today").innerHTML = '<div class="muted">Brak danych — zsynchronizuj Garmina.</div>'; return; }
  const sc = v => v >= 70 ? "good" : v >= 40 ? "warn" : "bad";
  const stats = [
    { label: "Body Battery", value: d.body_battery_max != null ? `${d.body_battery_min}–${d.body_battery_max}` : "—", sub: "min–max", cls: "" },
    { label: "HRV", value: fmt(d.hrv_avg, 0), sub: d.hrv_status || "", cls: "" },
    { label: "Sen", value: fmt(d.sleep_hours, 1), sub: `wynik ${d.sleep_score ?? "—"}`, cls: d.sleep_hours >= 7 ? "good" : d.sleep_hours >= 6 ? "warn" : "bad" },
    { label: "Gotowość", value: fmt(d.training_readiness, 0), sub: "/100", cls: sc(d.training_readiness) },
    { label: "Tętno spoc.", value: fmt(d.resting_hr, 0), sub: "bpm", cls: "" },
    { label: "Kroki", value: d.steps ? (d.steps / 1000).toFixed(1) + "k" : "—", sub: "", cls: "" },
    { label: "Stres", value: fmt(d.stress_avg, 0), sub: "/100", cls: "" },
  ];
  $("dash-today").innerHTML =
    `<div class="stats-grid">${stats.map(s => `<div class="stat ${s.cls}"><div class="stat-label">${s.label}</div><div class="stat-value">${s.value}</div><div class="stat-sub">${s.sub}</div></div>`).join("")}</div>` +
    renderSleepDetail(d);
}

function renderWeightCard(items) {
  if (!items.length) { $("dash-weight").innerHTML = '<div class="muted">Brak danych Withings.</div>'; return; }
  const l = items[0];
  $("dash-weight").innerHTML = `
    <div class="stats-grid">
      <div class="stat"><div class="stat-label">Waga</div><div class="stat-value">${fmt(l.weight_kg, 1)}</div><div class="stat-sub">kg</div></div>
      <div class="stat"><div class="stat-label">Masa tł.</div><div class="stat-value">${fmt(l.fat_mass_kg, 1)}</div><div class="stat-sub">kg</div></div>
      <div class="stat"><div class="stat-label">Mięśnie</div><div class="stat-value">${fmt(l.muscle_mass_kg, 1)}</div><div class="stat-sub">kg</div></div>
    </div>
    <div class="muted" style="margin-top:10px;font-size:12px">Ostatni pomiar: ${fmtDate(l.date)}</div>`;
}

function renderNutritionToday(item) {
  if (!item) { $("dash-nutrition").innerHTML = '<div class="muted">Brak danych — zsynchronizuj Fitatu.</div>'; return; }
  const macros = [
    { label: "Białko",       val: item.protein_g, target: 125, cls: "protein", unit: "g" },
    { label: "Węglowodany",  val: item.carbs_g,   target: 200, cls: "carbs",   unit: "g" },
    { label: "Tłuszcz",      val: item.fat_g,     target: 70,  cls: "fat",     unit: "g" },
    { label: "Błonnik",      val: item.fiber_g,   target: 30,  cls: "fiber",   unit: "g" },
  ];
  $("dash-nutrition").innerHTML = `
    <div class="stats-grid" style="margin-bottom:14px">
      <div class="stat"><div class="stat-label">Kalorie</div><div class="stat-value">${fmt(item.calories, 0)}</div><div class="stat-sub">kcal</div></div>
    </div>
    ${macros.map(m => `<div style="margin-bottom:8px">
      <div style="display:flex;justify-content:space-between;font-size:12px;margin-bottom:4px">
        <span style="color:var(--t1)">${m.label}</span>
        <span>${fmt(m.val, 1)} ${m.unit}</span>
      </div>
      <div class="nutr-bar-wrap"><div class="nutr-bar-bg"><div class="nutr-bar-fill ${m.cls}" style="width:${Math.min(100, ((m.val || 0) / m.target) * 100)}%"></div></div></div>
    </div>`).join("")}`;
}

function renderExerciseSets(setsJson) {
  if (!setsJson) return "";
  let sets;
  try { sets = JSON.parse(setsJson); } catch { return ""; }
  sets = sets.filter(s => s.name !== "WARM_UP" && s.name !== "COOL_DOWN" && (s.sets || 0) > 0);
  if (!sets.length) return "";
  return `<div class="ex-sets">${sets.map(s => {
    const name = s.name.replace(/_/g, " ").toLowerCase().replace(/\b\w/g, c => c.toUpperCase());
    const repsEach = s.sets > 0 ? Math.round(s.reps / s.sets) : s.reps;
    const w = s.max_weight_kg > 0 ? ` · <strong>${s.max_weight_kg} kg</strong>` : "";
    return `<span class="ex-set"><strong>${name}</strong> ${s.sets}×${repsEach}${w}</span>`;
  }).join("")}</div>`;
}

function renderRecentActivities(items) {
  if (!items.length) { $("dash-recent-act").innerHTML = '<div class="muted">Brak aktywności.</div>'; return; }
  $("dash-recent-act").innerHTML = `<table>
    <thead><tr><th>Data</th><th>Sport</th><th>Czas</th><th>Dystans</th><th>HR</th></tr></thead>
    <tbody>${items.map(a => {
      const sets = a.exercise_sets_json ? renderExerciseSets(a.exercise_sets_json) : "";
      return `<tr>
        <td>${fmtDate(a.start_time_local)}</td>
        <td><span class="${sportCss(a.sport)}">${sportLabel(a.sport)}</span></td>
        <td class="num">${a.duration_s ? Math.round(a.duration_s/60)+" min" : "—"}</td>
        <td class="num">${a.distance_m ? (a.distance_m/1000).toFixed(2)+" km" : "—"}</td>
        <td class="num">${a.avg_hr ? Math.round(a.avg_hr)+" bpm" : "—"}</td>
      </tr>${sets ? `<tr><td colspan="5" class="td-sets">${sets}</td></tr>` : ""}`;
    }).join("")}</tbody></table>`;
}

function renderDailyTable(items) {
  if (!items.length) { $("dash-daily-table").innerHTML = '<div class="muted">Brak danych.</div>'; return; }
  $("dash-daily-table").innerHTML = `<table>
    <thead><tr><th>Data</th><th class="num">BB max</th><th class="num">HRV</th><th class="num">Sen</th><th class="num">Gotow.</th><th class="num">Tętno sp.</th><th class="num">Kroki</th><th class="num">Stres</th></tr></thead>
    <tbody>${items.map(d => `<tr>
      <td>${fmtDate(d.date)}</td>
      <td class="num">${fmt(d.body_battery_max, 0)}</td>
      <td class="num">${fmt(d.hrv_avg, 0)}</td>
      <td class="num">${fmt(d.sleep_hours, 1)} h</td>
      <td class="num">${fmt(d.training_readiness, 0)}</td>
      <td class="num">${fmt(d.resting_hr, 0)}</td>
      <td class="num">${d.steps ? (d.steps/1000).toFixed(1)+"k" : "—"}</td>
      <td class="num">${fmt(d.stress_avg, 0)}</td>
    </tr>`).join("")}</tbody></table>`;
}

// ---------------------------------------------------------------------------
// Weight
// ---------------------------------------------------------------------------

function svgLine(items, series, opts = {}) {
  const W = 760, H = opts.height || 140;
  const pad = { t: 10, r: 16, b: 24, l: 44 };
  const cw = W - pad.l - pad.r, ch = H - pad.t - pad.b;
  const vals = series.flatMap(s => items.map(d => d[s.key]).filter(v => v != null));
  if (!vals.length) return '<div class="muted">Brak danych.</div>';
  let yMin = Math.min(...vals), yMax = Math.max(...vals);
  const mg = (yMax - yMin) * 0.12 || 0.5;
  yMin -= mg; yMax += mg;
  const yr = yMax - yMin;
  const xi = i => (pad.l + (i / Math.max(1, items.length - 1)) * cw).toFixed(1);
  const yv = v => (pad.t + ch - ((v - yMin) / yr) * ch).toFixed(1);
  let s = `<svg viewBox="0 0 ${W} ${H}" style="width:100%;display:block">`;
  for (let t = 0; t <= 4; t++) {
    const v = yMin + yr * t / 4, yp = +yv(v);
    s += `<line x1="${pad.l}" x2="${W - pad.r}" y1="${yp}" y2="${yp}" stroke="#252934" stroke-width="1"/>`;
    s += `<text x="${pad.l - 5}" y="${yp + 4}" fill="#8a8f9a" font-size="11" text-anchor="end">${Number(v).toFixed(1)}</text>`;
  }
  const ls = Math.max(1, Math.floor(items.length / 7));
  for (let i = 0; i < items.length; i += ls) {
    s += `<text x="${xi(i)}" y="${H - 5}" fill="#8a8f9a" font-size="10" text-anchor="middle">${items[i].date.slice(5)}</text>`;
  }
  for (const sr of series) {
    let d = "";
    for (let i = 0; i < items.length; i++) {
      const v = items[i][sr.key];
      if (v != null) d += (d === "" ? "M" : "L") + `${xi(i)},${yv(v)}`;
    }
    if (d) s += `<path d="${d}" fill="none" stroke="${sr.color}" stroke-width="2.5" stroke-linejoin="round" stroke-linecap="round"/>`;
    for (let i = items.length - 1; i >= 0; i--) {
      if (items[i][sr.key] != null) { s += `<circle cx="${xi(i)}" cy="${yv(items[i][sr.key])}" r="4" fill="${sr.color}"/>`; break; }
    }
  }
  return s + "</svg>";
}

function weightDelta(items, days) {
  if (!items.length) return null;
  const latest = items[items.length - 1];
  const cutoff = new Date(latest.date);
  cutoff.setDate(cutoff.getDate() - days);
  const cutStr = cutoff.toISOString().slice(0, 10);
  const ref = [...items].reverse().find(d => d.date <= cutStr && d.weight_kg != null);
  if (!ref) return null;
  return latest.weight_kg - ref.weight_kg;
}

async function loadWeight() {
  const days = parseInt($("weight-range")?.value || "90");
  const loading = '<div class="muted loading-pulse">Ładuję...</div>';
  $("weight-chart-weight").innerHTML = loading;
  $("weight-chart-fat").innerHTML = loading;
  $("weight-chart-water").innerHTML = loading;
  $("weight-table").innerHTML = loading;

  try {
    const data = await api("GET", `/api/withings/weights?limit=${days + 10}`);
    const all = (data.items || []).slice(0, days).reverse(); // oldest→newest

    all.forEach(d => {
      if (d.fat_mass_kg != null && d.weight_kg != null)
        d.fat_pct = d.fat_mass_kg / d.weight_kg * 100;
    });

    // Stats cards
    const latest = all.length ? all[all.length - 1] : null;
    const d7 = weightDelta(all, 7), d30 = weightDelta(all, 30), d90 = weightDelta(all, 90);
    const deltaHtml = (d, label) => {
      if (d == null) return "";
      const sign = d > 0 ? "+" : "";
      const cls = d < 0 ? "good" : d > 0 ? "bad" : "";
      return `<div class="stat ${cls}"><div class="stat-label">${label}</div><div class="stat-value">${sign}${d.toFixed(2)}</div><div class="stat-sub">kg</div></div>`;
    };
    $("weight-stats-row").innerHTML = `
      <div class="card"><div class="stats-grid">
        <div class="stat"><div class="stat-label">Aktualna waga</div><div class="stat-value">${latest ? latest.weight_kg.toFixed(1) : "—"}</div><div class="stat-sub">kg · cel 79 kg</div></div>
        <div class="stat"><div class="stat-label">% tłuszczu</div><div class="stat-value">${latest?.fat_pct != null ? latest.fat_pct.toFixed(1) : "—"}</div><div class="stat-sub">%</div></div>
        <div class="stat"><div class="stat-label">% wody</div><div class="stat-value">${latest?.water_pct != null ? latest.water_pct.toFixed(1) : "—"}</div><div class="stat-sub">%</div></div>
        ${deltaHtml(d7, "Zmiana 7 dni")}${deltaHtml(d30, "Zmiana 30 dni")}${deltaHtml(d90, "Zmiana 90 dni")}
      </div></div>`;

    // Charts
    $("weight-chart-weight").innerHTML = svgLine(all, [{ key: "weight_kg", color: "#6ea8fe" }]);
    $("weight-chart-fat").innerHTML = all.some(d => d.fat_pct != null)
      ? svgLine(all, [{ key: "fat_pct", color: "#f97316" }], { height: 120 })
      : '<div class="muted">Brak danych o składzie ciała.</div>';
    $("weight-chart-water").innerHTML = all.some(d => d.water_pct != null)
      ? svgLine(all, [{ key: "water_pct", color: "#22c55e" }], { height: 120 })
      : '<div class="muted">Brak danych o nawodnieniu.</div>';

    // Table (newest first)
    const rows = [...all].reverse();
    $("weight-table").innerHTML = `<table><thead><tr>
      <th>Data</th><th class="num">Waga kg</th><th class="num">Tłuszcz %</th><th class="num">Masa tł. kg</th><th class="num">Mięśnie kg</th><th class="num">Woda %</th>
    </tr></thead><tbody>${rows.map(d => `<tr>
      <td>${d.date}</td>
      <td class="num">${fmt(d.weight_kg, 2)}</td>
      <td class="num">${d.fat_pct != null ? d.fat_pct.toFixed(1) : "—"}</td>
      <td class="num">${fmt(d.fat_mass_kg, 2)}</td>
      <td class="num">${fmt(d.muscle_mass_kg, 2)}</td>
      <td class="num">${fmt(d.water_pct, 1)}</td>
    </tr>`).join("")}</tbody></table>`;
  } catch (e) {
    $("weight-chart-weight").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
  }
}

$("weight-range")?.addEventListener("change", loadWeight);

// ---------------------------------------------------------------------------
// Activities
// ---------------------------------------------------------------------------
async function loadActivities() {
  $("all-activities").innerHTML = '<div class="muted loading-pulse">Ładuję aktywności...</div>';
  try {
    const data = await api("GET", "/api/garmin/activities?limit=100");
    const items = data.items;
    if (!items.length) { $("all-activities").innerHTML = '<div class="muted">Brak danych.</div>'; return; }
    $("all-activities").innerHTML = `<table>
      <thead><tr><th>Data</th><th>Sport</th><th>Nazwa</th><th class="num">Czas</th><th class="num">Dystans</th><th class="num">HR śr/max</th><th class="num">Load</th><th class="num">kcal</th><th></th></tr></thead>
      <tbody>${items.map(a => {
        const sets = a.exercise_sets_json ? renderExerciseSets(a.exercise_sets_json) : "";
        return `<tr>
          <td>${fmtDate(a.start_time_local)}</td>
          <td><span class="${sportCss(a.sport)}">${sportLabel(a.sport)}</span></td>
          <td style="max-width:160px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;color:var(--t1)">${a.name || "—"}</td>
          <td class="num">${a.duration_s ? Math.round(a.duration_s/60)+" min" : "—"}</td>
          <td class="num">${a.distance_m ? (a.distance_m/1000).toFixed(2)+" km" : "—"}</td>
          <td class="num">${a.avg_hr ? Math.round(a.avg_hr) : "—"} / ${a.max_hr ? Math.round(a.max_hr) : "—"}</td>
          <td class="num">${fmt(a.training_load, 0)}</td>
          <td class="num">${fmt(a.calories, 0)}</td>
          <td><button class="secondary" style="font-size:11px;padding:3px 8px" onclick="evalActivity(${a.activity_id})">Oceń</button></td>
        </tr>${sets ? `<tr><td colspan="9" class="td-sets">${sets}</td></tr>` : ""}`;
      }).join("")}</tbody></table>`;
  } catch (e) {
    $("all-activities").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
  }
}

$("reload-activities").onclick = () => withBtn($("reload-activities"), "Ładuję...", loadActivities);

function evalActivity(id) {
  document.querySelector('[data-tab="coach"]').click();
  document.querySelector('[data-coach="eval"]').click();
  setTimeout(() => { $("eval-kind").value = "garmin"; updateEvalSelect("garmin"); setTimeout(() => { $("eval-id").value = id; }, 300); }, 100);
}

// ---------------------------------------------------------------------------
// Gym
// ---------------------------------------------------------------------------
let _gymSessions = [];
let _editingSession = null;
let _gymExercises = [];

async function loadGymSessions() {
  $("gym-sessions-list").innerHTML = '<div class="muted loading-pulse">Ładuję sesje...</div>';
  try {
    const [data, ex] = await Promise.all([api("GET", "/api/gym/sessions?limit=60"), api("GET", "/api/gym/exercises")]);
    _gymSessions = data.items;
    _gymExercises = ex.items.map(e => e.exercise);
    renderGymList();
  } catch (e) {
    $("gym-sessions-list").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
  }
}

function renderGymList() {
  if (!_gymSessions.length) { $("gym-sessions-list").innerHTML = '<div class="muted">Brak sesji.</div>'; return; }
  $("gym-sessions-list").innerHTML = _gymSessions.map(s => `
  <details>
    <summary>
      <span>
        <strong>${s.date}</strong>
        <span style="margin-left:8px;color:var(--t1)">${s.exercises || "brak ćwiczeń"}</span>
        <span class="muted" style="margin-left:8px;font-size:12px">${[s.duration_min ? s.duration_min+" min" : "", s.rpe ? "RPE "+s.rpe : ""].filter(Boolean).join(" · ")}</span>
      </span>
      <span style="display:flex;gap:6px">
        <button class="secondary" style="font-size:11px;padding:3px 8px" onclick="editSession(${s.id});event.preventDefault()">Edytuj</button>
        <button class="secondary" style="font-size:11px;padding:3px 8px" onclick="evalGym(${s.id});event.preventDefault()">Oceń</button>
      </span>
    </summary>
    <div class="detail-body" id="gym-detail-${s.id}"></div>
  </details>`).join("");

  document.querySelectorAll("details").forEach(d => {
    d.addEventListener("toggle", async () => {
      if (!d.open) return;
      const detailEl = d.querySelector("[id^=gym-detail-]");
      if (!detailEl || detailEl.innerHTML) return;
      const id = parseInt(detailEl.id.split("-").pop());
      detailEl.innerHTML = '<div class="muted loading-pulse">Ładuję...</div>';
      const data = await api("GET", `/api/gym/sessions/${id}`);
      const s = data.item;
      if (!s.sets.length) { detailEl.innerHTML = '<div class="muted">Brak serii.</div>'; return; }
      const byEx = {};
      s.sets.forEach(x => { (byEx[x.exercise] = byEx[x.exercise] || []).push(x); });
      detailEl.innerHTML = Object.entries(byEx).map(([ex, sets]) => `<div class="gym-exercise-group">
        <div style="font-weight:600;margin-bottom:6px">${ex}</div>
        ${sets.map(x => `<div style="font-size:12px;color:var(--t1);padding:2px 0">Seria ${x.set_idx+1}: ${x.reps||"?"} powt. × ${x.weight_kg!=null ? x.weight_kg+"kg" : "—"}${x.rpe ? " · RPE "+x.rpe : ""}</div>`).join("")}
      </div>`).join("");
    });
  });
}

$("gym-new-btn").onclick = () => {
  _editingSession = null;
  $("gym-date").value = new Date().toISOString().slice(0, 10);
  $("gym-duration").value = ""; $("gym-rpe").value = ""; $("gym-notes").value = "";
  $("gym-sets-editor").innerHTML = "";
  $("gym-editor").classList.remove("hidden");
};
$("gym-cancel").onclick = () => $("gym-editor").classList.add("hidden");
$("gym-add-exercise").onclick = () => addExerciseBlock();

function addExerciseBlock(name = "", sets = []) {
  const div = document.createElement("div");
  div.className = "gym-exercise-group";
  div.innerHTML = `<div class="form-row">
    <input list="ex-list" placeholder="Ćwiczenie" class="ex-name grow" value="${name}" />
    <button type="button" class="danger" onclick="this.closest('.gym-exercise-group').remove()" style="padding:4px 8px">✕</button>
  </div>
  <datalist id="ex-list">${_gymExercises.map(e => `<option value="${e}">`).join("")}</datalist>
  <div class="gym-sets"></div>
  <button type="button" class="secondary" style="margin-top:6px;font-size:12px" onclick="addSetRow(this)">+ Seria</button>`;
  $("gym-sets-editor").appendChild(div);
  if (sets.length) sets.forEach(s => addSetRow(div.querySelector("button"), s));
  else addSetRow(div.querySelector("button"));
}

function addSetRow(btn, preset = {}) {
  const container = btn.closest(".gym-exercise-group").querySelector(".gym-sets");
  const row = document.createElement("div");
  row.className = "gym-set-row";
  const idx = container.children.length;
  row.innerHTML = `<span class="muted" style="font-size:12px">Seria ${idx + 1}</span>
    <input type="number" placeholder="Powt." class="set-reps" value="${preset.reps || ""}" min="1" />
    <input type="number" placeholder="kg" class="set-weight" value="${preset.weight_kg != null ? preset.weight_kg : ""}" step="0.5" />
    <input type="number" placeholder="RPE" class="set-rpe" value="${preset.rpe || ""}" min="1" max="10" step="0.5" />
    <button type="button" class="danger" style="padding:3px 7px;font-size:11px" onclick="this.closest('.gym-set-row').remove()">✕</button>`;
  container.appendChild(row);
}

$("gym-save").onclick = async () => {
  await withBtn($("gym-save"), "Zapisuję...", async () => {
    const date = $("gym-date").value;
    if (!date) { toast("Wybierz datę.", false); return; }
    const dur = parseInt($("gym-duration").value) || null;
    const rpe = parseInt($("gym-rpe").value) || null;
    const notes = $("gym-notes").value;
    try {
      let session;
      if (_editingSession) {
        const r = await api("PATCH", `/api/gym/sessions/${_editingSession}`, { date, duration_min: dur, rpe, notes });
        session = r.item;
      } else {
        const r = await api("POST", "/api/gym/sessions", { date, duration_min: dur, rpe, notes });
        session = r.item;
      }
      const sets = [];
      document.querySelectorAll(".gym-exercise-group").forEach(grp => {
        const exName = grp.querySelector(".ex-name").value.trim();
        if (!exName) return;
        grp.querySelectorAll(".gym-set-row").forEach((row, i) => {
          sets.push({ exercise: exName, set_idx: i, reps: parseInt(row.querySelector(".set-reps").value) || null, weight_kg: parseFloat(row.querySelector(".set-weight").value) || null, rpe: parseFloat(row.querySelector(".set-rpe").value) || null, notes: "" });
        });
      });
      await api("PUT", `/api/gym/sessions/${session.id}/sets`, { sets });
      $("gym-editor").classList.add("hidden");
      _editingSession = null;
      toast("Sesja zapisana.");
      await loadGymSessions();
    } catch (e) {
      toast("Błąd zapisu: " + e.message, false);
    }
  });
};

async function editSession(id) {
  const data = await api("GET", `/api/gym/sessions/${id}`);
  const s = data.item;
  _editingSession = id;
  $("gym-date").value = s.date; $("gym-duration").value = s.duration_min || "";
  $("gym-rpe").value = s.rpe || ""; $("gym-notes").value = s.notes || "";
  $("gym-sets-editor").innerHTML = "";
  const byEx = {};
  (s.sets || []).forEach(x => { (byEx[x.exercise] = byEx[x.exercise] || []).push(x); });
  Object.entries(byEx).forEach(([ex, sets]) => addExerciseBlock(ex, sets));
  $("gym-editor").classList.remove("hidden");
  $("gym-editor").scrollIntoView({ behavior: "smooth" });
}

function evalGym(id) {
  document.querySelector('[data-tab="coach"]').click();
  document.querySelector('[data-coach="eval"]').click();
  setTimeout(() => { $("eval-kind").value = "gym"; updateEvalSelect("gym"); setTimeout(() => { $("eval-id").value = id; }, 300); }, 100);
}

// ---------------------------------------------------------------------------
// Nutrition
// ---------------------------------------------------------------------------
async function loadNutrition() {
  $("nutrition-table").innerHTML = '<div class="muted loading-pulse">Ładuję dane Fitatu...</div>';
  try {
    const data = await api("GET", "/api/fitatu/diary?limit=30");
    const items = data.items;
    if (!items.length) { $("nutrition-table").innerHTML = '<div class="muted">Brak danych — zaloguj się do Fitatu i zsynchronizuj.</div>'; return; }
    const avg = k => { const vals = items.filter(x => x[k] != null).map(x => x[k]); return vals.length ? vals.reduce((a, b) => a + b, 0) / vals.length : null; };
    $("nutrition-table").innerHTML = `<div class="stats-grid" style="margin-bottom:14px">
      <div class="stat"><div class="stat-label">Śr. kalorie</div><div class="stat-value">${fmt(avg("calories"), 0)}</div><div class="stat-sub">kcal/dzień</div></div>
      <div class="stat"><div class="stat-label">Śr. białko</div><div class="stat-value">${fmt(avg("protein_g"), 0)}</div><div class="stat-sub">g/dzień</div></div>
      <div class="stat"><div class="stat-label">Śr. węglowodany</div><div class="stat-value">${fmt(avg("carbs_g"), 0)}</div><div class="stat-sub">g/dzień</div></div>
      <div class="stat"><div class="stat-label">Śr. tłuszcz</div><div class="stat-value">${fmt(avg("fat_g"), 0)}</div><div class="stat-sub">g/dzień</div></div>
    </div>
    <table><thead><tr><th>Data</th><th class="num">Kalorie</th><th class="num">Białko g</th><th class="num">Węglowodany g</th><th class="num">Tłuszcz g</th><th class="num">Błonnik g</th></tr></thead>
    <tbody>${items.map(d => `<tr><td>${d.date}</td><td class="num">${fmt(d.calories, 0)}</td><td class="num">${fmt(d.protein_g, 1)}</td><td class="num">${fmt(d.carbs_g, 1)}</td><td class="num">${fmt(d.fat_g, 1)}</td><td class="num">${fmt(d.fiber_g, 1)}</td></tr>`).join("")}</tbody></table>`;
  } catch (e) {
    $("nutrition-table").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
  }
}

$("fitatu-sync-btn").onclick = () => withBtn($("fitatu-sync-btn"), "Synchronizuję...", async () => {
  setStatus("fitatu-sync-status", "Łączę z Fitatu...", "info");
  try {
    const r = await api("POST", "/api/fitatu/sync", { days: 30 });
    setStatus("fitatu-sync-status", `Zsynchronizowano ${r.synced_days} dni`, "ok");
    await loadNutrition();
    toast(`Fitatu: zsynchronizowano ${r.synced_days} dni.`);
  } catch (e) {
    setStatus("fitatu-sync-status", "Błąd: " + e.message, "err");
    toast("Błąd sync Fitatu: " + e.message, false);
  }
});

// ---------------------------------------------------------------------------
// Coach - provider badge
// ---------------------------------------------------------------------------
async function loadProviderBadge() {
  try {
    const p = await api("GET", "/api/coach/provider");
    const badge = $("coach-provider-badge");
    if (badge) {
      badge.textContent = p.provider === "anthropic" ? `Claude (${p.model})` : `Ollama: ${p.model}`;
      badge.style.color = p.provider === "ollama" ? "#22c55e" : "#6ea8fe";
    }
  } catch {}
}

// ---------------------------------------------------------------------------
// Coach - Gym session
// ---------------------------------------------------------------------------
$("coach-gym-session-btn").onclick = () => withBtn($("coach-gym-session-btn"), "Generuję...", async () => {
  $("coach-gym-session-output").innerHTML = `<div class="coach-thinking"><span class="spinner"></span> Analizuję regenerację i historię ćwiczeń — zajmie to 20–40 s...</div>`;
  try {
    const data = await api("POST", "/api/coach/gym-session");
    renderGymSession(data);
  } catch (e) {
    $("coach-gym-session-output").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
  }
});

function renderGymSession(d) {
  const exTable = d.exercises?.length ? `
    <table style="font-size:12px;margin-top:8px">
      <thead><tr><th>Ćwiczenie</th><th class="num">Serie</th><th class="num">Powt.</th><th class="num">Ciężar</th><th>Uwagi</th></tr></thead>
      <tbody>${d.exercises.map(ex => `<tr>
        <td>${ex.name}</td>
        <td class="num">${ex.sets}</td>
        <td class="num">${ex.reps}</td>
        <td class="num">${ex.weight_kg != null ? ex.weight_kg + " kg" : "BW"}</td>
        <td class="muted" style="font-size:11px">${ex.notes || ""}</td>
      </tr>`).join("")}</tbody>
    </table>` : "";
  $("coach-gym-session-output").innerHTML = `
    ${d.rationale ? `<div class="day-plan-intent" style="margin-bottom:10px">${d.rationale}</div>` : ""}
    ${d.warmup ? `<div class="coach-section"><h4>Rozgrzewka</h4><div class="day-plan-session">${d.warmup}</div></div>` : ""}
    <div class="coach-section"><h4>Ćwiczenia (${d.exercises?.length || 0})</h4>${exTable}</div>
    ${d.cooldown ? `<div class="coach-section" style="margin-top:10px"><h4>Schłodzenie</h4><div class="day-plan-session">${d.cooldown}</div></div>` : ""}
  `;
}

// ---------------------------------------------------------------------------
// Coach - Plan
// ---------------------------------------------------------------------------
$("coach-plan-btn").onclick = () => withBtn($("coach-plan-btn"), "Generuję plan...", async () => {
  $("coach-plan-output").innerHTML = `<div class="coach-thinking"><span class="spinner"></span> Analizuję 4 tygodnie danych i generuję plan — zajmie to 20–60 s...</div>`;
  try {
    const data = await api("POST", "/api/coach/plan");
    renderPlan(data);
    await loadPlanHistory();
  } catch (e) {
    $("coach-plan-output").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
    toast("Błąd generowania planu: " + e.message, false);
  }
});

function renderPlan(d) {
  let html = "";
  if (d.diagnosis && d.diagnosis.length) html += `<div class="coach-section"><h4>Diagnoza</h4><ul class="bullet-list">${d.diagnosis.map(x => `<li>${x}</li>`).join("")}</ul></div>`;
  if (d.issues && d.issues.length) html += `<div class="coach-section"><h4>Błędy / Ryzyka</h4><ul class="bullet-list">${d.issues.map(x => `<li>${x}</li>`).join("")}</ul></div>`;
  if (d.plan && d.plan.length) html += `<div class="coach-section"><h4>Plan 7 dni</h4>${d.plan.map(day => `
    <div class="day-plan-card">
      <div class="day-plan-header" onclick="this.nextElementSibling.classList.toggle('open')">
        <span class="day-plan-date">${day.day}</span>
        <span class="day-plan-focus">${day.focus}</span>
        <span class="day-plan-toggle">▾</span>
      </div>
      <div class="day-plan-body">
        ${day.intent ? `<div class="day-plan-intent">${day.intent}</div>` : ""}
        ${day.session ? `<div class="day-plan-session" style="margin-bottom:${day.exercises?.length ? "10px" : "0"}">${day.session}</div>` : ""}
        ${day.exercises?.length ? `<table style="font-size:12px;margin-top:4px"><thead><tr><th>Ćwiczenie</th><th class="num">Serie</th><th class="num">Powt.</th><th class="num">Ciężar</th><th>Uwagi</th></tr></thead><tbody>${day.exercises.map(ex => `<tr><td>${ex.name}</td><td class="num">${ex.sets}</td><td class="num">${ex.reps}</td><td class="num">${ex.weight_kg != null ? ex.weight_kg + " kg" : "BW"}</td><td class="muted" style="font-size:11px">${ex.notes || ""}</td></tr>`).join("")}</tbody></table>` : ""}
      </div>
    </div>`).join("")}</div>`;
  $("coach-plan-output").innerHTML = html || '<div class="muted">Brak danych.</div>';
}

async function loadPlanHistory() {
  const data = await api("GET", "/api/coach/history?kind=plan&limit=5");
  if (!data.items.length) { $("coach-plan-history").innerHTML = '<div class="muted">Brak historii.</div>'; return; }
  $("coach-plan-history").innerHTML = data.items.map(item => `
  <details>
    <summary style="color:var(--blue)">${fmtDate(item.created_at)} — ${item.model}</summary>
    <div class="detail-body history-text">${item.text}</div>
  </details>`).join("");
}

// ---------------------------------------------------------------------------
// Coach - Eval
// ---------------------------------------------------------------------------
$("eval-kind").onchange = () => updateEvalSelect($("eval-kind").value);

async function updateEvalSelect(kind) {
  $("eval-id").innerHTML = '<option>— ładuję —</option>';
  try {
    if (kind === "garmin") {
      const data = await api("GET", "/api/garmin/activities?limit=50");
      $("eval-id").innerHTML = data.items.map(a => `<option value="${a.activity_id}">${fmtDate(a.start_time_local)} — ${sportLabel(a.sport)}${a.name ? " – " + a.name : ""}</option>`).join("");
    } else {
      const data = await api("GET", "/api/gym/sessions?limit=50");
      $("eval-id").innerHTML = data.items.map(s => `<option value="${s.id}">${s.date} — ${s.exercises || "siłka"}${s.duration_min ? " " + s.duration_min + "min" : ""}</option>`).join("");
    }
  } catch (e) {
    $("eval-id").innerHTML = `<option>Błąd: ${e.message}</option>`;
  }
}

async function loadEvalSelects() { await updateEvalSelect($("eval-kind").value); }

$("coach-eval-btn").onclick = () => withBtn($("coach-eval-btn"), "Oceniam...", async () => {
  const kind = $("eval-kind").value;
  const id = parseInt($("eval-id").value);
  if (!id) { toast("Wybierz sesję.", false); return; }
  $("coach-eval-output").innerHTML = `<div class="coach-thinking"><span class="spinner"></span> Analizuję sesję...</div>`;
  try {
    const data = await api("POST", "/api/coach/eval", { kind, id });
    renderEval(data);
  } catch (e) {
    $("coach-eval-output").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
    toast("Błąd oceny: " + e.message, false);
  }
});

function renderEval(d) {
  const sc = scoreClass(d.score);
  $("coach-eval-output").innerHTML = `
  <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px">
    <div class="score-badge ${sc}">${d.score}</div>
    <div style="font-size:15px">${d.summary}</div>
  </div>
  ${d.positives && d.positives.length ? `<div class="coach-section"><h4>Co poszło dobrze</h4><ul class="bullet-list">${d.positives.map(x => `<li>${x}</li>`).join("")}</ul></div>` : ""}
  ${d.concerns && d.concerns.length ? `<div class="coach-section"><h4>Do obserwacji</h4><ul class="bullet-list">${d.concerns.map(x => `<li>${x}</li>`).join("")}</ul></div>` : ""}
  ${d.next_session ? `<div class="coach-section"><h4>Następna sesja</h4><div>${d.next_session}</div></div>` : ""}`;
}

// ---------------------------------------------------------------------------
// Coach - Recovery
// ---------------------------------------------------------------------------
$("coach-recovery-btn").onclick = () => withBtn($("coach-recovery-btn"), "Oceniam...", async () => {
  $("coach-recovery-output").innerHTML = `<div class="coach-thinking"><span class="spinner"></span> Analizuję ostatnie 7 dni...</div>`;
  try {
    const data = await api("POST", "/api/coach/recovery");
    renderRecovery(data);
  } catch (e) {
    $("coach-recovery-output").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
    toast("Błąd: " + e.message, false);
  }
});

function renderRecovery(d) {
  const statusColor = { ready: "#4ade80", moderate: "#f59e0b", fatigued: "#f97316", overreached: "#ef4444" }[d.status] || "#8a8f9a";
  $("coach-recovery-output").innerHTML = `
  <div style="display:flex;align-items:center;gap:14px;margin-bottom:16px">
    <div class="score-badge ${scoreClass(d.score)}">${d.score}</div>
    <div>
      <span style="color:${statusColor};font-weight:700;text-transform:uppercase;font-size:13px;letter-spacing:1px">${d.status}</span>
      <div style="margin-top:4px">${d.summary}</div>
    </div>
  </div>
  ${d.signals && d.signals.length ? `<div class="coach-section"><h4>Sygnały</h4><ul class="bullet-list">${d.signals.map(x => `<li>${x}</li>`).join("")}</ul></div>` : ""}
  ${d.recommendation ? `<div class="coach-section"><h4>Rekomendacja</h4><div style="font-size:14px">${d.recommendation}</div></div>` : ""}`;
}

// ---------------------------------------------------------------------------
// Coach - Nutrition analysis
// ---------------------------------------------------------------------------
$("coach-nutrition-btn").onclick = () => withBtn($("coach-nutrition-btn"), "Analizuję...", async () => {
  $("coach-nutrition-output").innerHTML = `<div class="coach-thinking"><span class="spinner"></span> Analizuję 30 dni danych żywieniowych i treningowych...</div>`;
  try {
    const data = await api("POST", "/api/coach/nutrition");
    renderNutritionAnalysis(data);
  } catch (e) {
    $("coach-nutrition-output").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
    toast("Błąd: " + e.message, false);
  }
});

function renderNutritionAnalysis(d) {
  $("coach-nutrition-output").innerHTML = `
  <div class="coach-section"><p style="font-size:14px">${d.summary}</p></div>
  ${d.patterns && d.patterns.length ? `<div class="coach-section"><h4>Wzorce żywieniowe</h4><ul class="bullet-list">${d.patterns.map(x => `<li>${x}</li>`).join("")}</ul></div>` : ""}
  ${d.correlations && d.correlations.length ? `<div class="coach-section"><h4>Zależności żywienie ↔ trening</h4><ul class="bullet-list">${d.correlations.map(x => `<li>${x}</li>`).join("")}</ul></div>` : ""}
  ${d.recommendations && d.recommendations.length ? `<div class="coach-section"><h4>Rekomendacje</h4><ul class="bullet-list">${d.recommendations.map(x => `<li>${x}</li>`).join("")}</ul></div>` : ""}`;
}

// ---------------------------------------------------------------------------
// Equipment
// ---------------------------------------------------------------------------
async function loadEquipment() {
  $("eq-list").innerHTML = '<div class="muted loading-pulse">Ładuję...</div>';
  try {
    const data = await api("GET", "/api/equipment");
    renderEquipment(data.items);
  } catch (e) {
    $("eq-list").innerHTML = `<div class="status err">Błąd: ${e.message}</div>`;
  }
}

function renderEquipment(items) {
  if (!items.length) { $("eq-list").innerHTML = '<div class="muted">Brak sprzętu.</div>'; return; }
  $("eq-list").innerHTML = items.map(e => `
  <div class="eq-row" data-id="${e.id}">
    <input class="eq-name" value="${e.name}" placeholder="Nazwa" />
    <input class="eq-kind" value="${e.kind}" placeholder="Rodzaj" style="width:120px" />
    <input class="eq-detail" value="${e.detail}" placeholder="Opis" />
    <button class="danger" style="padding:4px 8px" onclick="deleteEquipment(${e.id})">✕</button>
  </div>`).join("") + `
  <div class="form-row" style="margin-top:12px">
    <button id="eq-save-btn">Zapisz zmiany</button>
    <span id="eq-save-status" class="muted" style="display:none"></span>
  </div>`;
  $("eq-save-btn").onclick = saveEquipment;
}

$("eq-add-btn").onclick = () => withBtn($("eq-add-btn"), "Dodaję...", async () => {
  for (const row of document.querySelectorAll(".eq-row")) {
    await api("PATCH", `/api/equipment/${parseInt(row.dataset.id)}`, {
      name: row.querySelector(".eq-name").value.trim(),
      kind: row.querySelector(".eq-kind").value.trim(),
      detail: row.querySelector(".eq-detail").value.trim(),
    });
  }
  await api("POST", "/api/equipment", { name: "Nowy sprzęt", kind: "other", detail: "" });
  await loadEquipment();
});

async function saveEquipment() {
  await withBtn($("eq-save-btn"), "Zapisuję...", async () => {
    try {
      for (const row of document.querySelectorAll(".eq-row")) {
        const id = parseInt(row.dataset.id);
        await api("PATCH", `/api/equipment/${id}`, {
          name: row.querySelector(".eq-name").value.trim(),
          kind: row.querySelector(".eq-kind").value.trim(),
          detail: row.querySelector(".eq-detail").value.trim(),
        });
      }
      setStatus("eq-save-status", "Zapisano.", "ok");
      toast("Sprzęt zapisany.");
    } catch (e) {
      setStatus("eq-save-status", "Błąd: " + e.message, "err");
    }
  });
}

async function deleteEquipment(id) {
  for (const row of document.querySelectorAll(".eq-row")) {
    if (parseInt(row.dataset.id) === id) continue;
    await api("PATCH", `/api/equipment/${parseInt(row.dataset.id)}`, {
      name: row.querySelector(".eq-name").value.trim(),
      kind: row.querySelector(".eq-kind").value.trim(),
      detail: row.querySelector(".eq-detail").value.trim(),
    });
  }
  await api("DELETE", `/api/equipment/${id}`);
  await loadEquipment();
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------
async function loadSettings() {
  try {
    const data = await api("GET", "/api/settings");
    const env = data.env || {};
    const cfg = data.config || {};

    document.querySelectorAll("[data-env]").forEach(el => {
      const v = env[el.dataset.env];
      if (typeof v === "object") el.placeholder = v.set ? v.preview : "(nie ustawione)";
      else el.value = v || "";
    });

    document.querySelectorAll("[data-cfg]").forEach(el => {
      const k = el.dataset.cfg;
      if (k in cfg) {
        if (el.tagName === "SELECT") {
          el.value = cfg[k] || "";
        } else {
          el.value = cfg[k] || "";
        }
      }
    });

    // Connections
    const [gs, ws, fs] = await Promise.all([
      api("GET", "/api/garmin/status"),
      api("GET", "/api/withings/status"),
      api("GET", "/api/fitatu/status"),
    ]);

    setStatus("garmin-status-label", gs.logged_in ? "Połączono" : gs.status === "mfa_pending" ? "Czeka na MFA..." : "Niepołączono", gs.logged_in ? "ok" : "info", true);
    $("garmin-mfa-row").classList.toggle("hidden", gs.status !== "mfa_pending");

    setStatus("withings-status-label", ws.connected ? `Połączono (${ws.userid})` : "Niepołączono", ws.connected ? "ok" : "info", true);
    $("withings-disconnect-btn").classList.toggle("hidden", !ws.connected);

    setStatus("fitatu-status-label", fs.connected ? `Połączono (ID: ${fs.user_id})` : "Niepołączono", fs.connected ? "ok" : "info", true);
    $("fitatu-disconnect-btn").classList.toggle("hidden", !fs.connected);
  } catch (e) {
    toast("Błąd ładowania ustawień: " + e.message, false);
  }
}

$("env-save-btn").onclick = () => withBtn($("env-save-btn"), "Zapisuję...", async () => {
  const updates = {};
  document.querySelectorAll("[data-env]").forEach(el => { if (el.value.trim()) updates[el.dataset.env] = el.value.trim(); });
  try {
    await api("POST", "/api/settings/env", { updates });
    setStatus("env-save-status", "Zapisano.", "ok");
    toast("Klucze zapisane.");
  } catch (e) {
    setStatus("env-save-status", "Błąd: " + e.message, "err");
    toast(e.message === "authentication required" ? "Najpierw się zaloguj." : "Błąd: " + e.message, false);
  }
});

$("config-save-btn").onclick = () => withBtn($("config-save-btn"), "Zapisuję...", async () => {
  const updates = {};
  document.querySelectorAll("[data-cfg]").forEach(el => { if (el.value.trim()) updates[el.dataset.cfg] = el.value.trim(); });
  try {
    await api("POST", "/api/settings/config", { updates });
    setStatus("config-save-status", "Zapisano.", "ok");
    toast("Konfiguracja zapisana.");
    loadProviderBadge();
  } catch (e) {
    setStatus("config-save-status", "Błąd: " + e.message, "err");
    toast(e.message === "authentication required" ? "Najpierw się zaloguj." : "Błąd: " + e.message, false);
  }
});

// Garmin
$("garmin-login-btn").onclick = () => withBtn($("garmin-login-btn"), "Loguję...", async () => {
  setStatus("garmin-status-label", "Łączę z Garmin...", "info");
  try {
    const r = await api("POST", "/api/garmin/login", {});
    if (r.status === "mfa_pending") {
      setStatus("garmin-status-label", "Wymagany kod MFA", "warn");
      $("garmin-mfa-row").classList.remove("hidden");
      $("garmin-mfa-input").focus();
      toast("Podaj kod MFA z emaila / aplikacji Garmin.");
    } else if (r.status === "success") {
      setStatus("garmin-status-label", "Połączono", "ok", true);
      toast("Garmin połączony!");
      loadSettings();
    } else {
      setStatus("garmin-status-label", r.error || r.status, "err");
      toast("Błąd logowania: " + (r.error || r.status), false);
    }
  } catch (e) {
    setStatus("garmin-status-label", "Błąd: " + e.message, "err");
    toast("Błąd: " + e.message, false);
  }
});

$("garmin-mfa-btn").onclick = () => withBtn($("garmin-mfa-btn"), "Weryfikuję...", async () => {
  const code = $("garmin-mfa-input").value.trim();
  if (!code) { toast("Wpisz kod MFA.", false); return; }
  setStatus("garmin-status-label", "Weryfikuję kod...", "info");
  try {
    const r = await api("POST", "/api/garmin/mfa", { code });
    if (r.status === "success") {
      setStatus("garmin-status-label", "Połączono", "ok", true);
      $("garmin-mfa-row").classList.add("hidden");
      $("garmin-mfa-input").value = "";
      toast("Garmin połączony!");
      loadSettings();
    } else {
      setStatus("garmin-status-label", r.error || r.status, "err");
      toast("MFA błąd: " + (r.error || r.status), false);
    }
  } catch (e) {
    setStatus("garmin-status-label", "Błąd: " + e.message, "err");
    toast("Błąd: " + e.message, false);
  }
});

$("garmin-sync-btn").onclick = () => withBtn($("garmin-sync-btn"), "Synchronizuję...", async () => {
  setStatus("garmin-status-label", "Synchronizuję...", "info");
  try {
    const r = await api("POST", "/api/garmin/sync", {});
    setStatus("garmin-status-label", `Połączono — ${r.activities.inserted} akt., ${r.daily.days} dni`, "ok", true);
    toast(`Garmin zsynchronizowany: ${r.activities.inserted} aktywności, ${r.daily.days} dni.`);
  } catch (e) {
    setStatus("garmin-status-label", "Błąd sync: " + e.message, "err");
    toast("Błąd sync Garmin: " + e.message, false);
  }
});

// Withings
$("withings-connect-btn").onclick = () => { window.location.href = "/api/withings/authorize"; };

$("withings-sync-btn").onclick = () => withBtn($("withings-sync-btn"), "Synchronizuję...", async () => {
  setStatus("withings-status-label", "Synchronizuję...", "info");
  try {
    const r = await api("POST", "/api/withings/sync");
    setStatus("withings-status-label", `Połączono — ${r.inserted_days} pomiarów`, "ok", true);
    toast(`Withings: ${r.inserted_days} dni pomiarów.`);
  } catch (e) {
    setStatus("withings-status-label", "Błąd: " + e.message, "err");
    toast("Błąd sync Withings: " + e.message, false);
  }
});

$("withings-disconnect-btn").onclick = () => withBtn($("withings-disconnect-btn"), "Odłączam...", async () => {
  await api("POST", "/api/withings/disconnect");
  toast("Withings odłączony.");
  loadSettings();
});

// Fitatu
$("fitatu-login-btn").onclick = async () => {
  const emailEl = document.querySelector("[data-env=FITATU_EMAIL]");
  const savedEmail = emailEl?.value.trim();
  const body = savedEmail ? { email: savedEmail } : {};
  await withBtn($("fitatu-login-btn"), "Loguję...", async () => {
    setStatus("fitatu-status-label", "Łączę z Fitatu...", "info");
    try {
      const r = await api("POST", "/api/fitatu/login", body);
      setStatus("fitatu-status-label", `Połączono (ID: ${r.user_id})`, "ok", true);
      toast("Fitatu połączony!");
      loadSettings();
    } catch (e) {
      setStatus("fitatu-status-label", "Błąd: " + e.message, "err");
      toast("Błąd Fitatu: " + e.message, false);
    }
  });
};

$("fitatu-sync-settings-btn").onclick = () => withBtn($("fitatu-sync-settings-btn"), "Synchronizuję...", async () => {
  setStatus("fitatu-status-label", "Synchronizuję...", "info", true);
  try {
    const r = await api("POST", "/api/fitatu/sync", { days: 30 });
    setStatus("fitatu-status-label", `Połączono — ${r.synced_days} dni`, "ok", true);
    toast(`Fitatu: zsynchronizowano ${r.synced_days} dni.`);
  } catch (e) {
    setStatus("fitatu-status-label", "Błąd: " + e.message, "err");
    toast("Błąd sync Fitatu: " + e.message, false);
  }
});

$("fitatu-disconnect-btn").onclick = () => withBtn($("fitatu-disconnect-btn"), "Odłączam...", async () => {
  await api("POST", "/api/fitatu/disconnect");
  toast("Fitatu odłączony.");
  loadSettings();
});

// ---------------------------------------------------------------------------
// Init
// ---------------------------------------------------------------------------
(async () => {
  await checkAuth();
  initFromHash();
  loadProviderBadge();
})();
