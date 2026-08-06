#!/usr/bin/env python3
"""
One-off: cut players out of their portrait photos, so a headshot's studio backdrop
stops rendering as a bright disc on a dark card.

Run it by hand when the player pool changes; the OUTPUT IS COMMITTED, and the site
build never imports this file. That is the same deal scripts/faces/render.mjs has,
and for the same reason: the build stays dependency-free and offline, and a page can
be rendered from a checkout without fetching 460 photos from ten different hosts.

    python3 -m pip install pillow
    python3 scripts/cutout_portraits.py league-data/2004_predraft.json

What it can and cannot do
-------------------------
A headshot on a flat studio backdrop can be cut out exactly: flood-fill inward from
the top edge through pixels close to the backdrop colour, and stop at the player. That
covers the basketball-reference and thedraftreview photos, which is most of the pool.

An action photo cannot -- separating a player from a crowd is a matting problem, not a
fill, and the naive fill eats the jersey and leaves speckles through the face. So every
photo is gated on TOP_FLAT_STD: if the top row of pixels is not one flat colour, the
photo is left alone and the page goes on hot-linking it. Better an honest background
than a shredded player.

Photos that already carry transparency (cdn.nba.com, a.espncdn.com) are skipped too --
there is nothing to remove, and re-hosting them would only add weight.
"""

from __future__ import annotations

import argparse
import io
import json
import statistics
import sys
import urllib.error
import urllib.request
from collections import deque
from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover - one-off tool, not part of the build
    sys.exit("This script needs Pillow: python3 -m pip install pillow")

OUT_DIR = Path(__file__).resolve().parent / "portraits" / "rendered"

# How far a pixel may drift from the backdrop colour and still be background. Tuned on
# the 2003-04 pool: 30 clears JPEG ringing around the shoulders without reaching skin.
FILL_TOLERANCE = 30

# Per-channel standard deviation of the top row, above which the backdrop is "busy"
# (a crowd, a court) and the photo is left alone.
TOP_FLAT_STD = 9.0

# A fill that clears almost nothing found no backdrop; one that clears almost everything
# ran through the player. Either way the result is not a cutout, so keep the original.
MIN_CLEARED, MAX_CLEARED = 0.04, 0.80

# Cutouts have to be PNG (JPEG has no alpha), and photographic PNG-24 is enormous --
# 38KB for a 120x180 headshot, five times the JPEG it replaced, on a draft pool that
# lazy-loads three hundred of them. Quantising to 128 colours brings that back to ~8KB.
# It is indistinguishable at the 32-132px these are ever drawn at; check proto renders
# before lowering it further.
QUANTIZE_COLORS = 128

USER_AGENT = "Mozilla/5.0 (compatible; smp-league-portraits/1.0)"
TIMEOUT = 30


def fetch(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def already_transparent(image: Image.Image) -> bool:
    """Does this photo already have an alpha channel that is actually used?"""
    if image.mode != "RGBA":
        return False
    width, _ = image.size
    return any(image.getpixel((x, 0))[3] == 0 for x in (0, width - 1))


def top_row_is_flat(image: Image.Image) -> bool:
    row = [image.getpixel((x, 0))[:3] for x in range(image.size[0])]
    if len(row) < 2:
        return False
    return max(statistics.pstdev([c[channel] for c in row]) for channel in range(3)) <= TOP_FLAT_STD


def cut_out(image: Image.Image) -> tuple[Image.Image, float]:
    """Flood-fill the backdrop to transparent, seeded from the whole top edge.

    Seeding from the top only -- not all four edges -- is what keeps the fill off the
    jersey: a headshot's shoulders run off the bottom of the frame, so a bottom seed
    starts inside the player and eats him.
    """
    image = image.convert("RGBA")
    width, height = image.size
    pixels = image.load()
    backdrop = tuple(sum(pixels[x, 0][channel] for x in range(width)) // width for channel in range(3))

    def is_backdrop(colour) -> bool:
        return all(abs(colour[c] - backdrop[c]) <= FILL_TOLERANCE for c in range(3))

    seen = bytearray(width * height)
    queue = deque((x, 0) for x in range(width))
    cleared = 0
    while queue:
        x, y = queue.popleft()
        if x < 0 or y < 0 or x >= width or y >= height or seen[y * width + x]:
            continue
        colour = pixels[x, y]
        if colour[3] != 0 and not is_backdrop(colour[:3]):
            continue
        seen[y * width + x] = 1
        cleared += 1
        pixels[x, y] = (colour[0], colour[1], colour[2], 0)
        queue.extend(((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)))
    return image, cleared / (width * height)


def process(url: str) -> tuple[bytes | None, str]:
    """Return (png bytes, verdict). ``None`` means "keep hot-linking the original"."""
    try:
        raw = fetch(url)
    except (urllib.error.URLError, urllib.error.HTTPError, OSError, ValueError) as exc:
        return None, f"unreachable ({exc})"
    try:
        image = Image.open(io.BytesIO(raw))
        image.load()
    except Exception as exc:  # noqa: BLE001 - any decode failure is the same outcome
        return None, f"undecodable ({exc})"

    image = image.convert("RGBA")
    if already_transparent(image):
        return None, "already transparent"
    if not top_row_is_flat(image):
        return None, "busy backdrop"

    cut, cleared = cut_out(image)
    if not (MIN_CLEARED <= cleared <= MAX_CLEARED):
        return None, f"fill cleared {cleared:.0%}, out of range"
    return encode(cut), f"cut out ({cleared:.0%} cleared)"


def encode(image: Image.Image) -> bytes:
    """Quantised PNG bytes. Deterministic, so a rerun rewrites identical files."""
    quantized = image.convert("RGBA").quantize(colors=QUANTIZE_COLORS,
                                               method=Image.Quantize.FASTOCTREE)
    buffer = io.BytesIO()
    quantized.save(buffer, "PNG", optimize=True)
    return buffer.getvalue()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("league", type=Path, help="league export, e.g. league-data/2004_predraft.json")
    parser.add_argument("--only", type=int, default=None, help="process a single pid (for tuning)")
    args = parser.parse_args()

    league = json.loads(args.league.read_text(encoding="utf-8"))
    players = [p for p in league.get("players", []) if (p.get("imgURL") or "").strip()]
    if args.only is not None:
        players = [p for p in players if p.get("pid") == args.only]

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # pid -> source URL. The URL is the staleness guard: a cutout is only used when the
    # player still carries the exact photo it was cut from, so a manifest left over from
    # another league cannot paint a stranger's face onto whoever holds that pid now.
    manifest: dict[str, str] = {}
    tally: dict[str, int] = {}
    for i, player in enumerate(players, 1):
        pid = player["pid"]
        url = player["imgURL"].strip()
        png, verdict = process(url)
        tally[verdict.split(" (")[0]] = tally.get(verdict.split(" (")[0], 0) + 1
        name = f"{player.get('firstName', '')} {player.get('lastName', '')}".strip()
        print(f"[{i:>3}/{len(players)}] {name:<24} {verdict}")
        if png is None:
            continue
        (OUT_DIR / f"{pid}.png").write_bytes(png)
        manifest[str(pid)] = url

    # Rewrite the manifest wholesale, and drop cutouts it no longer lists, so a rerun
    # after a pool change cannot leave an orphan PNG behind for a pid to pick up.
    if args.only is None:
        (OUT_DIR / "manifest.json").write_text(
            json.dumps(manifest, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")
        for stale in OUT_DIR.glob("*.png"):
            if stale.stem not in manifest:
                stale.unlink()

    print("\n" + "\n".join(f"  {count:>4}  {verdict}" for verdict, count in sorted(tally.items())))
    print(f"\n{len(manifest)} cutouts in {OUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
