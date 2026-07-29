"""Build team and player-specific Shiny Wars rankings and a static-site JSON feed."""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from .horde_core import (
    SEASONS,
    TIMES,
    ScoringState,
    annotate_location_instances,
    annotate_temporal_exclusivity,
    build_tier_mapping,
    family_set_from_names,
    iter_active_horde_rows,
    load_monsters,
    load_tier_chart,
    name_key,
    normalize_horde_probabilities,
    rank_contexts,
)
from .sheets_client import SheetInput, read_sheet_input, write_generated_tabs


@dataclass(frozen=True)
class NormalizedInput:
    players: tuple[str, ...]
    all_players: tuple[str, ...]
    catches_by_player: dict[str, tuple[str, ...]]
    warnings: tuple[str, ...]


def parse_bool(value: Any, default: bool = True) -> bool:
    text = str(value or "").strip().casefold()
    if not text:
        return default
    return text not in {"false", "0", "no", "n", "off", "inactive"}


def load_local_csv(input_dir: Path) -> SheetInput:
    def read(name: str) -> list[dict[str, str]]:
        path = input_dir / name
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            return list(csv.DictReader(handle))

    return SheetInput(players=read("players.csv"), catches=read("catches.csv"))


def normalize_input(raw: SheetInput) -> NormalizedInput:
    active_players: list[str] = []
    all_players: list[str] = []
    canonical_player: dict[str, str] = {}
    warnings: list[str] = []

    for row_number, row in enumerate(raw.players, start=2):
        player = str(row.get("Player", row.get("In-Game Name", ""))).strip()
        if not player:
            continue
        key = player.casefold()
        if key in canonical_player:
            warnings.append(f"Players row {row_number}: duplicate player {player!r} ignored")
            continue
        canonical_player[key] = player
        all_players.append(player)
        if parse_bool(row.get("Active", ""), default=True):
            active_players.append(player)

    catches: dict[str, list[str]] = {player: [] for player in all_players}
    seen: set[tuple[str, str]] = set()
    for row_number, row in enumerate(raw.catches, start=2):
        if not parse_bool(row.get("Active", ""), default=True):
            continue
        player_raw = str(row.get("Player", "")).strip()
        pokemon = str(row.get("Pokemon", row.get("Pokémon", ""))).strip()
        if not player_raw and not pokemon:
            continue
        player = canonical_player.get(player_raw.casefold())
        if player is None:
            raise ValueError(f"Catches row {row_number}: unknown player {player_raw!r}")
        if not pokemon:
            raise ValueError(f"Catches row {row_number}: Pokémon is empty")
        catch_key = (player.casefold(), pokemon.casefold())
        if catch_key in seen:
            warnings.append(
                f"Catches row {row_number}: duplicate {player} / {pokemon} ignored; counts do not affect scoring"
            )
            continue
        seen.add(catch_key)
        catches[player].append(pokemon)

    if not active_players:
        raise ValueError("No active players were found in the Players sheet")

    return NormalizedInput(
        players=tuple(active_players),
        all_players=tuple(all_players),
        catches_by_player={player: tuple(values) for player, values in catches.items()},
        warnings=tuple(warnings),
    )


def active_season(schedule: list[dict[str, Any]], now: datetime) -> str:
    for entry in schedule:
        start = datetime.fromisoformat(str(entry["start_utc"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(entry["end_utc"]).replace("Z", "+00:00"))
        if start <= now < end:
            return str(entry["season"])
    return "All"


def build_static_model(monsters_path: Path, tiers_path: Path):
    monsters, diagnostics = load_monsters(monsters_path)
    tier_map = load_tier_chart(tiers_path)
    mapping_by_id, name_to_families, mapping_rows = build_tier_mapping(monsters, tier_map)
    raw_rows = list(iter_active_horde_rows(monsters, mapping_by_id))
    raw_rows, location_diagnostics = annotate_location_instances(raw_rows)
    raw_rows, temporal_rows, temporal_diagnostics = annotate_temporal_exclusivity(raw_rows)
    horde_rows, by_context = normalize_horde_probabilities(raw_rows)
    diagnostics.update(location_diagnostics)
    diagnostics.update(temporal_diagnostics)
    diagnostics.update(
        {
            "tier_chart_entry_count": len(tier_map),
            "horde_row_count": len(horde_rows),
            "context_count": len(by_context),
        }
    )
    return {
        "monsters": monsters,
        "mapping_rows": mapping_rows,
        "name_to_families": name_to_families,
        "temporal_rows": temporal_rows,
        "horde_rows": horde_rows,
        "by_context": by_context,
        "diagnostics": diagnostics,
    }


def resolve_catch_families(
    normalized: NormalizedInput,
    name_to_families: dict[str, set[str]],
) -> tuple[dict[str, set[str]], set[str], dict[str, list[str]]]:
    player_families: dict[str, set[str]] = {}
    team_families: set[str] = set()
    family_owners: dict[str, list[str]] = defaultdict(list)

    for player in normalized.all_players:
        names = normalized.catches_by_player.get(player, ())
        families = {
            name_key(family)
            for family in family_set_from_names(names, name_to_families)
        }
        player_families[player] = families
        team_families.update(families)
        for family in sorted(families):
            family_owners[family].append(player)
    return player_families, team_families, family_owners


def context_family_sets(by_context: dict[str, list[dict[str, Any]]]) -> dict[str, set[str]]:
    return {
        context_id: {name_key(str(row["scoring_family"])) for row in records}
        for context_id, records in by_context.items()
    }


def serialize_target(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "species": str(row["encountered_species"]),
        "family": str(row["scoring_family"]),
        "tier": row["tier"],
        "basePoints": float(row["base_points"]),
        "effectivePoints": float(row["effective_points_if_shiny"]),
        "status": str(row["score_status"]),
        "hordeProbabilityPercent": float(row["horde_roll_probability_percent"]),
        "shinyCheckSharePercent": float(row["shiny_check_share_percent"]),
        "weightedHordeSize": float(row["weighted_horde_size"]),
        "temporalExclusivity": float(row["species_temporal_exclusivity_average"]),
        "temporalDetails": str(row["species_temporal_exclusivity_details"]),
        "adjustedContribution": float(row["ranking_score_index_contribution"]),
        "legacyContribution": float(row["score_index_contribution"]),
    }


def serialize_context(
    row: dict[str, Any],
    targets_by_context: dict[str, list[dict[str, Any]]],
    view_rank: int,
) -> dict[str, Any]:
    context_id = str(row["context_id"])
    targets = targets_by_context.get(context_id, [])
    location_name = str(row["location_display"])
    return {
        "rank": view_rank,
        "contextId": context_id,
        "region": str(row["region"]),
        "locationId": str(row["location_id"]),
        "locationName": location_name,
        "displayName": f"{row['region']} — {location_name}",
        "encounterType": str(row["encounter_type"]),
        "season": str(row["season"]),
        "timeOfDay": str(row["time_of_day"]),
        "adjustedScore": float(row["ranking_score_index_per_sweet_scent"]),
        "legacyScore": float(row["state_score_index_per_sweet_scent"]),
        "expectedChecks": float(row["expected_checks_per_sweet_scent"]),
        "newUniqueSharePercent": float(row["new_unique_shiny_check_share_percent"]),
        "topTarget": str(row["top_target"]),
        "topTargetFamily": str(row["top_target_family"]),
        "topTargetPoints": float(row["top_target_points"]),
        "topTargetProbabilityPercent": float(row["top_target_horde_probability_percent"]),
        "topTargetExclusivity": float(row["top_target_temporal_exclusivity"]),
        "fallbackTarget": str(row.get("fallback_target", "")),
        "fallbackPoints": float(row["fallback_target_points"]) if row.get("fallback_target_points") not in ("", None) else None,
        "allTargetsText": str(row["all_targets"]),
        "targets": [serialize_target(target) for target in targets],
    }


def build_views(
    ranking_rows: list[dict[str, Any]],
    target_rows: list[dict[str, Any]],
    top_n: int,
) -> dict[str, Any]:
    targets_by_context: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for target in target_rows:
        targets_by_context[str(target["context_id"])].append(target)

    filters: list[tuple[str, str]] = [("All", "All")]
    filters.extend(("All", time_name) for time_name in TIMES)
    for season in SEASONS:
        filters.append((season, "All"))
        filters.extend((season, time_name) for time_name in TIMES)

    entries: dict[str, dict[str, Any]] = {}
    views: dict[str, list[str]] = {}
    for season, time_name in filters:
        selected = [
            row
            for row in ranking_rows
            if (season == "All" or row["season"] == season)
            and (time_name == "All" or row["time_of_day"] == time_name)
        ][:top_n]
        key = f"{season}|{time_name}"
        ids: list[str] = []
        for row in selected:
            context_id = str(row["context_id"])
            ids.append(context_id)
            if context_id not in entries:
                entries[context_id] = serialize_context(row, targets_by_context, 0)
                entries[context_id].pop("rank", None)
        views[key] = ids
    return {"entries": entries, "views": views}


def rank_for_state(
    by_context: dict[str, list[dict[str, Any]]],
    team_families: set[str],
    player_families: set[str],
    unique_bonus: float,
    duplicate_points: float,
    exclusivity_power: float,
    exclude_contexts: bool,
    family_sets_by_context: dict[str, set[str]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], int]:
    state = ScoringState(
        unique_bonus=unique_bonus,
        duplicate_points=duplicate_points,
        team_caught_families=frozenset(team_families),
        player_caught_families=frozenset(player_families),
    )
    rankings, targets = rank_contexts(
        by_context,
        state,
        use_temporal_exclusivity=True,
        exclusivity_power=exclusivity_power,
    )
    if not exclude_contexts or not player_families:
        return rankings, targets, 0

    excluded_ids = {
        context_id
        for context_id, families in family_sets_by_context.items()
        if families.intersection(player_families)
    }
    filtered_rankings = [row for row in rankings if str(row["context_id"]) not in excluded_ids]
    filtered_targets = [row for row in targets if str(row["context_id"]) not in excluded_ids]
    return filtered_rankings, filtered_targets, len(excluded_ids)


def build_team_checklist(
    mapping_rows: list[dict[str, Any]],
    team_families: set[str],
    family_owners: dict[str, list[str]],
) -> list[dict[str, Any]]:
    family_info: dict[str, dict[str, Any]] = {}
    for row in mapping_rows:
        family = str(row.get("scoring_family", ""))
        if not family:
            continue
        key = name_key(family)
        info = family_info.setdefault(
            key,
            {
                "family": family,
                "tier": row.get("tier", ""),
                "base_points": row.get("base_points", ""),
                "members": set(),
            },
        )
        info["members"].add(str(row["pokemon"]))

    result: list[dict[str, Any]] = []
    for key, info in family_info.items():
        result.append(
            {
                "family": info["family"],
                "caught": key in team_families,
                "owners": sorted(family_owners.get(key, []), key=str.casefold),
                "tier": info["tier"],
                "basePoints": float(info["base_points"]) if info["base_points"] != "" else None,
                "members": sorted(info["members"]),
            }
        )
    result.sort(key=lambda row: (not row["caught"], -(row["basePoints"] or 0), row["family"]))
    return result


def build_payload(
    model: dict[str, Any],
    normalized: NormalizedInput,
    config: dict[str, Any],
    generated_at: datetime,
) -> tuple[dict[str, Any], list[list[Any]], list[list[Any]], list[list[Any]]]:
    player_families, team_families, family_owners = resolve_catch_families(
        normalized, model["name_to_families"]
    )
    family_sets = context_family_sets(model["by_context"])
    top_n = int(config.get("top_n", 25))
    unique_bonus = float(config.get("unique_species_bonus", 8))
    duplicate_points = float(config.get("duplicate_points", 1))
    exclusivity_power = float(config.get("temporal_exclusivity_weight_power", 1.0))
    exclusion_enabled = bool(config.get("exclude_player_context_if_any_target_family_caught", True))

    team_rankings, team_targets, _ = rank_for_state(
        model["by_context"],
        team_families,
        set(),
        unique_bonus,
        duplicate_points,
        exclusivity_power,
        False,
        family_sets,
    )
    rankings: dict[str, Any] = {
        "team": build_views(team_rankings, team_targets, top_n),
        "players": {},
    }
    player_summaries: list[dict[str, Any]] = []
    active = active_season(config.get("event_schedule", []), generated_at)

    for player in normalized.players:
        player_rankings, player_targets, excluded_count = rank_for_state(
            model["by_context"],
            team_families,
            player_families[player],
            unique_bonus,
            duplicate_points,
            exclusivity_power,
            exclusion_enabled,
            family_sets,
        )
        views = build_views(player_rankings, player_targets, top_n)
        rankings["players"][player] = views
        default_key = f"{active}|All" if active != "All" else "All|All"
        default_ids = views["views"].get(default_key, [])
        top = views["entries"].get(default_ids[0]) if default_ids else None
        player_summaries.append(
            {
                "player": player,
                "caughtSpecies": list(normalized.catches_by_player.get(player, ())),
                "caughtFamilyCount": len(player_families[player]),
                "excludedContextCount": excluded_count,
                "topSpot": top["displayName"] if top else "",
                "topTarget": top["topTarget"] if top else "",
                "topScore": top["adjustedScore"] if top else None,
            }
        )

    checklist = build_team_checklist(
        model["mapping_rows"], team_families, family_owners
    )
    payload = {
        "meta": {
            "generatedAtUtc": generated_at.isoformat(),
            "activeSeason": active,
            "topN": top_n,
            "playerCount": len(normalized.players),
            "teamCaughtFamilyCount": len(team_families),
            "routeContextCount": model["diagnostics"]["context_count"],
            "rankingMode": "temporal_exclusivity",
            "exclusivityPower": exclusivity_power,
            "uniqueSpeciesBonus": unique_bonus,
            "duplicatePoints": duplicate_points,
            "playerContextExclusionEnabled": exclusion_enabled,
            "playerContextExclusionRule": (
                "Exclude a context when the player has already caught any scoring family available there"
                if exclusion_enabled
                else "No hard context exclusion; personal duplicate families score duplicate points"
            ),
            "warnings": list(normalized.warnings),
        },
        "players": list(normalized.players),
        "rankings": rankings,
        "teamChecklist": checklist,
        "playerSummary": player_summaries,
    }

    sync_status = [
        ["Key", "Value"],
        ["Last successful update (UTC)", generated_at.isoformat()],
        ["Active event season", active],
        ["Active players", len(normalized.players)],
        ["Team caught evolution families", len(team_families)],
        ["Ranked route contexts", model["diagnostics"]["context_count"]],
        ["Top spots per view", top_n],
        ["Player context exclusion", "Enabled" if exclusion_enabled else "Disabled"],
        ["Warnings", " | ".join(normalized.warnings)],
    ]
    team_checklist_rows = [["Scoring Family", "Caught", "Owners", "Tier", "Base Points", "Evolution Members"]]
    for item in checklist:
        team_checklist_rows.append(
            [
                item["family"],
                item["caught"],
                " | ".join(item["owners"]),
                item["tier"],
                item["basePoints"],
                " | ".join(item["members"]),
            ]
        )
    player_summary_rows = [[
        "Player", "Caught Species", "Caught Families", "Excluded Contexts", "Current Top Spot", "Top Target", "Adjusted Score"
    ]]
    for item in player_summaries:
        player_summary_rows.append(
            [
                item["player"],
                " | ".join(item["caughtSpecies"]),
                item["caughtFamilyCount"],
                item["excludedContextCount"],
                item["topSpot"],
                item["topTarget"],
                item["topScore"],
            ]
        )
    return payload, sync_status, team_checklist_rows, player_summary_rows



def _top_team_display(payload: dict[str, Any]) -> str:
    season = payload["meta"]["activeSeason"]
    key = f"{season}|All" if season != "All" else "All|All"
    team = payload["rankings"]["team"]
    ids = team["views"].get(key, [])
    return team["entries"].get(ids[0], {}).get("displayName", "") if ids else ""

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monsters", type=Path, default=Path("data/monsters.json"))
    parser.add_argument("--tiers", type=Path, default=Path("data/shiny_wars_2026_tier_chart.csv"))
    parser.add_argument("--config", type=Path, default=Path("config/dashboard_config.json"))
    parser.add_argument("--output", type=Path, default=Path("web/data/strategy.json"))
    parser.add_argument("--local-input-dir", type=Path)
    parser.add_argument("--google-sheet", action="store_true")
    args = parser.parse_args()

    config = json.loads(args.config.read_text(encoding="utf-8"))
    if args.google_sheet:
        spreadsheet_id = os.environ.get("GOOGLE_SHEET_ID", "").strip()
        if not spreadsheet_id:
            raise RuntimeError("GOOGLE_SHEET_ID is not set")
        raw_input = read_sheet_input(spreadsheet_id)
    else:
        input_dir = args.local_input_dir or Path("local_input")
        raw_input = load_local_csv(input_dir)

    normalized = normalize_input(raw_input)
    model = build_static_model(args.monsters, args.tiers)
    generated_at = datetime.now(timezone.utc)
    payload, sync_status, checklist_rows, player_summary_rows = build_payload(
        model, normalized, config, generated_at
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")

    if args.google_sheet:
        write_generated_tabs(
            os.environ["GOOGLE_SHEET_ID"],
            sync_status,
            checklist_rows,
            player_summary_rows,
        )

    print(
        json.dumps(
            {
                "output": str(args.output),
                "players": len(normalized.players),
                "team_caught_families": payload["meta"]["teamCaughtFamilyCount"],
                "active_season": payload["meta"]["activeSeason"],
                "top_team_spot": _top_team_display(payload),
                "warnings": list(normalized.warnings),
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
