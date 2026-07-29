(function attachShinyWarsClock(globalObject) {
  "use strict";

  function parseClockMinute(value) {
    const [hourText, minuteText] = String(value).split(":", 2);
    const hour = Number(hourText);
    const minute = Number(minuteText);
    if (!Number.isInteger(hour) || !Number.isInteger(minute) || hour < 0 || hour > 23 || minute < 0 || minute > 59) {
      throw new Error(`Invalid clock time: ${value}`);
    }
    return hour * 60 + minute;
  }

  function zonedParts(date, timeZone) {
    const formatter = new Intl.DateTimeFormat("en-GB", {
      timeZone,
      hourCycle: "h23",
      year: "numeric",
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
    });
    const values = Object.fromEntries(
      formatter.formatToParts(date)
        .filter(part => part.type !== "literal")
        .map(part => [part.type, Number(part.value)])
    );
    return values;
  }

  function classifyGameTime(gameMinute, windows) {
    for (const key of ["morning", "day", "night"]) {
      const entry = windows[key];
      if (!entry) continue;
      const start = parseClockMinute(entry.start);
      const end = parseClockMinute(entry.end);
      const matches = start <= end
        ? gameMinute >= start && gameMinute <= end
        : gameMinute >= start || gameMinute <= end;
      if (matches) {
        return {
          key,
          label: entry.label || key.charAt(0).toUpperCase() + key.slice(1),
        };
      }
    }
    throw new Error(`No configured time window contains minute ${gameMinute}`);
  }

  function gameClockAt(date, config) {
    const timeZone = config.timezone || "Europe/Berlin";
    const anchors = [...(config.gameDayStartHoursLocal || [2, 8, 14, 20])]
      .map(Number)
      .sort((a, b) => a - b);
    const realSecondsPerGameMinute = Number(config.realSecondsPerGameMinute || 15);
    if (!anchors.length || !Number.isFinite(realSecondsPerGameMinute) || realSecondsPerGameMinute <= 0) {
      throw new Error("Invalid game-clock configuration");
    }

    const local = zonedParts(date, timeZone);
    const localSeconds = local.hour * 3600 + local.minute * 60 + local.second;
    const anchorSeconds = anchors.map(hour => hour * 3600);
    const previousAnchors = anchorSeconds.filter(value => value <= localSeconds);
    const activeAnchor = previousAnchors.length
      ? previousAnchors[previousAnchors.length - 1]
      : anchorSeconds[anchorSeconds.length - 1] - 24 * 3600;
    const elapsedRealSeconds = localSeconds - activeAnchor;
    const gameMinute = Math.floor(elapsedRealSeconds / realSecondsPerGameMinute) % (24 * 60);
    const timeWindow = classifyGameTime(gameMinute, config.timeWindows || {});
    const gameHour = Math.floor(gameMinute / 60);
    const gameMinuteWithinHour = gameMinute % 60;

    return {
      gameMinute,
      gameTime: `${String(gameHour).padStart(2, "0")}:${String(gameMinuteWithinHour).padStart(2, "0")}`,
      timeOfDay: timeWindow.key,
      timeOfDayLabel: timeWindow.label,
      secondsUntilNextGameMinute: realSecondsPerGameMinute - (elapsedRealSeconds % realSecondsPerGameMinute),
      localDateTime: local,
    };
  }

  function seasonAt(date, rotation) {
    const order = [...(rotation.seasonOrder || [])];
    const anchorSeason = rotation.anchorSeason;
    const anchorUtc = new Date(rotation.anchorUtc);
    const intervalDays = Number(rotation.intervalDays || 7);
    if (!order.length || !order.includes(anchorSeason) || Number.isNaN(anchorUtc.getTime()) || intervalDays <= 0) {
      throw new Error("Invalid season-rotation configuration");
    }
    const intervalMs = intervalDays * 24 * 60 * 60 * 1000;
    const steps = Math.floor((date.getTime() - anchorUtc.getTime()) / intervalMs);
    const anchorIndex = order.indexOf(anchorSeason);
    return order[((anchorIndex + steps) % order.length + order.length) % order.length];
  }

  const api = { classifyGameTime, gameClockAt, parseClockMinute, seasonAt, zonedParts };
  globalObject.ShinyWarsClock = api;
  if (typeof module !== "undefined" && module.exports) {
    module.exports = api;
  }
})(typeof window !== "undefined" ? window : globalThis);
