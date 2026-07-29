from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from src.build_dashboard import (
    NormalizedInput,
    build_payload,
    active_season,
    build_static_model,
    context_family_sets,
    current_game_clock,
    rank_for_state,
    resolve_catch_families,
)

ROOT = Path(__file__).resolve().parents[1]


class DashboardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.model = build_static_model(
            ROOT / "data/monsters.json",
            ROOT / "data/shiny_wars_2026_tier_chart.csv",
        )
        cls.config = json.loads((ROOT / "config/dashboard_config.json").read_text())

    def test_static_model_keeps_location_ids(self):
        relic = [
            row
            for row in self.model["horde_rows"]
            if row["region"] == "Unova" and row["location_full"] == "Relic Castle (Depths)"
        ]
        self.assertGreater(len({str(row["location_id"]) for row in relic}), 1)
        self.assertTrue(all(row["location_display"] for row in relic))

    def test_single_payload_contains_team_and_player_views(self):
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
        self.assertEqual(payload["meta"]["activeSeason"], "Winter")
        self.assertEqual(payload["players"], ["Alpha", "Beta"])
        expected_top_n = int(self.config["top_n"])
        self.assertEqual(len(payload["rankings"]["team"]["views"]["All|All"]), expected_top_n)
        self.assertEqual(len(payload["rankings"]["players"]["Alpha"]["views"]["Winter|All"]), expected_top_n)
        self.assertIn("liveFilter", payload["meta"])
        self.assertEqual(payload["meta"]["liveFilter"]["seasonRotation"]["anchorSeason"], "Winter")

    def test_weekly_season_rotation_uses_configured_local_anchor(self):
        self.assertEqual(
            active_season(self.config, datetime(2026, 7, 29, 19, 45, tzinfo=timezone.utc)),
            "Autumn",
        )
        self.assertEqual(
            active_season(self.config, datetime(2026, 7, 31, 22, 1, tzinfo=timezone.utc)),
            "Winter",
        )
        self.assertEqual(
            active_season(self.config, datetime(2026, 8, 7, 22, 1, tzinfo=timezone.utc)),
            "Spring",
        )

    def test_game_clock_and_time_windows(self):
        self.assertEqual(
            current_game_clock(self.config, datetime(2026, 7, 29, 0, 0, tzinfo=timezone.utc)),
            ("00:00", "night"),
        )
        self.assertEqual(
            current_game_clock(self.config, datetime(2026, 7, 29, 1, 0, tzinfo=timezone.utc)),
            ("04:00", "morning"),
        )
        self.assertEqual(
            current_game_clock(self.config, datetime(2026, 7, 29, 2, 45, tzinfo=timezone.utc)),
            ("11:00", "day"),
        )
        self.assertEqual(
            current_game_clock(self.config, datetime(2026, 7, 29, 5, 15, tzinfo=timezone.utc)),
            ("21:00", "night"),
        )

    def test_player_catch_excludes_contexts_containing_that_family(self):
        normalized = NormalizedInput(
            players=("Alpha",),
            all_players=("Alpha",),
            catches_by_player={"Alpha": ("Volbeat",)},
            warnings=(),
        )
        player_families, team_families, _ = resolve_catch_families(
            normalized, self.model["name_to_families"]
        )
        rankings, _, excluded = rank_for_state(
            self.model["by_context"],
            team_families,
            player_families["Alpha"],
            8.0,
            1.0,
            1.0,
            True,
            context_family_sets(self.model["by_context"]),
        )
        self.assertGreater(excluded, 0)
        self.assertTrue(
            all("volbeat" not in str(row["all_scoring_families"]).casefold() for row in rankings)
        )

    def test_team_view_keeps_already_caught_family_at_base_points(self):
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
        self.assertTrue(all(target["status"] == "team_already_unique" for target in volbeat_targets))
        self.assertTrue(all(target["effectivePoints"] == target["basePoints"] for target in volbeat_targets))


if __name__ == "__main__":
    unittest.main()
