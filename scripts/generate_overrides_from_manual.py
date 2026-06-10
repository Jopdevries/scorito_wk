from __future__ import annotations

import csv
from pathlib import Path
import yaml

INPUT = Path("input/manual_player_metadata.csv")
OUTPUT = Path("config/player_position_overrides.yaml")


def load_csv(path: Path):
    with path.open(encoding="utf-8-sig") as fh:
        reader = csv.DictReader(fh)
        return list(reader)


def build_overrides(rows: list[dict[str, str]]):
    out: dict[str, dict] = {}
    for r in rows:
        player = r.get("player") or ""
        if not player:
            continue
        details = {
            "position": (r.get("position") or "UNKNOWN").upper(),
        }
        if r.get("country"):
            details["country"] = r.get("country")
        # Preserve starter_prob and other numeric flags if present
        if r.get("starter_prob"):
            try:
                details["starter_prob"] = float(r.get("starter_prob"))
            except Exception:
                pass
        for intfield in ("penalty_taker", "set_piece_taker"):
            if r.get(intfield):
                try:
                    details[intfield] = int(r.get(intfield))
                except Exception:
                    pass
        if r.get("minutes_risk"):
            details["minutes_risk"] = r.get("minutes_risk")
        out[player] = details
    return out


def main():
    rows = load_csv(INPUT)
    overrides = build_overrides(rows)
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        yaml.safe_dump(overrides, fh, sort_keys=False, allow_unicode=True)
    print(f"Wrote {len(overrides)} overrides to {OUTPUT}")


if __name__ == "__main__":
    main()
