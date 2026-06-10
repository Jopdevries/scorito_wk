from __future__ import annotations

from pathlib import Path
import yaml
import csv

INPUT = Path("config/player_position_overrides.yaml")
OUTPUT = Path("output/unknown_player_positions.csv")


def main() -> None:
    if not INPUT.exists():
        print(f"Missing {INPUT}")
        return
    with INPUT.open(encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    rows = []
    for player, details in data.items():
        if isinstance(details, dict):
            pos = str(details.get("position", "")).upper()
            if pos == "UNKNOWN":
                rows.append(
                    {
                        "player": player,
                        "country": details.get("country", ""),
                        "starter_prob": details.get("starter_prob", ""),
                        "minutes_risk": details.get("minutes_risk", ""),
                    }
                )
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["player", "country", "starter_prob", "minutes_risk"] )
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {len(rows)} unknowns to {OUTPUT}")


if __name__ == "__main__":
    main()
