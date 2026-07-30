from __future__ import annotations

import json
import unittest
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

from src.build_dashboard import (
    NormalizedInput,
    active_season,
    build_payload,
    build_static_model,
    context_family_sets,
    current_game_clock,
    rank_for_state,
    recommendation_season_scope,
    resolve_catch_families,
    resolve_dashboard_time,
)
from src.horde_core import (
    ScoringState,
    aggregate_context_targets,
    annotate_temporal_exclusivity,
    temporal_exclusivity_score_multiplier,
    temporal_score_multiplier,
)

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.config = json.loads(
            (ROOT / "config/dashboard_config.json").read_text(encoding="utf-8")
        )
        cls.model = build_static_model(
            ROOT / "data/monsters.json",
            ROOT / "data/shiny_wars_2026_tier_chart.csv",
            cls.config.get("fixed_horde_probability_overrides", []),
        )

    def test_static_model_keeps_location_ids(self) -> None:
        relic = [
            row
            for row in self.model["horde_rows"]
            if row["region"] == "Unova"
            and row["location_full"] == "Relic Castle (Depths)"
        ]
        self.assertGreater(len({str(row["location_id"]) for row in relic}), 1)
        self.assertTrue(all(row["location_display"] for row in relic))

    def test_payload_contains_all_team_and_player_contexts(self) -> None:
        normalized = NormalizedInput(
            players=("Alpha", "Beta"),
            all_players=("Alpha", "Beta"),
            catches_by_player={"Alpha": (), "Beta": ()},
            warnings=(),
        )
        payload, *_ = build_payload(
            self.model,
            normalized,
            self.config,
            datetime(2026, 8, 2, tzinfo=timezone.utc),
        )

        expected_contexts = self.model["diagnostics"]["context_count"]
        team_all = payload["rankings"]["team"]["views"]["All|All"]
        alpha_all = payload["rankings"]["players"]["Alpha"]["views"]["All|All"]

        self.assertEqual(payload["meta"]["activeSeason"], "Summer")
        self.assertEqual(payload["players"], ["Alpha", "Beta"])
        self.assertNotIn("topN", payload["meta"])
        self.assertEqual(len(team_all), expected_contexts)
        self.assertEqual(len(alpha_all), expected_contexts)
        self.assertEqual(
            payload["meta"]["scoreAdjustmentByCombinationCount"],
            {"1": 2.0, "2": 1.5, "3": 1.25, "4": 1.1, "default": 1.0},
        )

        team_entry = payload["rankings"]["team"]["entries"][team_all[0]]
        target = team_entry["targets"][0]
        combination_count = target["seasonTimeCombinationCount"]
        combination_total = target["seasonTimeCombinationTotal"]

        self.assertNotIn("topTargetExclusivity", team_entry)
        self.assertNotIn("temporalExclusivity", target)
        self.assertNotIn("temporalDetails", target)
        self.assertIsInstance(combination_count, int)
        self.assertGreaterEqual(combination_count, 1)
        self.assertLessEqual(combination_count, 12)
        self.assertEqual(combination_count, combination_total)
        self.assertEqual(
            target["scoreMultiplier"],
            temporal_score_multiplier(combination_count),
        )
        self.assertAlmostEqual(
            target["adjustedContribution"],
            target["legacyContribution"] * target["scoreMultiplier"],
        )

    def test_recommendations_drop_expired_summer_but_keep_summer_filter(self) -> None:
        normalized = NormalizedInput(
            players=("Alpha",),
            all_players=("Alpha",),
            catches_by_player={"Alpha": ()},
            warnings=(),
        )
        payload, *_ = build_payload(
            self.model,
            normalized,
            self.config,
            datetime(2026, 8, 10, tzinfo=timezone.utc),
        )

        scope = payload["meta"]["recommendationSeasonScope"]
        self.assertEqual(scope["phase"], "during_event")
        self.assertEqual(
            scope["eligibleSeasons"],
            ["Autumn", "Winter", "Spring"],
        )
        self.assertEqual(scope["expiredSeasons"], ["Summer"])

        team = payload["rankings"]["team"]
        recommendation_ids = team["views"]["All|All"]
        summer_ids = team["views"]["Summer|All"]
        self.assertTrue(recommendation_ids)
        self.assertTrue(summer_ids)
        self.assertTrue(
            all(team["entries"][context_id]["season"] != "Summer" for context_id in recommendation_ids)
        )
        self.assertTrue(
            all(team["entries"][context_id]["season"] == "Summer" for context_id in summer_ids)
        )
        self.assertLess(
            len(recommendation_ids),
            payload["meta"]["routeContextCount"],
        )
        self.assertEqual(
            len(recommendation_ids),
            payload["meta"]["recommendationContextCount"],
        )

        reduced_targets = [
            target
            for entry in team["entries"].values()
            for target in entry["targets"]
            if target["seasonTimeCombinationCount"]
            < target["seasonTimeCombinationTotal"]
        ]
        self.assertTrue(reduced_targets)
        for target in reduced_targets[:50]:
            self.assertEqual(
                target["scoreMultiplier"],
                temporal_score_multiplier(
                    target["seasonTimeCombinationCount"]
                ),
            )

    def test_combination_ratio_uses_remaining_union_as_numerator(self) -> None:
        rows = [
            {
                "pokemon": "Alpha",
                "scoring_family": "Alpha family",
                "season": "Summer",
                "time_of_day": "morning",
                "region_id": 1,
                "location_id": 1,
                "tier": 1,
                "base_points": 10.0,
            },
            {
                "pokemon": "Beta",
                "scoring_family": "Alpha family",
                "season": "Autumn",
                "time_of_day": "morning",
                "region_id": 1,
                "location_id": 2,
                "tier": 1,
                "base_points": 10.0,
            },
        ]

        annotated, _, _ = annotate_temporal_exclusivity(
            rows,
            eligible_seasons=["Autumn", "Winter", "Spring"],
        )
        self.assertTrue(
            all(
                row["family_temporal_combination_count_remaining"] == 1
                for row in annotated
            )
        )
        self.assertTrue(
            all(
                row["family_temporal_combination_count_total"] == 2
                for row in annotated
            )
        )
        self.assertTrue(
            all(row["family_temporal_combination_count"] == 1 for row in annotated)
        )

    def test_after_event_returns_automatically_to_full_year(self) -> None:
        scope = recommendation_season_scope(
            self.config,
            datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
        self.assertEqual(scope["phase"], "after_event_full_year")
        self.assertEqual(scope["eligibleSeasons"], list(("Summer", "Autumn", "Winter", "Spring")))
        self.assertEqual(scope["expiredSeasons"], [])

    def test_post_event_payload_restores_full_year_counts_and_recommendations(self) -> None:
        normalized = NormalizedInput(
            players=("Alpha",),
            all_players=("Alpha",),
            catches_by_player={"Alpha": ()},
            warnings=(),
        )
        payload, *_ = build_payload(
            self.model,
            normalized,
            self.config,
            datetime(2026, 8, 30, tzinfo=timezone.utc),
        )
        team = payload["rankings"]["team"]
        self.assertEqual(
            len(team["views"]["All|All"]),
            payload["meta"]["routeContextCount"],
        )
        for entry in list(team["entries"].values())[:100]:
            for target in entry["targets"]:
                self.assertEqual(
                    target["seasonTimeCombinationCount"],
                    target["seasonTimeCombinationTotal"],
                )


    def test_disabled_time_simulation_uses_actual_time(self) -> None:
        config = deepcopy(self.config)
        config["time_simulation"]["enabled"] = False
        actual = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)

        effective, metadata = resolve_dashboard_time(config, actual)

        self.assertEqual(effective, actual)
        self.assertFalse(metadata["enabled"])
        self.assertIsNone(metadata["configuredDateTimeLocal"])
        self.assertEqual(metadata["effectiveAtUtc"], "2026-07-30T16:00:00Z")

    def test_config_can_simulate_arbitrary_local_datetime(self) -> None:
        config = deepcopy(self.config)
        config["time_simulation"] = {
            "enabled": True,
            "timezone": "Europe/Berlin",
            "datetime_local": "2026-08-08T00:02:00",
        }
        actual = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)

        effective, metadata = resolve_dashboard_time(config, actual)

        self.assertEqual(
            effective,
            datetime(2026, 8, 7, 22, 2, tzinfo=timezone.utc),
        )
        self.assertTrue(metadata["enabled"])
        self.assertEqual(
            metadata["configuredDateTimeLocal"],
            "2026-08-08T00:02:00",
        )
        scope = recommendation_season_scope(config, effective)
        self.assertEqual(
            scope["eligibleSeasons"],
            ["Autumn", "Winter", "Spring"],
        )
        self.assertEqual(scope["expiredSeasons"], ["Summer"])

    def test_simulated_payload_keeps_actual_build_timestamp_separate(self) -> None:
        config = deepcopy(self.config)
        config["time_simulation"] = {
            "enabled": True,
            "timezone": "Europe/Berlin",
            "datetime_local": "2026-08-08T00:02:00",
        }
        actual = datetime(2026, 7, 30, 16, 0, tzinfo=timezone.utc)
        effective, metadata = resolve_dashboard_time(config, actual)
        normalized = NormalizedInput(
            players=("Alpha",),
            all_players=("Alpha",),
            catches_by_player={"Alpha": ()},
            warnings=(),
        )

        payload, *_ = build_payload(
            self.model,
            normalized,
            config,
            effective,
            actual_generated_at=actual,
            time_simulation=metadata,
        )

        self.assertEqual(payload["meta"]["generatedAtUtc"], actual.isoformat())
        self.assertEqual(payload["meta"]["calculationAtUtc"], effective.isoformat())
        self.assertTrue(payload["meta"]["timeSimulation"]["enabled"])
        self.assertEqual(payload["meta"]["activeSeason"], "Autumn")
        self.assertEqual(
            payload["meta"]["recommendationSeasonScope"]["expiredSeasons"],
            ["Summer"],
        )

    def test_weekly_season_rotation_uses_configured_local_anchor(self) -> None:
        self.assertEqual(
            active_season(
                self.config,
                datetime(2026, 7, 29, 19, 45, tzinfo=timezone.utc),
            ),
            "Autumn",
        )
        self.assertEqual(
            active_season(
                self.config,
                datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc),
            ),
            "Autumn",
        )
        self.assertEqual(
            active_season(
                self.config,
                datetime(2026, 7, 31, 22, 1, tzinfo=timezone.utc),
            ),
            "Summer",
        )
        self.assertEqual(
            active_season(
                self.config,
                datetime(2026, 8, 7, 22, 1, tzinfo=timezone.utc),
            ),
            "Autumn",
        )

    def test_temporal_score_multipliers_use_combination_count(self) -> None:
        expected = {
            1: 2.0,
            2: 1.5,
            3: 1.25,
            4: 1.1,
            5: 1.0,
            12: 1.0,
        }
        for count, multiplier in expected.items():
            self.assertEqual(temporal_score_multiplier(count), multiplier)

        # Compatibility wrapper based on the old 12/count exclusivity value.
        self.assertEqual(temporal_exclusivity_score_multiplier(12), 2.0)
        self.assertEqual(temporal_exclusivity_score_multiplier(6), 1.5)
        self.assertEqual(temporal_exclusivity_score_multiplier(4), 1.25)
        self.assertEqual(temporal_exclusivity_score_multiplier(3), 1.1)

    def test_family_combination_count_is_union_of_member_availability(self) -> None:
        rows = [
            {
                "pokemon": "Alpha",
                "scoring_family": "Alpha family",
                "season": "Summer",
                "time_of_day": "morning",
                "region_id": 1,
                "location_id": 1,
                "tier": 1,
                "base_points": 10.0,
            },
            {
                "pokemon": "Alpha",
                "scoring_family": "Alpha family",
                "season": "Summer",
                "time_of_day": "day",
                "region_id": 1,
                "location_id": 2,
                "tier": 1,
                "base_points": 10.0,
            },
            {
                "pokemon": "Beta",
                "scoring_family": "Alpha family",
                "season": "Summer",
                "time_of_day": "day",
                "region_id": 1,
                "location_id": 3,
                "tier": 1,
                "base_points": 10.0,
            },
            {
                "pokemon": "Beta",
                "scoring_family": "Alpha family",
                "season": "Autumn",
                "time_of_day": "night",
                "region_id": 1,
                "location_id": 4,
                "tier": 1,
                "base_points": 10.0,
            },
        ]

        annotated, _, _ = annotate_temporal_exclusivity(rows)

        # Summer/day occurs for both species, but is counted only once.
        self.assertTrue(
            all(row["family_temporal_combination_count"] == 3 for row in annotated)
        )
        self.assertTrue(
            all(float(row["family_temporal_exclusivity"]) == 4.0 for row in annotated)
        )

    def test_adjusted_contribution_uses_family_combination_multiplier(self) -> None:
        state = ScoringState(
            unique_bonus=0.0,
            duplicate_points=1.0,
            team_caught_families=frozenset(),
            player_caught_families=frozenset(),
        )

        def record(species: str, probability: float) -> dict:
            return {
                "context_id": "test",
                "region_id": 1,
                "region": "Test",
                "location_id": 1,
                "location_full": "Test Route",
                "location_display": "Test Route",
                "location_name_instance_count": 1,
                "location_name_requires_id": False,
                "encounter_type": "Grass",
                "season": "Summer",
                "time_of_day": "day",
                "scoring_family": "Test family",
                "pokemon": species,
                "tier": 1,
                "base_points": 10.0,
                "horde_roll_probability": probability,
                "horde_size": 5,
                # The species can differ, but the scoring multiplier is family-based.
                "species_temporal_combination_count": 1 if species == "Alpha" else 12,
                "species_temporal_exclusivity": 12.0 if species == "Alpha" else 1.0,
                "family_temporal_combination_count": 4,
                "family_temporal_exclusivity": 3.0,
            }

        rows = aggregate_context_targets(
            [record("Alpha", 0.5), record("Beta", 0.5)],
            state,
            use_temporal_exclusivity=True,
        )

        self.assertEqual(len(rows), 1)
        target = rows[0]
        self.assertEqual(target["family_temporal_combination_count"], 4)
        self.assertEqual(target["family_temporal_score_multiplier"], 1.1)
        self.assertEqual(target["score_index_contribution"], 50.0)
        self.assertAlmostEqual(
            target["exclusivity_adjusted_score_index_contribution"],
            55.0,
        )
        self.assertAlmostEqual(
            target["ranking_score_index_contribution"],
            55.0,
        )


    def test_explicit_sweet_scent_tables_are_complete_and_normalized(self) -> None:
        contexts = [
            records
            for records in self.model["by_context"].values()
            if records
            and str(records[0]["encounter_type"]).casefold() == "sweet scent"
        ]

        self.assertGreater(len(contexts), 0)
        for records in contexts:
            self.assertAlmostEqual(
                sum(float(row["horde_roll_probability"]) for row in records),
                1.0,
                places=7,
            )
            raw_total = float(records[0]["horde_pool_raw_total_percent"])
            self.assertGreaterEqual(raw_total, 99.98)
            self.assertLessEqual(raw_total, 100.02)
            self.assertIn(
                "Normalized explicit Sweet Scent horde table",
                str(records[0]["probability_basis"]),
            )

    def test_zorua_override_reserves_five_percent_and_normalizes_remainder(self) -> None:
        matching_contexts = [
            records
            for records in self.model["by_context"].values()
            if records
            and str(records[0]["region"]) == "Unova"
            and str(records[0]["location_id"]) == "385"
            and str(records[0]["encounter_type"]) == "Grass"
            and str(records[0]["season"]) == "Summer"
            and str(records[0]["time_of_day"]) == "morning"
        ]

        self.assertEqual(len(matching_contexts), 1)
        records = matching_contexts[0]
        probabilities = {
            str(row["pokemon"]): float(row["horde_roll_probability"])
            for row in records
        }

        self.assertAlmostEqual(sum(probabilities.values()), 1.0, places=7)
        self.assertAlmostEqual(probabilities["Zorua"], 0.05, places=7)
        self.assertAlmostEqual(probabilities["Heracross"], 0.38, places=7)
        self.assertAlmostEqual(probabilities["Petilil"], 0.38, places=7)
        self.assertAlmostEqual(probabilities["Venipede"], 0.19, places=7)
        self.assertTrue(all(bool(row["probability_override_applied"]) for row in records))
        self.assertAlmostEqual(
            float(records[0]["fixed_horde_probability_total_percent"]),
            5.0,
            places=7,
        )

        zorua = next(row for row in records if row["pokemon"] == "Zorua")
        self.assertEqual(zorua["raw_rarity_value"], "???")
        self.assertAlmostEqual(
            float(zorua["fixed_horde_roll_probability"]),
            0.05,
            places=7,
        )

    def test_zorua_override_applies_to_all_twelve_season_time_combinations(self) -> None:
        zorua_rows = [
            row
            for row in self.model["horde_rows"]
            if row["pokemon"] == "Zorua"
            and str(row["location_id"]) == "385"
            and row["encounter_type"] == "Grass"
        ]

        self.assertEqual(len(zorua_rows), 12)
        self.assertEqual(
            {(row["season"], row["time_of_day"]) for row in zorua_rows},
            {
                (season, time_name)
                for season in ("Summer", "Autumn", "Winter", "Spring")
                for time_name in ("morning", "day", "night")
            },
        )
        self.assertTrue(
            all(
                abs(float(row["horde_roll_probability"]) - 0.05) < 1e-9
                for row in zorua_rows
            )
        )

    def test_game_clock_and_time_windows(self) -> None:
        self.assertEqual(
            current_game_clock(
                self.config,
                datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc),
            ),
            ("00:00", "night"),
        )
        self.assertEqual(
            current_game_clock(
                self.config,
                datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc),
            ),
            ("04:00", "morning"),
        )
        self.assertEqual(
            current_game_clock(
                self.config,
                datetime(2026, 7, 29, 2, 45, tzinfo=timezone.utc),
            ),
            ("11:00", "day"),
        )
        self.assertEqual(
            current_game_clock(
                self.config,
                datetime(2026, 7, 29, 5, 15, tzinfo=timezone.utc),
            ),
            ("21:00", "night"),
        )

    def test_player_catch_excludes_contexts_containing_that_family(self) -> None:
        normalized = NormalizedInput(
            players=("Alpha",),
            all_players=("Alpha",),
            catches_by_player={"Alpha": ("Volbeat",)},
            warnings=(),
        )
        player_families, team_families, _ = resolve_catch_families(
            normalized,
            self.model["name_to_families"],
        )
        rankings, _, excluded = rank_for_state(
            self.model["by_context"],
            team_families,
            player_families["Alpha"],
            8.0,
            1.0,
            True,
            context_family_sets(self.model["by_context"]),
        )
        self.assertGreater(excluded, 0)
        self.assertTrue(
            all(
                "volbeat" not in str(row["all_scoring_families"]).casefold()
                for row in rankings
            )
        )

    def test_team_view_keeps_already_caught_family_at_base_points(self) -> None:
        normalized = NormalizedInput(
            players=("Alpha",),
            all_players=("Alpha",),
            catches_by_player={"Alpha": ("Volbeat",)},
            warnings=(),
        )
        payload, *_ = build_payload(
            self.model,
            normalized,
            self.config,
            datetime(2026, 8, 10, tzinfo=timezone.utc),
        )
        team_entries = payload["rankings"]["team"]["entries"].values()
        volbeat_targets = [
            target
            for entry in team_entries
            for target in entry["targets"]
            if target["family"].casefold() == "volbeat"
        ]
        self.assertTrue(volbeat_targets)
        self.assertTrue(
            all(target["status"] == "team_already_unique" for target in volbeat_targets)
        )
        self.assertTrue(
            all(
                target["effectivePoints"] == target["basePoints"]
                for target in volbeat_targets
            )
        )
        self.assertTrue(
            all(
                target["scoreMultiplier"]
                == temporal_score_multiplier(target["seasonTimeCombinationCount"])
                for target in volbeat_targets
            )
        )


if __name__ == "__main__":
    unittest.main()
