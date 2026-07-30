#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any


SEASONS = (
    "Summer",
    "Autumn",
    "Winter",
    "Spring",
)

TIMES = (
    "morning",
    "day",
    "night",
)

EXPECTED_VIEW_KEYS = (
    "All|All",
    "All|morning",
    "All|day",
    "All|night",
    "Summer|All",
    "Summer|morning",
    "Summer|day",
    "Summer|night",
    "Autumn|All",
    "Autumn|morning",
    "Autumn|day",
    "Autumn|night",
    "Winter|All",
    "Winter|morning",
    "Winter|day",
    "Winter|night",
    "Spring|All",
    "Spring|morning",
    "Spring|day",
    "Spring|night",
)

ALLOWED_SCORE_MULTIPLIERS = (
    1.0,
    1.1,
    1.25,
    1.5,
    2.0,
)

ALLOWED_TARGET_STATUSES = {
    "new_team_unique",
    "team_already_unique",
    "personal_duplicate",
}

FLOAT_TOLERANCE = 1e-6


class ValidationError(ValueError):
    """Raised when generated site data is invalid."""


def fail(message: str) -> None:
    raise ValidationError(message)


def require(
    condition: bool,
    message: str,
) -> None:
    if not condition:
        fail(message)


def require_dict(
    value: Any,
    label: str,
) -> dict[str, Any]:
    require(
        isinstance(value, dict),
        f"{label} must be an object",
    )

    return value


def require_list(
    value: Any,
    label: str,
) -> list[Any]:
    require(
        isinstance(value, list),
        f"{label} must be an array",
    )

    return value


def require_string(
    value: Any,
    label: str,
    *,
    allow_empty: bool = False,
) -> str:
    require(
        isinstance(value, str),
        f"{label} must be a string",
    )

    if not allow_empty:
        require(
            bool(value.strip()),
            f"{label} must not be empty",
        )

    return value


def require_number(
    value: Any,
    label: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    require(
        isinstance(value, (int, float))
        and not isinstance(value, bool),
        f"{label} must be numeric",
    )

    number = float(value)

    require(
        math.isfinite(number),
        f"{label} must be finite",
    )

    if minimum is not None:
        require(
            number >= minimum,
            f"{label} must be >= {minimum}",
        )

    if maximum is not None:
        require(
            number <= maximum,
            f"{label} must be <= {maximum}",
        )

    return number


def almost_equal(
    left: float,
    right: float,
) -> bool:
    return math.isclose(
        left,
        right,
        rel_tol=1e-9,
        abs_tol=FLOAT_TOLERANCE,
    )


def parse_iso_datetime(
    value: Any,
    label: str,
) -> datetime:
    text = require_string(
        value,
        label,
    )

    try:
        return datetime.fromisoformat(
            text.replace(
                "Z",
                "+00:00",
            )
        )
    except ValueError as exc:
        fail(
            f"{label} is not a valid "
            f"ISO-8601 datetime: {exc}"
        )


def validate_meta(
    data: dict[str, Any],
) -> tuple[int, bool]:
    meta = require_dict(
        data.get("meta"),
        "meta",
    )

    # The all-results version must no longer
    # depend on a Top-N limit.
    require(
        "topN" not in meta,
        "meta.topN is still present; "
        "remove the Top-N limit from "
        "build_dashboard.py",
    )

    parse_iso_datetime(
        meta.get("generatedAtUtc"),
        "meta.generatedAtUtc",
    )

    player_count = int(
        require_number(
            meta.get("playerCount"),
            "meta.playerCount",
            minimum=1,
        )
    )

    route_context_count = int(
        require_number(
            meta.get("routeContextCount"),
            "meta.routeContextCount",
            minimum=1,
        )
    )

    active_season = require_string(
        meta.get("activeSeason"),
        "meta.activeSeason",
    )

    require(
        active_season in {*SEASONS, "All"},
        "meta.activeSeason has unsupported "
        f"value {active_season!r}",
    )

    active_time = require_string(
        meta.get("activeTimeOfDay"),
        "meta.activeTimeOfDay",
    )

    require(
        active_time in {*TIMES, "All"},
        "meta.activeTimeOfDay has unsupported "
        f"value {active_time!r}",
    )

    require_string(
        meta.get("gameTimeAtBuild"),
        "meta.gameTimeAtBuild",
    )

    require_string(
        meta.get("rankingMode"),
        "meta.rankingMode",
    )

    require_number(
        meta.get("teamCaughtFamilyCount"),
        "meta.teamCaughtFamilyCount",
        minimum=0,
    )

    require_number(
        meta.get("uniqueSpeciesBonus"),
        "meta.uniqueSpeciesBonus",
        minimum=0,
    )

    require_number(
        meta.get("duplicatePoints"),
        "meta.duplicatePoints",
        minimum=0,
    )

    exclusion_enabled = (
        meta.get(
            "playerContextExclusionEnabled"
        )
    )

    require(
        isinstance(
            exclusion_enabled,
            bool,
        ),
        "meta.playerContextExclusionEnabled "
        "must be boolean",
    )

    require_string(
        meta.get(
            "playerContextExclusionRule"
        ),
        "meta.playerContextExclusionRule",
    )

    require_list(
        meta.get("warnings"),
        "meta.warnings",
    )

    expected_adjustments = {
        "1": 2.0,
        "2": 1.5,
        "3": 1.25,
        "4": 1.1,
        "default": 1.0,
    }

    adjustments = require_dict(
        meta.get(
            "scoreAdjustmentByCombinationCount"
        ),
        "meta.scoreAdjustmentByCombinationCount",
    )

    require(
        adjustments == expected_adjustments,
        "meta.scoreAdjustmentByCombinationCount "
        "does not match the current scoring rules",
    )

    live_filter = require_dict(
        meta.get("liveFilter"),
        "meta.liveFilter",
    )

    require_string(
        live_filter.get("timezone"),
        "meta.liveFilter.timezone",
    )

    require(
        isinstance(
            live_filter.get("defaultEnabled"),
            bool,
        ),
        "meta.liveFilter.defaultEnabled "
        "must be boolean",
    )

    day_starts = require_list(
        live_filter.get(
            "gameDayStartHoursLocal"
        ),
        "meta.liveFilter."
        "gameDayStartHoursLocal",
    )

    require(
        bool(day_starts),
        "meta.liveFilter."
        "gameDayStartHoursLocal is empty",
    )

    for index, value in enumerate(
        day_starts
    ):
        require_number(
            value,
            "meta.liveFilter."
            "gameDayStartHoursLocal"
            f"[{index}]",
            minimum=0,
            maximum=23,
        )

    require_number(
        live_filter.get(
            "realSecondsPerGameMinute"
        ),
        "meta.liveFilter."
        "realSecondsPerGameMinute",
        minimum=1,
    )

    time_windows = require_dict(
        live_filter.get("timeWindows"),
        "meta.liveFilter.timeWindows",
    )

    for time_name in TIMES:
        window = require_dict(
            time_windows.get(time_name),
            "meta.liveFilter.timeWindows."
            f"{time_name}",
        )

        require_string(
            window.get("label"),
            "meta.liveFilter.timeWindows."
            f"{time_name}.label",
        )

        require_string(
            window.get("start"),
            "meta.liveFilter.timeWindows."
            f"{time_name}.start",
        )

        require_string(
            window.get("end"),
            "meta.liveFilter.timeWindows."
            f"{time_name}.end",
        )

    rotation = require_dict(
        live_filter.get("seasonRotation"),
        "meta.liveFilter.seasonRotation",
    )

    parse_iso_datetime(
        rotation.get("anchorUtc"),
        "meta.liveFilter."
        "seasonRotation.anchorUtc",
    )

    require_string(
        rotation.get("anchorLocal"),
        "meta.liveFilter."
        "seasonRotation.anchorLocal",
    )

    require(
        rotation.get("anchorSeason")
        == "Summer",
        "Season rotation must start "
        "with Summer",
    )

    require(
        rotation.get(
            "beforeAnchorSeason"
        )
        == "Autumn",
        "Season before the anchor "
        "must be Autumn",
    )

    require(
        rotation.get("seasonOrder")
        == list(SEASONS),
        "Season order must be "
        "Summer, Autumn, Winter, Spring",
    )

    require_number(
        rotation.get("intervalDays"),
        "meta.liveFilter."
        "seasonRotation.intervalDays",
        minimum=1,
    )

    require(
        player_count >= 1,
        "At least one player is required",
    )

    return (
        route_context_count,
        exclusion_enabled,
    )


def validate_target(
    target: Any,
    label: str,
) -> None:
    target = require_dict(
        target,
        label,
    )

    require_string(
        target.get("species"),
        f"{label}.species",
    )

    require_string(
        target.get("family"),
        f"{label}.family",
    )

    require_number(
        target.get("basePoints"),
        f"{label}.basePoints",
        minimum=0,
    )

    require_number(
        target.get("effectivePoints"),
        f"{label}.effectivePoints",
        minimum=0,
    )

    status = require_string(
        target.get("status"),
        f"{label}.status",
    )

    require(
        status
        in ALLOWED_TARGET_STATUSES,
        f"{label}.status has unsupported "
        f"value {status!r}",
    )

    require_number(
        target.get(
            "hordeProbabilityPercent"
        ),
        f"{label}."
        "hordeProbabilityPercent",
        minimum=0,
        maximum=100,
    )

    require_number(
        target.get(
            "shinyCheckSharePercent"
        ),
        f"{label}."
        "shinyCheckSharePercent",
        minimum=0,
        maximum=100,
    )

    require_number(
        target.get("weightedHordeSize"),
        f"{label}.weightedHordeSize",
        minimum=0,
    )

    multiplier = require_number(
        target.get("scoreMultiplier"),
        f"{label}.scoreMultiplier",
        minimum=1,
    )

    require(
        any(
            almost_equal(
                multiplier,
                allowed,
            )
            for allowed
            in ALLOWED_SCORE_MULTIPLIERS
        ),
        f"{label}.scoreMultiplier has "
        f"unsupported value {multiplier}",
    )

    legacy = require_number(
        target.get("legacyContribution"),
        f"{label}.legacyContribution",
        minimum=0,
    )

    adjusted = require_number(
        target.get(
            "adjustedContribution"
        ),
        f"{label}.adjustedContribution",
        minimum=0,
    )

    require(
        almost_equal(
            adjusted,
            legacy * multiplier,
        ),
        f"{label}.adjustedContribution "
        "does not equal "
        "legacyContribution × "
        "scoreMultiplier",
    )

    # Exclusivity remains internal and must
    # not be exposed on the website.
    forbidden_keys = (
        "temporalExclusivity",
        "temporalDetails",
        "exclusivity",
    )

    for forbidden_key in forbidden_keys:
        require(
            forbidden_key not in target,
            f"{label}.{forbidden_key} "
            "must not be present in "
            "public site data",
        )


def validate_entry(
    entry: Any,
    context_id: str,
    label: str,
) -> None:
    entry = require_dict(
        entry,
        label,
    )

    require(
        entry.get("contextId")
        == context_id,
        f"{label}.contextId does not "
        "match its entries key",
    )

    required_string_fields = (
        "region",
        "locationId",
        "locationName",
        "displayName",
        "encounterType",
        "topTarget",
        "topTargetFamily",
        "allTargetsText",
    )

    for key in required_string_fields:
        require_string(
            entry.get(key),
            f"{label}.{key}",
        )

    season = require_string(
        entry.get("season"),
        f"{label}.season",
    )

    require(
        season in SEASONS,
        f"{label}.season has unsupported "
        f"value {season!r}",
    )

    time_name = require_string(
        entry.get("timeOfDay"),
        f"{label}.timeOfDay",
    )

    require(
        time_name in TIMES,
        f"{label}.timeOfDay has unsupported "
        f"value {time_name!r}",
    )

    adjusted_score = require_number(
        entry.get("adjustedScore"),
        f"{label}.adjustedScore",
        minimum=0,
    )

    legacy_score = require_number(
        entry.get("legacyScore"),
        f"{label}.legacyScore",
        minimum=0,
    )

    require(
        adjusted_score
        + FLOAT_TOLERANCE
        >= legacy_score,
        f"{label}.adjustedScore must "
        "not be lower than legacyScore",
    )

    require_number(
        entry.get("expectedChecks"),
        f"{label}.expectedChecks",
        minimum=0,
    )

    require_number(
        entry.get(
            "newUniqueSharePercent"
        ),
        f"{label}.newUniqueSharePercent",
        minimum=0,
        maximum=100,
    )

    require_number(
        entry.get("topTargetPoints"),
        f"{label}.topTargetPoints",
        minimum=0,
    )

    require_number(
        entry.get(
            "topTargetProbabilityPercent"
        ),
        f"{label}."
        "topTargetProbabilityPercent",
        minimum=0,
        maximum=100,
    )

    top_multiplier = require_number(
        entry.get(
            "topTargetScoreMultiplier"
        ),
        f"{label}."
        "topTargetScoreMultiplier",
        minimum=1,
    )

    require(
        any(
            almost_equal(
                top_multiplier,
                allowed,
            )
            for allowed
            in ALLOWED_SCORE_MULTIPLIERS
        ),
        f"{label}."
        "topTargetScoreMultiplier has "
        f"unsupported value "
        f"{top_multiplier}",
    )

    require_string(
        entry.get("fallbackTarget"),
        f"{label}.fallbackTarget",
        allow_empty=True,
    )

    fallback_points = entry.get(
        "fallbackPoints"
    )

    if fallback_points is not None:
        require_number(
            fallback_points,
            f"{label}.fallbackPoints",
            minimum=0,
        )

    targets = require_list(
        entry.get("targets"),
        f"{label}.targets",
    )

    require(
        bool(targets),
        f"{label}.targets must not "
        "be empty",
    )

    for index, target in enumerate(
        targets
    ):
        validate_target(
            target,
            f"{label}.targets[{index}]",
        )

    target_species = [
        target["species"]
        for target in targets
    ]

    require(
        entry["topTarget"]
        in target_species,
        f"{label}.topTarget is not "
        "present in targets",
    )

    adjusted_sum = sum(
        float(
            target[
                "adjustedContribution"
            ]
        )
        for target in targets
    )

    legacy_sum = sum(
        float(
            target[
                "legacyContribution"
            ]
        )
        for target in targets
    )

    require(
        almost_equal(
            adjusted_score,
            adjusted_sum,
        ),
        f"{label}.adjustedScore does "
        "not equal the sum of adjusted "
        "target contributions",
    )

    require(
        almost_equal(
            legacy_score,
            legacy_sum,
        ),
        f"{label}.legacyScore does "
        "not equal the sum of legacy "
        "target contributions",
    )

    forbidden_keys = (
        "topTargetExclusivity",
        "temporalExclusivity",
        "exclusivity",
    )

    for forbidden_key in forbidden_keys:
        require(
            forbidden_key not in entry,
            f"{label}.{forbidden_key} "
            "must not be present in "
            "public site data",
        )


def validate_sorted_view(
    view_ids: list[str],
    entries: dict[str, Any],
    label: str,
) -> None:
    previous_score: float | None = None

    for position, context_id in enumerate(
        view_ids,
        start=1,
    ):
        score = float(
            entries[context_id][
                "adjustedScore"
            ]
        )

        if previous_score is not None:
            require(
                score
                <= previous_score
                + FLOAT_TOLERANCE,
                f"{label} is not sorted "
                "by adjustedScore "
                "descending at position "
                f"{position}",
            )

        previous_score = score


def expected_ids_for_view(
    all_ids: list[str],
    entries: dict[str, Any],
    view_key: str,
) -> list[str]:
    season, time_name = (
        view_key.split(
            "|",
            1,
        )
    )

    return [
        context_id
        for context_id in all_ids
        if (
            season == "All"
            or entries[context_id][
                "season"
            ]
            == season
        )
        and (
            time_name == "All"
            or entries[context_id][
                "timeOfDay"
            ]
            == time_name
        )
    ]


def validate_bundle(
    bundle: Any,
    label: str,
    *,
    route_context_count: int,
    require_all_contexts: bool,
) -> int:
    bundle = require_dict(
        bundle,
        label,
    )

    entries = require_dict(
        bundle.get("entries"),
        f"{label}.entries",
    )

    views = require_dict(
        bundle.get("views"),
        f"{label}.views",
    )

    require(
        set(views)
        == set(EXPECTED_VIEW_KEYS),
        f"{label}.views does not "
        "contain exactly the expected "
        "20 filter views",
    )

    all_ids_raw = require_list(
        views.get("All|All"),
        f"{label}.views.All|All",
    )

    all_ids = [
        require_string(
            context_id,
            f"{label}.views.All|All"
            f"[{index}]",
        )
        for index, context_id
        in enumerate(all_ids_raw)
    ]

    require(
        bool(all_ids),
        f"{label}.views.All|All "
        "is empty",
    )

    require(
        len(all_ids)
        == len(set(all_ids)),
        f"{label}.views.All|All "
        "contains duplicate context IDs",
    )

    require(
        set(entries)
        == set(all_ids),
        f"{label}.entries must contain "
        "exactly the contexts from "
        "views.All|All",
    )

    if require_all_contexts:
        require(
            len(all_ids)
            == route_context_count,
            f"{label}.views.All|All "
            f"contains {len(all_ids)} "
            "contexts, but "
            "meta.routeContextCount is "
            f"{route_context_count}. "
            "The backend is probably "
            "still truncating the ranking.",
        )
    else:
        require(
            len(all_ids)
            <= route_context_count,
            f"{label}.views.All|All "
            "exceeds "
            "meta.routeContextCount",
        )

    for context_id in all_ids:
        validate_entry(
            entries[context_id],
            context_id,
            f"{label}.entries"
            f"[{context_id!r}]",
        )

    for view_key in EXPECTED_VIEW_KEYS:
        ids_raw = require_list(
            views.get(view_key),
            f"{label}.views.{view_key}",
        )

        ids = [
            require_string(
                context_id,
                f"{label}.views."
                f"{view_key}[{index}]",
            )
            for index, context_id
            in enumerate(ids_raw)
        ]

        require(
            len(ids)
            == len(set(ids)),
            f"{label}.views.{view_key} "
            "contains duplicate "
            "context IDs",
        )

        missing = [
            context_id
            for context_id in ids
            if context_id not in entries
        ]

        require(
            not missing,
            f"{label}.views.{view_key} "
            "references missing entries: "
            f"{missing[:5]}",
        )

        expected_ids = (
            expected_ids_for_view(
                all_ids,
                entries,
                view_key,
            )
        )

        require(
            ids == expected_ids,
            f"{label}.views.{view_key} "
            "is incomplete, incorrectly "
            "filtered, or out of order",
        )

        validate_sorted_view(
            ids,
            entries,
            f"{label}.views.{view_key}",
        )

    return len(all_ids)


def validate_players(
    data: dict[str, Any],
    expected_count: int,
) -> list[str]:
    players_raw = require_list(
        data.get("players"),
        "players",
    )

    players = [
        require_string(
            player,
            f"players[{index}]",
        )
        for index, player
        in enumerate(players_raw)
    ]

    require(
        len(players)
        == expected_count,
        "players length does not match "
        "meta.playerCount",
    )

    require(
        len(players)
        == len(set(players)),
        "players contains duplicate names",
    )

    return players


def validate_summaries(
    data: dict[str, Any],
    players: list[str],
) -> None:
    summaries = require_list(
        data.get("playerSummary"),
        "playerSummary",
    )

    require(
        len(summaries)
        == len(players),
        "playerSummary length does not "
        "match players length",
    )

    summary_players: list[str] = []

    for index, summary_raw in enumerate(
        summaries
    ):
        label = (
            f"playerSummary[{index}]"
        )

        summary = require_dict(
            summary_raw,
            label,
        )

        player = require_string(
            summary.get("player"),
            f"{label}.player",
        )

        summary_players.append(player)

        require_list(
            summary.get("caughtSpecies"),
            f"{label}.caughtSpecies",
        )

        require_number(
            summary.get(
                "caughtFamilyCount"
            ),
            f"{label}.caughtFamilyCount",
            minimum=0,
        )

        require_number(
            summary.get(
                "excludedContextCount"
            ),
            f"{label}."
            "excludedContextCount",
            minimum=0,
        )

        require_string(
            summary.get("topSpot"),
            f"{label}.topSpot",
            allow_empty=True,
        )

        require_string(
            summary.get("topTarget"),
            f"{label}.topTarget",
            allow_empty=True,
        )

        if (
            summary.get("topScore")
            is not None
        ):
            require_number(
                summary.get("topScore"),
                f"{label}.topScore",
                minimum=0,
            )

    require(
        summary_players == players,
        "playerSummary order or player "
        "names do not match players",
    )


def validate_team_checklist(
    data: dict[str, Any],
) -> None:
    checklist = require_list(
        data.get("teamChecklist"),
        "teamChecklist",
    )

    require(
        bool(checklist),
        "teamChecklist is empty",
    )

    for index, item_raw in enumerate(
        checklist
    ):
        label = (
            f"teamChecklist[{index}]"
        )

        item = require_dict(
            item_raw,
            label,
        )

        require_string(
            item.get("family"),
            f"{label}.family",
        )

        require(
            isinstance(
                item.get("caught"),
                bool,
            ),
            f"{label}.caught "
            "must be boolean",
        )

        require_list(
            item.get("owners"),
            f"{label}.owners",
        )

        require_list(
            item.get("members"),
            f"{label}.members",
        )

        if (
            item.get("basePoints")
            is not None
        ):
            require_number(
                item.get("basePoints"),
                f"{label}.basePoints",
                minimum=0,
            )


def load_json(
    path: Path,
) -> dict[str, Any]:
    require(
        path.is_file(),
        "Generated strategy file "
        f"does not exist: {path}",
    )

    try:
        data = json.loads(
            path.read_text(
                encoding="utf-8"
            )
        )
    except json.JSONDecodeError as exc:
        fail(
            "Generated strategy file "
            f"is invalid JSON: {exc}"
        )

    return require_dict(
        data,
        "root",
    )


def main() -> None:
    path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "web/data/strategy.json"
    )

    try:
        data = load_json(path)

        (
            route_context_count,
            exclusion_enabled,
        ) = validate_meta(data)

        player_count = int(
            data["meta"]["playerCount"]
        )

        players = validate_players(
            data,
            player_count,
        )

        rankings = require_dict(
            data.get("rankings"),
            "rankings",
        )

        team_count = validate_bundle(
            rankings.get("team"),
            "rankings.team",
            route_context_count=(
                route_context_count
            ),
            require_all_contexts=True,
        )

        player_bundles = require_dict(
            rankings.get("players"),
            "rankings.players",
        )

        require(
            set(player_bundles)
            == set(players),
            "rankings.players keys do "
            "not match players",
        )

        player_counts: list[int] = []

        for player in players:
            player_counts.append(
                validate_bundle(
                    player_bundles[
                        player
                    ],
                    "rankings.players"
                    f"[{player!r}]",
                    route_context_count=(
                        route_context_count
                    ),
                    require_all_contexts=(
                        not exclusion_enabled
                    ),
                )
            )

        validate_team_checklist(data)

        validate_summaries(
            data,
            players,
        )

    except ValidationError as exc:
        print(
            f"Validation failed: {exc}",
            file=sys.stderr,
        )

        raise SystemExit(1) from exc

    minimum_player_count = (
        min(player_counts)
        if player_counts
        else 0
    )

    maximum_player_count = (
        max(player_counts)
        if player_counts
        else 0
    )

    print(
        f"Validated all {team_count} "
        "team route contexts and "
        f"{len(players)} player rankings "
        f"({minimum_player_count}-"
        f"{maximum_player_count} "
        "contexts per player)."
    )


if __name__ == "__main__":
    main()
