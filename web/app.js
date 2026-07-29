const state = {
  data: null,
  viewer: "team",
  season: "All",
  time: "All",
  search: "",
};

const els = {
  viewer: document.querySelector("#viewerSelect"),
  season: document.querySelector("#seasonSelect"),
  time: document.querySelector("#timeSelect"),
  search: document.querySelector("#searchInput"),
  body: document.querySelector("#rankingBody"),
  empty: document.querySelector("#emptyState"),
  badge: document.querySelector("#statusBadge"),
  activeSeason: document.querySelector("#activeSeason"),
  caughtFamilies: document.querySelector("#caughtFamilies"),
  selectedView: document.querySelector("#selectedView"),
  lastUpdate: document.querySelector("#lastUpdate"),
  title: document.querySelector("#rankingTitle"),
  explanation: document.querySelector("#rankingExplanation"),
  methodButton: document.querySelector("#methodButton"),
  methodPanel: document.querySelector("#methodPanel"),
  footerMeta: document.querySelector("#footerMeta"),
};

function formatNumber(value, digits = 1) {
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(value);
}

function statusLabel(status) {
  if (status === "new_team_unique") return ["New team unique", "new"];
  if (status === "team_already_unique") return ["Team already has family", "team"];
  return ["Personal duplicate", "duplicate"];
}

function escapeHtml(value) {
  return String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function currentViews() {
  const key = `${state.season}|${state.time}`;
  const bundle = state.viewer === "team"
    ? state.data.rankings.team
    : state.data.rankings.players[state.viewer];
  if (!bundle) return [];
  return (bundle.views[key] || []).map(id => bundle.entries[id]).filter(Boolean);
}

function targetDetailsHtml(targets) {
  return targets.map(target => {
    const [label, cls] = statusLabel(target.status);
    return `
      <article class="target-card">
        <strong>${escapeHtml(target.species)}</strong>
        <span class="pill ${cls}">${label}</span>
        <dl>
          <dt>Evolution family</dt><dd>${escapeHtml(target.family)}</dd>
          <dt>Points if shiny</dt><dd>${formatNumber(target.effectivePoints, 1)}</dd>
          <dt>Horde chance</dt><dd>${formatNumber(target.hordeProbabilityPercent, 1)}%</dd>
          <dt>Weighted horde size</dt><dd>${formatNumber(target.weightedHordeSize, 1)}</dd>
          <dt>Temporal exclusivity</dt><dd>×${formatNumber(target.temporalExclusivity, 2)}</dd>
          <dt>Adjusted contribution</dt><dd>${formatNumber(target.adjustedContribution, 1)}</dd>
        </dl>
      </article>`;
  }).join("");
}

function render() {
  const query = state.search.trim().toLocaleLowerCase();
  const rows = currentViews().filter(row => {
    if (!query) return true;
    return [row.displayName, row.locationId, row.topTarget, row.fallbackTarget, row.allTargetsText]
      .join(" ")
      .toLocaleLowerCase()
      .includes(query);
  });

  els.body.innerHTML = rows.map((row, index) => {
    const topStatus = row.targets[0]?.status || "new_team_unique";
    const [topLabel, topClass] = statusLabel(topStatus);
    const windowText = `${row.season} · ${row.timeOfDay}`;
    return `
      <tr>
        <td class="rank">${index + 1}</td>
        <td><span class="spot-name">${escapeHtml(row.displayName)}</span><span class="location-id">Location ID ${escapeHtml(row.locationId)} · ${escapeHtml(row.encounterType)}</span></td>
        <td>${escapeHtml(windowText)}</td>
        <td class="score">${formatNumber(row.adjustedScore, 1)}<span class="legacy">Legacy ${formatNumber(row.legacyScore, 1)}</span></td>
        <td><span class="target-name">${escapeHtml(row.topTarget)}</span><div class="target-meta">${formatNumber(row.topTargetPoints, 1)} pts · ×${formatNumber(row.topTargetExclusivity, 2)} exclusivity</div><div class="target-meta"><span class="pill ${topClass}">${topLabel}</span></div></td>
        <td>${formatNumber(row.topTargetProbabilityPercent, 1)}%</td>
        <td>${row.fallbackTarget ? `${escapeHtml(row.fallbackTarget)}<div class="target-meta">${formatNumber(row.fallbackPoints, 1)} pts</div>` : "—"}</td>
        <td><button class="details-button" data-context="${escapeHtml(row.contextId)}" aria-expanded="false">Show ${row.targets.length} target${row.targets.length === 1 ? "" : "s"}</button></td>
      </tr>
      <tr class="details-row" data-details="${escapeHtml(row.contextId)}" hidden><td colspan="8"><div class="target-details">${targetDetailsHtml(row.targets)}</div></td></tr>`;
  }).join("");

  els.empty.hidden = rows.length > 0;
  els.selectedView.textContent = state.viewer === "team" ? "Team overall" : state.viewer;
  els.title.textContent = `Top ${Math.min(state.data.meta.topN, rows.length || state.data.meta.topN)} spots — ${state.viewer === "team" ? "Team overall" : state.viewer}`;
  els.explanation.textContent = state.viewer === "team"
    ? "Team view values uncaught evolution families with the Unique Species bonus and already-owned team families at their normal base points."
    : state.data.meta.playerContextExclusionEnabled
      ? "Player view removes every context containing an evolution family already caught by this player, then ranks the remaining spots."
      : "Player view keeps all routes and reduces personally duplicated evolution families to the configured duplicate value.";

  document.querySelectorAll(".details-button").forEach(button => {
    button.addEventListener("click", () => {
      const id = button.dataset.context;
      const detail = document.querySelector(`[data-details="${CSS.escape(id)}"]`);
      const open = detail.hidden;
      detail.hidden = !open;
      button.setAttribute("aria-expanded", String(open));
      button.textContent = open ? "Hide targets" : `Show ${detail.querySelectorAll(".target-card").length} targets`;
    });
  });
}

async function init() {
  try {
    const response = await fetch("data/strategy.json", { cache: "no-store" });
    if (!response.ok) throw new Error(`HTTP ${response.status}`);
    state.data = await response.json();

    els.viewer.innerHTML = `<option value="team">Team overall</option>` + state.data.players
      .map(player => `<option value="${escapeHtml(player)}">${escapeHtml(player)}</option>`)
      .join("");

    state.season = state.data.meta.activeSeason !== "All" ? state.data.meta.activeSeason : "All";
    els.season.value = state.season;
    els.activeSeason.textContent = state.data.meta.activeSeason;
    els.caughtFamilies.textContent = state.data.meta.teamCaughtFamilyCount;
    els.lastUpdate.textContent = new Date(state.data.meta.generatedAtUtc).toLocaleString();
    els.footerMeta.textContent = `${state.data.meta.playerCount} players · ${state.data.meta.routeContextCount} route contexts`;
    els.badge.textContent = "Strategy data loaded";
    els.badge.classList.add("ok");
    render();
  } catch (error) {
    console.error(error);
    els.badge.textContent = "Strategy data unavailable";
    els.badge.classList.add("error");
    els.empty.hidden = false;
    els.empty.textContent = "The generated strategy file could not be loaded. Check the latest GitHub Actions run.";
  }
}

els.viewer.addEventListener("change", event => { state.viewer = event.target.value; render(); });
els.season.addEventListener("change", event => { state.season = event.target.value; render(); });
els.time.addEventListener("change", event => { state.time = event.target.value; render(); });
els.search.addEventListener("input", event => { state.search = event.target.value; render(); });
els.methodButton.addEventListener("click", () => {
  els.methodPanel.hidden = !els.methodPanel.hidden;
  els.methodButton.textContent = els.methodPanel.hidden ? "How scoring works" : "Hide scoring method";
});

init();
