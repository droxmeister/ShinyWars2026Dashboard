#!/usr/bin/env python3
"""PokeMMO Shiny Wars 2026 horde route analyzer.

This parser combines a PokeMMO ``monsters.json`` export with the official
Shiny Wars tier chart and produces state-aware horde rankings.

Key rules implemented:
- Every evolution-line scoring anchor inherits one tier value.
- The first shiny from an evolution line caught by the team gets +8 BP.
- A second shiny from the same evolution line caught by the same player is
  worth 1 point (normal wild shinies only; Alpha logic is outside this horde
  route model).
- Standard horde rows are stored as a 5% split of the wild encounter table.
  Sweet Scent rolls only between the active horde splits, so each species'
  Sweet Scent probability is raw_split / sum(active_horde_splits).
- Explicit ``type = Sweet Scent`` early-game tables are retained and normalized
  the same way. No horde-marked records are excluded.

The legacy score index is proportional to expected event points per Sweet Scent use:
    sum(horde_probability * horde_size * score_if_shiny)

The recommended temporal-exclusivity index additionally multiplies each
encountered species by 12 / its number of available season-time combinations.
The common per-check shiny probability is deliberately omitted because it is
identical across normal wild horde routes and does not affect route ordering.

Only Python's standard library is required.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import re
import shutil
from collections import defaultdict, deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator, Sequence

TIER_HEADER_RE = re.compile(r"TIER\s+(\d+)\s*\((\d+)\s*pts\)", re.IGNORECASE)
CONTROL_CHARS_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
NAME_ALIASES = {
    "Nidoran [M]": "Nidoran♂",
    "Nidoran [F]": "Nidoran♀",
    "Nidoran M": "Nidoran♂",
    "Nidoran F": "Nidoran♀",
}
TIMES = ("morning", "day", "night")
SEASONS = ("Summer", "Autumn", "Winter", "Spring")
STANDARD_HORDE_POOL_PERCENT = 5.0
DEFAULT_UNIQUE_BONUS = 8.0
DEFAULT_DUPLICATE_POINTS = 1.0
TOTAL_TEMPORAL_COMBINATIONS = len(SEASONS) * len(TIMES)
DEFAULT_EXCLUSIVITY_POWER = 1.0
OFFICIAL_RULES_URL = "https://forums.pokemmo.com/index.php?/topic/198507-pokemmo-shiny-wars-2026/"
RULES_MIRROR_URL = "https://pokemmo.shoutwiki.com/wiki/Event:Shiny_Wars_2026"


@dataclass(frozen=True)
class TierEntry:
    chart_name: str
    pokemon_name: str
    tier: int
    points: int


@dataclass(frozen=True)
class ScoringState:
    unique_bonus: float
    duplicate_points: float
    team_caught_families: frozenset[str]
    player_caught_families: frozenset[str]


def clean_text(value: Any) -> Any:
    """Recursively remove invalid control characters from parsed strings."""
    if isinstance(value, str):
        return CONTROL_CHARS_RE.sub("", value)
    if isinstance(value, list):
        return [clean_text(item) for item in value]
    if isinstance(value, dict):
        return {key: clean_text(item) for key, item in value.items()}
    return value


def normalize_name(name: str) -> str:
    return NAME_ALIASES.get(name.strip(), name.strip())


def name_key(name: str) -> str:
    return normalize_name(name).casefold()


def format_number(value: float, digits: int = 8) -> float:
    """Round floating-point output while retaining numeric CSV cells."""
    if not math.isfinite(value):
        return 0.0
    return round(value, digits)


def load_monsters(path: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    raw = path.read_text(encoding="utf-8", errors="replace")
    control_chars = CONTROL_CHARS_RE.findall(raw)
    monsters = json.loads(raw, strict=False)
    if not isinstance(monsters, list):
        raise ValueError("monsters.json must contain a top-level JSON array")
    return clean_text(monsters), {
        "monster_count": len(monsters),
        "raw_control_character_count": len(control_chars),
    }


def load_tier_chart(path: Path) -> dict[str, TierEntry]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if not rows:
        raise ValueError("Tier CSV is empty")

    headers: list[tuple[int, int]] = []
    for header in rows[0]:
        match = TIER_HEADER_RE.fullmatch(header.strip())
        if not match:
            raise ValueError(f"Unsupported tier header: {header!r}")
        headers.append((int(match.group(1)), int(match.group(2))))

    tier_map: dict[str, TierEntry] = {}
    for row in rows[1:]:
        padded = row + [""] * (len(headers) - len(row))
        for index, cell in enumerate(padded[: len(headers)]):
            chart_name = cell.strip()
            if not chart_name:
                continue
            pokemon_name = normalize_name(chart_name)
            tier, points = headers[index]
            if pokemon_name in tier_map:
                raise ValueError(f"Duplicate tier-chart species: {pokemon_name}")
            tier_map[pokemon_name] = TierEntry(chart_name, pokemon_name, tier, points)
    return tier_map


def build_evolution_graph(
    monsters: list[dict[str, Any]],
) -> tuple[dict[int, dict[str, Any]], dict[int, set[int]]]:
    by_id = {int(monster["id"]): monster for monster in monsters}
    graph: dict[int, set[int]] = defaultdict(set)
    for monster_id, monster in by_id.items():
        graph[monster_id]
        for evolution in monster.get("evolutions", []):
            evolution_id = evolution.get("id")
            if isinstance(evolution_id, int) and evolution_id in by_id:
                graph[monster_id].add(evolution_id)
                graph[evolution_id].add(monster_id)
    return by_id, graph


def nearest_tier_species(
    monster_id: int,
    by_id: dict[int, dict[str, Any]],
    graph: dict[int, set[int]],
    tier_map: dict[str, TierEntry],
) -> tuple[str | None, int | None, list[str]]:
    own_name = normalize_name(str(by_id[monster_id]["name"]))
    if own_name in tier_map:
        return own_name, 0, [own_name]

    queue: deque[tuple[int, int]] = deque([(monster_id, 0)])
    visited = {monster_id}
    nearest_distance: int | None = None
    candidates: list[str] = []

    while queue:
        current_id, distance = queue.popleft()
        if nearest_distance is not None and distance > nearest_distance:
            break
        current_name = normalize_name(str(by_id[current_id]["name"]))
        if current_name in tier_map:
            nearest_distance = distance
            candidates.append(current_name)
            continue
        for neighbor in sorted(graph[current_id]):
            if neighbor not in visited:
                visited.add(neighbor)
                queue.append((neighbor, distance + 1))

    candidates = sorted(set(candidates))
    if not candidates:
        return None, None, []
    chosen = max(
        candidates,
        key=lambda name: (tier_map[name].points, -tier_map[name].tier, name),
    )
    return chosen, nearest_distance, candidates


def build_tier_mapping(
    monsters: list[dict[str, Any]], tier_map: dict[str, TierEntry]
) -> tuple[dict[int, dict[str, Any]], dict[str, set[str]], list[dict[str, Any]]]:
    by_id, graph = build_evolution_graph(monsters)
    mapping_by_id: dict[int, dict[str, Any]] = {}
    name_to_families: dict[str, set[str]] = defaultdict(set)
    rows: list[dict[str, Any]] = []

    for monster_id in sorted(by_id):
        monster = by_id[monster_id]
        pokemon = normalize_name(str(monster["name"]))
        tier_species, distance, candidates = nearest_tier_species(
            monster_id, by_id, graph, tier_map
        )
        tier_entry = tier_map.get(tier_species) if tier_species else None
        row = {
            "pokemon_id": monster_id,
            "pokemon": pokemon,
            "scoring_family": tier_species or "",
            "tier_chart_species": tier_species or "",
            "tier": tier_entry.tier if tier_entry else "",
            "base_points": tier_entry.points if tier_entry else "",
            "mapping_type": "exact" if distance == 0 else ("evolution_family" if tier_entry else "unmapped"),
            "evolution_distance": distance if distance is not None else "",
            "candidate_tier_species": " | ".join(candidates),
            "ambiguous_mapping": len(candidates) > 1,
            "obtainable": bool(monster.get("obtainable", False)),
        }
        rows.append(row)
        mapping_by_id[monster_id] = row
        if tier_species:
            name_to_families[name_key(pokemon)].add(tier_species)
            name_to_families[name_key(tier_species)].add(tier_species)
    return mapping_by_id, name_to_families, rows


def parse_percent(value: Any) -> float:
    if value is None:
        return 0.0
    text = str(value).strip()
    if not text or text == "--":
        return 0.0
    if text.endswith("%"):
        text = text[:-1]
    try:
        return float(text)
    except ValueError:
        return 0.0


def family_set_from_names(
    raw_names: Iterable[str], name_to_families: dict[str, set[str]]
) -> set[str]:
    result: set[str] = set()
    unknown: list[str] = []
    for raw_name in raw_names:
        raw_name = raw_name.strip()
        if not raw_name:
            continue
        families = name_to_families.get(name_key(raw_name), set())
        if not families:
            unknown.append(raw_name)
            continue
        result.update(families)
    if unknown:
        raise ValueError(
            "Could not map caught Pokémon/family names: " + ", ".join(sorted(unknown))
        )
    return result


def iter_active_horde_rows(
    monsters: list[dict[str, Any]], mapping_by_id: dict[int, dict[str, Any]]
) -> Iterator[dict[str, Any]]:
    record_id = 0
    for monster in monsters:
        monster_id = int(monster["id"])
        mapping = mapping_by_id[monster_id]
        pokemon = normalize_name(str(monster["name"]))
        for location in monster.get("locations", []):
            is_3x = bool(location.get("is_horde_3x"))
            is_5x = bool(location.get("is_horde_5x"))
            if not (is_3x or is_5x):
                continue
            if mapping["base_points"] == "":
                continue
            horde_size = 5 if is_5x else 3
            season = str(location.get("season", "Any"))
            active_seasons: Sequence[str] = SEASONS if season.casefold() == "any" else (season,)
            for active_season in active_seasons:
                for time_of_day in TIMES:
                    raw_split = parse_percent(location.get(f"rarity_{time_of_day}"))
                    if raw_split <= 0:
                        continue
                    record_id += 1
                    yield {
                        "horde_record_id": record_id,
                        "pokemon_id": monster_id,
                        "pokemon": pokemon,
                        "scoring_family": mapping["scoring_family"],
                        "tier": mapping["tier"],
                        "base_points": float(mapping["base_points"]),
                        "mapping_type": mapping["mapping_type"],
                        "region_id": location.get("region_id", ""),
                        "region": location.get("region_name", ""),
                        "location_id": location.get("location_id", ""),
                        "location": location.get("location_name", ""),
                        "location_full": location.get("location_name_full", ""),
                        "encounter_type": location.get("type", ""),
                        "horde_size": horde_size,
                        "min_level": location.get("min_level", ""),
                        "max_level": location.get("max_level", ""),
                        "source_season": season,
                        "season": active_season,
                        "time_of_day": time_of_day,
                        "raw_horde_split_percent": raw_split,
                        "rarity_flags": location.get("rarity_flags", ""),
                    }


def annotate_location_instances(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Keep same-named maps separate and add unambiguous display labels."""
    ids_by_name: dict[tuple[Any, ...], set[str]] = defaultdict(set)
    for row in rows:
        key = (row["region_id"], row["region"], row["location_full"])
        ids_by_name[key].add(str(row["location_id"]))
    for row in rows:
        key = (row["region_id"], row["region"], row["location_full"])
        count = len(ids_by_name[key])
        needs_id = count > 1
        row["location_display"] = (
            f"{row['location_full']} [Location ID {row['location_id']}]"
            if needs_id else str(row["location_full"])
        )
        row["location_name_instance_count"] = count
        row["location_name_requires_id"] = needs_id
    return rows, {
        "reused_location_name_count": sum(1 for ids in ids_by_name.values() if len(ids) > 1),
        "rows_requiring_location_id": sum(1 for row in rows if row["location_name_requires_id"]),
    }


def annotate_temporal_exclusivity(
    rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any]]:
    """Add the requested season/time exclusivity measure to every horde row.

    The game has four seasons and three time windows, therefore twelve possible
    temporal combinations. For each encountered species:

        availability quotient = distinct combinations / 12
        temporal exclusivity = 1 / quotient = 12 / distinct combinations

    The same information is also calculated for the union of each scoring
    evolution family for transparency, but route scoring uses the species-level
    measure requested by the team.
    """
    combos_by_species: dict[str, set[tuple[str, str]]] = defaultdict(set)
    combos_by_family: dict[str, set[tuple[str, str]]] = defaultdict(set)
    locations_by_species: dict[str, set[tuple[Any, Any]]] = defaultdict(set)
    species_family: dict[str, str] = {}
    species_tier: dict[str, Any] = {}
    species_base_points: dict[str, float] = {}

    for row in rows:
        species = str(row["pokemon"])
        family = str(row["scoring_family"])
        combo = (str(row["season"]), str(row["time_of_day"]))
        combos_by_species[species].add(combo)
        combos_by_family[family].add(combo)
        locations_by_species[species].add((row["region_id"], row["location_id"]))
        species_family[species] = family
        species_tier[species] = row["tier"]
        species_base_points[species] = float(row["base_points"])

    order = {season: index for index, season in enumerate(SEASONS)}
    time_order = {time_name: index for index, time_name in enumerate(TIMES)}

    summary_rows: list[dict[str, Any]] = []
    for species in sorted(combos_by_species):
        family = species_family[species]
        species_combos = combos_by_species[species]
        family_combos = combos_by_family[family]
        species_count = len(species_combos)
        family_count = len(family_combos)
        summary_rows.append({
            "pokemon": species,
            "scoring_family": family,
            "tier": species_tier[species],
            "base_points": species_base_points[species],
            "first_team_catch_points": species_base_points[species] + DEFAULT_UNIQUE_BONUS,
            "possible_temporal_combinations": TOTAL_TEMPORAL_COMBINATIONS,
            "species_temporal_combination_count": species_count,
            "species_temporal_availability_quotient": format_number(species_count / TOTAL_TEMPORAL_COMBINATIONS),
            "species_temporal_exclusivity": format_number(TOTAL_TEMPORAL_COMBINATIONS / species_count),
            "species_temporal_combinations": " | ".join(
                f"{season}/{time_name}"
                for season, time_name in sorted(
                    species_combos, key=lambda item: (order.get(item[0], 99), time_order.get(item[1], 99))
                )
            ),
            "distinct_location_count": len(locations_by_species[species]),
            "family_temporal_combination_count": family_count,
            "family_temporal_availability_quotient": format_number(family_count / TOTAL_TEMPORAL_COMBINATIONS),
            "family_temporal_exclusivity": format_number(TOTAL_TEMPORAL_COMBINATIONS / family_count),
        })

    summary_by_species = {str(row["pokemon"]): row for row in summary_rows}
    for row in rows:
        metrics = summary_by_species[str(row["pokemon"])]
        for key in (
            "possible_temporal_combinations",
            "species_temporal_combination_count",
            "species_temporal_availability_quotient",
            "species_temporal_exclusivity",
            "family_temporal_combination_count",
            "family_temporal_availability_quotient",
            "family_temporal_exclusivity",
        ):
            row[key] = metrics[key]

    exclusivity_values = [float(row["species_temporal_exclusivity"]) for row in summary_rows]
    return rows, summary_rows, {
        "temporal_combination_universe": TOTAL_TEMPORAL_COMBINATIONS,
        "temporal_exclusivity_species_count": len(summary_rows),
        "maximum_species_temporal_exclusivity": max(exclusivity_values, default=0.0),
        "minimum_species_temporal_exclusivity": min(exclusivity_values, default=0.0),
        "single_combination_species_count": sum(
            1 for row in summary_rows if int(row["species_temporal_combination_count"]) == 1
        ),
        "all_combinations_species_count": sum(
            1 for row in summary_rows
            if int(row["species_temporal_combination_count"]) == TOTAL_TEMPORAL_COMBINATIONS
        ),
    }


def context_key(row: dict[str, Any]) -> tuple[Any, ...]:
    return (
        row["region_id"],
        row["region"],
        row["location_id"],
        row["location_full"],
        row["encounter_type"],
        row["season"],
        row["time_of_day"],
    )


def context_id_from_key(key: tuple[Any, ...]) -> str:
    return "|".join(str(value) for value in key)


def probability_basis(encounter_type: str, total_raw_split: float) -> str:
    if encounter_type.casefold() == "sweet scent":
        return "Normalized explicit Sweet Scent horde table"
    if math.isclose(total_raw_split, STANDARD_HORDE_POOL_PERCENT, abs_tol=0.02):
        return "Normalized standard 5% wild horde split"
    return f"Normalized active horde splits (raw total {format_number(total_raw_split, 4)}%)"


def normalize_horde_probabilities(
    raw_rows: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        grouped[context_key(row)].append(row)

    normalized_rows: list[dict[str, Any]] = []
    by_context: dict[str, list[dict[str, Any]]] = {}
    for key, records in grouped.items():
        total_raw = sum(float(record["raw_horde_split_percent"]) for record in records)
        if total_raw <= 0:
            continue
        expected_checks = sum(
            (float(record["raw_horde_split_percent"]) / total_raw) * float(record["horde_size"])
            for record in records
        )
        context_id = context_id_from_key(key)
        basis = probability_basis(str(key[4]), total_raw)
        context_records: list[dict[str, Any]] = []
        for record in records:
            roll_probability = float(record["raw_horde_split_percent"]) / total_raw
            check_weight = roll_probability * float(record["horde_size"])
            row = dict(record)
            row.update({
                "context_id": context_id,
                "horde_pool_raw_total_percent": format_number(total_raw),
                "horde_roll_probability": format_number(roll_probability),
                "horde_roll_probability_percent": format_number(roll_probability * 100),
                "expected_checks_per_sweet_scent": format_number(expected_checks),
                "shiny_check_share": format_number(check_weight / expected_checks if expected_checks else 0),
                "shiny_check_share_percent": format_number((check_weight / expected_checks * 100) if expected_checks else 0),
                "probability_basis": basis,
            })
            context_records.append(row)
            normalized_rows.append(row)
        by_context[context_id] = context_records

    normalized_rows.sort(
        key=lambda row: (
            str(row["region"]),
            str(row["location_full"]),
            str(row["encounter_type"]),
            str(row["season"]),
            str(row["time_of_day"]),
            -float(row["horde_roll_probability"]),
            str(row["pokemon"]),
        )
    )
    return normalized_rows, by_context


def score_for_family(family: str, base_points: float, state: ScoringState) -> tuple[float, str]:
    key = name_key(family)
    if key in state.player_caught_families:
        return state.duplicate_points, "player_duplicate"
    if key in state.team_caught_families:
        return base_points, "team_already_unique"
    return base_points + state.unique_bonus, "new_team_unique"


def aggregate_context_targets(
    records: list[dict[str, Any]],
    state: ScoringState,
    use_temporal_exclusivity: bool = False,
    exclusivity_power: float = DEFAULT_EXCLUSIVITY_POWER,
) -> list[dict[str, Any]]:
    family_groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for record in records:
        family_groups[str(record["scoring_family"])].append(record)

    target_rows: list[dict[str, Any]] = []
    expected_checks = sum(
        float(record["horde_roll_probability"]) * float(record["horde_size"])
        for record in records
    )
    for family, family_records in family_groups.items():
        base_points = float(family_records[0]["base_points"])
        effective_score, score_status = score_for_family(family, base_points, state)
        horde_probability = sum(float(record["horde_roll_probability"]) for record in family_records)
        check_weight = sum(
            float(record["horde_roll_probability"]) * float(record["horde_size"])
            for record in family_records
        )
        legacy_contribution = check_weight * effective_score
        exclusivity_contribution = sum(
            float(record["horde_roll_probability"])
            * float(record["horde_size"])
            * effective_score
            * (float(record["species_temporal_exclusivity"]) ** exclusivity_power)
            for record in family_records
        )
        average_exclusivity = (
            exclusivity_contribution / legacy_contribution if legacy_contribution else 1.0
        )
        ranking_contribution = (
            exclusivity_contribution if use_temporal_exclusivity else legacy_contribution
        )
        species_details = sorted({
            (
                str(record["pokemon"]),
                int(record["species_temporal_combination_count"]),
                float(record["species_temporal_exclusivity"]),
            )
            for record in family_records
        })
        target_rows.append({
            "context_id": family_records[0]["context_id"],
            "region_id": family_records[0]["region_id"],
            "region": family_records[0]["region"],
            "location_id": family_records[0]["location_id"],
            "location_full": family_records[0]["location_full"],
            "location_display": family_records[0]["location_display"],
            "location_name_instance_count": family_records[0]["location_name_instance_count"],
            "location_name_requires_id": family_records[0]["location_name_requires_id"],
            "encounter_type": family_records[0]["encounter_type"],
            "season": family_records[0]["season"],
            "time_of_day": family_records[0]["time_of_day"],
            "scoring_family": family,
            "encountered_species": " | ".join(sorted({str(record["pokemon"]) for record in family_records})),
            "tier": family_records[0]["tier"],
            "base_points": base_points,
            "unique_bonus": state.unique_bonus if score_status == "new_team_unique" else 0.0,
            "effective_points_if_shiny": effective_score,
            "score_status": score_status,
            "horde_roll_probability": format_number(horde_probability),
            "horde_roll_probability_percent": format_number(horde_probability * 100),
            "shiny_check_share": format_number(check_weight / expected_checks if expected_checks else 0),
            "shiny_check_share_percent": format_number((check_weight / expected_checks * 100) if expected_checks else 0),
            "weighted_horde_size": format_number(check_weight / horde_probability if horde_probability else 0),
            "species_temporal_exclusivity_average": format_number(average_exclusivity, 6),
            "species_temporal_exclusivity_min": format_number(min(item[2] for item in species_details)),
            "species_temporal_exclusivity_max": format_number(max(item[2] for item in species_details)),
            "species_temporal_combination_count_min": min(item[1] for item in species_details),
            "species_temporal_combination_count_max": max(item[1] for item in species_details),
            "species_temporal_exclusivity_details": " | ".join(
                f"{species}: {count}/12 combos, x{format_number(multiplier, 4)}"
                for species, count, multiplier in species_details
            ),
            "score_index_contribution": format_number(legacy_contribution),
            "exclusivity_adjusted_score_index_contribution": format_number(exclusivity_contribution, 6),
            "ranking_score_index_contribution": format_number(ranking_contribution),
            "ranking_mode": "temporal_exclusivity" if use_temporal_exclusivity else "legacy_no_exclusivity",
        })

    target_rows.sort(
        key=lambda row: (
            float(row["ranking_score_index_contribution"]),
            float(row["effective_points_if_shiny"]),
            float(row["shiny_check_share"]),
            str(row["scoring_family"]),
        ),
        reverse=True,
    )
    for index, row in enumerate(target_rows, start=1):
        row["target_rank"] = index
    return target_rows


def rank_contexts(
    by_context: dict[str, list[dict[str, Any]]],
    state: ScoringState,
    use_temporal_exclusivity: bool = False,
    exclusivity_power: float = DEFAULT_EXCLUSIVITY_POWER,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    ranking_rows: list[dict[str, Any]] = []
    all_target_rows: list[dict[str, Any]] = []

    for context_id, records in by_context.items():
        targets = aggregate_context_targets(
            records, state, use_temporal_exclusivity, exclusivity_power
        )
        if not targets:
            continue
        all_target_rows.extend(targets)
        expected_checks = sum(
            float(record["horde_roll_probability"]) * float(record["horde_size"])
            for record in records
        )
        base_score_index = sum(
            float(record["horde_roll_probability"])
            * float(record["horde_size"])
            * float(record["base_points"])
            for record in records
        )
        exclusivity_base_score_index = sum(
            float(record["horde_roll_probability"])
            * float(record["horde_size"])
            * float(record["base_points"])
            * (float(record["species_temporal_exclusivity"]) ** exclusivity_power)
            for record in records
        )
        state_score_index = sum(float(target["score_index_contribution"]) for target in targets)
        exclusivity_state_score_index = sum(
            float(target["exclusivity_adjusted_score_index_contribution"]) for target in targets
        )
        new_unique_index = sum(
            float(target["score_index_contribution"])
            for target in targets if target["score_status"] == "new_team_unique"
        )
        exclusivity_new_unique_index = sum(
            float(target["exclusivity_adjusted_score_index_contribution"])
            for target in targets if target["score_status"] == "new_team_unique"
        )
        new_unique_check_weight = sum(
            float(target["shiny_check_share"]) for target in targets
            if target["score_status"] == "new_team_unique"
        )
        duplicate_check_weight = sum(
            float(target["shiny_check_share"]) for target in targets
            if target["score_status"] == "player_duplicate"
        )
        ranking_score = (
            exclusivity_state_score_index if use_temporal_exclusivity else state_score_index
        )
        ranking_new_unique = (
            exclusivity_new_unique_index if use_temporal_exclusivity else new_unique_index
        )
        primary = targets[0]
        fallback = targets[1] if len(targets) > 1 else None
        third = targets[2] if len(targets) > 2 else None
        first = records[0]
        ranking_rows.append({
            "context_id": context_id,
            "ranking_mode": "temporal_exclusivity" if use_temporal_exclusivity else "legacy_no_exclusivity",
            "region_id": first["region_id"],
            "region": first["region"],
            "location_id": first["location_id"],
            "location_full": first["location_full"],
            "location_display": first["location_display"],
            "location_name_instance_count": first["location_name_instance_count"],
            "location_name_requires_id": first["location_name_requires_id"],
            "encounter_type": first["encounter_type"],
            "season": first["season"],
            "time_of_day": first["time_of_day"],
            "probability_basis": first["probability_basis"],
            "horde_pool_raw_total_percent": first["horde_pool_raw_total_percent"],
            "family_count": len(targets),
            "species_count": len({str(record["pokemon"]) for record in records}),
            "expected_checks_per_sweet_scent": format_number(expected_checks),
            "expected_base_points_per_shiny": format_number(base_score_index / expected_checks if expected_checks else 0),
            "expected_state_points_per_shiny": format_number(state_score_index / expected_checks if expected_checks else 0),
            "expected_exclusivity_adjusted_points_per_shiny": format_number(exclusivity_state_score_index / expected_checks if expected_checks else 0, 6),
            "base_score_index_per_sweet_scent": format_number(base_score_index),
            "state_score_index_per_sweet_scent": format_number(state_score_index),
            "exclusivity_adjusted_base_score_index_per_sweet_scent": format_number(exclusivity_base_score_index, 6),
            "exclusivity_adjusted_state_score_index_per_sweet_scent": format_number(exclusivity_state_score_index, 6),
            "ranking_score_index_per_sweet_scent": format_number(ranking_score, 6),
            "new_unique_score_index": format_number(new_unique_index),
            "exclusivity_adjusted_new_unique_score_index": format_number(exclusivity_new_unique_index, 6),
            "ranking_new_unique_score_index": format_number(ranking_new_unique, 6),
            "new_unique_shiny_check_share": format_number(new_unique_check_weight),
            "new_unique_shiny_check_share_percent": format_number(new_unique_check_weight * 100),
            "player_duplicate_shiny_check_share": format_number(duplicate_check_weight),
            "player_duplicate_shiny_check_share_percent": format_number(duplicate_check_weight * 100),
            "top_target": primary["encountered_species"],
            "top_target_family": primary["scoring_family"],
            "top_target_points": primary["effective_points_if_shiny"],
            "top_target_temporal_exclusivity": primary["species_temporal_exclusivity_average"],
            "top_target_temporal_combinations": primary["species_temporal_combination_count_min"],
            "top_target_horde_probability_percent": primary["horde_roll_probability_percent"],
            "top_target_shiny_check_share_percent": primary["shiny_check_share_percent"],
            "fallback_target": fallback["encountered_species"] if fallback else "",
            "fallback_target_family": fallback["scoring_family"] if fallback else "",
            "fallback_target_points": fallback["effective_points_if_shiny"] if fallback else "",
            "fallback_target_temporal_exclusivity": fallback["species_temporal_exclusivity_average"] if fallback else "",
            "fallback_horde_probability_percent": fallback["horde_roll_probability_percent"] if fallback else "",
            "third_target": third["encountered_species"] if third else "",
            "third_target_family": third["scoring_family"] if third else "",
            "all_targets": " | ".join(target["encountered_species"] for target in targets),
            "all_scoring_families": " | ".join(target["scoring_family"] for target in targets),
        })

    ranking_rows.sort(
        key=lambda row: (
            float(row["ranking_score_index_per_sweet_scent"]),
            float(row["ranking_new_unique_score_index"]),
            float(row["expected_exclusivity_adjusted_points_per_shiny"] if use_temporal_exclusivity else row["expected_state_points_per_shiny"]),
            float(row["new_unique_shiny_check_share"]),
            int(row["family_count"]),
        ),
        reverse=True,
    )
    for rank, row in enumerate(ranking_rows, start=1):
        row["context_rank"] = rank

    context_rank_by_id = {str(row["context_id"]): int(row["context_rank"]) for row in ranking_rows}
    all_target_rows.sort(
        key=lambda row: (
            context_rank_by_id.get(str(row["context_id"]), 10**9),
            int(row["target_rank"]),
        )
    )
    return ranking_rows, all_target_rows


def best_context_per_route(
    ranking_rows: list[dict[str, Any]], per_season: bool = False
) -> list[dict[str, Any]]:
    best: dict[tuple[Any, ...], dict[str, Any]] = {}
    route_context_count: dict[tuple[Any, ...], int] = defaultdict(int)
    for row in ranking_rows:
        key: tuple[Any, ...]
        if per_season:
            key = (
                row["region_id"], row["region"], row["location_id"],
                row["location_full"], row["season"],
            )
        else:
            key = (
                row["region_id"], row["region"], row["location_id"], row["location_full"],
            )
        route_context_count[key] += 1
        current = best.get(key)
        if current is None or float(row["ranking_score_index_per_sweet_scent"]) > float(current["ranking_score_index_per_sweet_scent"]):
            best[key] = dict(row)

    result = list(best.values())
    for row in result:
        if per_season:
            key = (
                row["region_id"], row["region"], row["location_id"],
                row["location_full"], row["season"],
            )
        else:
            key = (
                row["region_id"], row["region"], row["location_id"], row["location_full"],
            )
        row["available_context_count"] = route_context_count[key]
    result.sort(
        key=lambda row: (
            float(row["ranking_score_index_per_sweet_scent"]),
            float(row["ranking_new_unique_score_index"]),
            float(row["new_unique_shiny_check_share"]),
        ),
        reverse=True,
    )
    for index, row in enumerate(result, start=1):
        row["route_rank"] = index
    if per_season:
        result.sort(
            key=lambda row: (
                SEASONS.index(str(row["season"])) if str(row["season"]) in SEASONS else 99,
                float(row["ranking_score_index_per_sweet_scent"]) * -1,
                float(row["ranking_new_unique_score_index"]) * -1,
            )
        )
        counts: dict[str, int] = defaultdict(int)
        for row in result:
            counts[str(row["season"])] += 1
            row["season_route_rank"] = counts[str(row["season"])]
    return result


def greedy_unique_strategy(
    by_context: dict[str, list[dict[str, Any]]],
    initial_state: ScoringState,
    max_steps: int,
    use_temporal_exclusivity: bool = False,
    exclusivity_power: float = DEFAULT_EXCLUSIVITY_POWER,
) -> list[dict[str, Any]]:
    """Build a fast greedy route ladder for collecting new scoring families.

    Target contributions are static while a family is still team-unique, so
    they are precomputed once. Each iteration then only removes families that
    have already been selected. This produces the same greedy choices as the
    prior implementation while making dual legacy/exclusivity exports fast.
    """
    team_caught = set(initial_state.team_caught_families)
    player_caught = set(initial_state.player_caught_families)
    output: list[dict[str, Any]] = []

    precomputed: dict[str, list[dict[str, Any]]] = {}
    for context_id, records in by_context.items():
        targets = aggregate_context_targets(
            records, initial_state, use_temporal_exclusivity, exclusivity_power
        )
        new_targets = [target for target in targets if target["score_status"] == "new_team_unique"]
        if new_targets:
            precomputed[context_id] = new_targets

    for step in range(1, max_steps + 1):
        best_candidate: tuple[float, float, float, str, list[dict[str, Any]]] | None = None
        for context_id, targets in precomputed.items():
            remaining_targets = [
                target for target in targets
                if name_key(str(target["scoring_family"])) not in team_caught
            ]
            if not remaining_targets:
                continue
            remaining_value = sum(
                float(target["ranking_score_index_contribution"])
                for target in remaining_targets
            )
            remaining_check_share = sum(
                float(target["shiny_check_share"]) for target in remaining_targets
            )
            highest_target = float(remaining_targets[0]["ranking_score_index_contribution"])
            candidate = (
                remaining_value, highest_target, remaining_check_share, context_id, remaining_targets
            )
            if best_candidate is None or candidate[:4] > best_candidate[:4]:
                best_candidate = candidate
        if best_candidate is None:
            break

        remaining_value, _, remaining_check_share, context_id, new_targets = best_candidate
        target = new_targets[0]
        family_key = name_key(str(target["scoring_family"]))
        team_caught.add(family_key)
        player_caught.add(family_key)
        output.append({
            "strategy_step": step,
            "ranking_mode": "temporal_exclusivity" if use_temporal_exclusivity else "legacy_no_exclusivity",
            "region": target["region"],
            "location_id": target["location_id"],
            "location_full": target["location_full"],
            "location_display": target["location_display"],
            "location_name_requires_id": target["location_name_requires_id"],
            "encounter_type": target["encounter_type"],
            "season": target["season"],
            "time_of_day": target["time_of_day"],
            "recommended_target": target["encountered_species"],
            "scoring_family": target["scoring_family"],
            "tier": target["tier"],
            "points_on_first_team_catch": target["effective_points_if_shiny"],
            "target_temporal_combination_count": target["species_temporal_combination_count_min"],
            "target_temporal_exclusivity": target["species_temporal_exclusivity_average"],
            "target_horde_probability_percent": target["horde_roll_probability_percent"],
            "target_shiny_check_share_percent": target["shiny_check_share_percent"],
            "target_legacy_score_index_contribution": target["score_index_contribution"],
            "target_exclusivity_adjusted_score_index_contribution": target["exclusivity_adjusted_score_index_contribution"],
            "target_ranking_score_index_contribution": target["ranking_score_index_contribution"],
            "remaining_new_unique_route_index_before_step": format_number(remaining_value),
            "remaining_new_unique_shiny_check_share_percent": format_number(remaining_check_share * 100),
            "other_new_targets_at_context": " | ".join(
                item["encountered_species"] for item in new_targets[1:]
            ),
            "context_id": context_id,
            "strategy_note": (
                "Greedy unique-family acquisition heuristic with temporal exclusivity; rerun after actual team catches."
                if use_temporal_exclusivity
                else "Legacy greedy unique-family acquisition heuristic without temporal exclusivity; rerun after actual team catches."
            ),
        })
    return output


def build_reused_location_guide(
    ranking_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Return the best context for every same-named location instance."""
    best: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in ranking_rows:
        if not bool(row.get("location_name_requires_id")):
            continue
        key = (str(row["region"]), str(row["location_full"]), str(row["location_id"]))
        current = best.get(key)
        if current is None or int(row["context_rank"]) < int(current["context_rank"]):
            best[key] = row
    result: list[dict[str, Any]] = []
    for key in sorted(best, key=lambda item: (item[0], item[1], item[2])):
        row = best[key]
        result.append({
            "ranking_mode": row["ranking_mode"],
            "region": row["region"],
            "location_full": row["location_full"],
            "location_id": row["location_id"],
            "location_display": row["location_display"],
            "best_context_rank": row["context_rank"],
            "best_season": row["season"],
            "best_time_of_day": row["time_of_day"],
            "encounter_type": row["encounter_type"],
            "ranking_score_index": row["ranking_score_index_per_sweet_scent"],
            "legacy_score_index": row["state_score_index_per_sweet_scent"],
            "top_target": row["top_target"],
            "top_target_temporal_exclusivity": row["top_target_temporal_exclusivity"],
            "fallback_target": row["fallback_target"],
            "all_targets": row["all_targets"],
        })
    return result


def compare_ranking_versions(
    exclusivity_rows: list[dict[str, Any]],
    legacy_rows: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Compare adjusted and legacy context ranks using the same context_id."""
    legacy_by_context = {str(row["context_id"]): row for row in legacy_rows}
    result: list[dict[str, Any]] = []
    for row in exclusivity_rows:
        legacy = legacy_by_context.get(str(row["context_id"]))
        legacy_rank = int(legacy["context_rank"]) if legacy else 0
        exclusive_rank = int(row["context_rank"])
        result.append({
            "context_id": row["context_id"],
            "exclusivity_rank": exclusive_rank,
            "legacy_rank": legacy_rank or "",
            "rank_improvement": legacy_rank - exclusive_rank if legacy_rank else "",
            "region": row["region"],
            "location_id": row["location_id"],
            "location_display": row["location_display"],
            "encounter_type": row["encounter_type"],
            "season": row["season"],
            "time_of_day": row["time_of_day"],
            "exclusivity_adjusted_score_index": row["ranking_score_index_per_sweet_scent"],
            "legacy_score_index": row["state_score_index_per_sweet_scent"],
            "top_target": row["top_target"],
            "top_target_temporal_combinations": row["top_target_temporal_combinations"],
            "top_target_temporal_exclusivity": row["top_target_temporal_exclusivity"],
            "fallback_target": row["fallback_target"],
        })
    return result


def event_schedule_rows() -> list[dict[str, Any]]:
    return [
        {"event_week": 1, "season": "Summer", "start_utc": "2026-08-01 00:00", "end_utc": "2026-08-07 23:59"},
        {"event_week": 2, "season": "Autumn", "start_utc": "2026-08-08 00:00", "end_utc": "2026-08-14 23:59"},
        {"event_week": 3, "season": "Winter", "start_utc": "2026-08-15 00:00", "end_utc": "2026-08-21 23:59"},
        {"event_week": 4, "season": "Spring", "start_utc": "2026-08-22 00:00", "end_utc": "2026-08-28 23:59"},
    ]


def rule_source_rows() -> list[dict[str, Any]]:
    return [
        {
            "rule": "Unique Species Bonus",
            "value": "+8 points for the first team catch of each evolution line",
            "source_url": OFFICIAL_RULES_URL,
        },
        {
            "rule": "Duplicate Penalty",
            "value": "Later catches from the same evolution line by the same player are worth 1 point",
            "source_url": OFFICIAL_RULES_URL,
        },
        {
            "rule": "Evolution-line scoring",
            "value": "All Pokémon in the same scoring evolution line inherit the same tier value",
            "source_url": OFFICIAL_RULES_URL,
        },
        {
            "rule": "Event season order",
            "value": "Summer > Autumn > Winter > Spring, rotating every seven days",
            "source_url": OFFICIAL_RULES_URL,
        },
        {
            "rule": "Reference mirror",
            "value": "Readable rules mirror used when the forum blocks automated retrieval",
            "source_url": RULES_MIRROR_URL,
        },
        {
            "rule": "Horde probability model",
            "value": "Sweet Scent normalizes across all active horde splits in a route context",
            "source_url": "User-provided mechanics clarification",
        },
        {
            "rule": "Map-instance identity",
            "value": "Same-named maps or rooms remain separate; location_id is the authoritative grouping key",
            "source_url": "User-provided PokeMMO forum clarification",
        },
        {
            "rule": "Temporal exclusivity strategy weight",
            "value": "Species exclusivity = 12 / distinct season-time combinations; adjusted score multiplies each species contribution by this factor",
            "source_url": "User-provided strategy requirement",
        },
    ]


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("", encoding="utf-8")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def read_config(path: Path | None) -> dict[str, Any]:
    if path is None:
        return {}
    with path.open("r", encoding="utf-8") as handle:
        config = json.load(handle)
    if not isinstance(config, dict):
        raise ValueError("Config must be a JSON object")
    return config


def split_names(value: str) -> list[str]:
    return [item.strip() for item in value.split(",") if item.strip()]


def build_readme(output_dir: Path, diagnostics: dict[str, Any]) -> None:
    top = diagnostics.get("top_route_context") or {}
    top_exclusive = diagnostics.get("top_route_context_with_exclusivity") or {}
    content = f"""# PokeMMO Shiny Wars 2026 Horde Route Analyzer

## Purpose

This package ranks every 3x and 5x horde marked in `monsters.json`, maps each encountered Pokémon to its Shiny Wars evolution-line score, applies the 2026 Unique Species and Duplicate rules, and provides both a legacy ranking and a temporal-exclusivity ranking.

## Rules implemented

- The first shiny from an evolution line caught by the team receives **base tier points + 8**.
- Once the team already owns that evolution line, a different player can still receive the normal base tier points.
- Once the current player already owns that evolution line, another normal shiny from that line is worth **1 point**.
- All Pokémon assigned to the same scoring evolution line inherit the same tier points.
- Shiny Alpha, Secret Shiny, Safari and Egg-specific scoring are outside this Sweet Scent horde route model.

Official rules: {OFFICIAL_RULES_URL}

Readable rules mirror: {RULES_MIRROR_URL}

## Horde probability model

Normal wild encounter tables store hordes as a **5% wild-encounter pool**. Sweet Scent rolls between the active horde splits:

- `2.5% / 5% = 50%` Sweet Scent horde probability
- `1% / 5% = 20%` Sweet Scent horde probability

For every route context, the parser calculates:

`Horde roll probability = raw horde split / sum of active horde splits`

This same normalization is used for the explicit early-game `type = Sweet Scent` horde tables. No horde-marked records are excluded.

## Map and room identity

`location_id` is the authoritative map-instance key. Same-named maps or rooms with
different IDs are never merged. Reused names are exported as `Name [Location ID 123]`.
Use `/loc` in game to identify the exact room.

## Ranking formulas

Legacy backup:

`Legacy score index = Σ(horde probability × horde size × score if shiny)`

Recommended temporal-exclusivity strategy:

`Availability quotient = distinct season/time combinations ÷ 12`

`Temporal exclusivity = 1 ÷ availability quotient = 12 ÷ distinct combinations`

`Adjusted score index = Σ(legacy target contribution × species temporal exclusivity)`

This index is proportional to expected Shiny Wars points per Sweet Scent activation. The common per-check shiny probability is omitted because it does not change the ordering of normal wild horde routes.

The exact score applied to a family is state-aware:

1. Current player already caught the family → `1 point`
2. Team caught it, current player did not → `base tier points`
3. Team has not caught it → `base tier points + 8 unique bonus`

## Main output files

- `pokemon_evolution_points_mapping.csv` — all JSON entries mapped to scoring families and points
- `horde_encounters_by_time.csv` — every active horde row with Sweet Scent probability and points
- `route_context_rankings_with_exclusivity.csv` — recommended ranking using temporal exclusivity
- `route_context_rankings.csv` — legacy backup without exclusivity
- `route_best_contexts_with_exclusivity.csv` — recommended best context for each route
- `route_best_contexts.csv` — legacy backup
- `season_route_rankings_with_exclusivity.csv` — recommended seasonal route ranking
- `season_route_rankings.csv` — legacy seasonal backup
- `route_target_rankings_with_exclusivity.csv` — recommended targets/fallbacks with exclusivity
- `route_target_rankings.csv` — legacy targets/fallbacks
- `pokemon_temporal_exclusivity_mapping.csv` — every hord-able Pokémon with its 1–12 combination count and multiplier
- `route_rank_comparison.csv` — direct adjusted-vs-legacy rank movement
- `reused_location_id_guide_with_exclusivity.csv` — repeated map names separated by exact location ID
- `greedy_unique_strategy_with_exclusivity.csv` — recommended diversity route ladder
- `greedy_unique_strategy.csv` — legacy route ladder without exclusivity
- `season_schedule.csv` — event week and season mapping
- `rule_sources.csv` — rule provenance
- `parser_diagnostics.json` — validation statistics and active scoring state
- `shiny_wars_2026_team_spot_guide.xlsx` — formatted team workbook with recommended and legacy rankings

## Current data summary

- Monster records: **{diagnostics.get('monster_count', 0)}**
- Tier-chart scoring anchors: **{diagnostics.get('tier_chart_entry_count', 0)}**
- Active horde rows after time expansion: **{diagnostics.get('active_horde_row_count', 0)}**
- Route contexts: **{diagnostics.get('route_context_count', 0)}**
- Horde species mapped to points: **{diagnostics.get('mapped_horde_species_count', 0)} / {diagnostics.get('horde_species_count', 0)}**
- Standard contexts with a 5% raw horde pool: **{diagnostics.get('standard_five_percent_context_count', 0)}**

Recommended initial top context with temporal exclusivity:

- **{top_exclusive.get('region', '')} — {top_exclusive.get('location_display', top_exclusive.get('location_full', ''))}**
- {top_exclusive.get('encounter_type', '')}, {top_exclusive.get('season', '')}, {top_exclusive.get('time_of_day', '')}
- Top target: **{top_exclusive.get('top_target', '')}** ({top_exclusive.get('top_target_points', '')} points; exclusivity x{top_exclusive.get('top_target_temporal_exclusivity', '')})
- Fallback: **{top_exclusive.get('fallback_target', '')}**
- Adjusted score index: **{top_exclusive.get('ranking_score_index_per_sweet_scent', '')}**

Legacy top context without temporal exclusivity:

- **{top.get('region', '')} — {top.get('location_display', top.get('location_full', ''))}**
- {top.get('encounter_type', '')}, {top.get('season', '')}, {top.get('time_of_day', '')}
- Top target: **{top.get('top_target', '')}**
- Legacy score index: **{top.get('state_score_index_per_sweet_scent', '')}**

## Running the parser

```bash
python shiny_wars_horde_parser.py \
  --monsters input/monsters.json \
  --tiers input/shiny_wars_2026_tier_chart.csv \
  --output-dir output \
  --config config/shiny_wars_rules.json
```

Update the live state in `config/shiny_wars_rules.json` or pass names directly:

```bash
python shiny_wars_horde_parser.py \
  --monsters input/monsters.json \
  --tiers input/shiny_wars_2026_tier_chart.csv \
  --output-dir output \
  --team-caught "Volbeat,Illumise" \
  --player-caught "Volbeat"
```

The names may be any member of the evolution line; they are converted to the scoring family automatically.

## Strategy interpretation

`route_context_rankings_with_exclusivity.csv` is the recommended **best-next-route ranking for the supplied team/player state**. `route_context_rankings.csv` retains the prior no-exclusivity strategy as a backup. Rerunning after actual catches is the reliable optimization method because catches are random and the duplicate penalty is player-specific.

`greedy_unique_strategy_with_exclusivity.csv` is the recommended transparent planning heuristic. `greedy_unique_strategy.csv` preserves the legacy version. It repeatedly selects the context with the highest remaining chance-weighted value of uncaught evolution lines, then marks its highest-value target as acquired. It is useful for initial team assignments, but it should not be treated as a guaranteed globally optimal stochastic policy.
"""
    (output_dir / "README.md").write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--monsters", type=Path, required=True)
    parser.add_argument("--tiers", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--team-caught", default="", help="Comma-separated Pokémon or scoring families already caught by the team")
    parser.add_argument("--player-caught", default="", help="Comma-separated Pokémon or scoring families already caught by this player")
    parser.add_argument("--unique-bonus", type=float, default=None)
    parser.add_argument("--duplicate-points", type=float, default=None)
    parser.add_argument("--strategy-steps", type=int, default=None)
    parser.add_argument("--exclusivity-power", type=float, default=None, help="Exponent applied to the temporal exclusivity multiplier; default 1.0")
    args = parser.parse_args()

    config = read_config(args.config)
    unique_bonus = args.unique_bonus if args.unique_bonus is not None else float(config.get("unique_species_bonus", DEFAULT_UNIQUE_BONUS))
    duplicate_points = args.duplicate_points if args.duplicate_points is not None else float(config.get("duplicate_points", DEFAULT_DUPLICATE_POINTS))
    strategy_steps = args.strategy_steps if args.strategy_steps is not None else int(config.get("strategy_steps", 120))
    exclusivity_power = args.exclusivity_power if args.exclusivity_power is not None else float(config.get("temporal_exclusivity_weight_power", DEFAULT_EXCLUSIVITY_POWER))

    team_names = split_names(args.team_caught) or [str(item) for item in config.get("team_caught_families", [])]
    player_names = split_names(args.player_caught) or [str(item) for item in config.get("player_caught_families", [])]

    monsters, diagnostics = load_monsters(args.monsters)
    tier_map = load_tier_chart(args.tiers)
    mapping_by_id, name_to_families, mapping_rows = build_tier_mapping(monsters, tier_map)

    team_families = {name_key(name) for name in family_set_from_names(team_names, name_to_families)}
    player_families = {name_key(name) for name in family_set_from_names(player_names, name_to_families)}
    # A player's catch necessarily means the team has that family too.
    team_families.update(player_families)
    state = ScoringState(
        unique_bonus=unique_bonus,
        duplicate_points=duplicate_points,
        team_caught_families=frozenset(team_families),
        player_caught_families=frozenset(player_families),
    )

    raw_horde_rows = list(iter_active_horde_rows(monsters, mapping_by_id))
    raw_horde_rows, location_diagnostics = annotate_location_instances(raw_horde_rows)
    diagnostics.update(location_diagnostics)
    raw_horde_rows, temporal_exclusivity_rows, temporal_diagnostics = annotate_temporal_exclusivity(raw_horde_rows)
    diagnostics.update(temporal_diagnostics)

    exclusivity_by_species = {str(row["pokemon"]): row for row in temporal_exclusivity_rows}
    for mapping_row in mapping_rows:
        metrics = exclusivity_by_species.get(str(mapping_row["pokemon"]))
        if metrics:
            for key in (
                "possible_temporal_combinations",
                "species_temporal_combination_count",
                "species_temporal_availability_quotient",
                "species_temporal_exclusivity",
                "family_temporal_combination_count",
                "family_temporal_availability_quotient",
                "family_temporal_exclusivity",
            ):
                mapping_row[key] = metrics[key]
        else:
            mapping_row.update({
                "possible_temporal_combinations": TOTAL_TEMPORAL_COMBINATIONS,
                "species_temporal_combination_count": "",
                "species_temporal_availability_quotient": "",
                "species_temporal_exclusivity": "",
                "family_temporal_combination_count": "",
                "family_temporal_availability_quotient": "",
                "family_temporal_exclusivity": "",
            })

    horde_rows, by_context = normalize_horde_probabilities(raw_horde_rows)

    # Legacy outputs: unchanged points/probability strategy, retained as backup.
    context_rankings, target_rankings = rank_contexts(
        by_context, state, use_temporal_exclusivity=False, exclusivity_power=exclusivity_power
    )
    route_best = best_context_per_route(context_rankings, per_season=False)
    season_best = best_context_per_route(context_rankings, per_season=True)
    strategy = greedy_unique_strategy(
        by_context, state, strategy_steps, use_temporal_exclusivity=False, exclusivity_power=exclusivity_power
    )

    # Recommended outputs: direct multiplication by 12 / available combinations.
    exclusivity_context_rankings, exclusivity_target_rankings = rank_contexts(
        by_context, state, use_temporal_exclusivity=True, exclusivity_power=exclusivity_power
    )
    exclusivity_route_best = best_context_per_route(exclusivity_context_rankings, per_season=False)
    exclusivity_season_best = best_context_per_route(exclusivity_context_rankings, per_season=True)
    exclusivity_strategy = greedy_unique_strategy(
        by_context, state, strategy_steps, use_temporal_exclusivity=True, exclusivity_power=exclusivity_power
    )

    output_dir = args.output_dir
    output_dir.mkdir(parents=True, exist_ok=True)
    write_csv(output_dir / "pokemon_evolution_points_mapping.csv", mapping_rows)
    write_csv(output_dir / "pokemon_temporal_exclusivity_mapping.csv", temporal_exclusivity_rows)
    write_csv(output_dir / "horde_encounters_by_time.csv", horde_rows)

    # Legacy backup rankings without exclusivity.
    write_csv(output_dir / "route_context_rankings.csv", context_rankings)
    write_csv(output_dir / "route_best_contexts.csv", route_best)
    write_csv(output_dir / "season_route_rankings.csv", season_best)
    write_csv(output_dir / "route_target_rankings.csv", target_rankings)
    write_csv(output_dir / "greedy_unique_strategy.csv", strategy)

    # Recommended rankings with temporal exclusivity.
    write_csv(output_dir / "route_context_rankings_with_exclusivity.csv", exclusivity_context_rankings)
    write_csv(output_dir / "route_best_contexts_with_exclusivity.csv", exclusivity_route_best)
    write_csv(output_dir / "season_route_rankings_with_exclusivity.csv", exclusivity_season_best)
    write_csv(output_dir / "route_target_rankings_with_exclusivity.csv", exclusivity_target_rankings)
    write_csv(output_dir / "greedy_unique_strategy_with_exclusivity.csv", exclusivity_strategy)
    write_csv(output_dir / "reused_location_id_guide.csv", build_reused_location_guide(context_rankings))
    write_csv(output_dir / "reused_location_id_guide_with_exclusivity.csv", build_reused_location_guide(exclusivity_context_rankings))
    write_csv(output_dir / "route_rank_comparison.csv", compare_ranking_versions(exclusivity_context_rankings, context_rankings))
    write_csv(output_dir / "season_schedule.csv", event_schedule_rows())
    write_csv(output_dir / "rule_sources.csv", rule_source_rows())

    horde_species = {str(row["pokemon"]) for row in horde_rows}
    mapped_horde_species = {str(row["pokemon"]) for row in horde_rows if row["scoring_family"]}
    context_totals = [float(records[0]["horde_pool_raw_total_percent"]) for records in by_context.values() if records]
    explicit_sweet_scent_contexts = sum(
        1 for records in by_context.values()
        if records and str(records[0]["encounter_type"]).casefold() == "sweet scent"
    )
    standard_contexts = sum(
        1 for total in context_totals
        if math.isclose(total, STANDARD_HORDE_POOL_PERCENT, abs_tol=0.02)
    )
    unmapped_rows = [row for row in mapping_rows if row["mapping_type"] == "unmapped"]
    ambiguous_rows = [row for row in mapping_rows if row["ambiguous_mapping"]]
    diagnostics.update({
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "tier_chart_entry_count": len(tier_map),
        "mapping_row_count": len(mapping_rows),
        "unmapped_monster_count": len(unmapped_rows),
        "ambiguous_mapping_count": len(ambiguous_rows),
        "active_horde_row_count": len(horde_rows),
        "route_context_count": len(context_rankings),
        "route_count": len(route_best),
        "horde_species_count": len(horde_species),
        "mapped_horde_species_count": len(mapped_horde_species),
        "unmapped_horde_species": sorted(horde_species - mapped_horde_species),
        "standard_five_percent_context_count": standard_contexts,
        "explicit_sweet_scent_context_count": explicit_sweet_scent_contexts,
        "nonstandard_raw_pool_context_count": len(context_totals) - standard_contexts - explicit_sweet_scent_contexts,
        "scoring_state": {
            "unique_species_bonus": unique_bonus,
            "duplicate_points": duplicate_points,
            "temporal_exclusivity_weight_power": exclusivity_power,
            "team_caught_families": sorted(team_families),
            "player_caught_families": sorted(player_families),
            "score_precedence": [
                "player duplicate -> duplicate_points",
                "team already unique -> base points",
                "new team unique -> base points + unique bonus",
            ],
        },
        "probability_model": {
            "standard_horde_pool_percent": STANDARD_HORDE_POOL_PERCENT,
            "formula": "raw_horde_split / sum(active_horde_splits in route context)",
            "example_2_5_percent": "2.5 / 5 = 50%",
            "example_1_percent": "1 / 5 = 20%",
            "explicit_sweet_scent_tables": "retained and normalized; never filtered out",
        },
        "temporal_exclusivity_model": {
            "possible_combinations": TOTAL_TEMPORAL_COMBINATIONS,
            "formula": "12 / distinct season-time combinations for each encountered species",
            "availability_quotient": "distinct season-time combinations / 12",
            "score_formula": "legacy score contribution * species temporal exclusivity ^ configured power",
            "configured_power": exclusivity_power,
            "scoring_level": "encountered species; evolution-family availability is exported for reference",
        },
        "top_route_context": context_rankings[0] if context_rankings else None,
        "top_route": route_best[0] if route_best else None,
        "top_route_context_with_exclusivity": exclusivity_context_rankings[0] if exclusivity_context_rankings else None,
        "top_route_with_exclusivity": exclusivity_route_best[0] if exclusivity_route_best else None,
    })
    (output_dir / "parser_diagnostics.json").write_text(
        json.dumps(diagnostics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    build_readme(output_dir, diagnostics)

    print(json.dumps({
        "output_dir": str(output_dir),
        "route_context_count": len(context_rankings),
        "route_count": len(route_best),
        "active_horde_row_count": len(horde_rows),
        "mapped_horde_species_count": len(mapped_horde_species),
        "top_context_legacy": context_rankings[0] if context_rankings else None,
        "top_context_with_exclusivity": exclusivity_context_rankings[0] if exclusivity_context_rankings else None,
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
