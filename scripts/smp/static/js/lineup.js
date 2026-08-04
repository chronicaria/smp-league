// ---------- Lineup Lab (lineup.html) ----------
// Self-contained IIFE: appended after the main site bundle's closing wrapper,
// so it guards on its own root element and no-ops on every other page.
(function () {
  const app = document.querySelector('[data-lineup-app]');
  if (!app) return;
  // Shared engine team-OVR port (constants + formula + MOV inverse): published
  // by trade-extras.js, which precedes this file in the bundle concat order.
  const O = window.SMPOvr;
  if (!O) return;

  const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const norm = (s) => s.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

  // ADAPTATION for a hand-picked group: team_ovr rates a full roster, so a bare
  // five would drag five literal 0.0 bench slots into the weighting and every
  // lineup would grade absurdly negative. The missing roster spots are filled
  // with app-data.sim.bench_ovrs — the league-average 6th..10th-best OVR
  // across the ten current rosters (5 floats, sorted desc):
  //   5-man mode:  your five + the whole league-average bench;
  //   10-man mode: your bench picks fill slots 6-10, and each EMPTY bench slot
  //                falls back to that slot's league-average value.
  // The weighting itself is untouched — the effective ten feed
  // projections.team_ovr exactly (via SMPOvr.teamOvrRaw). Safety net for a
  // stale app-data.json without bench_ovrs: pad with simmodel.REPLACEMENT_OVR
  // (40.0), the repo's "freely-available filler" constant, which tests assert
  // against projections.team_ovr.
  const REPLACEMENT_OVR = 40.0;
  let benchOvrs = null; // payload.sim.bench_ovrs when present, else null
  function benchAt(i) {
    return benchOvrs && Number.isFinite(benchOvrs[i]) ? benchOvrs[i] : REPLACEMENT_OVR;
  }

  // YIQ text-on-color pick (presentational only; server pages get the audited
  // on_primary from identity.py — app-data carries primary/secondary only).
  function textOn(hex) {
    let c = String(hex || '').replace('#', '');
    if (c.length === 3) c = c.split('').map((x) => x + x).join('');
    const n = parseInt(c, 16);
    if (!Number.isFinite(n)) return '#e8ecf1';
    const yiq = (((n >> 16) & 255) * 299 + (((n >> 8) & 255)) * 587 + (n & 255) * 114) / 1000;
    return yiq >= 140 ? '#101317' : '#e8ecf1';
  }

  const fmtMoney = (thousands) => '$' + (thousands / 1000).toFixed(1) + 'M';
  const fmtPct = (p) => (p * 100).toFixed(1) + '%'; // one decimal, everywhere

  let mode = 5; // 5 = your five + league-average bench; 10 = you build the bench
  const slots = [null, null, null, null, null, null, null, null, null, null];
  const inputs = Array.from(app.querySelectorAll('[data-ll-input]'));
  const summaryEl = app.querySelector('[data-ll-summary]');
  const matchupsEl = app.querySelector('[data-ll-matchups]');
  const benchWrap = app.querySelector('[data-ll-bench]');
  const headingEl = app.querySelector('[data-ll-heading]');
  const benchNoteEl = document.querySelector('[data-ll-benchnote]');
  const modeInputs = Array.from(app.querySelectorAll('[data-ll-mode]'));

  let payload = null;
  let byPid = {};
  let byTid = {};

  function teamChip(tid) {
    const team = byTid[tid];
    if (!team) {
      const label = tid === -2 ? 'Draft' : 'FA';
      return '<span class="team-chip ll-chip ll-chip-neutral">' + label + '</span>';
    }
    const c = team.colors || {};
    const style = '--team-primary:' + escapeHtml(c.primary || '#39424f')
      + ';--team-secondary:' + escapeHtml(c.secondary || '#8899aa')
      + ';--team-on-primary:' + escapeHtml(textOn(c.primary || '#39424f'));
    return '<span class="team-chip ll-chip" style="' + style + '"><span class="team-chip-dot"></span>'
      + escapeHtml(team.abbrev) + '</span>';
  }

  function optionLabel(p) {
    const team = byTid[p.tid];
    const t = team ? team.abbrev : (p.tid === -2 ? 'Draft' : 'FA');
    return t + ' · ' + p.pos + ' · ' + p.ovr + ' ovr';
  }

  // --- lineup size mode ------------------------------------------------------
  function setMode(next, silent) {
    mode = next === 10 ? 10 : 5;
    if (mode === 5) {
      // 5-man mode has no personal bench: drop bench picks so the formula,
      // the salary bill and the shareable URL all describe what's visible.
      for (let i = 5; i < 10; i += 1) {
        slots[i] = null;
        if (inputs[i]) inputs[i].value = '';
      }
    }
    if (benchWrap) benchWrap.hidden = mode !== 10;
    modeInputs.forEach((r) => { r.checked = Number(r.value) === mode; });
    if (headingEl) headingEl.textContent = mode === 10 ? 'Your ten' : 'Your five';
    if (benchNoteEl) {
      benchNoteEl.textContent = mode === 10
        ? 'Your ten (league-average fill for empty bench slots) vs each full roster, scored by the home page’s win-probability model.'
        : 'Your five + a league-average bench vs each full roster, scored by the home page’s win-probability model.';
    }
    if (!silent) {
      syncHash();
      render();
    }
  }
  modeInputs.forEach((r) => {
    r.addEventListener('change', () => { if (r.checked) setMode(Number(r.value)); });
  });

  // The ten OVRs the engine formula weighs, honouring the mode: picked players
  // first, then league-average bench values for whatever is missing (per-slot
  // in 10-man mode, the whole bench in 5-man mode).
  function effectiveOvrs() {
    const ovrs = [];
    for (let i = 0; i < 5; i += 1) {
      if (slots[i] !== null && byPid[slots[i]]) ovrs.push(byPid[slots[i]].ovr);
    }
    if (mode === 10) {
      for (let j = 0; j < 5; j += 1) {
        const pid = slots[5 + j];
        ovrs.push(pid !== null && byPid[pid] ? byPid[pid].ovr : benchAt(j));
      }
    } else {
      for (let j = 0; j < 5; j += 1) ovrs.push(benchAt(j));
    }
    // empty starter slots: league-average filler so a partial lineup still grades
    let j = 0;
    while (ovrs.length < 10) ovrs.push(benchAt(j++));
    return ovrs;
  }

  // --- filterable combobox per slot (ARIA pattern modeled on search.js) ------
  function comboFor(input) {
    const slot = Number(input.dataset.slot);
    const list = document.getElementById(input.getAttribute('aria-controls'));
    const clearBtn = app.querySelector('[data-ll-clear][data-slot="' + slot + '"]');
    let selected = -1;

    function close() {
      list.hidden = true;
      selected = -1;
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-activedescendant', '');
    }

    function syncSelected(options) {
      options.forEach((o, i) => {
        const on = i === selected;
        o.classList.toggle('selected', on);
        o.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      input.setAttribute('aria-activedescendant', selected >= 0 && options[selected] ? options[selected].id : '');
    }

    function matches() {
      if (!payload) return [];
      const q = norm(input.value.trim());
      const taken = new Set(slots.filter((pid, i) => pid !== null && i !== slot));
      const pool = payload.players.filter((p) => !taken.has(p.pid));
      if (!q) return pool.slice(0, 12); // payload is sorted by ovr desc
      const score = (name) => {
        const n = norm(name);
        if (n.startsWith(q)) return 0;
        if (n.split(' ').some((w) => w.startsWith(q))) return 1;
        if (n.includes(q)) return 2;
        return -1;
      };
      const found = [];
      pool.forEach((p) => {
        const s = score(p.name);
        if (s >= 0) found.push([s, p]);
      });
      found.sort((a, b) => a[0] - b[0] || b[1].ovr - a[1].ovr || a[1].name.localeCompare(b[1].name));
      return found.slice(0, 12).map((f) => f[1]);
    }

    function open() {
      const found = matches();
      if (!found.length) {
        list.innerHTML = '<div class="search-empty" role="option" aria-disabled="true">No matches.</div>';
      } else {
        list.innerHTML = found.map((p, i) =>
          '<button type="button" class="ll-option" id="ll-opt-' + slot + '-' + i + '" role="option" aria-selected="false" data-pid="' + p.pid + '">'
          + '<span>' + escapeHtml(p.name) + '</span><span class="muted">' + escapeHtml(optionLabel(p)) + '</span></button>').join('');
      }
      list.hidden = false;
      selected = -1;
      input.setAttribute('aria-expanded', 'true');
      input.setAttribute('aria-activedescendant', '');
    }

    function pickPid(pid) {
      slots[slot] = pid;
      if (byPid[pid]) input.value = byPid[pid].name; // even while focused (renderPicks skips the active input)
      close();
      syncHash();
      render();
    }

    input.addEventListener('input', open);
    input.addEventListener('focus', () => { if (payload) open(); });
    input.addEventListener('keydown', (event) => {
      const options = Array.from(list.querySelectorAll('[role="option"][data-pid]'));
      if (event.key === 'Escape') { close(); return; }
      if (event.key === 'ArrowDown' && list.hidden) { event.preventDefault(); open(); return; }
      if (!options.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, options.length - 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = options[Math.max(0, selected)];
        if (target) pickPid(Number(target.dataset.pid));
        return;
      } else { return; }
      syncSelected(options);
    });
    list.addEventListener('click', (event) => {
      const option = event.target.closest('[data-pid]');
      if (option) pickPid(Number(option.dataset.pid));
    });
    document.addEventListener('click', (event) => {
      if (!input.contains(event.target) && !list.contains(event.target)) close();
    });
    if (clearBtn) {
      clearBtn.addEventListener('click', () => {
        slots[slot] = null;
        input.value = '';
        syncHash();
        render();
        input.focus();
      });
    }
  }

  // --- shareable state: mode + pids in the hash ------------------------------
  // 5-man mode keeps the legacy "#pid,pid,…" format (old links stay valid);
  // 10-man mode is "#10:" + the ten slots positionally, empty slots as empty
  // strings ("#10:12,,34" = starters 1+3 picked), trailing blanks trimmed.
  function syncHash() {
    if (mode === 10) {
      const parts = slots.map((pid) => (pid === null ? '' : String(pid)));
      while (parts.length && parts[parts.length - 1] === '') parts.pop();
      history.replaceState(null, '', '#10:' + parts.join(','));
      return;
    }
    const pids = slots.slice(0, 5).filter((pid) => pid !== null);
    history.replaceState(null, '', pids.length ? '#' + pids.join(',') : location.pathname + location.search);
  }

  function readHash() {
    const raw = (location.hash || '').replace(/^#/, '');
    if (raw.slice(0, 3) === '10:') {
      setMode(10, true);
      raw.slice(3).split(',').slice(0, 10).forEach((part, i) => {
        const pid = Number(part);
        if (part !== '' && byPid[pid]) slots[i] = pid;
      });
      return;
    }
    raw.split(',').filter(Boolean).slice(0, 5).forEach((part, i) => {
      const pid = Number(part);
      if (byPid[pid]) slots[i] = pid;
    });
  }

  // --- rendering -------------------------------------------------------------
  function renderPicks() {
    slots.forEach((pid, i) => {
      const pickEl = app.querySelector('[data-ll-pick="' + i + '"]');
      const clearBtn = app.querySelector('[data-ll-clear][data-slot="' + i + '"]');
      const p = pid !== null ? byPid[pid] : null;
      if (!p) {
        pickEl.innerHTML = i >= 5
          ? '<span class="muted">League-average fill</span>'
          : '<span class="muted">Empty slot</span>';
        if (clearBtn) clearBtn.hidden = true;
        return;
      }
      if (inputs[i] && document.activeElement !== inputs[i]) inputs[i].value = p.name;
      pickEl.innerHTML = teamChip(p.tid)
        + ' <span class="ll-pick-meta">' + escapeHtml(p.pos) + ' · <strong>' + p.ovr + '</strong> ovr · '
        + escapeHtml(fmtMoney(p.salary)) + (p.exp ? ' thru ' + p.exp : '') + '</span>';
      if (clearBtn) clearBtn.hidden = false;
    });
  }

  function renderSummary(picked, matchupRows) {
    const starters = slots.slice(0, 5).filter((pid) => pid !== null).length;
    const benchPicked = mode === 10 ? slots.slice(5).filter((pid) => pid !== null).length : 0;
    const count = picked.length;
    const ovr = count ? O.roundOvr(O.teamOvrRaw(effectiveOvrs())) : null;
    const salary = picked.reduce((sum, p) => sum + (p.salary || 0), 0);
    const capLine = payload.finance.tax_line;   // $100M hard cap
    const overCap = salary > capLine;
    const gap = Math.abs(salary - capLine);
    let avgWin = null;
    if (matchupRows.length) {
      avgWin = matchupRows.reduce((sum, r) => sum + (r.home + r.away) / 2, 0) / matchupRows.length;
    }
    const tile = (label, value, sub, cls) =>
      '<div class="ll-tile' + (cls ? ' ' + cls : '') + '"><span class="ll-tile-label">' + label + '</span>'
      + '<strong>' + value + '</strong><span class="muted">' + sub + '</span></div>';
    const benchLabel = benchOvrs ? 'a league-average bench' : 'a replacement-level bench';
    let ovrSub;
    if (mode === 10) {
      ovrSub = (starters === 5 && benchPicked === 5)
        ? 'your ten'
        : (starters + benchPicked) + ' picked · league-average fill for the rest';
    } else {
      ovrSub = (starters === 5 ? 'your five' : starters + ' of 5 picked') + ' + ' + benchLabel;
    }
    summaryEl.innerHTML = '<div class="ll-tiles">'
      + tile('Lineup OVR', ovr === null ? '—' : String(ovr), ovrSub, '')
      + tile('Total salary', fmtMoney(salary),
             overCap ? fmtMoney(gap) + ' OVER the ' + fmtMoney(capLine) + ' cap — illegal roster'
                     : fmtMoney(gap) + ' under the ' + fmtMoney(capLine) + ' cap',
             overCap ? 'll-over-tax' : '')
      + tile('Average win %', avgWin === null ? '—' : fmtPct(avgWin),
             avgWin === null ? 'pick five players' : 'home/road average vs all ' + matchupRows.length + ' rosters', '')
      + '</div>';
  }

  function matchupData() {
    // matchups need the full first five; the bench may stay league-average
    const startersFull = slots.slice(0, 5).every((pid) => pid !== null);
    if (!startersFull || !payload) return [];
    const k = payload.sim.logistic_k;
    const hca = payload.sim.hca;
    const mine = O.ovrToMov(O.teamOvrRaw(effectiveOvrs()));
    return payload.teams.map((team) => {
      const roster = payload.players.filter((p) => p.tid === team.tid);
      const raw = O.teamOvrRaw(roster.map((p) => p.ovr));
      const diff = mine - O.ovrToMov(raw);
      return {
        team: team,
        ovr: O.roundOvr(raw),
        home: 1 / (1 + Math.exp(-(diff + hca) * k)),
        away: 1 / (1 + Math.exp(-(diff - hca) * k)),
      };
    }).sort((a, b) => b.ovr - a.ovr || a.team.tid - b.team.tid);
  }

  function renderMatchups(rows) {
    if (!rows.length) {
      matchupsEl.innerHTML = '<p class="muted">Pick five players to see the matchup board.</p>';
      return;
    }
    const bar = (p) => '<span class="ll-bar" aria-hidden="true"><i style="width:'
      + Math.max(2, Math.min(100, p * 100)).toFixed(1) + '%"></i></span>';
    let html = '<div class="table-wrap"><table class="ll-table">'
      + '<caption class="sr-only">Projected win probability for your lineup against each roster</caption>'
      + '<thead><tr><th scope="col">Opponent</th><th scope="col">Their OVR</th>'
      + '<th scope="col">Win % at home</th><th scope="col">Win % on road</th></tr></thead><tbody>';
    rows.forEach((r) => {
      html += '<tr><td>' + teamChip(r.team.tid) + ' <span class="ll-opp-name">'
        + escapeHtml(r.team.region + ' ' + r.team.name) + '</span></td>'
        + '<td>' + r.ovr + '</td>'
        + '<td>' + bar(r.home) + ' ' + fmtPct(r.home) + '</td>'
        + '<td>' + bar(r.away) + ' ' + fmtPct(r.away) + '</td></tr>';
    });
    html += '</tbody></table></div>';
    matchupsEl.innerHTML = html;
  }

  function render() {
    if (!payload) return;
    renderPicks();
    const picked = slots.filter((pid) => pid !== null).map((pid) => byPid[pid]);
    const rows = matchupData();
    renderSummary(picked, rows);
    renderMatchups(rows);
  }

  fetch((document.body.dataset.root || '') + 'assets/app-data.json')
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((data) => {
      payload = data;
      const bench = data.sim && data.sim.bench_ovrs;
      if (Array.isArray(bench) && bench.length === 5 && bench.every((v) => Number.isFinite(v))) {
        benchOvrs = bench;
      }
      data.players.forEach((p) => { byPid[p.pid] = p; });
      data.teams.forEach((t) => { byTid[t.tid] = t; });
      inputs.forEach(comboFor);
      readHash();
      render();
    })
    .catch(() => {
      summaryEl.innerHTML = '<p class="muted">Could not load player data (assets/app-data.json). Reload to try again.</p>';
    });
})();
