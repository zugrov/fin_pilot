"""CLI: пересобрать fixtures и проверить оракул ожиданий."""

from __future__ import annotations

import json
from pathlib import Path

from tests.synthetic_polygon.emit import write_all, write_polygon_oracle_json
from tests.synthetic_polygon.expectations import assert_oracle_matches_profiles

REPO_ROOT = Path(__file__).resolve().parents[3]


def main() -> None:
    assert_oracle_matches_profiles()
    manifest = write_all()
    write_polygon_oracle_json(REPO_ROOT)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
