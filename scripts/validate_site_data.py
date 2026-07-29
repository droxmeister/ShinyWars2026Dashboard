#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


def main() -> None:
    path = Path(sys.argv[1] if len(sys.argv) > 1 else "web/data/strategy.json")
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["players"], "No players in generated data"
    assert data["rankings"]["team"]["views"]["All|All"], "Team ranking is empty"
    assert len(data["rankings"]["team"]["views"]["All|All"]) <= data["meta"]["topN"]
    for player in data["players"]:
        bundle = data["rankings"]["players"][player]
        assert bundle["views"]["All|All"], f"Ranking is empty for {player}"
        for context_id in bundle["views"]["All|All"]:
            row = bundle["entries"][context_id]
            assert row["locationId"], f"Missing location ID for {player}"
            assert row["locationName"], f"Missing location name for {player}"
    print(
        f"Validated {len(data['players'])} player rankings and "
        f"{len(data['rankings']['team']['views']['All|All'])} team spots."
    )


if __name__ == "__main__":
    main()
