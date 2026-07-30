"""Build team and player-specific Shiny Wars rankings and a static-site JSON feed."""
from __future__ import annotations

import argparse
import csv
import json
import os
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from math import floor
from zoneinfo import ZoneInfo
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


def _parse_clock_minute(value: str) -> int:
    hour_text, minute_text = str(value).split(":", 1)
    hour = int(hour_text)
    minute = int(minute_text)
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Invalid clock time: {value!r}")
    return hour * 60 + minute


def _classify_game_time(game_minute: int, windows: dict[str, Any]) -> str:
    for key in ("morning", "day", "night"):
        entry = windows.get(key, {})
        start = _parse_clock_minute(str(entry.get("start", "00:00")))
        end = _parse_clock_minute(str(entry.get("end", "23:59")))
        if start <= end:
            matches = start <= game_minute <= end
        else:
            matches = game_minute >= start or game_minute <= end
        if matches:
            return key
    raise ValueError(f"No time window contains game minute {game_minute}")


def current_game_clock(config: dict[str, Any], now: datetime) -> tuple[str, str]:
    live = config.get("live_filter", {})
    timezone_name = str(live.get("timezone", "Europe/Berlin"))
    game = live.get("game_clock", {})
    anchors = sorted(int(value) for value in game.get("day_start_hours_local", [2, 8, 14, 20]))
    seconds_per_game_minute = int(game.get("real_seconds_per_game_minute", 15))
    if not anchors or seconds_per_game_minute <= 0:
        raise ValueError("live_filter.game_clock is invalid")

    local_now = now.astimezone(ZoneInfo(timezone_name))
    local_seconds = local_now.hour * 3600 + local_now.minute * 60 + local_now.second
    anchor_seconds = [hour * 3600 for hour in anchors]
    previous = [value for value in anchor_seconds if value <= local_seconds]
    active_anchor = previous[-1] if previous else anchor_seconds[-1] - 24 * 3600
    elapsed_real_seconds = local_seconds - active_anchor
    game_minute = int(elapsed_real_seconds // seconds_per_game_minute) % (24 * 60)
    game_time = f"{game_minute // 60:02d}:{game_minute % 60:02d}"
    windows = game.get(
        "time_windows",
        {
            "morning": {"start": "04:00", "end": "10:59"},
            "day": {"start": "11:00", "end": "20:59"},
            "night": {"start": "21:00", "end": "03:59"},
        },
    )
    return game_time, _classify_game_time(game_minute, windows)


def _rotation_anchor_utc(config: dict[str, Any]) -> datetime:
    live = config.get("live_filter", {})
    timezone_name = str(live.get("timezone", "Europe/Berlin"))
    rotation = live.get("season_rotation", {})
    anchor = datetime.fromisoformat(str(rotation["anchor_local"]))
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=ZoneInfo(timezone_name))
    return anchor.astimezone(timezone.utc)


def active_season(config: dict[str, Any], now: datetime) -> str:
    live = config.get("live_filter", {})
    rotation = live.get("season_rotation")
    if rotation:
        order = [str(value) for value in rotation.get("season_order", [])]
        anchor_season = str(rotation.get("anchor_season", ""))
        interval_days = float(rotation.get("interval_days", 7))
        if not order or anchor_season not in order or interval_days <= 0:
            raise ValueError("live_filter.season_rotation is invalid")
        anchor = _rotation_anchor_utc(config)
        before_anchor_season = str(rotation.get("before_anchor_season", "")).strip()
        if now.astimezone(timezone.utc) < anchor and before_anchor_season:
            if before_anchor_season not in order:
                raise ValueError(
                    "live_filter.season_rotation.before_anchor_season must be in season_order"
                )
            return before_anchor_season
        steps = floor((now.astimezone(timezone.utc) - anchor).total_seconds() / (interval_days * 86400))
        anchor_index = order.index(anchor_season)
        return order[(anchor_index + steps) % len(order)]

    for entry in config.get("event_schedule", []):
        start = datetime.fromisoformat(str(entry["start_utc"]).replace("Z", "+00:00"))
        end = datetime.fromisoformat(str(entry["end_utc"]).replace("Z", "+00:00"))
        if start <= now < end:
            return str(entry["season"])
    return "All"


def live_filter_payload(config: dict[str, Any]) -> dict[str, Any]:
    live = config.get("live_filter", {})
    game = live.get("game_clock", {})
    rotation = live.get("season_rotation", {})
    anchor_utc = _rotation_anchor_utc(config) if rotation else None
    return {
        "defaultEnabled": bool(live.get("default_enabled", True)),
        "timezone": str(live.get("timezone", "Europe/Berlin")),
        "gameDayStartHoursLocal": [int(value) for value in game.get("day_start_hours_local", [2, 8, 14, 20])],
        "realSecondsPerGameMinute": int(game.get("real_seconds_per_game_minute", 15)),
        "timeWindows": game.get("time_windows", {}),
        "seasonRotation": {
            "anchorUtc": anchor_utc.isoformat().replace("+00:00", "Z") if anchor_utc else None,
            "anchorLocal": rotation.get("anchor_local"),
            "anchorSeason": rotation.get("anchor_season"),
            "beforeAnchorSeason": rotation.get("before_anchor_season"),
            "seasonOrder": rotation.get("season_order", []),
            "intervalDays": float(rotation.get("interval_days", 7)),
        },
    }


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
        "scoreMultiplier": float(row["species_temporal_score_multiplier_average"]),
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
        "topTargetScoreMultiplier": float(row["top_target_score_multiplier"]),
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
    exclusion_enabled = bool(config.get("exclude_player_context_if_any_target_family_caught", True))

    team_rankings, team_targets, _ = rank_for_state(
        model["by_context"],
        team_families,
        set(),
        unique_bonus,
        duplicate_points,
        False,
        family_sets,
    )
    rankings: dict[str, Any] = {
        "team": build_views(team_rankings, team_targets, top_n),
        "players": {},
    }
    player_summaries: list[dict[str, Any]] = []
    active = active_season(config, generated_at)
    game_time_at_build, active_time_of_day = current_game_clock(config, generated_at)

    for player in normalized.players:
        player_rankings, player_targets, excluded_count = rank_for_state(
            model["by_context"],
            team_families,
            player_families[player],
            unique_bonus,
            duplicate_points,
            exclusion_enabled,
            family_sets,
        )
        views = build_views(player_rankings, player_targets, top_n)
        rankings["players"][player] = views
        default_key = f"{active}|{active_time_of_day}" if active != "All" else f"All|{active_time_of_day}"
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
            "activeTimeOfDay": active_time_of_day,
            "gameTimeAtBuild": game_time_at_build,
            "liveFilter": live_filter_payload(config),
            "topN": top_n,
            "playerCount": len(normalized.players),
            "teamCaughtFamilyCount": len(team_families),
            "routeContextCount": model["diagnostics"]["context_count"],
            "rankingMode": "temporal_exclusivity",
            "scoreAdjustmentByCombinationCount": {
                "1": 2.0,
                "2": 1.5,
                "3": 1.25,
                "4": 1.1,
                "default": 1.0,
            },
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
        ["Active in-game time window", active_time_of_day],
        ["In-game time at build", game_time_at_build],
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
    time_of_day = payload["meta"].get("activeTimeOfDay", "All")
    key = f"{season}|{time_of_day}" if season != "All" else f"All|{time_of_day}"
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
