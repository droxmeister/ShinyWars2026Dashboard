#!/usr/bin/env python3
from __future__ import annotations

import json
import math
import sys
from pathlib import Path
from typing import Any


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


def require_number(value: Any, label: str) -> float:
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

    return number


def validate_entry(
    context_id: str,
    entry: Any,
    label: str,
) -> None:
    entry = require_dict(entry, label)

    require(
        entry.get("contextId") == context_id,
        f"{label}.contextId does not match its entries key",
    )

    adjusted_score = require_number(
        entry.get("adjustedScore"),
        f"{label}.adjustedScore",
    )

    legacy_score = require_number(
        entry.get("legacyScore"),
        f"{label}.legacyScore",
    )

    require(
        adjusted_score >= 0,
        f"{label}.adjustedScore must not be negative",
    )

    require(
        legacy_score >= 0,
        f"{label}.legacyScore must not be negative",
    )

    require(
        adjusted_score + 1e-6 >= legacy_score,
        f"{label}.adjustedScore must not be below legacyScore",
    )

    require(
        isinstance(entry.get("topTarget"), str),
        f"{label}.topTarget must be a string",
    )

    targets = require_list(
        entry.get("targets"),
        f"{label}.targets",
    )

    require(
        len(targets) > 0,
        f"{label}.targets must not be empty",
    )

    target_names: list[str] = []

    for index, target_raw in enumerate(targets):
        target_label = f"{label}.targets[{index}]"
        target = require_dict(target_raw, target_label)

        species = target.get("species")

        require(
            isinstance(species, str) and species.strip(),
            f"{target_label}.species must be a non-empty string",
        )

        target_names.append(species)

        legacy_contribution = require_number(
            target.get("legacyContribution"),
            f"{target_label}.legacyContribution",
        )

        adjusted_contribution = require_number(
            target.get("adjustedContribution"),
            f"{target_label}.adjustedContribution",
        )

        require(
            legacy_contribution >= 0,
            f"{target_label}.legacyContribution must not be negative",
        )

        require(
            adjusted_contribution >= 0,
            f"{target_label}.adjustedContribution must not be negative",
        )

        multiplier = target.get("scoreMultiplier")

        if multiplier is not None:
            multiplier = require_number(
                multiplier,
                f"{target_label}.scoreMultiplier",
            )

            require(
                1.0 <= multiplier <= 2.0,
                f"{target_label}.scoreMultiplier must be between 1.0 and 2.0",
            )

    require(
        entry["topTarget"] in target_names,
        f"{label}.topTarget is not present in targets",
    )

    # A combined spot multiplier may be a weighted value such as 1.05.
    top_multiplier = entry.get("topTargetScoreMultiplier")

    if top_multiplier is not None:
        top_multiplier = require_number(
            top_multiplier,
            f"{label}.topTargetScoreMultiplier",
        )

        require(
            1.0 <= top_multiplier <= 2.0,
            f"{label}.topTargetScoreMultiplier must be between 1.0 and 2.0",
        )


def validate_view(
    view_ids: Any,
    entries: dict[str, Any],
    label: str,
) -> int:
    view_ids = require_list(view_ids, label)

    require(
        len(view_ids) == len(set(view_ids)),
        f"{label} contains duplicate context IDs",
    )

    previous_score: float | None = None

    for position, context_id in enumerate(view_ids, start=1):
        require(
            context_id in entries,
            f"{label} references missing context {context_id!r}",
        )

        score = require_number(
            entries[context_id].get("adjustedScore"),
            f"{label}[{position}].adjustedScore",
        )

        if previous_score is not None:
            require(
                score <= previous_score + 1e-6,
                f"{label} is not sorted descending at position {position}",
            )

        previous_score = score

    return len(view_ids)


def validate_bundle(
    bundle_raw: Any,
    label: str,
    *,
    expected_team_contexts: int | None = None,
) -> int:
    bundle = require_dict(bundle_raw, label)

    entries = require_dict(
        bundle.get("entries"),
        f"{label}.entries",
    )

    views = require_dict(
        bundle.get("views"),
        f"{label}.views",
    )

    require(
        "All|All" in views,
        f"{label}.views must contain All|All",
    )

    all_ids = require_list(
        views["All|All"],
        f"{label}.views.All|All",
    )

    require(
        len(all_ids) > 0,
        f"{label}.views.All|All must not be empty",
    )

    require(
        set(all_ids) == set(entries),
        f"{label}.entries must match the IDs in views.All|All",
    )

    if expected_team_contexts is not None:
        require(
            len(all_ids) == expected_team_contexts,
            f"{label} contains {len(all_ids)} contexts, "
            f"but meta.routeContextCount is {expected_team_contexts}. "
            "The ranking may still be truncated.",
        )

    for context_id, entry in entries.items():
        validate_entry(
            context_id,
            entry,
            f"{label}.entries[{context_id!r}]",
        )

    for view_name, view_ids in views.items():
        validate_view(
            view_ids,
            entries,
            f"{label}.views[{view_name!r}]",
        )

    return len(all_ids)


def load_json(path: Path) -> dict[str, Any]:
    require(
        path.is_file(),
        f"Strategy file does not exist: {path}",
    )

    try:
        data = json.loads(
            path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as exc:
        raise ValidationError(
            f"Strategy file contains invalid JSON: {exc}"
        ) from exc

    return require_dict(data, "root")


def main() -> None:
    path = Path(
        sys.argv[1]
        if len(sys.argv) > 1
        else "web/data/strategy.json"
    )

    try:
        data = load_json(path)

        meta = require_dict(
            data.get("meta"),
            "meta",
        )

        route_context_count = int(
            require_number(
                meta.get("routeContextCount"),
                "meta.routeContextCount",
            )
        )

        players = require_list(
            data.get("players"),
            "players",
        )

        require(
            len(players) > 0,
            "players must not be empty",
        )

        require(
            len(players) == len(set(players)),
            "players contains duplicate names",
        )

        configured_player_count = meta.get("playerCount")

        if configured_player_count is not None:
            require(
                int(require_number(
                    configured_player_count,
                    "meta.playerCount",
                )) == len(players),
                "meta.playerCount does not match players",
            )

        rankings = require_dict(
            data.get("rankings"),
            "rankings",
        )

        team_count = validate_bundle(
            rankings.get("team"),
            "rankings.team",
            expected_team_contexts=route_context_count,
        )

        player_bundles = require_dict(
            rankings.get("players"),
            "rankings.players",
        )

        require(
            set(player_bundles) == set(players),
            "rankings.players does not match players",
        )

        player_counts = []

        for player in players:
            player_counts.append(
                validate_bundle(
                    player_bundles[player],
                    f"rankings.players[{player!r}]",
                )
            )

    except ValidationError as exc:
        print(
            f"Validation failed: {exc}",
            file=sys.stderr,
        )
        raise SystemExit(1) from exc

    print(
        f"Validated {team_count} team contexts and "
        f"{len(players)} player rankings "
        f"({min(player_counts)}–{max(player_counts)} contexts per player)."
    )


if __name__ == "__main__":
    main()
