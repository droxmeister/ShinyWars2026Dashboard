"use strict";

const assert = require("assert");
const fs = require("fs");
const vm = require("vm");

function fakeElement() {
  return {
    value: "",
    disabled: false,
    hidden: false,
    textContent: "",
    innerHTML: "",
    dataset: {},
    style: {},
    className: "",
    classList: {
      add() {},
      toggle() {},
    },
    setAttribute() {},
    addEventListener() {},
    append() {},
    appendChild() {},
    insertBefore() {},
    querySelectorAll() { return []; },
    scrollIntoView() {},
  };
}

const elements = new Map();
function getElement(selector) {
  if (!elements.has(selector)) {
    elements.set(selector, fakeElement());
  }
  return elements.get(selector);
}

const context = {
  console,
  Intl,
  Date,
  Number,
  String,
  Boolean,
  Array,
  Object,
  Math,
  Promise,
  setTimeout,
  clearTimeout,
  document: {
    querySelector: getElement,
    querySelectorAll() { return []; },
    createElement() { return fakeElement(); },
  },
  CSS: { escape: String },
  window: {
    requestAnimationFrame(callback) { callback(); },
    setInterval() { return 1; },
    clearInterval() {},
  },
};
context.globalThis = context;
vm.createContext(context);

let source = fs.readFileSync("web/app.js", "utf8");
source = source.replace(/\ninit\(\);\s*$/, "\n");
source += `\nglobalThis.__test = {\n  state,\n  currentViews,\n  setBestSpotsOnly,\n  topTargetDetails,\n  rankingScoreLabel,\n};\n`;
vm.runInContext(source, context, { filename: "app.js" });

const {
  state,
  currentViews,
  setBestSpotsOnly,
  rankingScoreLabel,
} = context.__test;
const bestTarget = {
  species: "Mismagius",
  family: "Misdreavus",
  status: "new_team_unique",
  hordeProbabilityPercent: 50,
  scoreMultiplier: 2,
  seasonTimeCombinationCount: 1,
  seasonTimeCombinationTotal: 2,
  adjustedContribution: 100,
  legacyContribution: 50,
  isBestAnnualFamilyContext: true,
};
const fallbackTarget = {
  species: "Golbat",
  family: "Zubat",
  status: "team_already_unique",
  hordeProbabilityPercent: 50,
  scoreMultiplier: 1,
  seasonTimeCombinationCount: 12,
  seasonTimeCombinationTotal: 12,
  adjustedContribution: 25,
  legacyContribution: 25,
  isBestAnnualFamilyContext: false,
};
const nonBestTarget = { ...bestTarget, species: "Banette", family: "Shuppet", isBestAnnualFamilyContext: false };

const bestRow = {
  contextId: "autumn-night-best",
  displayName: "Unova — Test Route",
  region: "Unova",
  locationName: "Test Route",
  locationId: "123",
  encounterType: "Grass",
  season: "Autumn",
  timeOfDay: "night",
  adjustedScore: 125,
  legacyScore: 75,
  topTarget: "Mismagius",
  topTargetFamily: "Misdreavus",
  topTargetPoints: 40,
  topTargetProbabilityPercent: 50,
  topTargetScoreMultiplier: 2,
  fallbackTarget: "Golbat",
  fallbackPoints: 10,
  allTargetsText: "Mismagius Golbat",
  targets: [bestTarget, fallbackTarget],
};
const nonBestRow = {
  ...bestRow,
  contextId: "autumn-night-normal",
  topTarget: "Banette",
  topTargetFamily: "Shuppet",
  targets: [nonBestTarget, fallbackTarget],
};
const summerRow = {
  ...bestRow,
  contextId: "summer-night-best",
  season: "Summer",
};

state.data = {
  meta: {
    activeSeason: "Autumn",
    activeTimeOfDay: "night",
    gameTimeAtBuild: "22:00",
    liveFilter: null,
    timeSimulation: { enabled: false },
    playerContextExclusionEnabled: false,
  },
  rankings: {
    team: {
      entries: {
        [bestRow.contextId]: bestRow,
        [nonBestRow.contextId]: nonBestRow,
        [summerRow.contextId]: summerRow,
      },
      views: {
        "Autumn|night": [bestRow.contextId, nonBestRow.contextId],
        "Summer|night": [summerRow.contextId],
      },
      bestSpots: [
        {
          contextId: "synthetic-best-row",
          targets: [bestTarget],
        },
      ],
    },
    players: {},
  },
};
assert.strictEqual(rankingScoreLabel(), "Adjusted Score");
state.data.meta.temporalExclusivityScoreMultiplierEnabled = false;
assert.strictEqual(rankingScoreLabel(), "Legacy Score");
state.data.meta.temporalExclusivityScoreMultiplierEnabled = true;

state.viewer = "team";
state.autoFilter = false;
state.manualSeason = "Autumn";
state.manualTime = "night";

assert.deepStrictEqual(
  Array.from(currentViews(), row => row.contextId),
  [bestRow.contextId, nonBestRow.contextId]
);

setBestSpotsOnly(true);
assert.strictEqual(state.autoFilter, false);
assert.strictEqual(state.manualSeason, "Autumn");
assert.strictEqual(state.manualTime, "night");
const filtered = currentViews();
assert.deepStrictEqual(
  Array.from(filtered, row => row.contextId),
  [bestRow.contextId]
);
assert.strictEqual(filtered[0].targets.length, 2);
assert.strictEqual(filtered[0].fallbackTarget, "Golbat");
assert.notStrictEqual(filtered[0].contextId, "synthetic-best-row");

state.manualSeason = "Summer";
assert.deepStrictEqual(
  Array.from(currentViews(), row => row.contextId),
  [summerRow.contextId]
);

setBestSpotsOnly(false);
assert.strictEqual(state.manualSeason, "Summer");
assert.strictEqual(state.manualTime, "night");

console.log("app best-spots filter tests passed");
