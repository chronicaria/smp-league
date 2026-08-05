from __future__ import annotations

"""Lineup Lab (lineup.html): pick any five players — or flip to 10-man mode and
build the bench too — then see the projected lineup overall, win odds against
every real roster, and the salary bill.

The page is a static shell — all data comes from assets/app-data.json, all math
runs client-side in static/js/lineup.js (via the shared window.SMPOvr port of
the projections.py team_ovr weighting; parity is asserted by
tests/test_tools_pages.py). Ten combobox slots are rendered; the five bench
slots stay hidden until 10-man mode. The shell degrades to a useful no-JS
message.
"""

from typing import Any

from ..core import esc, page_html
from ..finance import FIN_SOFT_CAP


def _slot_html(i: int) -> str:
    """One filterable-combobox slot (ARIA combobox pattern, same shape as the
    global search in nav_html/search.js: input[role=combobox] + [role=listbox]).
    Slots 0-4 are the starters; 5-9 are the 10-man-mode bench."""
    label = f"Player {i + 1}" if i < 5 else f"Bench {i + 1}"
    return f"""
        <div class="ll-slot">
          <label class="ll-label" for="ll-input-{i}">{label}</label>
          <div class="ll-combo">
            <input id="ll-input-{i}" type="text" data-ll-input data-slot="{i}"
                   role="combobox" aria-autocomplete="list" aria-expanded="false"
                   aria-controls="ll-list-{i}" aria-activedescendant=""
                   autocomplete="off" placeholder="Type a name…">
            <button type="button" class="ll-clear" data-ll-clear data-slot="{i}"
                    aria-label="Clear {label.lower()}" hidden>&times;</button>
            <div class="search-results ll-results" id="ll-list-{i}" role="listbox"
                 aria-label="Player matches" hidden></div>
          </div>
          <div class="ll-pick" data-ll-pick="{i}"></div>
        </div>"""


def _mode_toggle() -> str:
    """5-man / 10-man segmented radio control (native radios, keyboard-first)."""
    return """
        <div class="ll-segs" role="radiogroup" aria-label="Lineup size">
          <label class="ll-seg"><input type="radio" name="ll-mode" value="5" checked data-ll-mode><span>5-man</span></label>
          <label class="ll-seg"><input type="radio" name="ll-mode" value="10" data-ll-mode><span>10-man</span></label>
        </div>"""


def render_lineup_page(
    data: dict[str, Any],
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    season: int,
    start_season: int = 2026,
) -> str:
    cap_m = f"${FIN_SOFT_CAP / 1000:.0f}M"
    starters = "".join(_slot_html(i) for i in range(5))
    bench = "".join(_slot_html(i) for i in range(5, 10))
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Lineup Lab</h1>
        <p class="muted">Build a five — or a full ten · projected overall, win odds vs every roster,
        salary vs the {esc(cap_m)} league average · the URL tracks your lineup</p>
      </div>
      <div class="muted">{esc(season)} ratings</div>
    </section>
    <noscript>
      <section class="card">
        <h2>JavaScript required</h2>
        <p class="muted">Lineup Lab is an interactive tool and needs JavaScript to build lineups. With scripts off,
        the <a href="players/index.html">player index</a> has every player's ratings and contract, and each
        team page shows its projected overall.</p>
      </section>
    </noscript>
    <div data-lineup-app>
      <section class="card">
        <div class="section-title-row ll-head">
          <h2 data-ll-heading>Your five</h2>{_mode_toggle()}
        </div>
        <div class="ll-slots">{starters}
        </div>
        <div class="ll-bench" data-ll-bench hidden>
          <h3 class="ll-bench-title">Bench <span class="muted small-copy">empty slots fill with the league-average bench</span></h3>
          <div class="ll-slots">{bench}
          </div>
        </div>
        <div class="ll-summary" data-ll-summary aria-live="polite">
          <p class="muted">Loading player data…</p>
        </div>
      </section>
      <section class="card">
        <h2>Matchups</h2>
        <p class="tool-note muted" data-ll-benchnote title="Both sides use the engine's team-overall formula; the rating gap feeds the same logistic win-probability model as the home page's playoff odds, with home and road split by the model's home-court edge.">Your
        five + a league-average bench vs each full roster, scored by the home page's win-probability model.</p>
        <div data-ll-matchups>
          <p class="muted">Pick five players to see the matchup board.</p>
        </div>
      </section>
    </div>
    """
    return page_html("Lineup Lab", body, teams, root="", active="lineup")


def render_lineup_pages(
    data: dict[str, Any],
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    season: int,
    start_season: int = 2026,
) -> dict[str, str]:
    """{output filename: html} for the Lineup Lab (single page)."""
    return {"lineup.html": render_lineup_page(data, teams, players, season, start_season)}
