const assert = require("node:assert/strict");
const { gameClockAt, seasonAt } = require("../web/live-time.js");

const config = {
  timezone: "Europe/Berlin",
  gameDayStartHoursLocal: [2, 8, 14, 20],
  realSecondsPerGameMinute: 15,
  timeWindows: {
    morning: { label: "Morning", start: "04:00", end: "10:59" },
    day: { label: "Day", start: "11:00", end: "20:59" },
    night: { label: "Night", start: "21:00", end: "03:59" },
  },
};

assert.deepEqual(
  { time: gameClockAt(new Date("2026-07-29T00:00:00Z"), config).gameTime, window: gameClockAt(new Date("2026-07-29T00:00:00Z"), config).timeOfDay },
  { time: "00:00", window: "night" },
);
assert.deepEqual(
  { time: gameClockAt(new Date("2026-07-29T01:00:00Z"), config).gameTime, window: gameClockAt(new Date("2026-07-29T01:00:00Z"), config).timeOfDay },
  { time: "04:00", window: "morning" },
);
assert.deepEqual(
  { time: gameClockAt(new Date("2026-07-29T02:45:00Z"), config).gameTime, window: gameClockAt(new Date("2026-07-29T02:45:00Z"), config).timeOfDay },
  { time: "11:00", window: "day" },
);
assert.deepEqual(
  { time: gameClockAt(new Date("2026-07-29T05:15:00Z"), config).gameTime, window: gameClockAt(new Date("2026-07-29T05:15:00Z"), config).timeOfDay },
  { time: "21:00", window: "night" },
);

const rotation = {
  anchorUtc: "2026-07-31T22:01:00Z",
  anchorSeason: "Summer",
  beforeAnchorSeason: "Autumn",
  seasonOrder: ["Summer", "Autumn", "Winter", "Spring"],
  intervalDays: 7,
};
assert.equal(seasonAt(new Date("2026-07-29T19:45:00Z"), rotation), "Autumn");
assert.equal(seasonAt(new Date("2026-07-31T22:00:00Z"), rotation), "Autumn");
assert.equal(seasonAt(new Date("2026-07-31T22:01:00Z"), rotation), "Summer");
assert.equal(seasonAt(new Date("2026-08-07T22:01:00Z"), rotation), "Autumn");

console.log("live-time tests passed");
