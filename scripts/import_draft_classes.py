"""Replace an export's draft pool with the league's real draft classes.

Basketball GM's "random players" draft classes are placeholder noise -- the site's
Draft page is supposed to show the actual 2004-2013 boards the league drafts from.
Those classes are exported one file per year from the game's own Draft Class screen
and committed to ``league-data/draft_classes/<year>.json``; this script drops every
undrafted player (tid == -2) already in an export and writes the real ones in.

    python3 scripts/import_draft_classes.py league-data/2004_preseason.json

Output is committed -- the site build never reads ``draft_classes/``, only the export.
Re-run it when a class file changes.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

DRAFT_PROSPECT_TID = -2
CLASS_DIR = Path("league-data/draft_classes")

# BBGM's stand-in for "no photo". Left in place it renders as a 404'd <img> that
# has to fail before the face SVG takes over, so it is stripped on the way in.
BLANK_PHOTO = "/img/blank-face.png"


def load_classes(class_dir: Path) -> dict[int, list[dict[str, Any]]]:
    """``{year: players}`` from every ``<year>.json`` in the class directory."""
    classes: dict[int, list[dict[str, Any]]] = {}
    for path in sorted(class_dir.glob("*.json")):
        try:
            year = int(path.stem)
        except ValueError:
            continue
        # BBGM writes these with a UTF-8 BOM.
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        classes[year] = data.get("players") or []
    return classes


def prepare(player: dict[str, Any], year: int) -> dict[str, Any]:
    """One class player, normalized to how the export stores a prospect."""
    player = dict(player)
    player["tid"] = DRAFT_PROSPECT_TID
    if (player.get("imgURL") or "").strip() == BLANK_PHOTO:
        player.pop("imgURL", None)
    draft = dict(player.get("draft") or {})
    draft.update({"tid": -1, "originalTid": -1, "round": 0, "pick": 0, "year": year})
    player["draft"] = draft
    # A prospect has no league history; a stray stats row would show up as a
    # career table on his player page.
    player["stats"] = []
    return player


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("export", type=Path, help="league export JSON to rewrite in place")
    ap.add_argument("--classes", type=Path, default=CLASS_DIR)
    args = ap.parse_args()

    data = json.loads(args.export.read_text())
    classes = load_classes(args.classes)
    if not classes:
        raise SystemExit(f"no draft classes found in {args.classes}")

    kept = [p for p in data["players"] if p.get("tid") != DRAFT_PROSPECT_TID]
    dropped = len(data["players"]) - len(kept)

    # pid has to stay unique across the whole export, and the class files were
    # exported from a different league, so they get renumbered above the league's
    # own high-water mark rather than trusted to not collide.
    next_pid = max((int(p["pid"]) for p in kept if p.get("pid") is not None), default=-1) + 1
    added: list[dict[str, Any]] = []
    for year in sorted(classes):
        for player in classes[year]:
            prospect = prepare(player, year)
            prospect["pid"] = next_pid
            next_pid += 1
            added.append(prospect)

    data["players"] = kept + added
    args.export.write_text(json.dumps(data, separators=(",", ":")))
    years = ", ".join(str(y) for y in sorted(classes))
    print(f"{args.export}: dropped {dropped} prospects, added {len(added)} from {years}")


if __name__ == "__main__":
    main()
