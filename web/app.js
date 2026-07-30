const PAGE_SIZE = 100;

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
  visibleCount: PAGE_SIZE,
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
  subtitle: document.querySelector(".subtitle"),
  tableCard: document.querySelector(".table-card"),
  loadMoreContainer: null,
  resultCount: null,
  loadMoreButton: null,
};

function formatNumber(value, digits = 1) {
  const number = Number(value);

  if (!Number.isFinite(number)) {
    return "—";
  }

  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: digits,
    minimumFractionDigits: digits,
  }).format(number);
}

function titleCase(value) {
  if (!value || value === "All") {
    return value || "All";
  }

  return value.charAt(0).toUpperCase() + value.slice(1);
}

function statusLabel(status) {
  if (status === "new_team_unique") {
    return ["New team unique", "new"];
  }

  if (status === "team_already_unique") {
    return ["Team already has family", "team"];
  }

  return ["Personal duplicate", "duplicate"];
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function effectiveSeason() {
  return state.autoFilter
    ? state.liveSeason
    : state.manualSeason;
}

function effectiveTime() {
  return state.autoFilter
    ? state.liveTime
    : state.manualTime;
}

function resetVisibleCount() {
  state.visibleCount = PAGE_SIZE;
}

function currentBundle() {
  if (!state.data) {
    return null;
  }

  if (state.viewer === "team") {
    return state.data.rankings?.team || null;
  }

  return state.data.rankings?.players?.[state.viewer] || null;
}

function currentViews() {
  const bundle = currentBundle();

  if (!bundle) {
    return [];
  }

  const key = `${effectiveSeason()}|${effectiveTime()}`;
  const contextIds = bundle.views?.[key] || [];

  return contextIds
    .map((contextId) => bundle.entries?.[contextId])
    .filter(Boolean);
}

function searchableText(row) {
  const targetNames = Array.isArray(row.targets)
    ? row.targets.map((target) => {
        return [
          target.species,
          target.family,
          target.status,
        ].join(" ");
      })
    : [];

  return [
    row.displayName,
    row.region,
    row.locationName,
    row.locationId,
    row.encounterType,
    row.season,
    row.timeOfDay,
    row.topTarget,
    row.topTargetFamily,
    row.fallbackTarget,
    row.allTargetsText,
    ...targetNames,
  ]
    .join(" ")
    .toLocaleLowerCase();
}

function filteredCurrentRows() {
  const allRows = currentViews();
  const query = state.search
    .trim()
    .toLocaleLowerCase();

  return allRows
    .map((row, index) => ({
      row,
      rank: index + 1,
    }))
    .filter(({ row }) => {
      if (!query) {
        return true;
      }

      return searchableText(row).includes(query);
    });
}

function combinationLabelInfo(combinationCount) {
  const count = Number(combinationCount);

  if (!Number.isInteger(count) || count < 1) {
    return null;
  }

  const text =
    count === 1
      ? "1 S/T Combination"
      : `${count} S/T Combinations`;

  if (count === 1) {
    return {
      text,
      cssClass: "combination-red",
    };
  }

  if (count === 2) {
    return {
      text,
      cssClass: "combination-orange",
    };
  }

  if (count <= 4) {
    return {
      text,
      cssClass: "combination-yellow",
    };
  }

  return {
    text,
    cssClass: "combination-green",
  };
}

function targetDetailsHtml(targets) {
  if (!Array.isArray(targets) || targets.length === 0) {
    return `
      <article class="target-card">
        <strong>No target details available</strong>
      </article>
    `;
  }

  return targets
    .map((target) => {
      const [label, cssClass] = statusLabel(target.status);

      const combinationInfo = combinationLabelInfo(
        target.seasonTimeCombinationCount
      );

      const combinationLabel = combinationInfo
        ? `
          <span class="pill ${combinationInfo.cssClass}">
            ${escapeHtml(combinationInfo.text)}
          </span>
        `
        : "";

      return `
        <article class="target-card">
          <strong>${escapeHtml(target.species)}</strong>

          <div class="target-pill-row">
            <span class="pill ${cssClass}">
              ${escapeHtml(label)}
            </span>

            ${combinationLabel}
          </div>

          <dl>
            <dt>Evolution family</dt>
            <dd>${escapeHtml(target.family)}</dd>

            <dt>Points if shiny</dt>
            <dd>
              ${formatNumber(
                target.effectivePoints,
                1
              )}
            </dd>

            <dt>Horde chance</dt>
            <dd>
              ${formatNumber(
                target.hordeProbabilityPercent,
                1
              )}%
            </dd>

            <dt>Weighted horde size</dt>
            <dd>
              ${formatNumber(
                target.weightedHordeSize,
                1
              )}
            </dd>

            <dt>Score multiplier</dt>
            <dd>
              ×${formatNumber(
                target.scoreMultiplier,
                2
              )}
            </dd>

            <dt>Legacy contribution</dt>
            <dd>
              ${formatNumber(
                target.legacyContribution,
                1
              )}
            </dd>

            <dt>Adjusted contribution</dt>
            <dd>
              ${formatNumber(
                target.adjustedContribution,
                1
              )}
            </dd>
          </dl>
        </article>
      `;
    })
    .join("");
}

function ensurePaginationControls() {
  if (
    els.loadMoreContainer &&
    els.resultCount &&
    els.loadMoreButton
  ) {
    return;
  }

  const container = document.createElement("div");
  container.className = "pagination-controls";

  container.style.display = "flex";
  container.style.alignItems = "center";
  container.style.justifyContent = "space-between";
  container.style.gap = "1rem";
  container.style.flexWrap = "wrap";
  container.style.padding = "1rem";

  const resultCount = document.createElement("span");
  resultCount.className = "pagination-summary";

  const loadMoreButton = document.createElement("button");
  loadMoreButton.type = "button";
  loadMoreButton.className = "secondary-button";
  loadMoreButton.hidden = true;

  loadMoreButton.addEventListener("click", () => {
    state.visibleCount += PAGE_SIZE;
    render();
  });

  container.append(
    resultCount,
    loadMoreButton
  );

  els.tableCard.appendChild(container);

  els.loadMoreContainer = container;
  els.resultCount = resultCount;
  els.loadMoreButton = loadMoreButton;
}

function updatePaginationControls(
  shownCount,
  totalCount
) {
  ensurePaginationControls();

  els.resultCount.textContent =
    totalCount === 0
      ? "No matching results"
      : `Showing ${shownCount} of ${totalCount} results`;

  const remainingCount =
    totalCount - shownCount;

  if (remainingCount <= 0) {
    els.loadMoreButton.hidden = true;
    return;
  }

  const nextCount = Math.min(
    PAGE_SIZE,
    remainingCount
  );

  els.loadMoreButton.hidden = false;
  els.loadMoreButton.textContent =
    `Show ${nextCount} more`;
}

function updateFilterControls() {
  const season = effectiveSeason();
  const time = effectiveTime();

  els.season.disabled = state.autoFilter;
  els.time.disabled = state.autoFilter;

  els.season.value = season;
  els.time.value = time;

  els.liveFilterToggle.setAttribute(
    "aria-pressed",
    String(state.autoFilter)
  );

  els.liveFilterToggle.classList.toggle(
    "is-live",
    state.autoFilter
  );

  els.liveFilterButtonText.textContent =
    state.autoFilter
      ? "Live filters: ON"
      : "Live filters: OFF";

  els.liveFilterHint.textContent =
    state.autoFilter
      ? (
          `Automatically using ` +
          `${state.liveSeason} · ` +
          `${state.liveTimeLabel}`
        )
      : (
          `Manual selection: ` +
          `${season} · ` +
          `${
            time === "All"
              ? "All times"
              : titleCase(time)
          }`
        );
}

function refreshLiveContext({
  forceRender = false,
} = {}) {
  if (!state.data) {
    return;
  }

  const liveConfig =
    state.data.meta.liveFilter;

  let nextSeason =
    state.data.meta.activeSeason || "All";

  let nextTime =
    state.data.meta.activeTimeOfDay || "All";

  let nextTimeLabel =
    titleCase(nextTime);

  let nextGameTime =
    state.data.meta.gameTimeAtBuild || "—";

  try {
    if (
      liveConfig &&
      window.ShinyWarsClock
    ) {
      const now = new Date();

      const clock =
        window.ShinyWarsClock.gameClockAt(
          now,
          liveConfig
        );

      const season =
        window.ShinyWarsClock.seasonAt(
          now,
          liveConfig.seasonRotation
        );

      nextSeason = season;
      nextTime = clock.timeOfDay;
      nextTimeLabel =
        clock.timeOfDayLabel;
      nextGameTime = clock.gameTime;
    }
  } catch (error) {
    console.error(
      "Could not calculate live game context",
      error
    );
  }

  const filterChanged =
    nextSeason !== state.liveSeason ||
    nextTime !== state.liveTime;

  state.liveSeason = nextSeason;
  state.liveTime = nextTime;
  state.liveTimeLabel = nextTimeLabel;
  state.gameTime = nextGameTime;

  els.activeSeason.textContent =
    state.liveSeason;

  els.gameTime.textContent =
    state.gameTime;

  els.activeTimeWindow.textContent =
    state.liveTimeLabel;

  updateFilterControls();

  if (
    filterChanged &&
    state.autoFilter
  ) {
    resetVisibleCount();
  }

  if (
    (filterChanged && state.autoFilter) ||
    forceRender
  ) {
    render();
  }
}

function rankingRowHtml({
  row,
  rank,
}) {
  const targets = Array.isArray(row.targets)
    ? row.targets
    : [];

  const topStatus =
    targets[0]?.status ||
    "new_team_unique";

  const [
    topLabel,
    topClass,
  ] = statusLabel(topStatus);

  const windowText =
    `${row.season} · ` +
    `${titleCase(row.timeOfDay)}`;

  const fallbackHtml =
    row.fallbackTarget
      ? `
        ${escapeHtml(row.fallbackTarget)}
        <div class="target-meta">
          ${formatNumber(
            row.fallbackPoints,
            1
          )} pts
        </div>
      `
      : "—";

  return `
    <tr>
      <td class="rank">
        ${rank}
      </td>

      <td>
        <span class="spot-name">
          ${escapeHtml(row.displayName)}
        </span>

        <span class="location-id">
          Location ID
          ${escapeHtml(row.locationId)}
          ·
          ${escapeHtml(row.encounterType)}
        </span>
      </td>

      <td>
        ${escapeHtml(windowText)}
      </td>

      <td class="score">
        ${formatNumber(
          row.adjustedScore,
          1
        )}

        <span class="legacy">
          Legacy
          ${formatNumber(
            row.legacyScore,
            1
          )}
        </span>
      </td>

      <td>
        <span class="target-name">
          ${escapeHtml(row.topTarget)}
        </span>

        <div class="target-meta">
          ${formatNumber(
            row.topTargetPoints,
            1
          )}
          pts · score
          ×${formatNumber(
            row.topTargetScoreMultiplier,
            2
          )}
        </div>

        <div class="target-meta">
          <span class="pill ${topClass}">
            ${escapeHtml(topLabel)}
          </span>
        </div>
      </td>

      <td>
        ${formatNumber(
          row.topTargetProbabilityPercent,
          1
        )}%
      </td>

      <td>
        ${fallbackHtml}
      </td>

      <td>
        <button
          class="details-button"
          data-context="${escapeHtml(
            row.contextId
          )}"
          aria-expanded="false"
          type="button"
        >
          Show
          ${targets.length}
          target${
            targets.length === 1
              ? ""
              : "s"
          }
        </button>
      </td>
    </tr>

    <tr
      class="details-row"
      data-details="${escapeHtml(
        row.contextId
      )}"
      hidden
    >
      <td colspan="8">
        <div class="target-details">
          ${targetDetailsHtml(targets)}
        </div>
      </td>
    </tr>
  `;
}

function attachDetailsListeners() {
  document
    .querySelectorAll(".details-button")
    .forEach((button) => {
      button.addEventListener(
        "click",
        () => {
          const contextId =
            button.dataset.context;

          const escapedContextId =
            CSS.escape(contextId);

          const detail =
            document.querySelector(
              `[data-details="${escapedContextId}"]`
            );

          if (!detail) {
            return;
          }

          const open = detail.hidden;

          detail.hidden = !open;

          button.setAttribute(
            "aria-expanded",
            String(open)
          );

          const targetCount =
            detail.querySelectorAll(
              ".target-card"
            ).length;

          button.textContent =
            open
              ? "Hide targets"
              : (
                  `Show ${targetCount} ` +
                  `target${
                    targetCount === 1
                      ? ""
                      : "s"
                  }`
                );
        }
      );
    });
}

function render() {
  if (!state.data) {
    return;
  }

  const allRows = currentViews();
  const filteredRows =
    filteredCurrentRows();

  const visibleRows =
    filteredRows.slice(
      0,
      state.visibleCount
    );

  els.body.innerHTML =
    visibleRows
      .map(rankingRowHtml)
      .join("");

  const season = effectiveSeason();
  const time = effectiveTime();

  const selectedName =
    state.viewer === "team"
      ? "Team overall"
      : state.viewer;

  const hasSearch =
    state.search.trim().length > 0;

  els.empty.hidden =
    filteredRows.length > 0;

  els.selectedView.textContent =
    selectedName;

  if (hasSearch) {
    els.title.textContent =
      `${filteredRows.length} matching ` +
      `spot${
        filteredRows.length === 1
          ? ""
          : "s"
      } — ${selectedName}`;
  } else {
    els.title.textContent =
      `${allRows.length} ranked ` +
      `spot${
        allRows.length === 1
          ? ""
          : "s"
      } — ${selectedName}`;
  }

  const filterText =
    `${season} · ` +
    `${
      time === "All"
        ? "All times"
        : titleCase(time)
    }`;

  const modeText =
    state.autoFilter
      ? "live game context"
      : "manual filters";

  els.explanation.textContent =
    state.viewer === "team"
      ? (
          `Showing all ${filterText} results ` +
          `in descending score order via ` +
          `${modeText}. Team view values ` +
          `uncaught evolution families with ` +
          `the Unique Species bonus and ` +
          `already-owned team families at ` +
          `their normal base points.`
        )
      : state.data.meta
          .playerContextExclusionEnabled
        ? (
            `Showing all ${filterText} results ` +
            `in descending score order via ` +
            `${modeText}. Player view removes ` +
            `every context containing an ` +
            `evolution family already caught ` +
            `by this player, then ranks the ` +
            `remaining spots.`
          )
        : (
            `Showing all ${filterText} results ` +
            `in descending score order via ` +
            `${modeText}. Player view keeps ` +
            `all routes and reduces personally ` +
            `duplicated evolution families to ` +
            `the configured duplicate value.`
          );

  updatePaginationControls(
    visibleRows.length,
    filteredRows.length
  );

  attachDetailsListeners();
}

async function init() {
  try {
    ensurePaginationControls();

    const response = await fetch(
      "data/strategy.json",
      {
        cache: "no-store",
      }
    );

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`
      );
    }

    state.data =
      await response.json();

    els.viewer.innerHTML =
      `
        <option value="team">
          Team overall
        </option>
      ` +
      state.data.players
        .map((player) => {
          return `
            <option value="${escapeHtml(
              player
            )}">
              ${escapeHtml(player)}
            </option>
          `;
        })
        .join("");

    state.autoFilter =
      state.data.meta.liveFilter
        ?.defaultEnabled !== false;

    refreshLiveContext();

    state.manualSeason =
      state.liveSeason;

    state.manualTime =
      state.liveTime;

    updateFilterControls();

    els.caughtFamilies.textContent =
      state.data.meta
        .teamCaughtFamilyCount;

    els.lastUpdate.textContent =
      new Date(
        state.data.meta.generatedAtUtc
      ).toLocaleString();

    els.footerMeta.textContent =
      `${state.data.meta.playerCount} players ` +
      `· ` +
      `${state.data.meta.routeContextCount} ` +
      `route contexts`;

    if (els.subtitle) {
      els.subtitle.textContent =
        "All team and player-specific " +
        "horde spots, ranked from " +
        "highest to lowest score.";
    }

    els.badge.textContent =
      "Strategy data loaded";

    els.badge.classList.add("ok");

    render();

    state.clockTimer =
      window.setInterval(
        () => refreshLiveContext(),
        1000
      );
  } catch (error) {
    console.error(error);

    els.badge.textContent =
      "Strategy data unavailable";

    els.badge.classList.add("error");

    els.empty.hidden = false;

    els.empty.textContent =
      "The generated strategy file " +
      "could not be loaded. Check the " +
      "latest GitHub Actions run.";

    updatePaginationControls(0, 0);
  }
}

els.viewer.addEventListener(
  "change",
  (event) => {
    state.viewer =
      event.target.value;

    resetVisibleCount();
    render();
  }
);

els.season.addEventListener(
  "change",
  (event) => {
    state.manualSeason =
      event.target.value;

    if (!state.autoFilter) {
      resetVisibleCount();
      render();
    }
  }
);

els.time.addEventListener(
  "change",
  (event) => {
    state.manualTime =
      event.target.value;

    if (!state.autoFilter) {
      resetVisibleCount();
      render();
    }
  }
);

els.search.addEventListener(
  "input",
  (event) => {
    state.search =
      event.target.value;

    resetVisibleCount();
    render();
  }
);

els.liveFilterToggle.addEventListener(
  "click",
  () => {
    state.autoFilter =
      !state.autoFilter;

    resetVisibleCount();
    updateFilterControls();
    render();
  }
);

els.methodButton.addEventListener(
  "click",
  () => {
    els.methodPanel.hidden =
      !els.methodPanel.hidden;

    els.methodButton.textContent =
      els.methodPanel.hidden
        ? "How scoring works"
        : "Hide scoring method";
  }
);

init();

function combinationLabelInfo(combinationCount) {
  const count = Number(combinationCount);

  if (!Number.isFinite(count) || count < 1) {
    return null;
  }

  const text =
    count === 1
      ? "1 S/T Combination"
      : `${count} S/T Combinations`;

  if (count === 1) {
    return { text, cssClass: "combination-red" };
  }

  if (count === 2) {
    return { text, cssClass: "combination-orange" };
  }

  if (count === 3 || count === 4) {
    return { text, cssClass: "combination-yellow" };
  }

  return { text, cssClass: "combination-green" };
}