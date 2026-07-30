#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from datetime import datetime
from pathlib import Path
from typing import Any

TOLERANCE = 1e-6
SEASONS = {"Summer", "Autumn", "Winter", "Spring"}
MULTIPLIERS = {1: 2.0, 2: 1.5, 3: 1.25, 4: 1.1}


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def obj(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def array(value: Any, label: str) -> list[Any]:
    require(isinstance(value, list), f"{label} must be an array")
    return value


def number(value: Any, label: str) -> float:
    require(
        isinstance(value, (int, float)) and not isinstance(value, bool),
        f"{label} must be numeric",
    )
    result = float(value)
    require(math.isfinite(result), f"{label} must be finite")
    return result


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=TOLERANCE)


def iso_datetime(value: Any, label: str) -> datetime:
    require(isinstance(value, str) and value.strip(), f"{label} must be a non-empty string")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValidationError(f"{label} must be a valid ISO-8601 datetime") from exc
    require(parsed.tzinfo is not None, f"{label} must include timezone information")
    return parsed


def expected_multiplier(remaining_count: int) -> float:
    return MULTIPLIERS.get(remaining_count, 1.0)


def validate_target(target_raw: Any, label: str) -> None:
    target = obj(target_raw, label)
    require(bool(str(target.get("species", "")).strip()), f"{label}.species is empty")
    require(bool(str(target.get("family", "")).strip()), f"{label}.family is empty")

    remaining_value = number(
        target.get("seasonTimeCombinationCount"),
        f"{label}.seasonTimeCombinationCount",
    )
    total_value = number(
        target.get("seasonTimeCombinationTotal"),
        f"{label}.seasonTimeCombinationTotal",
    )
    require(remaining_value.is_integer(), f"{label} remaining combinations must be an integer")
    require(total_value.is_integer(), f"{label} total combinations must be an integer")
    remaining = int(remaining_value)
    total = int(total_value)
    require(0 <= remaining <= total <= 12, f"{label} must have 0 <= remaining <= total <= 12")
    require(total >= 1, f"{label} total combinations must be at least 1")

    multiplier = number(target.get("scoreMultiplier"), f"{label}.scoreMultiplier")
    require(
        close(multiplier, expected_multiplier(remaining)),
        f"{label}.scoreMultiplier {multiplier} does not match {remaining}/{total} combinations",
    )

    legacy = number(target.get("legacyContribution"), f"{label}.legacyContribution")
    adjusted = number(target.get("adjustedContribution"), f"{label}.adjustedContribution")
    require(legacy >= 0 and adjusted >= 0, f"{label} contributions must not be negative")
    require(
        close(adjusted, legacy * multiplier),
        f"{label}.adjustedContribution must equal legacyContribution × scoreMultiplier",
    )

    marker = target.get("isBestAnnualFamilyContext")
    require(
        isinstance(marker, bool),
        f"{label}.isBestAnnualFamilyContext must be boolean",
    )


def validate_entry(context_id: str, entry_raw: Any, label: str) -> None:
    entry = obj(entry_raw, label)
    require(entry.get("contextId") == context_id, f"{label}.contextId does not match")
    require(entry.get("season") in SEASONS, f"{label}.season is invalid")

    targets = array(entry.get("targets"), f"{label}.targets")
    require(targets, f"{label}.targets must not be empty")
    for index, target in enumerate(targets):
        validate_target(target, f"{label}.targets[{index}]")

    target_by_species = {str(target["species"]): target for target in targets}
    top_name = str(entry.get("topTarget", ""))
    require(top_name in target_by_species, f"{label}.topTarget is not present in targets")
    top_multiplier = number(
        entry.get("topTargetScoreMultiplier"),
        f"{label}.topTargetScoreMultiplier",
    )
    require(
        close(top_multiplier, float(target_by_species[top_name]["scoreMultiplier"])),
        f"{label}.topTargetScoreMultiplier does not match the top target",
    )

    legacy_score = number(entry.get("legacyScore"), f"{label}.legacyScore")
    adjusted_score = number(entry.get("adjustedScore"), f"{label}.adjustedScore")
    annual_adjusted_score = number(
        entry.get("annualAdjustedScore"),
        f"{label}.annualAdjustedScore",
    )
    require(
        annual_adjusted_score >= 0,
        f"{label}.annualAdjustedScore must not be negative",
    )
    require(
        close(legacy_score, sum(float(target["legacyContribution"]) for target in targets)),
        f"{label}.legacyScore does not match target contributions",
    )
    require(
        close(adjusted_score, sum(float(target["adjustedContribution"]) for target in targets)),
        f"{label}.adjustedScore does not match target contributions",
    )


def validate_best_spots(
    best_spots_raw: Any,
    entries: dict[str, Any],
    marker_contexts: dict[str, str],
    label: str,
) -> list[dict[str, Any]]:
    best_spots = array(best_spots_raw, label)
    require(
        len(best_spots) == len(marker_contexts),
        f"{label} must contain exactly one row per annual-best evolution family",
    )

    seen_families: set[str] = set()
    previous_score: float | None = None
    for index, best_raw in enumerate(best_spots):
        best = obj(best_raw, f"{label}[{index}]")
        best_id = str(best.get("contextId", ""))
        require(best_id, f"{label}[{index}].contextId is empty")
        validate_entry(best_id, best, f"{label}[{index}]")
        require(
            best.get("isBestSpotEntry") is True,
            f"{label}[{index}].isBestSpotEntry must be true",
        )

        source_context_id = str(best.get("sourceContextId", ""))
        require(
            source_context_id in entries,
            f"{label}[{index}] references missing source context {source_context_id!r}",
        )
        source = entries[source_context_id]
        for field in (
            "region",
            "locationId",
            "encounterType",
            "season",
            "timeOfDay",
        ):
            require(
                best.get(field) == source.get(field),
                f"{label}[{index}].{field} does not match its source context",
            )

        targets = best["targets"]
        require(
            len(targets) == 1,
            f"{label}[{index}] must contain exactly one evolution-family target",
        )
        target = targets[0]
        family = str(target["family"])
        require(
            target["isBestAnnualFamilyContext"] is True,
            f"{label}[{index}] target must carry the annual-best marker",
        )
        require(
            family not in seen_families,
            f"{label} contains duplicate evolution family {family!r}",
        )
        seen_families.add(family)
        require(
            best.get("bestSpotFamily") == family,
            f"{label}[{index}].bestSpotFamily does not match the target family",
        )
        require(
            best.get("topTargetFamily") == family,
            f"{label}[{index}].topTargetFamily does not match the target family",
        )
        require(
            marker_contexts.get(family) == source_context_id,
            f"{label}[{index}] does not use the marked annual-best source context",
        )

        source_marked_targets = [
            source_target
            for source_target in source["targets"]
            if str(source_target["family"]) == family
            and source_target["isBestAnnualFamilyContext"]
        ]
        require(
            len(source_marked_targets) == 1,
            f"{label}[{index}] source context does not contain exactly one matching marker",
        )
        require(
            close(
                float(target["adjustedContribution"]),
                float(source_marked_targets[0]["adjustedContribution"]),
            ),
            f"{label}[{index}] score differs from its marked source target",
        )
        require(
            close(
                float(best["annualAdjustedScore"]),
                float(source["annualAdjustedScore"]),
            ),
            f"{label}[{index}] annual context score differs from its source context",
        )

        score = number(best.get("adjustedScore"), f"{label}[{index}].adjustedScore")
        if previous_score is not None:
            require(
                score <= previous_score + TOLERANCE,
                f"{label} is not sorted by descending expected contribution",
            )
        previous_score = score

    require(
        seen_families == set(marker_contexts),
        f"{label} evolution families do not match annual-best markers",
    )
    return best_spots


def validate_view(
    view_ids_raw: Any,
    entries: dict[str, Any],
    label: str,
    *,
    eligible_seasons: set[str],
    view_name: str,
) -> list[str]:
    view_ids = array(view_ids_raw, label)
    require(len(view_ids) == len(set(view_ids)), f"{label} contains duplicates")
    season_filter, time_filter = view_name.split("|", 1)
    previous: float | None = None

    for position, context_id in enumerate(view_ids, start=1):
        require(context_id in entries, f"{label} references missing {context_id!r}")
        entry = entries[context_id]
        if season_filter == "All":
            require(entry["season"] in eligible_seasons, f"{label} contains expired season {entry['season']}")
        else:
            require(entry["season"] == season_filter, f"{label} contains wrong season")
        if time_filter != "All":
            require(entry["timeOfDay"] == time_filter, f"{label} contains wrong time window")

        score = number(entry.get("adjustedScore"), f"{label}[{position}].adjustedScore")
        if previous is not None:
            require(score <= previous + TOLERANCE, f"{label} is not sorted descending")
        previous = score

    return view_ids


def validate_bundle(
    bundle_raw: Any,
    label: str,
    *,
    eligible_seasons: set[str],
    route_context_count: int,
    recommendation_context_count: int | None = None,
    require_complete_annual_markers: bool = False,
) -> tuple[int, dict[str, str]]:
    bundle = obj(bundle_raw, label)
    entries = obj(bundle.get("entries"), f"{label}.entries")
    views = obj(bundle.get("views"), f"{label}.views")
    require("All|All" in views, f"{label}.views must contain All|All")

    family_targets: dict[str, list[tuple[str, dict[str, Any]]]] = {}
    marker_contexts: dict[str, str] = {}
    for context_id, entry in entries.items():
        validate_entry(context_id, entry, f"{label}.entries[{context_id!r}]")
        for target in entry["targets"]:
            family = str(target["family"])
            family_targets.setdefault(family, []).append((context_id, target))
            if target["isBestAnnualFamilyContext"]:
                require(
                    family not in marker_contexts,
                    f"{label} contains more than one annual-best marker for {family!r}",
                )
                marker_contexts[family] = context_id

    if require_complete_annual_markers:
        require(
            set(marker_contexts) == set(family_targets),
            f"{label} must contain exactly one annual-best marker per evolution family",
        )

    for family, context_id in marker_contexts.items():
        candidates = family_targets[family]
        maximum_context_score = max(
            float(entries[candidate_context]["annualAdjustedScore"])
            for candidate_context, _ in candidates
        )
        require(
            close(
                float(entries[context_id]["annualAdjustedScore"]),
                maximum_context_score,
            ),
            f"{label} annual-best marker for {family!r} is not on a "
            "maximum full-context annual score",
        )

    validate_best_spots(
        bundle.get("bestSpots"),
        entries,
        marker_contexts,
        f"{label}.bestSpots",
    )

    all_ids: list[str] = []
    for view_name, view_ids in views.items():
        ids = validate_view(
            view_ids,
            entries,
            f"{label}.views[{view_name!r}]",
            eligible_seasons=eligible_seasons,
            view_name=view_name,
        )
        if view_name == "All|All":
            all_ids = ids

    require(len(entries) <= route_context_count, f"{label}.entries exceeds routeContextCount")
    if recommendation_context_count is not None:
        require(
            len(all_ids) == recommendation_context_count,
            f"{label}.All|All has {len(all_ids)} contexts, expected {recommendation_context_count}",
        )
    return len(all_ids), marker_contexts


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "web/data/strategy.json")
    try:
        require(path.is_file(), f"Strategy file does not exist: {path}")
        data = obj(json.loads(path.read_text(encoding="utf-8")), "root")
        meta = obj(data.get("meta"), "meta")
        generated_at = iso_datetime(meta.get("generatedAtUtc"), "meta.generatedAtUtc")
        calculation_at = iso_datetime(meta.get("calculationAtUtc"), "meta.calculationAtUtc")
        simulation = obj(meta.get("timeSimulation"), "meta.timeSimulation")
        simulation_enabled = simulation.get("enabled")
        require(isinstance(simulation_enabled, bool), "meta.timeSimulation.enabled must be boolean")
        simulation_effective = iso_datetime(
            simulation.get("effectiveAtUtc"),
            "meta.timeSimulation.effectiveAtUtc",
        )
        simulation_build = iso_datetime(
            simulation.get("actualBuildAtUtc"),
            "meta.timeSimulation.actualBuildAtUtc",
        )
        require(
            simulation_effective == calculation_at,
            "timeSimulation.effectiveAtUtc must match calculationAtUtc",
        )
        require(
            simulation_build == generated_at,
            "timeSimulation.actualBuildAtUtc must match generatedAtUtc",
        )
        if simulation_enabled:
            require(
                bool(str(simulation.get("configuredDateTimeLocal", "")).strip()),
                "enabled time simulation requires configuredDateTimeLocal",
            )

        scope = obj(meta.get("recommendationSeasonScope"), "meta.recommendationSeasonScope")
        eligible_list = array(scope.get("eligibleSeasons"), "eligibleSeasons")
        eligible = {str(season) for season in eligible_list}
        require(eligible.issubset(SEASONS), "eligibleSeasons contains an invalid season")
        require(len(eligible) == len(eligible_list), "eligibleSeasons contains duplicates")

        route_count = int(number(meta.get("routeContextCount"), "meta.routeContextCount"))
        recommendation_count = int(
            number(meta.get("recommendationContextCount"), "meta.recommendationContextCount")
        )
        rankings = obj(data.get("rankings"), "rankings")
        team_count, team_marker_contexts = validate_bundle(
            rankings.get("team"),
            "rankings.team",
            eligible_seasons=eligible,
            route_context_count=route_count,
            recommendation_context_count=recommendation_count,
            require_complete_annual_markers=True,
        )

        require(
            meta.get("annualBestSelectionMode") == "full_context_adjusted_score",
            "meta.annualBestSelectionMode must be full_context_adjusted_score",
        )

        expected_marker_count = int(
            number(
                meta.get("annualBestFamilyMarkerCount"),
                "meta.annualBestFamilyMarkerCount",
            )
        )
        require(
            len(team_marker_contexts) == expected_marker_count,
            "meta.annualBestFamilyMarkerCount does not match team markers",
        )
        expected_best_spot_count = int(
            number(
                meta.get("annualBestSpotCount"),
                "meta.annualBestSpotCount",
            )
        )
        require(
            expected_best_spot_count == expected_marker_count,
            "meta.annualBestSpotCount must match annualBestFamilyMarkerCount",
        )

        players = array(data.get("players"), "players")
        require(
            players == sorted(players, key=lambda value: str(value).casefold()),
            "players must be sorted alphabetically ascending",
        )
        player_bundles = obj(rankings.get("players"), "rankings.players")
        require(set(player_bundles) == set(players), "rankings.players does not match players")
        player_results = [
            validate_bundle(
                player_bundles[player],
                f"rankings.players[{player!r}]",
                eligible_seasons=eligible,
                route_context_count=route_count,
                require_complete_annual_markers=True,
            )
            for player in players
        ]
        player_counts = [count for count, _ in player_results]
    except (ValidationError, json.JSONDecodeError) as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(
        f"Validated {team_count} recommended team contexts across "
        f"{', '.join(eligible_list) or 'no remaining seasons'} and "
        f"{len(players)} player rankings "
        f"({min(player_counts, default=0)}-{max(player_counts, default=0)} recommended contexts)."
    )


if __name__ == "__main__":
    main()
