#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


TOLERANCE = 1e-6
MULTIPLIER_BY_COMBINATION_COUNT = {
    1: 2.0,
    2: 1.5,
    3: 1.25,
    4: 1.1,
}


class ValidationError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ValidationError(message)


def require_dict(value: Any, label: str) -> dict[str, Any]:
    require(isinstance(value, dict), f"{label} must be an object")
    return value


def require_list(value: Any, label: str) -> list[Any]:
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


def expected_multiplier(combination_count: int) -> float:
    return MULTIPLIER_BY_COMBINATION_COUNT.get(combination_count, 1.0)


def validate_target(target_raw: Any, label: str) -> None:
    target = require_dict(target_raw, label)

    require(
        isinstance(target.get("species"), str) and target["species"].strip(),
        f"{label}.species must be a non-empty string",
    )
    require(
        isinstance(target.get("family"), str) and target["family"].strip(),
        f"{label}.family must be a non-empty string",
    )

    combination_value = number(
        target.get("seasonTimeCombinationCount"),
        f"{label}.seasonTimeCombinationCount",
    )
    require(
        combination_value.is_integer() and 1 <= combination_value <= 12,
        f"{label}.seasonTimeCombinationCount must be an integer from 1 to 12",
    )
    combination_count = int(combination_value)

    multiplier = number(target.get("scoreMultiplier"), f"{label}.scoreMultiplier")
    require(
        close(multiplier, expected_multiplier(combination_count)),
        f"{label}.scoreMultiplier {multiplier} does not match "
        f"{combination_count} S/T combinations",
    )

    legacy = number(
        target.get("legacyContribution"),
        f"{label}.legacyContribution",
    )
    adjusted = number(
        target.get("adjustedContribution"),
        f"{label}.adjustedContribution",
    )
    require(legacy >= 0 and adjusted >= 0, f"{label} contributions must not be negative")
    require(
        close(adjusted, legacy * multiplier),
        f"{label}.adjustedContribution must equal legacyContribution × scoreMultiplier",
    )

    for forbidden in ("exclusivity", "temporalExclusivity", "temporalDetails"):
        require(forbidden not in target, f"{label}.{forbidden} must not be public")


def validate_entry(context_id: str, entry_raw: Any, label: str) -> None:
    entry = require_dict(entry_raw, label)
    require(entry.get("contextId") == context_id, f"{label}.contextId does not match")

    targets = require_list(entry.get("targets"), f"{label}.targets")
    require(targets, f"{label}.targets must not be empty")

    for index, target in enumerate(targets):
        validate_target(target, f"{label}.targets[{index}]")

    target_by_species = {
        str(target["species"]): target
        for target in targets
    }
    top_target_name = entry.get("topTarget")
    require(
        top_target_name in target_by_species,
        f"{label}.topTarget is not present in targets",
    )

    top_multiplier = number(
        entry.get("topTargetScoreMultiplier"),
        f"{label}.topTargetScoreMultiplier",
    )
    require(
        close(top_multiplier, float(target_by_species[top_target_name]["scoreMultiplier"])),
        f"{label}.topTargetScoreMultiplier does not match the top target",
    )

    legacy_score = number(entry.get("legacyScore"), f"{label}.legacyScore")
    adjusted_score = number(entry.get("adjustedScore"), f"{label}.adjustedScore")
    require(legacy_score >= 0 and adjusted_score >= 0, f"{label} scores must not be negative")

    require(
        close(
            legacy_score,
            sum(float(target["legacyContribution"]) for target in targets),
        ),
        f"{label}.legacyScore does not equal the target contribution sum",
    )
    require(
        close(
            adjusted_score,
            sum(float(target["adjustedContribution"]) for target in targets),
        ),
        f"{label}.adjustedScore does not equal the target contribution sum",
    )

    require("topTargetExclusivity" not in entry, f"{label}.topTargetExclusivity must not be public")


def validate_bundle(
    bundle_raw: Any,
    label: str,
    *,
    expected_all_count: int | None = None,
) -> int:
    bundle = require_dict(bundle_raw, label)
    entries = require_dict(bundle.get("entries"), f"{label}.entries")
    views = require_dict(bundle.get("views"), f"{label}.views")
    require("All|All" in views, f"{label}.views must contain All|All")

    all_ids = require_list(views["All|All"], f"{label}.views.All|All")
    require(all_ids, f"{label}.views.All|All must not be empty")
    require(len(all_ids) == len(set(all_ids)), f"{label}.views.All|All contains duplicates")
    require(set(all_ids) == set(entries), f"{label}.entries must match views.All|All")

    if expected_all_count is not None:
        require(
            len(all_ids) == expected_all_count,
            f"{label} contains {len(all_ids)} contexts, expected {expected_all_count}; "
            "the ranking may still be truncated",
        )

    for context_id, entry in entries.items():
        validate_entry(context_id, entry, f"{label}.entries[{context_id!r}]")

    for view_name, view_raw in views.items():
        view_ids = require_list(view_raw, f"{label}.views[{view_name!r}]")
        require(len(view_ids) == len(set(view_ids)), f"{label}.{view_name} contains duplicates")

        previous_score: float | None = None
        for position, context_id in enumerate(view_ids, start=1):
            require(context_id in entries, f"{label}.{view_name} references missing {context_id!r}")
            score = number(
                entries[context_id].get("adjustedScore"),
                f"{label}.{view_name}[{position}].adjustedScore",
            )
            if previous_score is not None:
                require(
                    score <= previous_score + TOLERANCE,
                    f"{label}.{view_name} is not sorted descending at position {position}",
                )
            previous_score = score

    return len(all_ids)


def load_json(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Strategy file does not exist: {path}")
    try:
        return require_dict(
            json.loads(path.read_text(encoding="utf-8")),
            "root",
        )
    except json.JSONDecodeError as exc:
        raise ValidationError(f"Strategy file contains invalid JSON: {exc}") from exc


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "web/data/strategy.json")

    try:
        data = load_json(path)
        meta = require_dict(data.get("meta"), "meta")
        require("topN" not in meta, "meta.topN is still present")

        route_context_count = int(number(meta.get("routeContextCount"), "meta.routeContextCount"))
        require(route_context_count > 0, "meta.routeContextCount must be positive")

        players = require_list(data.get("players"), "players")
        require(players, "players must not be empty")
        require(len(players) == len(set(players)), "players contains duplicates")

        rankings = require_dict(data.get("rankings"), "rankings")
        team_count = validate_bundle(
            rankings.get("team"),
            "rankings.team",
            expected_all_count=route_context_count,
        )

        player_bundles = require_dict(rankings.get("players"), "rankings.players")
        require(set(player_bundles) == set(players), "rankings.players does not match players")

        player_counts = [
            validate_bundle(
                player_bundles[player],
                f"rankings.players[{player!r}]",
            )
            for player in players
        ]

    except ValidationError as exc:
        print(f"Validation failed: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc

    print(
        f"Validated {team_count} team contexts and {len(players)} player rankings "
        f"({min(player_counts)}-{max(player_counts)} contexts per player)."
    )


if __name__ == "__main__":
    main()
