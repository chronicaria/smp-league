  // ---------- trade machine (consumes window.SMPApps from compare.js) ----------
(function () {
  'use strict';

  // ---- shared engine team-OVR helper: window.SMPOvr -------------------------
  // Published before the page guard so BOTH client tools use one port:
  // trade-extras.js precedes lineup.js in the bundle concat order (build.py).
  // Faithful JS port of scripts/projections.py team_ovr (regular-season
  // branch), itself a port of zengm team/ovr.basketball.ts with
  // numPlayersOnCourt == 5: sort OVRs descending, take the top 10, pad to 10
  // with 0.0, then
  //   predictedMOV = -OVR_K + sum_i OVR_A * exp(OVR_B * i) * ovr[i]
  //   raw = predictedMOV * 50 / 15 + 50, displayed rounded half-up.
  // team_ovr anchors its scale to scoring margin (raw = MOV * 50/15 + 50), so
  // ovrToMov is the exact inverse: (raw - 50) * 15 / 50 maps a rating back to
  // predicted margin, which feeds app-data.sim's logistic win-probability
  // model — the same curve simulate_league uses (simmodel.sim_client_inputs).
  // tests/test_tools_pages.py regenerates these constants from projections.py
  // and asserts this formula matches projections.team_ovr on known groups.
  const OVR_A = 0.3334;
  const OVR_B = -0.1609;
  const OVR_K = 102.98;
  function teamOvrRaw(ovrs) {
    const top = ovrs.map(Number).sort((a, b) => b - a).slice(0, 10);
    while (top.length < 10) top.push(0);
    let mov = -OVR_K;
    for (let i = 0; i < 10; i += 1) mov += OVR_A * Math.exp(OVR_B * i) * top[i];
    return mov * 50 / 15 + 50;
  }
  const roundOvr = (raw) => Math.floor(raw + 0.5); // Math.round, like Python's floor(x+.5)
  const ovrToMov = (raw) => (raw - 50) * 15 / 50;
  window.SMPOvr = { teamOvrRaw, roundOvr, ovrToMov };

  let bootTries = 0;
  function boot() {
    const machine = document.querySelector('[data-app="trade"]');
    if (!machine) return;
    const A = window.SMPApps;
    if (!A) {
      // compare.js should precede this file in the bundle; one deferred retry
      // keeps a wrong concat order from silently killing the page.
      if (bootTries++ < 3) setTimeout(boot, 0);
      return;
    }

    const extraEl = document.getElementById('trade-extra');
    const picksByTid = (extraEl ? JSON.parse(extraEl.textContent) : { picks: {} }).picks || {};
    const summary = document.querySelector('[data-trade-summary]');
    const sides = [0, 1].map((i) => ({
      comboEl: document.querySelector('[data-trade-combo="' + i + '"]'),
      filterEl: document.querySelector('[data-trade-filter="' + i + '"]'),
      listEl: document.querySelector('[data-trade-list="' + i + '"]'),
      tid: null,
      picked: new Set(),
      pickedPicks: new Set(),
      filter: '',
    }));

    A.loadAppData().then((data) => init(data)).catch(() => {
      const msg = '<p class="app-error">Couldn’t load roster data (assets/app-data.json). Check your connection and refresh to retry.</p>';
      sides.forEach((side) => { side.listEl.innerHTML = msg; });
      if (summary) summary.innerHTML = '';
    });

    function init(data) {
      const esc = A.escapeHtml;
      const fmtM = A.fmtSalary;
      const teamsSorted = data.teams.slice().sort((a, b) => a.abbrev.localeCompare(b.abbrev));
      const teamsByTid = {};
      data.teams.forEach((t) => { teamsByTid[t.tid] = t; });
      const rostersByTid = {};
      data.players.forEach((p) => {
        if (p.tid >= 0) (rostersByTid[p.tid] = rostersByTid[p.tid] || []).push(p);
      });
      Object.keys(rostersByTid).forEach((tid) => {
        rostersByTid[tid].sort((a, b) => (b.salary - a.salary) || a.name.localeCompare(b.name) || (a.pid - b.pid));
      });
      const tax = data.finance.tax_line;
      // Projection model constants, all read from the payload so client math
      // agrees with the server sim (simmodel.SIM_HCA / SIM_LOGISTIC_K).
      const K = data.sim.logistic_k;
      const HCA = data.sim.hca;
      const seasonGames = (data.sim && data.sim.season_games) || 45;
      const wsSeason = data.ws_season || null;
      const fullName = (t) => (t.region ? t.region + ' ' : '') + t.name;

      const comboOptions = teamsSorted.map((t) => ({
        id: t.tid,
        label: t.abbrev + ' — ' + fullName(t),
        search: [t.abbrev, fullName(t)],
      }));
      const optionByTid = {};
      comboOptions.forEach((o) => { optionByTid[o.id] = o; });

      const combos = sides.map((side, index) => A.createCombobox(side.comboEl, {
        options: () => comboOptions,
        onSelect: (tid) => {
          side.tid = tid;
          side.picked.clear();
          side.pickedPicks.clear();
          side.filter = '';
          side.filterEl.value = '';
          renderSide(index);
          syncHash();
          renderSummary();
        },
      }));

      // Initial state: the URL hash when present (a/b = tids, ap/bp = picked
      // pids, ak/bk = picked dpids), else the first two teams by abbrev.
      const params = new URLSearchParams((location.hash || '').replace(/^#/, ''));
      const defaults = [teamsSorted[0], teamsSorted[1]];
      sides.forEach((side, index) => {
        const key = index === 0 ? 'a' : 'b';
        const fromHash = parseInt(params.get(key), 10);
        side.tid = teamsByTid[fromHash] ? fromHash : (defaults[index] ? defaults[index].tid : null);
        const roster = rostersByTid[side.tid] || [];
        const pids = new Set(roster.map((p) => p.pid));
        (params.get(key + 'p') || '').split('.').forEach((pid) => {
          const num = parseInt(pid, 10);
          if (pids.has(num)) side.picked.add(num);
        });
        const dpids = new Set((picksByTid[String(side.tid)] || []).map((pick) => pick.id));
        (params.get(key + 'k') || '').split('.').forEach((id) => {
          const num = parseInt(id, 10);
          if (dpids.has(num)) side.pickedPicks.add(num);
        });
        combos[index].setSelection(side.tid !== null ? optionByTid[side.tid] : null);
        combos[index].enable();
        side.filterEl.disabled = false;
        side.filterEl.addEventListener('input', () => {
          side.filter = A.norm(side.filterEl.value.trim());
          renderSide(index);
        });
      });

      function syncHash() {
        const params = new URLSearchParams();
        let dirty = false;
        sides.forEach((side, index) => {
          const key = index === 0 ? 'a' : 'b';
          params.set(key, side.tid);
          if (side.picked.size) { params.set(key + 'p', Array.from(side.picked).sort((x, y) => x - y).join('.')); dirty = true; }
          if (side.pickedPicks.size) { params.set(key + 'k', Array.from(side.pickedPicks).sort((x, y) => x - y).join('.')); dirty = true; }
          if (!defaults[index] || side.tid !== defaults[index].tid) dirty = true;
        });
        if (!dirty && !location.hash) return; // untouched default state: keep the URL clean
        history.replaceState(null, '', '#' + params.toString());
      }

      function renderSide(index) {
        const side = sides[index];
        const team = teamsByTid[side.tid];
        if (!team) { side.listEl.innerHTML = '<p class="muted">Pick a team.</p>'; return; }
        side.listEl.innerHTML = '';
        let shown = 0;
        (rostersByTid[side.tid] || []).forEach((p) => {
          if (side.filter && !A.norm(p.name).includes(side.filter)) return;
          shown += 1;
          const row = document.createElement('label');
          row.className = 'trade-row';
          row.innerHTML = '<input type="checkbox"> <span class="trade-name">' + esc(p.name) + '</span>'
            + '<span class="muted">' + esc(p.pos) + ' · ' + (p.age === null ? '—' : p.age + 'y') + ' · ' + p.ovr + ' ovr'
            + (p.ws === null ? '' : ' · ' + p.ws.toFixed(1) + ' WS') + '</span>'
            + '<span class="trade-amt">' + fmtM(p.salary) + '/' + (p.exp === null ? '—' : p.exp) + '</span>';
          const box = row.querySelector('input');
          box.checked = side.picked.has(p.pid);
          box.setAttribute('aria-label', 'Trade ' + p.name);
          box.addEventListener('change', () => {
            if (box.checked) side.picked.add(p.pid); else side.picked.delete(p.pid);
            syncHash();
            renderSummary();
          });
          side.listEl.appendChild(row);
        });
        (picksByTid[String(side.tid)] || []).forEach((pick) => {
          if (side.filter && !A.norm(pick.label).includes(side.filter)) return;
          shown += 1;
          const row = document.createElement('label');
          row.className = 'trade-row trade-pick';
          row.innerHTML = '<input type="checkbox"> <span class="trade-name">' + esc(pick.label) + '</span><span class="muted">draft pick</span><span class="trade-amt"></span>';
          const box = row.querySelector('input');
          box.checked = side.pickedPicks.has(pick.id);
          box.setAttribute('aria-label', 'Trade ' + pick.label + ' draft pick');
          box.addEventListener('change', () => {
            if (box.checked) side.pickedPicks.add(pick.id); else side.pickedPicks.delete(pick.id);
            syncHash();
            renderSummary();
          });
          side.listEl.appendChild(row);
        });
        if (!shown) {
          side.listEl.innerHTML = '<p class="empty-state">No assets match the filter.</p>';
        }
      }

      function sideAssets(side) {
        const team = teamsByTid[side.tid];
        const players = (rostersByTid[side.tid] || []).filter((p) => side.picked.has(p.pid));
        const picks = (picksByTid[String(side.tid)] || []).filter((pick) => side.pickedPicks.has(pick.id));
        const salary = players.reduce((s, p) => s + p.salary, 0);
        const ws = players.reduce((s, p) => s + (p.ws || 0), 0);
        return { team, players, picks, salary, ws };
      }

      // ---- post-trade roster projection ------------------------------------
      // Each roster is graded by the engine team-OVR formula (SMPOvr, shared
      // with the Lineup Lab); its MOV inverse feeds the sim's logistic model
      // against the other nine rosters, home/road averaged, over the full
      // regular season. Draft picks carry no OVR/WS, so they don't move the
      // numbers — the deal note says so whenever picks are in the package.
      function rosterRawOvr(roster) {
        return teamOvrRaw(roster.map((p) => p.ovr));
      }

      function projectedWins(myMov, oppMovs) {
        if (!oppMovs.length) return null;
        let sum = 0;
        oppMovs.forEach((theirs) => {
          const diff = myMov - theirs;
          const home = 1 / (1 + Math.exp(-(diff + HCA) * K));
          const away = 1 / (1 + Math.exp(-(diff - HCA) * K));
          sum += (home + away) / 2;
        });
        return seasonGames * (sum / oppMovs.length);
      }

      function leagueProjection(overrides) {
        // {tid: {raw, mov, wins}} for every team; `overrides` swaps in
        // post-trade rosters for the two teams in the deal.
        const raws = {};
        data.teams.forEach((t) => {
          const roster = overrides && overrides[t.tid] ? overrides[t.tid] : (rostersByTid[t.tid] || []);
          raws[t.tid] = rosterRawOvr(roster);
        });
        const out = {};
        data.teams.forEach((t) => {
          const mine = ovrToMov(raws[t.tid]);
          const opp = data.teams.filter((o) => o.tid !== t.tid).map((o) => ovrToMov(raws[o.tid]));
          out[t.tid] = { raw: raws[t.tid], wins: projectedWins(mine, opp) };
        });
        return out;
      }

      const fmtDelta = (n, dp) => {
        const v = Number(n.toFixed(dp));
        if (v === 0) return '±' + (0).toFixed(dp);
        return (v > 0 ? '+' : '−') + Math.abs(v).toFixed(dp);
      };
      const deltaCls = (n, dp) => {
        const v = Number(n.toFixed(dp));
        return v > 0 ? ' tproj-delta--up' : (v < 0 ? ' tproj-delta--down' : '');
      };
      const record = (wins) => Math.round(wins) + '–' + (seasonGames - Math.round(wins));

      function projCard(mine, other, before, after) {
        const tid = mine.team.tid;
        const ovr0 = roundOvr(before[tid].raw);
        const ovr1 = roundOvr(after[tid].raw);
        const w0 = before[tid].wins;
        const w1 = after[tid].wins;
        const wsIn = other.ws;   // players arriving came from the other side
        const wsOut = mine.ws;
        const wsNet = wsIn - wsOut;
        const rowHtml = (label, value, delta, title) =>
          '<div class="tproj-row"' + (title ? ' title="' + esc(title) + '"' : '') + '>'
          + '<span class="tproj-label">' + label + '</span>'
          + '<span class="tproj-vals">' + value + '</span>'
          + delta + '</div>';
        const chip = (n, dp, suffix) =>
          '<span class="tproj-delta' + deltaCls(n, dp) + '">' + fmtDelta(n, dp) + (suffix || '') + '</span>';
        let html = '<div class="tproj-side">'
          + '<div class="tproj-head"><strong>' + esc(mine.team.abbrev) + '</strong>'
          + '<span class="muted">' + esc(fullName(mine.team)) + '</span></div>';
        html += rowHtml('Team OVR', ovr0 + ' <span class="tproj-arrow">→</span> ' + ovr1,
          chip(ovr1 - ovr0, 0), 'Engine team overall for the top ten of the roster, before → after the trade');
        html += rowHtml('Proj. record', record(w0) + ' <span class="tproj-arrow">→</span> ' + record(w1),
          chip(w1 - w0, 1, ' w'),
          'Projected ' + seasonGames + '-game record vs the other nine rosters, home/road averaged, before → after');
        html += rowHtml('Win shares', 'in ' + wsIn.toFixed(1) + ' · out ' + wsOut.toFixed(1),
          chip(wsNet, 1),
          (wsSeason ? wsSeason + ' regular-season' : 'Last completed season’s') + ' Win Shares arriving vs leaving');
        html += '<p class="tproj-verdict">OVR ' + fmtDelta(ovr1 - ovr0, 0)
          + ' · projected wins ' + fmtDelta(w1 - w0, 1)
          + ' · net WS ' + fmtDelta(wsNet, 1) + '</p>';
        html += '</div>';
        return html;
      }

      function taxReadout(team, salaryOut, salaryIn) {
        const before = team.payroll;
        const after = before - salaryOut + salaryIn;
        const scale = Math.max(tax * 1.15, before, after);
        const over = after > tax;
        const room = tax - after;
        const note = over
          ? fmtM(-room) + ' above the ' + fmtM(tax) + ' league average'
          : fmtM(room) + ' below the ' + fmtM(tax) + ' league average';
        return '<div class="tfin-team' + (over ? ' tfin-team--over' : '') + '">'
          + '<div class="tfin-head"><strong>' + esc(team.abbrev) + '</strong>'
          + '<span class="tfin-nums">' + fmtM(before) + ' → <strong>' + fmtM(after) + '</strong></span></div>'
          + '<div class="tfin-bar"><i class="tfin-fill" style="width:' + Math.min(100, (after / scale) * 100).toFixed(1) + '%"></i>'
          + '<span class="tfin-tick" style="left:' + ((tax / scale) * 100).toFixed(1) + '%"></span></div>'
          + '<div class="tfin-note' + (over ? ' tfin-note--over' : '') + '">' + note + '</div>'
          + '</div>';
      }

      function renderSummary() {
        const a = sideAssets(sides[0]);
        const b = sideAssets(sides[1]);
        if (!a.team || !b.team) { summary.innerHTML = '<p class="muted">Pick two teams.</p>'; return; }
        if (a.team.tid === b.team.tid) {
          summary.innerHTML = '<p class="muted">Pick two different teams.</p>';
          return;
        }
        const outA = new Set(a.players.map((p) => p.pid));
        const outB = new Set(b.players.map((p) => p.pid));
        const overrides = {};
        overrides[a.team.tid] = (rostersByTid[a.team.tid] || []).filter((p) => !outA.has(p.pid)).concat(b.players);
        overrides[b.team.tid] = (rostersByTid[b.team.tid] || []).filter((p) => !outB.has(p.pid)).concat(a.players);
        const before = leagueProjection(null);
        const after = leagueProjection(overrides);

        const lines = [];
        const describe = (from, to) => {
          const bits = from.players.map((p) => esc(p.name)).concat(from.picks.map((pick) => esc(pick.label)));
          return '<p><strong>' + esc(from.team.abbrev) + ' → ' + esc(to.team.abbrev) + ':</strong> ' + (bits.join(', ') || '<span class="muted">nothing</span>')
            + ' <span class="muted">(salary ' + fmtM(from.salary) + ')</span></p>';
        };
        lines.push(describe(a, b));
        lines.push(describe(b, a));
        lines.push('<div class="tproj">' + projCard(a, b, before, after) + projCard(b, a, before, after) + '</div>');
        lines.push('<div class="tfin">' + taxReadout(a.team, a.salary, b.salary) + taxReadout(b.team, b.salary, a.salary) + '</div>');
        if (a.picks.length || b.picks.length) {
          lines.push('<p class="muted tproj-note">Draft picks change hands but carry no OVR or Win Shares, so they don’t move the projections.</p>');
        }
        summary.innerHTML = lines.join('');
      }

      renderSide(0);
      renderSide(1);
      renderSummary();
    }
  }

  boot();
})();
