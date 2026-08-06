from __future__ import annotations

"""Win-Out Machine (simulator.html): lock any remaining game's outcome and
re-simulate the rest of the season 5,000 times, client-side.

Static shell only — the schedule, team strengths, and the logistic model
constants all come from assets/app-data.json (built by smp.appdata from
simmodel.sim_client_inputs, so client odds agree with the home page's
Monte Carlo). The interactive board lives in static/js/simulator.js.
"""

from typing import Any

from ..core import completed_game_items, esc, page_html


def render_simulator_page(
    data: dict[str, Any],
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    season: int,
    start_season: int = 2026,
) -> str:
    fresh = not completed_game_items(data, season, playoffs=False)
    if fresh:
        board_note = (
            f"The {season} season hasn't tipped off yet, so the board is the full projected schedule."
        )
    else:
        board_note = "The board lists every remaining regular-season game."
    body = f"""
    <section class="page-hero">
      <div>
        <h1>Win-Out Machine</h1>
        <p class="muted">Call any game — the rest re-simulate 5,000 times and the playoff odds update live ·
        the URL tracks your picks</p>
      </div>
      <div class="muted">{esc(season)} season</div>
    </section>
    <noscript>
      <section class="card">
        <h2>JavaScript required</h2>
        <p class="muted">The Win-Out Machine re-simulates the season in your browser and needs JavaScript.
        With scripts off, the <a href="index.html">home page</a> carries the current playoff odds and the
        <a href="schedule.html">schedule</a> lists every game.</p>
      </section>
    </noscript>
    <div data-wo-app>
      <div class="wo-layout">
        <section class="card wo-games-card">
          <div class="section-title-row">
            <h2>The board</h2>
            <div class="wo-board-tools">
              <span class="muted" data-wo-count></span>
              <button type="button" class="wo-reset" data-wo-reset>Reset picks</button>
            </div>
          </div>
          <p class="tool-note muted">{esc(board_note)} Locking a game counts it as final; every game you leave
          alone is re-simulated.</p>
          <div class="wo-board" data-wo-games>
            <p class="muted">Loading schedule…</p>
          </div>
        </section>
        <section class="card wo-odds-card">
          <h2>Odds</h2>
          <p class="tool-note muted" title="Simulations use a deterministic seed, so the same set of picks always produces the same odds.">Uses
          the same team-strength model and win probability as the home page's playoff odds.</p>
          <div data-wo-odds aria-live="polite">
            <p class="muted">Loading…</p>
          </div>
        </section>
      </div>
    </div>
    """
    return page_html("Win-Out Machine", body, teams, root="", active="simulator")


def render_simulator_pages(
    data: dict[str, Any],
    teams: list[dict[str, Any]],
    players: list[dict[str, Any]],
    season: int,
    start_season: int = 2026,
) -> dict[str, str]:
    """{output filename: html} for the Win-Out Machine (single page)."""
    return {"simulator.html": render_simulator_page(data, teams, players, season, start_season)}
