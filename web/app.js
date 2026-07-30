const state = {
  data: null,
  viewer: "team",
  autoFilter: true,
  manualSeason: "All",
  manualTime: "All",
  liveSeason: "All",
  liveTime: "All",
  liveTimeLabel: "—",
  gameTime: "—",
  search: "",
  clockTimer: null,
};

const els = {
  viewer: document.querySelector("#viewerSelect"),
  season: document.querySelector("#seasonSelect"),
  time: document.querySelector("#timeSelect"),
  search: document.querySelector("#searchInput"),
  liveFilterToggle: document.querySelector("#liveFilterToggle"),
  liveFilterButtonText: document.querySelector("#liveFilterButtonText"),
  liveFilterHint: document.querySelector("#liveFilterHint"),
  body: document.querySelector("#rankingBody"),
  empty: document.querySelector("#emptyState"),
  badge: document.querySelector("#statusBadge"),
  activeSeason: document.querySelector("#activeSeason"),
  gameTime: document.querySelector("#gameTime"),
  activeTimeWindow: document.querySelector("#activeTimeWindow"),
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

function titleCase(value) {
  if (!value || value === "All") return value || "All";
  return value.charAt(0).toUpperCase() + value.slice(1);
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

function effectiveSeason() {
  return state.autoFilter ? state.liveSeason : state.manualSeason;
}

function effectiveTime() {
  return state.autoFilter ? state.liveTime : state.manualTime;
}

function currentViews() {
  const key = `${effectiveSeason()}|${effectiveTime()}`;
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
          <dt>Score multiplier</dt><dd>×${formatNumber(target.scoreMultiplier, 2)}</dd>
          <dt>Adjusted contribution</dt><dd>${formatNumber(target.adjustedContribution, 1)}</dd>
        </dl>
      </article>`;
  }).join("");
}

function updateFilterControls() {
  const season = effectiveSeason();
  const time = effectiveTime();
  els.season.disabled = state.autoFilter;
  els.time.disabled = state.autoFilter;
  els.season.value = season;
  els.time.value = time;
  els.liveFilterToggle.setAttribute("aria-pressed", String(state.autoFilter));
  els.liveFilterToggle.classList.toggle("is-live", state.autoFilter);
  els.liveFilterButtonText.textContent = state.autoFilter ? "Live filters: ON" : "Live filters: OFF";
  els.liveFilterHint.textContent = state.autoFilter
    ? `Automatically using ${state.liveSeason} · ${state.liveTimeLabel}`
    : `Manual selection: ${season} · ${time === "All" ? "All times" : titleCase(time)}`;
}

function refreshLiveContext({ forceRender = false } = {}) {
  if (!state.data) return;
  const liveConfig = state.data.meta.liveFilter;
  let nextSeason = state.data.meta.activeSeason || "All";
  let nextTime = state.data.meta.activeTimeOfDay || "All";
  let nextTimeLabel = titleCase(nextTime);
  let nextGameTime = state.data.meta.gameTimeAtBuild || "—";

  try {
    if (liveConfig && window.ShinyWarsClock) {
      const now = new Date();
      const clock = window.ShinyWarsClock.gameClockAt(now, liveConfig);
      const season = window.ShinyWarsClock.seasonAt(now, liveConfig.seasonRotation);
      nextSeason = season;
      nextTime = clock.timeOfDay;
      nextTimeLabel = clock.timeOfDayLabel;
      nextGameTime = clock.gameTime;
    }
  } catch (error) {
    console.error("Could not calculate live game context", error);
  }

  const filterChanged = nextSeason !== state.liveSeason || nextTime !== state.liveTime;
  state.liveSeason = nextSeason;
  state.liveTime = nextTime;
  state.liveTimeLabel = nextTimeLabel;
  state.gameTime = nextGameTime;

  els.activeSeason.textContent = state.liveSeason;
  els.gameTime.textContent = state.gameTime;
  els.activeTimeWindow.textContent = state.liveTimeLabel;
  updateFilterControls();

  if ((filterChanged && state.autoFilter) || forceRender) {
    render();
  }
}

function render() {
  if (!state.data) return;
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
    const windowText = `${row.season} · ${titleCase(row.timeOfDay)}`;
    return `
      <tr>
        <td class="rank">${index + 1}</td>
        <td><span class="spot-name">${escapeHtml(row.displayName)}</span><span class="location-id">Location ID ${escapeHtml(row.locationId)} · ${escapeHtml(row.encounterType)}</span></td>
        <td>${escapeHtml(windowText)}</td>
        <td class="score">${formatNumber(row.adjustedScore, 1)}<span class="legacy">Legacy ${formatNumber(row.legacyScore, 1)}</span></td>
        <td><span class="target-name">${escapeHtml(row.topTarget)}</span><div class="target-meta">${formatNumber(row.topTargetPoints, 1)} pts · ×${formatNumber(row.topTargetExclusivity, 2)} exclusivity · score ×${formatNumber(row.topTargetScoreMultiplier, 2)}</div><div class="target-meta"><span class="pill ${topClass}">${topLabel}</span></div></td>
        <td>${formatNumber(row.topTargetProbabilityPercent, 1)}%</td>
        <td>${row.fallbackTarget ? `${escapeHtml(row.fallbackTarget)}<div class="target-meta">${formatNumber(row.fallbackPoints, 1)} pts</div>` : "—"}</td>
        <td><button class="details-button" data-context="${escapeHtml(row.contextId)}" aria-expanded="false">Show ${row.targets.length} target${row.targets.length === 1 ? "" : "s"}</button></td>
      </tr>
      <tr class="details-row" data-details="${escapeHtml(row.contextId)}" hidden><td colspan="8"><div class="target-details">${targetDetailsHtml(row.targets)}</div></td></tr>`;
  }).join("");

  const season = effectiveSeason();
  const time = effectiveTime();
  const selectedName = state.viewer === "team" ? "Team overall" : state.viewer;
  els.empty.hidden = rows.length > 0;
  els.selectedView.textContent = selectedName;
  els.title.textContent = `Top ${Math.min(state.data.meta.topN, rows.length || state.data.meta.topN)} spots — ${selectedName}`;
  const filterText = `${season} · ${time === "All" ? "All times" : titleCase(time)}`;
  const modeText = state.autoFilter ? "live game context" : "manual filters";
  els.explanation.textContent = state.viewer === "team"
    ? `Showing ${filterText} via ${modeText}. Team view values uncaught evolution families with the Unique Species bonus and already-owned team families at their normal base points.`
    : state.data.meta.playerContextExclusionEnabled
      ? `Showing ${filterText} via ${modeText}. Player view removes every context containing an evolution family already caught by this player, then ranks the remaining spots.`
      : `Showing ${filterText} via ${modeText}. Player view keeps all routes and reduces personally duplicated evolution families to the configured duplicate value.`;

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

    state.autoFilter = state.data.meta.liveFilter?.defaultEnabled !== false;
    refreshLiveContext();
    state.manualSeason = state.liveSeason;
    state.manualTime = state.liveTime;
    updateFilterControls();

    els.caughtFamilies.textContent = state.data.meta.teamCaughtFamilyCount;
    els.lastUpdate.textContent = new Date(state.data.meta.generatedAtUtc).toLocaleString();
    els.footerMeta.textContent = `${state.data.meta.playerCount} players · ${state.data.meta.routeContextCount} route contexts`;
    els.badge.textContent = "Strategy data loaded";
    els.badge.classList.add("ok");
    render();

    state.clockTimer = window.setInterval(() => refreshLiveContext(), 1000);
  } catch (error) {
    console.error(error);
    els.badge.textContent = "Strategy data unavailable";
    els.badge.classList.add("error");
    els.empty.hidden = false;
    els.empty.textContent = "The generated strategy file could not be loaded. Check the latest GitHub Actions run.";
  }
}

els.viewer.addEventListener("change", event => {
  state.viewer = event.target.value;
  render();
});
els.season.addEventListener("change", event => {
  state.manualSeason = event.target.value;
  if (!state.autoFilter) render();
});
els.time.addEventListener("change", event => {
  state.manualTime = event.target.value;
  if (!state.autoFilter) render();
});
els.search.addEventListener("input", event => {
  state.search = event.target.value;
  render();
});
els.liveFilterToggle.addEventListener("click", () => {
  state.autoFilter = !state.autoFilter;
  updateFilterControls();
  render();
});
els.methodButton.addEventListener("click", () => {
  els.methodPanel.hidden = !els.methodPanel.hidden;
  els.methodButton.textContent = els.methodPanel.hidden ? "How scoring works" : "Hide scoring method";
});

init();
