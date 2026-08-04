(function () {
  function cellValue(row, index) {
    const cell = row.children[index];
    if (!cell) return "";
    return cell.dataset.sort !== undefined ? cell.dataset.sort : cell.textContent.trim();
  }

  function compareValues(a, b) {
    const na = Number(a);
    const nb = Number(b);
    const aNumeric = a !== "" && Number.isFinite(na);
    const bNumeric = b !== "" && Number.isFinite(nb);
    if (aNumeric && bNumeric) return na - nb;
    return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  document.querySelectorAll("table[data-sortable]").forEach((table) => {
    const headers = Array.from(table.querySelectorAll("thead th"));
    const caption = table.querySelector('caption');
    if (caption) table.setAttribute('aria-label', caption.textContent.trim());
    function activateSort(header, index) {
      const tbody = table.tBodies[0];
      if (!tbody) return;
      const rows = Array.from(tbody.rows);
      const descending = header.classList.contains("sort-asc");
      headers.forEach((h) => {
        h.classList.remove("sort-asc", "sort-desc");
        h.setAttribute("aria-sort", "none");
      });
      header.classList.add(descending ? "sort-desc" : "sort-asc");
      header.setAttribute("aria-sort", descending ? "descending" : "ascending");
      rows.sort((ra, rb) => {
        const result = compareValues(cellValue(ra, index), cellValue(rb, index));
        return descending ? -result : result;
      });
      rows.forEach((row) => tbody.appendChild(row));
    }
    headers.forEach((header, index) => {
      header.tabIndex = 0;
      header.setAttribute("aria-sort", "none");
      header.addEventListener("click", () => activateSort(header, index));
      header.addEventListener("keydown", (event) => {
        if (event.key !== "Enter" && event.key !== " ") return;
        event.preventDefault();
        activateSort(header, index);
      });
    });
  });

  document.querySelectorAll("[data-table-filter]").forEach((input) => {
    const table = document.getElementById(input.dataset.tableFilter);
    if (!table) return;
    input.addEventListener("input", () => {
      const needle = input.value.trim().toLowerCase();
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = needle && !row.textContent.toLowerCase().includes(needle);
      });
    });
  });

  document.querySelectorAll('[data-pos-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.posFilter);
    if (!table || table.dataset.posCol === undefined) return;
    const col = Number(table.dataset.posCol);
    const apply = () => {
      const f = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        const cell = row.cells[col];
        const pos = cell ? cell.textContent.trim() : '';
        // single-letter groups (G/F/C) match by substring; two-letter picks match exactly
        const match = f === 'all' || (f.length === 1 ? pos.indexOf(f) !== -1 : pos === f);
        row.classList.toggle('pos-hidden', !match);
      });
    };
    select.addEventListener('change', apply);
    apply();
  });
  document.querySelectorAll('[data-schedule-filter]').forEach((select) => {
    const table = document.getElementById(select.dataset.scheduleFilter);
    if (!table) return;
    const apply = () => {
      const value = select.value;
      Array.from(table.tBodies[0].rows).forEach((row) => {
        row.hidden = value !== 'all' && row.dataset.scheduleTeam !== value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('[data-day-select]').forEach((select) => {
    const panels = Array.from(document.querySelectorAll('[data-day-panel]'));
    const apply = () => {
      panels.forEach((panel) => {
        panel.hidden = panel.dataset.dayPanel !== select.value;
      });
    };
    select.addEventListener('change', apply);
    apply();
  });

  document.querySelectorAll('.click-row[data-href]').forEach((row) => {
    row.addEventListener('click', (event) => {
      const target = event.target;
      if (target && target.closest && target.closest('a')) return;
      window.location.href = row.dataset.href;
    });
  });

  document.querySelectorAll('[data-view-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.viewToggle);
    if (!table) return;
    const viewStoreKey = 'viewtoggle:' + wrap.dataset.viewToggle;
    function activateView(button, persist) {
      wrap.querySelectorAll('button').forEach((b) => {
        b.classList.remove('active');
        b.setAttribute('aria-pressed', 'false');
      });
      button.classList.add('active');
      button.setAttribute('aria-pressed', 'true');
      table.classList.remove('show-adv', 'show-p36', 'show-rate');
      if (button.dataset.view !== 'basic') table.classList.add('show-' + button.dataset.view);
      if (persist) { try { localStorage.setItem(viewStoreKey, button.dataset.view); } catch (e) {} }
    }
    wrap.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => activateView(button, true));
    });
    let storedView = null;
    try { storedView = localStorage.getItem(viewStoreKey); } catch (e) {}
    const savedButton = storedView && wrap.querySelector('button[data-view="' + storedView + '"]');
    if (savedButton && !savedButton.classList.contains('active')) activateView(savedButton, false);
  });

  document.querySelectorAll('[data-group-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.groupToggle);
    if (!table) return;
    const apply = () => {
      const active = new Set(
        Array.from(wrap.querySelectorAll('button.active')).map((b) => b.dataset.group)
      );
      Array.from(table.tBodies[0].rows).forEach((row) => {
        if (!row.dataset.group) return;
        row.classList.toggle('group-hidden', !active.has(row.dataset.group));
      });
    };
    wrap.querySelectorAll('button').forEach((button) => {
      button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
      button.addEventListener('click', () => {
        button.classList.toggle('active');
        button.setAttribute('aria-pressed', button.classList.contains('active') ? 'true' : 'false');
        apply();
      });
    });
    apply();
  });

  document.addEventListener('click', (event) => {
    document.querySelectorAll('details.team-dropdown[open], details.nav-dropdown[open]').forEach((details) => {
      if (!details.contains(event.target)) details.removeAttribute('open');
    });
  });

  // ---------- platform config + storage (shared by later fragments) ----------
  const smpConfigEl = document.getElementById('smp-config');
  let siteConfig = {};
  if (smpConfigEl) {
    try { siteConfig = JSON.parse(smpConfigEl.textContent) || {}; } catch (e) { siteConfig = {}; }
  }
  const smpStore = {
    get(key) { try { return localStorage.getItem(key); } catch (e) { return null; } },
    set(key, value) { try { localStorage.setItem(key, value); } catch (e) {} },
    remove(key) { try { localStorage.removeItem(key); } catch (e) {} },
  };

  // ---------- three-state theme toggle (auto / dark / light) ----------
  // Persisted as localStorage.theme = "dark"|"light"; auto = key absent, which is
  // exactly what the pre-paint snippet in page_html reads before first render.
  const themeBtn = document.querySelector('[data-theme-toggle]');
  const themeMedia = matchMedia('(prefers-color-scheme: light)');
  const THEME_LABELS = {
    auto: 'Theme: auto (follows your system)',
    dark: 'Theme: dark',
    light: 'Theme: light',
  };
  function applyThemePref(pref, persist) {
    document.documentElement.dataset.themePref = pref;
    document.documentElement.dataset.theme = pref === 'auto' ? (themeMedia.matches ? 'light' : 'dark') : pref;
    if (persist) {
      if (pref === 'auto') smpStore.remove('theme');
      else smpStore.set('theme', pref);
    }
    if (themeBtn) {
      themeBtn.setAttribute('aria-label', THEME_LABELS[pref]);
      themeBtn.title = THEME_LABELS[pref] + ' — click to change';
    }
  }
  const savedTheme = smpStore.get('theme');
  applyThemePref(savedTheme === 'dark' || savedTheme === 'light' ? savedTheme : 'auto', false);
  if (themeBtn) {
    themeBtn.addEventListener('click', () => {
      const order = ['auto', 'dark', 'light'];
      const current = document.documentElement.dataset.themePref || 'auto';
      applyThemePref(order[(order.indexOf(current) + 1) % order.length], true);
    });
  }
  const onThemeMediaChange = () => {
    if ((document.documentElement.dataset.themePref || 'auto') === 'auto') applyThemePref('auto', false);
  };
  if (themeMedia.addEventListener) themeMedia.addEventListener('change', onThemeMediaChange);
  else if (themeMedia.addListener) themeMedia.addListener(onThemeMediaChange);

  // ---------- My Team mode ----------
  // Picking a team stores the tid, retints --accent with the team's chart color
  // (readable on both themes by design), tags body[data-my-team], highlights every
  // row carrying data-tid, and pins the team to the top of the Teams menu.
  const teamPicker = document.querySelector('[data-my-team-picker]');
  const myTeamColors = siteConfig.teamColors || {};
  function applyMyTeam(tid, persist) {
    const rootStyle = document.documentElement.style;
    const colors = tid ? myTeamColors[tid] : null;
    document.querySelectorAll('tr.my-team-row').forEach((row) => row.classList.remove('my-team-row'));
    document.querySelectorAll('.my-team-link').forEach((a) => a.classList.remove('my-team-link'));
    if (!colors) {
      delete document.body.dataset.myTeam;
      rootStyle.removeProperty('--accent');
      rootStyle.removeProperty('--accent-soft');
      if (persist) { smpStore.remove('myTeam'); smpStore.remove('myTeamAccent'); }
    } else {
      document.body.dataset.myTeam = tid;
      rootStyle.setProperty('--accent', colors.chart);
      rootStyle.setProperty('--accent-soft', 'color-mix(in srgb, ' + colors.chart + ' 14%, transparent)');
      document.querySelectorAll('tr[data-tid="' + tid + '"]').forEach((row) => row.classList.add('my-team-row'));
      const navLink = document.querySelector('.team-menu a[data-tid="' + tid + '"]');
      if (navLink) {
        navLink.classList.add('my-team-link');
        if (navLink.parentElement && navLink.parentElement.firstElementChild !== navLink) {
          navLink.parentElement.insertBefore(navLink, navLink.parentElement.firstElementChild);
        }
      }
      if (persist) { smpStore.set('myTeam', tid); smpStore.set('myTeamAccent', colors.chart); }
    }
    if (teamPicker && teamPicker.value !== tid) teamPicker.value = tid;
  }
  const savedTeam = smpStore.get('myTeam');
  if (savedTeam && myTeamColors[savedTeam]) applyMyTeam(savedTeam, false);
  else if (savedTeam) { smpStore.remove('myTeam'); smpStore.remove('myTeamAccent'); }
  if (teamPicker) teamPicker.addEventListener('change', () => applyMyTeam(teamPicker.value, true));

  // ---------- heading anchor links (hover #, click copies the URL) ----------
  document.querySelectorAll('main.page-shell h2').forEach((heading) => {
    const text = heading.textContent.trim();
    if (!text) return;
    if (!heading.id) {
      const base = text.toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '')
        .replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '') || 'section';
      let id = base;
      let n = 2;
      while (document.getElementById(id)) { id = base + '-' + n; n += 1; }
      heading.id = id;
    }
    const anchor = document.createElement('a');
    anchor.className = 'h-anchor';
    anchor.href = '#' + heading.id;
    anchor.setAttribute('aria-label', 'Link to section: ' + text);
    anchor.textContent = '#';
    anchor.addEventListener('click', () => {
      if (!navigator.clipboard) return;
      const url = location.origin + location.pathname + '#' + heading.id;
      navigator.clipboard.writeText(url).then(() => {
        anchor.textContent = '✓';
        setTimeout(() => { anchor.textContent = '#'; }, 1200);
      }).catch(() => {});
    });
    heading.appendChild(anchor);
  });

  // ---------- player scatter chart ----------
  const chartCanvas = document.querySelector('[data-player-chart]');
  const chartDataEl = document.getElementById('player-chart-data');
  if (chartCanvas && chartDataEl) {
    const data = JSON.parse(chartDataEl.textContent);
    const labels = {};
    data.metrics.forEach((m) => { labels[m.key] = m.label; });
    const colors = {};
    data.teams.forEach((t) => { colors[t.abbrev] = t.color; });
    const hidden = new Set();
    const tooltip = document.querySelector('[data-chart-tooltip]');
    const legend = document.querySelector('[data-chart-legend]');
    const selX = document.querySelector('[data-chart-axis=\"x\"]');
    const selY = document.querySelector('[data-chart-axis=\"y\"]');
    const selPos = document.querySelector('[data-chart-pos]');
    const minMinInput = document.querySelector('[data-chart-minmin]');
    const minGpInput = document.querySelector('[data-chart-mingp]');
    const labelsInput = document.querySelector('[data-chart-labels]');
    let xKey = data.defaultX;
    let yKey = data.defaultY;
    let drawn = [];
    let hoverPt = null;

    // Theme-aware palette, resolved at draw time so light/dark both render true.
    function chartTheme() {
      const rootStyle = getComputedStyle(document.documentElement);
      const cssVar = (name, fallback) => (rootStyle.getPropertyValue(name) || '').trim() || fallback;
      return {
        line: cssVar('--line', '#2b313a'),
        muted: cssVar('--muted', '#939ca7'),
        text: cssVar('--text', '#e8ecf1'),
        accent: cssVar('--accent', '#5b9dff'),
        bg: getComputedStyle(chartCanvas).backgroundColor || '#171b21',
      };
    }

    // restore state from URL hash: #x=usg&y=ts&pos=G&min=20&labels=1
    const hashParams = new URLSearchParams((location.hash || '').replace(/^#/, ''));
    const validKeys = new Set(data.metrics.map((m) => m.key));
    if (validKeys.has(hashParams.get('x'))) xKey = hashParams.get('x');
    if (validKeys.has(hashParams.get('y'))) yKey = hashParams.get('y');
    if (selX) selX.value = xKey;
    if (selY) selY.value = yKey;
    if (selPos && ['G', 'F', 'C'].includes(hashParams.get('pos'))) selPos.value = hashParams.get('pos');
    if (minMinInput && hashParams.get('min')) minMinInput.value = hashParams.get('min');
    if (minGpInput && hashParams.get('mingp')) minGpInput.value = hashParams.get('mingp');
    if (labelsInput && hashParams.get('labels') === '1') labelsInput.checked = true;

    function syncHash() {
      const params = new URLSearchParams();
      params.set('x', xKey);
      params.set('y', yKey);
      if (selPos && selPos.value !== 'all') params.set('pos', selPos.value);
      if (minMinInput && Number(minMinInput.value) > 0) params.set('min', minMinInput.value);
      if (minGpInput && Number(minGpInput.value) > 0) params.set('mingp', minGpInput.value);
      if (labelsInput && labelsInput.checked) params.set('labels', '1');
      history.replaceState(null, '', '#' + params.toString());
    }

    data.teams.forEach((t) => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.style.setProperty('--dot', t.color);
      btn.setAttribute('aria-label', 'Toggle ' + t.abbrev + ' players');
      btn.setAttribute('aria-pressed', 'true');
      btn.innerHTML = '<span class=\"dot\"></span>' + t.abbrev;
      btn.addEventListener('click', () => {
        if (hidden.has(t.abbrev)) hidden.delete(t.abbrev); else hidden.add(t.abbrev);
        btn.classList.toggle('off', hidden.has(t.abbrev));
        btn.setAttribute('aria-pressed', hidden.has(t.abbrev) ? 'false' : 'true');
        draw();
      });
      legend.appendChild(btn);
    });

    function niceTicks(lo, hi, count) {
      const span = hi - lo || 1;
      const step0 = span / Math.max(1, count);
      const mag = Math.pow(10, Math.floor(Math.log10(step0)));
      const norm = step0 / mag;
      const step = (norm >= 5 ? 10 : norm >= 2 ? 5 : norm >= 1 ? 2 : 1) * mag;
      const ticks = [];
      for (let v = Math.ceil(lo / step) * step; v <= hi + 1e-9; v += step) ticks.push(v);
      return { ticks, step };
    }

    function fmtTick(value, step) {
      const digits = step >= 1 ? 0 : step >= 0.1 ? 1 : 2;
      return value.toFixed(digits);
    }

    // Dot radius scales gently with minutes: rotation players read larger.
    function dotRadius(p) {
      const min = Number.isFinite(p.v.min) ? p.v.min : 24;
      return 2.8 + 2.1 * Math.min(1, Math.max(0, min / 38));
    }

    function draw() {
      const theme = chartTheme();
      const dpr = window.devicePixelRatio || 1;
      const cw = chartCanvas.clientWidth;
      const ch = chartCanvas.clientHeight;
      chartCanvas.width = cw * dpr;
      chartCanvas.height = ch * dpr;
      const ctx = chartCanvas.getContext('2d');
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, cw, ch);
      ctx.font = '11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';

      const posFilter = selPos ? selPos.value : 'all';
      const minMin = minMinInput ? Number(minMinInput.value) || 0 : 0;
      const minGp = minGpInput ? Number(minGpInput.value) || 0 : 0;
      const pts = data.players.filter((p) =>
        !hidden.has(p.team)
        && Number.isFinite(p.v[xKey]) && Number.isFinite(p.v[yKey])
        && (posFilter === 'all' || (p.pos || '').includes(posFilter))
        && (!minMin || (Number.isFinite(p.v.min) && p.v.min >= minMin))
        && (!minGp || (Number.isFinite(p.v.gp) && p.v.gp >= minGp)));
      drawn = [];
      if (!pts.length) {
        if (tooltip) tooltip.hidden = true;
        hoverPt = null;
        ctx.fillStyle = theme.muted;
        ctx.fillText('No data for this combination.', 16, 24);
        return;
      }
      if (hoverPt && pts.indexOf(hoverPt.p) === -1) hoverPt = null;
      let xLo = Math.min(...pts.map((p) => p.v[xKey]));
      let xHi = Math.max(...pts.map((p) => p.v[xKey]));
      let yLo = Math.min(...pts.map((p) => p.v[yKey]));
      let yHi = Math.max(...pts.map((p) => p.v[yKey]));
      const xPad = (xHi - xLo || 1) * 0.06;
      const yPad = (yHi - yLo || 1) * 0.08;
      xLo -= xPad; xHi += xPad; yLo -= yPad; yHi += yPad;

      const m = { left: 52, right: 16, top: 14, bottom: 40 };
      const plotW = cw - m.left - m.right;
      const plotH = ch - m.top - m.bottom;
      const px = (v) => m.left + ((v - xLo) / (xHi - xLo)) * plotW;
      const py = (v) => m.top + plotH - ((v - yLo) / (yHi - yLo)) * plotH;

      // Horizontal gridlines only; the x-axis gets small tick marks instead.
      const xt = niceTicks(xLo, xHi, 8);
      const yt = niceTicks(yLo, yHi, 6);
      ctx.lineWidth = 1;
      ctx.strokeStyle = theme.line;
      ctx.fillStyle = theme.muted;
      yt.ticks.forEach((v) => {
        const y = py(v);
        ctx.globalAlpha = 0.5;
        ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke();
        ctx.globalAlpha = 1;
        ctx.textAlign = 'right';
        ctx.fillText(fmtTick(v, yt.step), m.left - 8, y + 3.5);
      });
      xt.ticks.forEach((v) => {
        const x = px(v);
        ctx.beginPath(); ctx.moveTo(x, m.top + plotH); ctx.lineTo(x, m.top + plotH + 5); ctx.stroke();
        ctx.textAlign = 'center';
        ctx.fillText(fmtTick(v, xt.step), x, m.top + plotH + 17);
      });
      // axis baselines
      ctx.strokeStyle = theme.line;
      ctx.beginPath();
      ctx.moveTo(m.left, m.top);
      ctx.lineTo(m.left, m.top + plotH);
      ctx.lineTo(m.left + plotW, m.top + plotH);
      ctx.stroke();
      // dashed zero lines when the range crosses zero
      ctx.strokeStyle = theme.muted;
      ctx.globalAlpha = 0.55;
      ctx.setLineDash([4, 4]);
      if (xLo < 0 && xHi > 0) { const x = px(0); ctx.beginPath(); ctx.moveTo(x, m.top); ctx.lineTo(x, m.top + plotH); ctx.stroke(); }
      if (yLo < 0 && yHi > 0) { const y = py(0); ctx.beginPath(); ctx.moveTo(m.left, y); ctx.lineTo(m.left + plotW, y); ctx.stroke(); }
      ctx.setLineDash([]);
      ctx.globalAlpha = 1;
      // axis labels
      ctx.fillStyle = theme.text;
      ctx.textAlign = 'center';
      ctx.font = '600 11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';
      ctx.fillText(labels[xKey] || xKey, m.left + plotW / 2, ch - 8);
      ctx.save();
      ctx.translate(13, m.top + plotH / 2);
      ctx.rotate(-Math.PI / 2);
      ctx.fillText(labels[yKey] || yKey, 0, 0);
      ctx.restore();
      ctx.font = '11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';

      pts.forEach((p) => {
        const x = px(p.v[xKey]);
        const y = py(p.v[yKey]);
        const r = dotRadius(p);
        ctx.beginPath();
        ctx.arc(x, y, r, 0, Math.PI * 2);
        ctx.fillStyle = colors[p.team] || theme.muted;
        ctx.globalAlpha = hoverPt && hoverPt.p !== p ? 0.55 : 0.95;
        ctx.fill();
        ctx.globalAlpha = 1;
        ctx.lineWidth = 1;
        ctx.strokeStyle = theme.bg;
        ctx.stroke();
        drawn.push({ x, y, p });
      });

      // label every visible point (overlap allowed)
      if (labelsInput && labelsInput.checked) {
        ctx.fillStyle = theme.muted;
        ctx.textAlign = 'left';
        ctx.font = '10px \"Helvetica Neue\", Helvetica, Arial, sans-serif';
        pts.forEach((p) => {
          if (hoverPt && hoverPt.p === p) return;
          ctx.fillText(p.name.split(' ').slice(-1)[0], px(p.v[xKey]) + dotRadius(p) + 3.5, py(p.v[yKey]) + 3);
        });
        ctx.font = '11px \"Helvetica Neue\", Helvetica, Arial, sans-serif';
      }

      // hovered point: full-strength dot with a halo ring and its name
      if (hoverPt) {
        const x = px(hoverPt.p.v[xKey]);
        const y = py(hoverPt.p.v[yKey]);
        const r = dotRadius(hoverPt.p);
        ctx.beginPath();
        ctx.arc(x, y, r + 1, 0, Math.PI * 2);
        ctx.fillStyle = colors[hoverPt.p.team] || theme.muted;
        ctx.fill();
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = theme.bg;
        ctx.stroke();
        ctx.beginPath();
        ctx.arc(x, y, r + 4.5, 0, Math.PI * 2);
        ctx.lineWidth = 1.5;
        ctx.strokeStyle = theme.text;
        ctx.globalAlpha = 0.7;
        ctx.stroke();
        ctx.globalAlpha = 1;
      }
    }

    function nearest(event) {
      const rect = chartCanvas.getBoundingClientRect();
      const mx = event.clientX - rect.left;
      const my = event.clientY - rect.top;
      let best = null;
      let bestDist = 144;
      drawn.forEach((d) => {
        const dist = (d.x - mx) * (d.x - mx) + (d.y - my) * (d.y - my);
        if (dist < bestDist) { bestDist = dist; best = d; }
      });
      return best;
    }

    chartCanvas.addEventListener('mousemove', (event) => {
      const hit = nearest(event);
      if ((hit && hit.p) !== (hoverPt && hoverPt.p)) {
        hoverPt = hit;
        draw();
      }
      if (!hit) { tooltip.hidden = true; chartCanvas.style.cursor = 'crosshair'; return; }
      chartCanvas.style.cursor = 'pointer';
      const dotColor = colors[hit.p.team] || '';
      tooltip.innerHTML = '<strong><span class=\"tip-dot\" style=\"--dot:' + dotColor + '\"></span>'
        + hit.p.name + ' <span class=\"tip-team\">' + hit.p.team + (hit.p.pos ? ' · ' + hit.p.pos : '') + '</span></strong>'
        + '<span>' + (labels[xKey] || xKey) + ' <b>' + hit.p.v[xKey] + '</b> · '
        + (labels[yKey] || yKey) + ' <b>' + hit.p.v[yKey] + '</b></span>';
      tooltip.hidden = false;
      const wrapRect = chartCanvas.parentElement.getBoundingClientRect();
      const rect = chartCanvas.getBoundingClientRect();
      let left = hit.x + (rect.left - wrapRect.left) + 14;
      let top = hit.y + (rect.top - wrapRect.top) - 14;
      if (left + tooltip.offsetWidth > wrapRect.width - 4) left = left - tooltip.offsetWidth - 28;
      tooltip.style.left = left + 'px';
      tooltip.style.top = top + 'px';
    });
    chartCanvas.addEventListener('mouseleave', () => {
      tooltip.hidden = true;
      if (hoverPt) { hoverPt = null; draw(); }
    });
    chartCanvas.addEventListener('click', (event) => {
      const hit = nearest(event);
      if (hit && hit.p.url) window.location.href = hit.p.url;
    });
    if (selX) selX.addEventListener('change', () => { xKey = selX.value; syncHash(); draw(); });
    if (selY) selY.addEventListener('change', () => { yKey = selY.value; syncHash(); draw(); });
    if (selPos) selPos.addEventListener('change', () => { syncHash(); draw(); });
    if (minMinInput) minMinInput.addEventListener('input', () => { syncHash(); draw(); });
    if (minGpInput) minGpInput.addEventListener('input', () => { syncHash(); draw(); });
    if (labelsInput) labelsInput.addEventListener('change', () => { syncHash(); draw(); });
    window.addEventListener('resize', draw);
    // repaint when the theme toggle stamps html[data-theme]
    new MutationObserver(() => draw()).observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] });
    draw();
  }

  // ---------- schedule/h2h column hover ----------
  document.querySelectorAll('.schedule-grid, .h2h-grid').forEach((table) => {
    table.addEventListener('mouseover', (event) => {
      const cell = event.target.closest('td, th');
      if (!cell || !table.contains(cell)) return;
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
      const idx = cell.cellIndex;
      if (idx > 0) {
        table.querySelectorAll('tr').forEach((tr) => {
          const target = tr.cells[idx];
          if (target) target.classList.add('col-hl');
        });
      }
    });
    table.addEventListener('mouseleave', () => {
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
    });
  });

  // ---------- home page: playoff-odds river hover crosshair ----------
  document.querySelectorAll('[data-oddsr]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.oddsr-chart');
    const tip = wrap.querySelector('[data-oddsr-tooltip]');
    const hLine = wrap.querySelector('[data-oddsr-hline]');
    const dataEl = wrap.parentElement &&
      wrap.parentElement.querySelector('script[type="application/json"]#oddsr-data');
    if (!svg || !tip || !hLine || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    if (!g || g.n < 2) return;
    const xs = (i) => g.ml + g.pw * i / (g.n - 1);

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function hide() {
      tip.hidden = true;
      hLine.style.display = 'none';
    }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let i = Math.round((loc.x - g.ml) / g.pw * (g.n - 1));
      if (i < 0) i = 0;
      if (i > g.n - 1) i = g.n - 1;
      const rows = d.teams
        .map((t) => ({ ab: t.ab, color: t.color, po: t.po[i] }))
        .filter((t) => t.po !== null && t.po !== undefined)
        .sort((a, b) => b.po - a.po);
      if (!rows.length) { hide(); return; }
      let html = '<strong>' + escapeHtml(d.names[i] || d.labels[i] || '') + '</strong>';
      rows.forEach((t) => {
        html += '<span class="oddsr-tip-row">' +
          '<span class="oddsr-tip-dot" style="background:' + escapeHtml(t.color) + '"></span>' +
          escapeHtml(t.ab) +
          '<span class="oddsr-tip-val">' + t.po.toFixed(1) + '%</span></span>';
      });
      const cx = xs(i);
      hLine.setAttribute('x1', cx);
      hLine.setAttribute('x2', cx);
      hLine.style.display = '';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;  // flip left
      if (left + tw > rect.width) left = rect.width - tw - 4;                // still over: pin right
      if (left < 0) left = 4;                                               // never off the left
      tip.style.left = left + 'px';
      let top = evt.clientY - rect.top + 12;
      if (top + tip.offsetHeight > rect.height) top = Math.max(4, rect.height - tip.offsetHeight - 4);
      tip.style.top = top + 'px';
    }

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

  // ---------- shared search index ----------
  const searchIndexRoot = document.body.dataset.root || '';
  let smpSearchIndex = null;
  function loadSearchIndex() {
    if (smpSearchIndex) return Promise.resolve(smpSearchIndex);
    return fetch(searchIndexRoot + 'assets/search-index.json')
      .then((r) => r.json())
      .then((data) => { smpSearchIndex = data; return smpSearchIndex; })
      .catch(() => ({ players: [], teams: [] }));
  }
  const smpNorm = (s) => String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');
  function smpMatchScore(name, q) {
    const n = smpNorm(name);
    if (n.startsWith(q)) return 0;
    if (n.split(' ').some((w) => w.startsWith(q))) return 1;
    if (n.includes(q)) return 2;
    return -1;
  }

  // ---------- global nav search ----------
  const searchInput = document.querySelector('[data-global-search]');
  const searchResults = document.querySelector('[data-search-results]');
  if (searchInput && searchResults) {
    const root = searchIndexRoot;
    let selected = -1;

    function close() {
      searchResults.hidden = true;
      selected = -1;
      searchInput.setAttribute('aria-expanded', 'false');
      searchInput.setAttribute('aria-activedescendant', '');
    }

    function syncSelected(links) {
      links.forEach((l, i) => {
        const on = i === selected;
        l.classList.toggle('selected', on);
        l.setAttribute('aria-selected', on ? 'true' : 'false');
      });
      searchInput.setAttribute('aria-activedescendant', selected >= 0 && links[selected] ? links[selected].id : '');
    }

    function renderResults(matches) {
      if (!matches.length) {
        searchResults.innerHTML = '<div class="search-empty" role="option" aria-disabled="true">No matches.</div>';
        searchResults.hidden = false;
        searchInput.setAttribute('aria-expanded', 'true');
        searchInput.setAttribute('aria-activedescendant', '');
        return;
      }
      searchResults.innerHTML = matches.map((m, i) =>
        '<a id="search-option-' + i + '" role="option" aria-selected="false" href="' + root + escapeHtml(m.u) + '"><span>' + escapeHtml(m.n) + '</span><span class="muted">' + escapeHtml(m.t) + '</span></a>').join('');
      searchResults.hidden = false;
      searchInput.setAttribute('aria-expanded', 'true');
      selected = -1;
    }

    function update() {
      const q = smpNorm(searchInput.value.trim());
      if (q.length < 2) { close(); return; }
      loadSearchIndex().then((data) => {
        const matches = [];
        (data.teams || []).forEach((t) => { const s = smpMatchScore(t.n, q); if (s >= 0) matches.push({ ...t, s: s - 0.5 }); });
        (data.players || []).forEach((p) => { const s = smpMatchScore(p.n, q); if (s >= 0) matches.push({ ...p, s }); });
        matches.sort((a, b) => a.s - b.s || a.n.localeCompare(b.n));
        renderResults(matches.slice(0, 8));
      });
    }

    searchInput.addEventListener('input', update);
    searchInput.addEventListener('focus', () => { loadSearchIndex(); if (searchInput.value.trim().length >= 2) update(); });
    searchInput.addEventListener('keydown', (event) => {
      const links = Array.from(searchResults.querySelectorAll('a'));
      if (event.key === 'Escape') { close(); searchInput.blur(); return; }
      if (!links.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, links.length - 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = links[Math.max(0, selected)];
        if (target) window.location.href = target.href;
        return;
      } else { return; }
      syncSelected(links);
    });
    document.addEventListener('click', (event) => {
      if (!searchInput.contains(event.target) && !searchResults.contains(event.target)) close();
    });
  }

  // ---------- command palette (Cmd+K / Ctrl+K / "/") ----------
  // Searches the same index as the nav search, grouped into Pages / Teams /
  // Players, with recent selections and t: / p: / g: prefix filters.
  const PALETTE_GROUPS = [
    { key: 'Pages', prefix: 'g' },
    { key: 'Teams', prefix: 't' },
    { key: 'Players', prefix: 'p' },
  ];
  let paletteOverlay = null;
  let paletteInput = null;
  let paletteResults = null;
  let paletteSelected = -1;
  let paletteReturnFocus = null;

  function paletteRecents() {
    try { return JSON.parse(smpStore.get('paletteRecents') || '[]') || []; } catch (e) { return []; }
  }
  function rememberRecent(item) {
    const next = [item].concat(paletteRecents().filter((r) => r.u !== item.u)).slice(0, 8);
    smpStore.set('paletteRecents', JSON.stringify(next));
  }

  function paletteEntries(data) {
    const pages = ((siteConfig && siteConfig.pages) || []).map((p) => ({ n: p.label, u: p.url, t: 'Page', g: 'Pages' }));
    const teams = (data.teams || []).map((t) => ({ n: t.n, u: t.u, t: t.t, g: 'Teams' }));
    const players = (data.players || []).map((p) => ({ n: p.n, u: p.u, t: p.t, g: 'Players' }));
    return { Pages: pages, Teams: teams, Players: players };
  }

  function renderPalette(groups) {
    const options = [];
    let html = '';
    groups.forEach((group) => {
      if (!group.items.length) return;
      html += '<div class="palette-group" role="presentation">' + escapeHtml(group.label) + '</div>';
      group.items.forEach((item) => {
        const i = options.length;
        options.push(item);
        html += '<a class="pal-opt" id="pal-opt-' + i + '" role="option" aria-selected="false" href="' + searchIndexRoot + escapeHtml(item.u) + '">'
          + '<span>' + escapeHtml(item.n) + '</span><span class="muted">' + escapeHtml(item.t || '') + '</span></a>';
      });
    });
    if (!options.length) html = '<div class="palette-empty">No matches.</div>';
    paletteResults.innerHTML = html;
    paletteSelected = options.length ? 0 : -1;
    syncPaletteSelected();
    paletteResults.querySelectorAll('a.pal-opt').forEach((a, i) => {
      a.addEventListener('click', () => rememberRecent(options[i]));
    });
    paletteResults._options = options;
  }

  function syncPaletteSelected() {
    const links = Array.from(paletteResults.querySelectorAll('a.pal-opt'));
    links.forEach((l, i) => {
      const on = i === paletteSelected;
      l.classList.toggle('selected', on);
      l.setAttribute('aria-selected', on ? 'true' : 'false');
      if (on) l.scrollIntoView({ block: 'nearest' });
    });
    paletteInput.setAttribute('aria-activedescendant', paletteSelected >= 0 && links[paletteSelected] ? links[paletteSelected].id : '');
  }

  function updatePalette() {
    const raw = paletteInput.value.trim();
    let only = null;
    let q = raw;
    const prefixMatch = raw.match(/^([gtp]):\s*(.*)$/i);
    if (prefixMatch) {
      const found = PALETTE_GROUPS.find((g) => g.prefix === prefixMatch[1].toLowerCase());
      if (found) { only = found.key; q = prefixMatch[2]; }
    }
    q = smpNorm(q);
    loadSearchIndex().then((data) => {
      const entries = paletteEntries(data);
      if (!q) {
        const groups = [];
        const recents = paletteRecents();
        if (recents.length && !only) groups.push({ label: 'Recent', items: recents });
        (only ? [only] : ['Pages']).forEach((key) => groups.push({ label: key, items: entries[key].slice(0, only ? 24 : 8) }));
        renderPalette(groups);
        return;
      }
      const caps = { Pages: 6, Teams: 6, Players: 9 };
      const groups = PALETTE_GROUPS
        .filter((g) => !only || g.key === only)
        .map((g) => {
          const items = entries[g.key]
            .map((item) => ({ item, s: smpMatchScore(item.n, q) }))
            .filter((x) => x.s >= 0)
            .sort((a, b) => a.s - b.s || a.item.n.localeCompare(b.item.n))
            .slice(0, only ? 24 : caps[g.key])
            .map((x) => x.item);
          return { label: g.key, items };
        });
      renderPalette(groups);
    });
  }

  function closePalette() {
    if (!paletteOverlay) return;
    paletteOverlay.hidden = true;
    if (paletteReturnFocus && paletteReturnFocus.focus) paletteReturnFocus.focus();
    paletteReturnFocus = null;
  }

  function buildPalette() {
    if (paletteOverlay) return;
    paletteOverlay = document.createElement('div');
    paletteOverlay.className = 'palette-overlay';
    paletteOverlay.hidden = true;
    paletteOverlay.innerHTML = '<div class="palette" role="dialog" aria-modal="true" aria-label="Site search">'
      + '<input type="text" class="palette-input" placeholder="Search players, teams, pages…" '
      + 'role="combobox" aria-autocomplete="list" aria-expanded="true" aria-controls="palette-results" '
      + 'aria-activedescendant="" autocomplete="off" spellcheck="false">'
      + '<div class="palette-results" id="palette-results" role="listbox" aria-label="Search results"></div>'
      + '<p class="palette-hint muted">↑↓ navigate · Enter open · Esc close · prefixes: t: teams · p: players · g: pages</p>'
      + '</div>';
    document.body.appendChild(paletteOverlay);
    paletteInput = paletteOverlay.querySelector('.palette-input');
    paletteResults = paletteOverlay.querySelector('.palette-results');
    paletteOverlay.addEventListener('click', (event) => {
      if (event.target === paletteOverlay) closePalette();
    });
    paletteInput.addEventListener('input', updatePalette);
    paletteInput.addEventListener('keydown', (event) => {
      const links = Array.from(paletteResults.querySelectorAll('a.pal-opt'));
      if (event.key === 'Escape') { event.preventDefault(); closePalette(); return; }
      if (event.key === 'Tab') { event.preventDefault(); return; }
      if (!links.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); paletteSelected = Math.min(paletteSelected + 1, links.length - 1); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); paletteSelected = Math.max(paletteSelected - 1, 0); }
      else if (event.key === 'Home' && paletteSelected > 0) { event.preventDefault(); paletteSelected = 0; }
      else if (event.key === 'End') { event.preventDefault(); paletteSelected = links.length - 1; }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = links[Math.max(0, paletteSelected)];
        if (target) {
          const options = paletteResults._options || [];
          const item = options[Math.max(0, paletteSelected)];
          if (item) rememberRecent(item);
          window.location.href = target.href;
        }
        return;
      } else { return; }
      syncPaletteSelected();
    });
  }

  function openPalette() {
    buildPalette();
    paletteReturnFocus = document.activeElement;
    paletteOverlay.hidden = false;
    paletteInput.value = '';
    paletteInput.focus();
    updatePalette();
  }

  document.addEventListener('keydown', (event) => {
    const isK = (event.key === 'k' || event.key === 'K') && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey;
    const isSlash = event.key === '/' && !event.metaKey && !event.ctrlKey && !event.altKey;
    if (!isK && !isSlash) return;
    if (isSlash) {
      const active = document.activeElement;
      if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT' || active.isContentEditable)) return;
    }
    if (paletteOverlay && !paletteOverlay.hidden) return;
    event.preventDefault();
    openPalette();
  });

  // =====================================================================
  // SMP.combobox — reusable filterable combobox factory
  //
  //   SMP.combobox({
  //     input:    HTMLInputElement (required). Gets combobox ARIA wiring; the
  //               popup list is created as a sibling inside a positioning wrap.
  //     items:    array of {label, sub?, value?} OR a function returning one.
  //               `label` is matched and shown left; `sub` shown right, muted.
  //     onSelect: function(item) called when the user picks an option (required).
  //     maxItems: cap on rendered options (default 12).
  //     minChars: minimum typed characters before the list opens (default 0;
  //               0 shows the top of the list on focus, like a select).
  //   }) -> { refresh(), close(), destroy() }
  //
  // Matching uses the same normalized prefix/word/substring scoring as site
  // search. Keyboard: ArrowUp/Down, Enter selects, Escape closes. On select the
  // input shows item.label and onSelect(item) fires.
  // =====================================================================
  window.SMP = window.SMP || {};
  window.SMP.combobox = function (opts) {
    const input = opts.input;
    if (!input) return null;
    const maxItems = opts.maxItems || 12;
    const minChars = opts.minChars || 0;
    const wrap = document.createElement('span');
    wrap.className = 'smp-combobox';
    input.parentNode.insertBefore(wrap, input);
    wrap.appendChild(input);
    const list = document.createElement('div');
    list.className = 'smp-combobox-list';
    list.setAttribute('role', 'listbox');
    list.id = 'smp-cbx-' + Math.abs((input.id || input.name || 'cbx').split('').reduce((h, c) => (h * 31 + c.charCodeAt(0)) | 0, 7));
    list.hidden = true;
    wrap.appendChild(list);
    input.setAttribute('role', 'combobox');
    input.setAttribute('aria-autocomplete', 'list');
    input.setAttribute('aria-expanded', 'false');
    input.setAttribute('aria-controls', list.id);
    input.setAttribute('autocomplete', 'off');
    let selected = -1;
    let current = [];

    function itemsNow() {
      return (typeof opts.items === 'function' ? opts.items() : opts.items) || [];
    }
    function close() {
      list.hidden = true;
      selected = -1;
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-activedescendant', '');
    }
    function choose(index) {
      const item = current[index];
      if (!item) return;
      input.value = item.label;
      close();
      opts.onSelect(item);
    }
    function sync() {
      Array.from(list.children).forEach((el, i) => {
        const on = i === selected;
        el.classList.toggle('selected', on);
        el.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) el.scrollIntoView({ block: 'nearest' });
      });
      input.setAttribute('aria-activedescendant', selected >= 0 && list.children[selected] ? list.children[selected].id : '');
    }
    function refresh() {
      const q = smpNorm(input.value.trim());
      if (q.length < minChars) { close(); return; }
      const scored = itemsNow()
        .map((item) => ({ item, s: q ? smpMatchScore(item.label, q) : 0 }))
        .filter((x) => x.s >= 0);
      if (q) scored.sort((a, b) => a.s - b.s || String(a.item.label).localeCompare(String(b.item.label)));
      current = scored.slice(0, maxItems).map((x) => x.item);
      if (!current.length) { close(); return; }
      list.innerHTML = current.map((item, i) =>
        '<div class="smp-cbx-opt" id="' + list.id + '-' + i + '" role="option" aria-selected="false">'
        + '<span>' + escapeHtml(item.label) + '</span>'
        + (item.sub ? '<span class="muted">' + escapeHtml(item.sub) + '</span>' : '')
        + '</div>').join('');
      Array.from(list.children).forEach((el, i) => {
        el.addEventListener('mousedown', (event) => { event.preventDefault(); choose(i); });
      });
      list.hidden = false;
      selected = -1;
      input.setAttribute('aria-expanded', 'true');
    }
    function onKeydown(event) {
      if (event.key === 'Escape') { close(); return; }
      if (list.hidden) {
        if (event.key === 'ArrowDown') { event.preventDefault(); refresh(); }
        return;
      }
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, current.length - 1); sync(); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); sync(); }
      else if (event.key === 'Enter') { event.preventDefault(); choose(Math.max(0, selected)); }
    }
    function onDocClick(event) {
      if (!wrap.contains(event.target)) close();
    }
    input.addEventListener('input', refresh);
    input.addEventListener('focus', refresh);
    input.addEventListener('keydown', onKeydown);
    document.addEventListener('click', onDocClick);
    return {
      refresh,
      close,
      destroy() {
        input.removeEventListener('input', refresh);
        input.removeEventListener('focus', refresh);
        input.removeEventListener('keydown', onKeydown);
        document.removeEventListener('click', onDocClick);
        list.remove();
      },
    };
  };

  // ---------- copy table as TSV ----------
  document.querySelectorAll('.table-wrap').forEach((wrap) => {
    const table = wrap.querySelector('table');
    if (!table || !navigator.clipboard) return;
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'copy-table';
    btn.title = 'Copy table for spreadsheets';
    btn.setAttribute('aria-label', 'Copy table for spreadsheets');
    btn.textContent = '⧉';
    btn.addEventListener('click', (event) => {
      event.stopPropagation();
      const lines = Array.from(table.querySelectorAll('tr')).map((tr) =>
        Array.from(tr.cells).map((cell) => cell.textContent.trim().replace(/\s+/g, ' ')).join('\t'));
      navigator.clipboard.writeText(lines.join('\n')).then(() => {
        btn.textContent = '✓';
        btn.setAttribute('aria-label', 'Copied table');
        setTimeout(() => {
          btn.textContent = '⧉';
          btn.setAttribute('aria-label', 'Copy table for spreadsheets');
        }, 1200);
      });
    });
    wrap.appendChild(btn);
  });

  // ---------- sticky second column (Year alongside Name) ----------
  const stickyTables = Array.from(document.querySelectorAll('table.sticky-col2'));
  function smpMeasureSticky() {
    stickyTables.forEach((table) => {
      const first = table.tHead && table.tHead.rows[0] && table.tHead.rows[0].cells[0];
      if (first) table.style.setProperty('--c1w', first.offsetWidth + 'px');
    });
  }
  if (stickyTables.length) {
    smpMeasureSticky();
    let stickyTimer = null;
    window.addEventListener('resize', () => {
      clearTimeout(stickyTimer);
      stickyTimer = setTimeout(smpMeasureSticky, 150);
    });
  }

  // ---------- column-group toggles (table_html colgroups=) ----------
  document.querySelectorAll('[data-colgroup-toggle]').forEach((wrap) => {
    const table = document.getElementById(wrap.dataset.colgroupToggle);
    if (!table) return;
    const cgStoreKey = 'colgroup:' + wrap.dataset.colgroupToggle;
    const buttons = Array.from(wrap.querySelectorAll('button[data-colgroup]'));
    function applyColgroup(token, persist) {
      buttons.forEach((b) => {
        const on = b.dataset.colgroup === token;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      table.querySelectorAll('th[data-colgroup], td[data-colgroup]').forEach((cell) => {
        cell.classList.toggle('cg-hidden', token !== 'all' && cell.dataset.colgroup.split(' ').indexOf(token) === -1);
      });
      if (persist) smpStore.set(cgStoreKey, token);
      smpMeasureSticky();
    }
    buttons.forEach((b) => b.addEventListener('click', () => applyColgroup(b.dataset.colgroup, true)));
    const storedGroup = smpStore.get(cgStoreKey);
    const storedValid = storedGroup && buttons.some((b) => b.dataset.colgroup === storedGroup);
    applyColgroup(storedValid ? storedGroup : (wrap.dataset.colgroupDefault || 'all'), false);
  });

  // ---------- glossary bottom sheet ----------
  // On hover-less (touch) devices, tapping a stat header opens a sheet with the
  // GLOSSARY definition plus a "sort" action (since the tap no longer sorts).
  // Everywhere, tapping a mini-skill chip opens the sheet on the skill legend.
  let glossarySheet = null;
  let glossaryReturnFocus = null;
  let glossarySortTh = null;
  let glossaryBypass = false;
  const coarsePointer = matchMedia('(hover: none)');

  function glossaryLegendHtml() {
    const skills = (siteConfig && siteConfig.skills) || {};
    const entries = Object.keys(skills).map((code) =>
      '<div class="gs-skill"><span class="mini-skill">' + escapeHtml(code) + '</span> ' + escapeHtml(skills[code]) + '</div>').join('');
    if (!entries) return '';
    return '<div class="gs-legend"><h4>Skill badges</h4>' + entries + '</div>';
  }

  function closeGlossarySheet() {
    if (!glossarySheet) return;
    glossarySheet.hidden = true;
    if (glossaryReturnFocus && glossaryReturnFocus.focus) glossaryReturnFocus.focus();
    glossaryReturnFocus = null;
    glossarySortTh = null;
  }

  function buildGlossarySheet() {
    if (glossarySheet) return glossarySheet;
    const overlay = document.createElement('div');
    overlay.className = 'gs-overlay';
    overlay.hidden = true;
    const sheet = document.createElement('div');
    sheet.className = 'glossary-sheet';
    sheet.setAttribute('role', 'dialog');
    sheet.setAttribute('aria-modal', 'true');
    sheet.setAttribute('aria-labelledby', 'gs-term');
    sheet.innerHTML = '<div class="gs-grip" aria-hidden="true"></div>'
      + '<h3 id="gs-term"></h3><p class="gs-def"></p>'
      + '<div class="gs-actions">'
      + '<button type="button" class="gs-sort">Sort by this column</button>'
      + '<button type="button" class="gs-close">Close</button></div>'
      + glossaryLegendHtml();
    overlay.appendChild(sheet);
    document.body.appendChild(overlay);
    overlay.addEventListener('click', (event) => { if (event.target === overlay) closeGlossarySheet(); });
    sheet.querySelector('.gs-close').addEventListener('click', closeGlossarySheet);
    sheet.querySelector('.gs-sort').addEventListener('click', () => {
      const th = glossarySortTh;
      closeGlossarySheet();
      if (th) { glossaryBypass = true; th.click(); glossaryBypass = false; }
    });
    document.addEventListener('keydown', (event) => {
      if (event.key === 'Escape' && !overlay.hidden) closeGlossarySheet();
    });
    glossarySheet = overlay;
    return overlay;
  }

  function openGlossarySheet(term, definition, sortTh) {
    const overlay = buildGlossarySheet();
    overlay.querySelector('#gs-term').textContent = term;
    const def = overlay.querySelector('.gs-def');
    def.textContent = definition || '';
    def.hidden = !definition;
    glossarySortTh = sortTh || null;
    overlay.querySelector('.gs-sort').hidden = !sortTh;
    overlay.hidden = false;
    glossaryReturnFocus = document.activeElement;
    overlay.querySelector('.gs-close').focus();
  }

  document.addEventListener('click', (event) => {
    if (glossaryBypass) return;
    const target = event.target;
    if (!target || !target.closest) return;
    const chip = target.closest('.mini-skill');
    if (chip) {
      const code = chip.textContent.trim();
      const skills = (siteConfig && siteConfig.skills) || {};
      openGlossarySheet('Skill: ' + code, skills[code] || chip.getAttribute('title') || '', null);
      return;
    }
    if (!coarsePointer.matches) return;
    const th = target.closest('table[data-sortable] thead th[title]');
    if (!th) return;
    event.preventDefault();
    event.stopPropagation();
    openGlossarySheet(th.textContent.trim(), th.getAttribute('title'), th);
  }, true); // capture: runs (and stops) before the sort handler bound on the th

  // ---------- generic card-list (mobile card view for opted-in tables) ----------
  // Any table[data-card-list] is mirrored as a .card-list of stacked cards on
  // narrow viewports: first cell becomes the card title, remaining cells become
  // labeled stats (columns with empty values are skipped per card).
  const cardListMq = matchMedia('(max-width: 700px)');
  document.querySelectorAll('table[data-card-list]').forEach((table) => {
    const wrap = table.closest('.table-wrap');
    if (!wrap || !table.tHead || !table.tBodies[0]) return;
    let list = null;
    function buildCards() {
      if (list) return list;
      const headers = Array.from(table.tHead.rows[0].cells).map((cell) => cell.textContent.trim());
      list = document.createElement('div');
      list.className = 'card-list';
      Array.from(table.tBodies[0].rows).forEach((row) => {
        const item = document.createElement('article');
        item.className = 'card-list-item';
        if (row.dataset.tid) item.dataset.tid = row.dataset.tid;
        const cells = Array.from(row.cells);
        const title = document.createElement('div');
        title.className = 'cl-title';
        title.innerHTML = cells.length ? cells[0].innerHTML : '';
        item.appendChild(title);
        const stats = document.createElement('div');
        stats.className = 'cl-stats';
        cells.slice(1).forEach((cell, i) => {
          const label = headers[i + 1] || '';
          const value = cell.textContent.trim();
          if (!label || value === '' || value === '—') return;
          const stat = document.createElement('span');
          stat.className = 'cl-stat';
          stat.innerHTML = '<b>' + escapeHtml(label) + '</b>' + escapeHtml(value);
          stats.appendChild(stat);
        });
        item.appendChild(stats);
        list.appendChild(item);
      });
      wrap.after(list);
      return list;
    }
    function syncCards() {
      const on = cardListMq.matches;
      if (on) buildCards();
      if (list) list.hidden = !on;
      wrap.classList.toggle('as-cards', on);
    }
    syncCards();
    if (cardListMq.addEventListener) cardListMq.addEventListener('change', syncCards);
    else if (cardListMq.addListener) cardListMq.addListener(syncCards);
  });

  // ---------- mobile nav toggle ----------
  const burger = document.querySelector('[data-nav-burger]');
  if (burger) {
    const nav = document.getElementById(burger.getAttribute('aria-controls')) || document.querySelector('.primary-nav');
    burger.addEventListener('click', () => {
      if (!nav) return;
      const open = !nav.classList.contains('open');
      nav.classList.toggle('open', open);
      burger.classList.toggle('open');
      burger.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('keydown', (event) => {
      if (event.key !== 'Escape' || !nav || !nav.classList.contains('open')) return;
      nav.classList.remove('open');
      burger.classList.remove('open');
      burger.setAttribute('aria-expanded', 'false');
    });
  }

  // ---------- nav dropdowns: one open at a time + Escape to close ----------
  const navDropdowns = Array.from(document.querySelectorAll('.primary-nav details.nav-dropdown'));
  navDropdowns.forEach((details) => {
    details.addEventListener('toggle', () => {
      if (details.open) {
        navDropdowns.forEach((other) => { if (other !== details) other.removeAttribute('open'); });
      }
    });
  });
  document.addEventListener('keydown', (event) => {
    if (event.key !== 'Escape') return;
    navDropdowns.forEach((details) => details.removeAttribute('open'));
  });

  // ---------- generic tabs ----------
  document.querySelectorAll('[data-tabs]').forEach((tablist) => {
    const tabs = Array.from(tablist.querySelectorAll('[role="tab"][data-tab-target]'));
    if (!tabs.length) return;
    function activate(tab, focus) {
      tabs.forEach((btn) => {
        const on = btn === tab;
        const panel = document.getElementById(btn.dataset.tabTarget || '');
        btn.setAttribute('aria-selected', on ? 'true' : 'false');
        btn.tabIndex = on ? 0 : -1;
        if (panel) panel.hidden = !on;
      });
      if (focus) tab.focus();
    }
    tabs.forEach((tab, index) => {
      tab.tabIndex = tab.getAttribute('aria-selected') === 'true' ? 0 : -1;
      tab.addEventListener('click', () => activate(tab, false));
      tab.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = tabs[(index + 1) % tabs.length];
        if (event.key === 'ArrowLeft') next = tabs[(index - 1 + tabs.length) % tabs.length];
        if (event.key === 'Home') next = tabs[0];
        if (event.key === 'End') next = tabs[tabs.length - 1];
        if (!next) return;
        event.preventDefault();
        activate(next, true);
      });
    });
    activate(tabs.find((tab) => tab.getAttribute('aria-selected') === 'true') || tabs[0], false);
  });

  // ---------- draft year tabs ----------
  const draftTabs = document.querySelector('[data-draft-tabs]');
  if (draftTabs) {
    const buttons = Array.from(draftTabs.querySelectorAll('button[data-draft-tab]'));
    function activateDraft(button, focus) {
      buttons.forEach((b) => {
        const on = b === button;
        b.classList.toggle('active', on);
        b.setAttribute('aria-selected', on ? 'true' : 'false');
        b.tabIndex = on ? 0 : -1;
      });
      document.querySelectorAll('[data-draft-panel]').forEach((panel) => {
        panel.hidden = panel.dataset.draftPanel !== button.dataset.draftTab;
      });
      if (focus) button.focus();
    }
    buttons.forEach((button, index) => {
      button.tabIndex = button.classList.contains('active') ? 0 : -1;
      button.addEventListener('click', () => {
        activateDraft(button, false);
      });
      button.addEventListener('keydown', (event) => {
        let next = null;
        if (event.key === 'ArrowRight') next = buttons[(index + 1) % buttons.length];
        if (event.key === 'ArrowLeft') next = buttons[(index - 1 + buttons.length) % buttons.length];
        if (event.key === 'Home') next = buttons[0];
        if (event.key === 'End') next = buttons[buttons.length - 1];
        if (!next) return;
        event.preventDefault();
        activateDraft(next, true);
      });
    });
    if (buttons.length) activateDraft(buttons.find((b) => b.classList.contains('active')) || buttons[0], false);
  }

  // ---------- keyboard shortcuts ----------
  document.addEventListener('keydown', (event) => {
    if (event.key !== '/' || event.metaKey || event.ctrlKey || event.altKey) return;
    const active = document.activeElement;
    if (active && (active.tagName === 'INPUT' || active.tagName === 'TEXTAREA' || active.tagName === 'SELECT')) return;
    const input = document.querySelector('[data-global-search]');
    if (input) { event.preventDefault(); input.focus(); input.select(); }
  });

  // ---------- player page: sticky section rail + scroll-spy ----------
  const playerRail = document.querySelector('[data-player-rail]');
  if (playerRail) {
    const siteHeader = document.querySelector('.site-header');
    const railLinks = Array.from(playerRail.querySelectorAll('a[href^="#"]'));
    const railSections = railLinks
      .map((link) => document.getElementById(link.getAttribute('href').slice(1)))
      .filter(Boolean);

    // The header wraps at narrow widths, so measure it instead of hardcoding:
    // --rail-offset pins the rail below the sticky header; --anchor-offset keeps
    // anchor jumps from landing underneath header + rail.
    function setRailOffsets() {
      const headerH = siteHeader ? siteHeader.offsetHeight : 0;
      const root = document.documentElement;
      root.style.setProperty('--rail-offset', headerH + 'px');
      root.style.setProperty('--anchor-offset', headerH + playerRail.offsetHeight + 10 + 'px');
    }
    setRailOffsets();
    window.addEventListener('resize', setRailOffsets);

    let activeRailId = null;
    function setRailActive(id) {
      if (id === activeRailId) return;
      activeRailId = id;
      railLinks.forEach((link) => {
        const on = link.getAttribute('href').slice(1) === id;
        link.classList.toggle('active', on);
        if (on) link.setAttribute('aria-current', 'true');
        else link.removeAttribute('aria-current');
      });
    }

    // Scroll-spy: the active section is the last one whose top has passed the
    // rail's bottom edge. Runs directly on (already frame-throttled) scroll
    // events — a handful of rect reads, cheap enough without rAF deferral.
    function runSpy() {
      if (!railSections.length) return;
      const line = (siteHeader ? siteHeader.offsetHeight : 0) + playerRail.offsetHeight + 14;
      let active = railSections[0];
      railSections.forEach((section) => {
        if (section.getBoundingClientRect().top <= line) active = section;
      });
      // At the very bottom of the page the last section wins even if short.
      if (window.innerHeight + window.scrollY >= document.body.offsetHeight - 2) {
        active = railSections[railSections.length - 1];
      }
      setRailActive(active.id);
    }
    window.addEventListener('scroll', runSpy, { passive: true });
    window.addEventListener('resize', runSpy);
    runSpy();
  }

  // ---------- player development projection charts (interactive hover) ----------
  document.querySelectorAll('[data-proj-chart]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.proj-chart');
    const tip = wrap.querySelector('[data-proj-tooltip]');
    const hLine = wrap.querySelector('[data-proj-hover-line]');
    const hDot = wrap.querySelector('[data-proj-hover-dot]');
    const dataEl = wrap.parentElement &&
      wrap.parentElement.querySelector('script[type="application/json"][id^="proj-data-"]');
    if (!svg || !tip || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const sSpan = Math.max(1, g.smax - g.smin);
    const xs = (s) => g.ml + (s - g.smin) / sSpan * g.pw;
    const yv = (v) => g.mt + g.ph - (v - g.lo) / Math.max(1e-9, g.hi - g.lo) * g.ph;
    const fmt = (v) => Math.round(v);

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function hide() {
      tip.hidden = true;
      hLine.style.display = 'none';
      hDot.style.display = 'none';
    }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let season = Math.round(g.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < g.smin) season = g.smin;
      if (season > g.smax) season = g.smax;
      const hi = d.hist.s.indexOf(season);
      const pi = d.proj.s.indexOf(season);
      let markY = null;
      let html = '';
      if (season <= d.cur && hi >= 0) {
        markY = d.hist.ovr[hi];
        html = '<strong>' + season + (season === d.cur ? ' · current' : '') + '</strong>' +
               '<span>Overall ' + fmt(d.hist.ovr[hi]) + ' · Potential ' + fmt(d.hist.pot[hi]) + '</span>';
        if (season === d.cur && pi >= 0) html += '<span>Projection starts here</span>';
      } else if (pi >= 0) {
        markY = d.proj.p50[pi];
        html = '<strong>' + season + ' · projected</strong>' +
               '<span>Median ' + fmt(d.proj.p50[pi]) + ' · 80% ' +
               fmt(d.proj.p10[pi]) + '–' + fmt(d.proj.p90[pi]) + '</span>' +
               '<span>50% ' + fmt(d.proj.p25[pi]) + '–' + fmt(d.proj.p75[pi]) + '</span>';
      } else {
        hide();
        return;
      }
      const cx = xs(season);
      hLine.setAttribute('x1', cx);
      hLine.setAttribute('x2', cx);
      hLine.style.display = '';
      hDot.setAttribute('cx', cx);
      hDot.setAttribute('cy', yv(markY));
      hDot.style.display = '';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;  // flip left
      if (left + tw > rect.width) left = rect.width - tw - 4;                // still over: pin right
      if (left < 0) left = 4;                                               // never off the left
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

  // ---------- team trajectory (projected team strength fan chart) ----------
  document.querySelectorAll('[data-team-traj]').forEach((wrap) => {
    const svg = wrap.querySelector('svg.ttraj-chart');
    const tip = wrap.querySelector('[data-ttraj-tooltip]');
    const hLine = wrap.querySelector('[data-ttraj-hover-line]');
    const hDot = wrap.querySelector('[data-ttraj-hover-dot]');
    const bandsG = wrap.querySelector('[data-ttraj-bands]');
    const lineG = wrap.querySelector('[data-ttraj-line]');
    const tid = wrap.getAttribute('data-ttraj-tid');
    const root = wrap.closest('section') || wrap.parentElement;
    const dataEl = document.getElementById('team-traj-' + tid);
    if (!svg || !tip || !dataEl || !bandsG || !lineG || !root) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const SVGNS = 'http://www.w3.org/2000/svg';
    const sSpan = Math.max(1, g.smax - g.smin);
    const xs = (s) => g.ml + (s - g.smin) / sSpan * g.pw;
    const yv = (v) => g.mt + g.ph - (Math.max(0, v) - g.lo) / Math.max(1e-9, g.hi - g.lo) * g.ph;
    const fmt = (v) => Math.round(Math.max(0, v));
    let active = 'proj';

    function bandPts(upper, lower) {
      const fwd = d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(upper[i]).toFixed(1));
      const back = d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(lower[i]).toFixed(1)).reverse();
      return fwd.concat(back).join(' ');
    }
    function linePts(p50) {
      return d.seasons.map((s, i) => xs(s).toFixed(1) + ',' + yv(p50[i]).toFixed(1)).join(' ');
    }

    function draw(scn) {
      const b = d.scn[scn];
      if (!b) return;
      active = scn;
      bandsG.innerHTML = '';
      const p80 = document.createElementNS(SVGNS, 'polygon');
      p80.setAttribute('points', bandPts(b.p90, b.p10));
      p80.setAttribute('class', 'ttraj-band-80');
      const p50b = document.createElementNS(SVGNS, 'polygon');
      p50b.setAttribute('points', bandPts(b.p75, b.p25));
      p50b.setAttribute('class', 'ttraj-band-50');
      bandsG.appendChild(p80); bandsG.appendChild(p50b);
      lineG.innerHTML = '';
      const ml = document.createElementNS(SVGNS, 'polyline');
      ml.setAttribute('points', linePts(b.p50));
      ml.setAttribute('class', 'ttraj-median');
      lineG.appendChild(ml);
    }

    function updateWindow(scn) {
      const out = root.querySelector('[data-ttraj-window] strong');
      if (!out || d.contender == null) return;
      const p50 = d.scn[scn].p50;
      const hit = [];
      d.seasons.forEach((s, i) => { if (p50[i] >= d.contender) hit.push(s); });
      let txt = 'none in window';
      if (hit.length) {
        const run = [hit[0]];
        for (let i = 1; i < hit.length; i++) {
          if (hit[i] === run[run.length - 1] + 1) run.push(hit[i]); else break;
        }
        txt = run[0] === run[run.length - 1] ? '' + run[0] : run[0] + '–' + run[run.length - 1];
      }
      out.textContent = txt;
    }

    function toViewBox(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm) return null;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      return pt.matrixTransform(ctm.inverse());
    }

    function hide() { tip.hidden = true; hLine.style.display = 'none'; hDot.style.display = 'none'; }

    function show(evt) {
      const loc = toViewBox(evt);
      if (!loc) return;
      let season = Math.round(g.smin + (loc.x - g.ml) / g.pw * sSpan);
      if (season < g.smin) season = g.smin;
      if (season > g.smax) season = g.smax;
      const i = d.seasons.indexOf(season);
      if (i < 0) { hide(); return; }
      const b = d.scn[active];
      const med = b.p50[i];
      const cx = xs(season);
      hLine.setAttribute('x1', cx); hLine.setAttribute('x2', cx); hLine.style.display = '';
      hDot.setAttribute('cx', cx); hDot.setAttribute('cy', yv(med)); hDot.style.display = '';
      const cnt = (d.counts && d.counts[i] != null) ? d.counts[i] : null;
      let html = '<strong>' + season + (season === d.cur ? ' · current' : '') + '</strong>' +
        '<span>' + (d.labels[active] || active) + '</span>' +
        '<span>Median ' + fmt(med) + ' · 80% ' + fmt(b.p10[i]) + '–' + fmt(b.p90[i]) + '</span>';
      if (cnt != null) html += '<span>' + cnt + ' under contract</span>';
      tip.innerHTML = html; tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;
      if (left + tw > rect.width) left = rect.width - tw - 4;
      if (left < 0) left = 4;
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    root.querySelectorAll('.ttraj-btn[data-ttraj-scn]').forEach((btn) => {
      btn.addEventListener('click', () => {
        const scn = btn.getAttribute('data-ttraj-scn');
        if (!d.scn[scn]) return;
        root.querySelectorAll('.ttraj-btn').forEach((b2) => {
          const on = b2 === btn;
          b2.classList.toggle('active', on);
          b2.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        draw(scn);
        updateWindow(scn);
        hide();
      });
    });

    svg.addEventListener('mousemove', show);
    svg.addEventListener('mouseleave', hide);
  });

  // power ranking bump: hover/highlight a team line + tooltip, dim the rest.
  document.querySelectorAll('[data-bump]').forEach((wrap) => {
    const card = wrap.closest('.bump-card') || wrap;
    const svg = wrap.querySelector('svg.bump-chart');
    const tip = wrap.querySelector('[data-bump-tooltip]');
    const dataEl = document.getElementById('bump-data');
    if (!svg || !tip || !dataEl) return;
    let d;
    try { d = JSON.parse(dataEl.textContent); } catch (e) { return; }
    const g = d.g;
    const n = (d.seasons || []).length;
    const byId = {};
    (d.teams || []).forEach((t) => { byId[String(t.tid)] = t; });

    const groups = Array.from(card.querySelectorAll('.bump-team[data-tid]'));
    const labels = Array.from(card.querySelectorAll('.bump-endlabel[data-tid]'));
    const chips = Array.from(card.querySelectorAll('.bump-chip[data-tid]'));
    if (!groups.length) return;

    function setActive(tid) {
      tid = String(tid);
      card.classList.add('bump-has-active');
      const apply = (el) => {
        const on = String(el.getAttribute('data-tid')) === tid;
        el.classList.toggle('is-active', on);
        el.classList.toggle('is-dim', !on);
        if (el.matches && el.matches('.bump-chip')) el.setAttribute('aria-pressed', on ? 'true' : 'false');
      };
      groups.forEach(apply); labels.forEach(apply); chips.forEach(apply);
    }
    function clear() {
      card.classList.remove('bump-has-active');
      [].concat(groups, labels, chips).forEach((el) => el.classList.remove('is-active', 'is-dim'));
      chips.forEach((el) => el.setAttribute('aria-pressed', 'false'));
      tip.hidden = true;
    }

    function seasonIndex(evt) {
      const ctm = svg.getScreenCTM();
      if (!ctm || n < 2) return 0;
      const pt = svg.createSVGPoint();
      pt.x = evt.clientX; pt.y = evt.clientY;
      const loc = pt.matrixTransform(ctm.inverse());
      let i = Math.round((loc.x - g.ml) / (g.pw / (n - 1)));
      return Math.max(0, Math.min(n - 1, i));
    }

    function showTip(tid, i, evt) {
      const t = byId[String(tid)];
      if (!t) return;
      // abbrev comes from league data; escape it before innerHTML (defense-in-depth).
      const escHtml = (s) => String(s).replace(/[&<>"]/g, (c) => (
        { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
      const games = (t.games && t.games[i] != null) ? t.games[i] : 0;
      const wins = (t.rec && t.rec[i] != null) ? t.rec[i] : 0;
      let html = '<strong>' + escHtml(t.abbrev || '') + ' · ' + d.seasons[i] +
        (i === 0 ? ' · now' : '') + '</strong>' +
        '<span>Rank #' + t.ranks[i] + ' of ' + d.rows + '</span>' +
        '<span>Strength ' + Math.round(t.p50[i]) + '</span>';
      if (games > 0) html += '<span>Est. ' + wins + '–' + Math.max(0, games - wins) + '</span>';
      tip.innerHTML = html;
      tip.hidden = false;
      const rect = wrap.getBoundingClientRect();
      const tw = tip.offsetWidth;
      let left = evt.clientX - rect.left + 14;
      if (left + tw > rect.width) left = evt.clientX - rect.left - tw - 14;
      if (left + tw > rect.width) left = rect.width - tw - 4;
      if (left < 0) left = 4;
      tip.style.left = left + 'px';
      tip.style.top = (evt.clientY - rect.top + 12) + 'px';
    }

    groups.forEach((grp) => {
      const tid = grp.getAttribute('data-tid');
      grp.addEventListener('mouseenter', () => setActive(tid));
      grp.addEventListener('mousemove', (e) => { setActive(tid); showTip(tid, seasonIndex(e), e); });
    });
    labels.forEach((l) => l.addEventListener('mouseenter', () => setActive(l.getAttribute('data-tid'))));
    chips.forEach((c) => {
      const tid = c.getAttribute('data-tid');
      c.addEventListener('mouseenter', () => setActive(tid));
      c.addEventListener('focus', () => setActive(tid));
      c.addEventListener('click', () => setActive(tid));
    });
    card.addEventListener('mouseleave', clear);
  });

})();
(function () {
  // ---------- team pages (W2): standalone module, appended after the core bundle ----------

  // 0-GP roster rows show (dimmed) by default; unchecking "show inactive" hides them
  document.querySelectorAll('[data-toggle-inactive]').forEach((input) => {
    const card = input.closest('[data-roster-card]');
    if (!card) return;
    const apply = () => card.classList.toggle('hide-inactive', !input.checked);
    input.addEventListener('change', apply);
    apply();
  });

  // scoring-share metric toggle (PTS / FGA / AST)
  document.querySelectorAll('[data-share-card]').forEach((card) => {
    const buttons = Array.from(card.querySelectorAll('button[data-share-metric]'));
    const panels = Array.from(card.querySelectorAll('[data-share-panel]'));
    if (!buttons.length) return;
    function activate(button) {
      buttons.forEach((b) => {
        const on = b === button;
        b.classList.toggle('active', on);
        b.setAttribute('aria-pressed', on ? 'true' : 'false');
      });
      panels.forEach((p) => { p.hidden = p.dataset.sharePanel !== button.dataset.shareMetric; });
    }
    buttons.forEach((button) => button.addEventListener('click', () => activate(button)));
  });

  // rotation map: hover crosshair — highlight the hovered row and game column
  document.querySelectorAll('table.rotation-map').forEach((table) => {
    function clear() {
      table.querySelectorAll('.col-hl').forEach((c) => c.classList.remove('col-hl'));
      table.querySelectorAll('.row-hl').forEach((r) => r.classList.remove('row-hl'));
    }
    table.addEventListener('mouseover', (evt) => {
      const cell = evt.target.closest('td, th');
      if (!cell || !table.contains(cell)) return;
      clear();
      const idx = cell.cellIndex;
      if (idx > 0) {
        table.querySelectorAll('tr').forEach((tr) => {
          const c = tr.cells[idx];
          if (c) c.classList.add('col-hl');
        });
      }
      const row = cell.closest('tbody tr');
      if (row) row.classList.add('row-hl');
    });
    table.addEventListener('mouseleave', clear);
  });
})();
// league.js — records all-time-leaders totals/per-game toggle + history
// transaction-log type/team filters. Self-contained IIFE (site.js is deferred,
// so the DOM is ready when this runs).
(function () {
  // ---------- all-time leaders: totals vs per-game ----------
  document.querySelectorAll('[data-leaders-toggle]').forEach((wrap) => {
    const section = wrap.closest('section');
    if (!section) return;
    const panels = Array.from(section.querySelectorAll('[data-leaders-panel]'));
    const buttons = Array.from(wrap.querySelectorAll('button[data-leaders-view]'));
    buttons.forEach((button) => {
      button.addEventListener('click', () => {
        buttons.forEach((b) => {
          const on = b === button;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        panels.forEach((panel) => {
          panel.hidden = panel.dataset.leadersPanel !== button.dataset.leadersView;
        });
      });
    });
  });

  // ---------- transaction log: type + team filters ----------
  document.querySelectorAll('[data-txlog]').forEach((card) => {
    const typeButtons = Array.from(card.querySelectorAll('[data-tx-type-filter] button[data-tx-type]'));
    const teamSelect = card.querySelector('[data-tx-team-filter]');
    const seasons = Array.from(card.querySelectorAll('details.tx-season'));
    const initiallyOpen = seasons.map((details) => details.open);
    if (!typeButtons.length && !teamSelect) return;

    function apply() {
      const activeButton = typeButtons.find((b) => b.classList.contains('active'));
      const type = activeButton ? activeButton.dataset.txType : 'all';
      const team = teamSelect ? teamSelect.value : 'all';
      const filtering = type !== 'all' || team !== 'all';
      seasons.forEach((details, index) => {
        let shown = 0;
        details.querySelectorAll('li[data-tx-type]').forEach((item) => {
          const typeOk = type === 'all' || item.dataset.txType === type;
          const teamOk = team === 'all' || (item.dataset.txTids || '').indexOf(',' + team + ',') !== -1;
          const ok = typeOk && teamOk;
          item.classList.toggle('tx-hidden', !ok);
          if (ok) shown += 1;
        });
        const pill = details.querySelector('[data-tx-count]');
        if (pill) {
          const total = Number(pill.dataset.txCount);
          pill.textContent = filtering ? shown + ' of ' + total + ' moves' : total + ' moves';
        }
        details.classList.toggle('tx-season-empty', filtering && shown === 0);
        details.open = filtering ? shown > 0 : initiallyOpen[index];
      });
    }

    typeButtons.forEach((button) => {
      button.addEventListener('click', () => {
        typeButtons.forEach((b) => {
          const on = b === button;
          b.classList.toggle('active', on);
          b.setAttribute('aria-pressed', on ? 'true' : 'false');
        });
        apply();
      });
    });
    if (teamSelect) teamSelect.addEventListener('change', apply);
  });
})();
  // ---------- client apps: shared helpers + Compare page ----------
  // compare.js owns window.SMPApps (app-data loader, combobox, portraits) and
  // must be concatenated BEFORE trade-extras.js, which consumes it.
(function () {
  'use strict';

  const rootPath = () => (document.body && document.body.dataset.root) || '';

  let appDataPromise = null;
  function loadAppData() {
    if (!appDataPromise) {
      appDataPromise = fetch(rootPath() + 'assets/app-data.json').then((r) => {
        if (!r.ok) throw new Error('HTTP ' + r.status);
        return r.json();
      });
    }
    return appDataPromise;
  }

  function escapeHtml(value) {
    return String(value).replace(/[&<>"]/g, (c) => (
      { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  }

  const norm = (s) => String(s).toLowerCase().normalize('NFD').replace(/[\u0300-\u036f]/g, '');

  // Mirrors core.fmt_money: thousands in, "$28M" / "$27.55M" / "$500K" out.
  function fmtSalary(k) {
    const num = Number(k);
    if (k === null || k === undefined || !Number.isFinite(num)) return '—';
    const sign = num < 0 ? '-' : '';
    const mag = Math.abs(num);
    if (mag >= 1000) {
      const millions = mag / 1000;
      if (Math.abs(millions - Math.round(millions)) < 1e-9) return sign + '$' + Math.round(millions) + 'M';
      return sign + '$' + millions.toFixed(2).replace(/0+$/, '').replace(/\.$/, '') + 'M';
    }
    return sign + '$' + Math.round(mag) + 'K';
  }

  // Mirrors core.slugify + player_url for the ASCII/diacritic names in play.
  function playerUrl(p) {
    let slug = String(p.name || '').normalize('NFKD')
      .replace(/[\u0300-\u036f]/g, '').replace(/[^\x00-\x7F]/g, '')
      .trim().toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-+|-+$/g, '');
    return rootPath() + 'players/' + (slug || 'player') + '-' + p.pid + '.html';
  }

  function teamAbbrevFor(tid, teamsByTid) {
    if (tid >= 0 && teamsByTid[tid]) return teamsByTid[tid].abbrev;
    return tid === -2 ? 'Draft' : 'FA';
  }

  const NEUTRAL_COLORS = { primary: '#3a4048', secondary: '#8a93a0', chart: '#8A93A5' };

  function teamColors(tid, teamsByTid) {
    return (tid >= 0 && teamsByTid[tid] && teamsByTid[tid].colors) || NEUTRAL_COLORS;
  }

  // WCAG-ish text-on-disc pick: white or near-black, whichever contrasts more
  // (mirrors identity._pick_on_color; app-data colors carry no on_primary).
  function onColor(bg) {
    const c = bg.replace('#', '');
    const chan = (i) => {
      const s = parseInt(c.slice(i, i + 2), 16) / 255;
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    };
    const lum = 0.2126 * chan(0) + 0.7152 * chan(2) + 0.0722 * chan(4);
    return (1.05 / (lum + 0.05)) >= ((lum + 0.05) / 0.0565) ? '#FFFFFF' : '#10131A';
  }

  function initialsOf(name) {
    const parts = String(name || '').trim().split(/\s+/);
    const letters = (parts[0] ? parts[0][0] : '') + (parts.length > 1 ? parts[parts.length - 1][0] : '');
    return (letters || '?').toUpperCase();
  }

  // Mirrors identity.monogram_svg with literal colors (client has no --team-* vars).
  function monogramSvg(text, colors) {
    const t = String(text || '?').slice(0, 3).toUpperCase();
    const font = { 1: 26, 2: 22, 3: 17 }[t.length] || 17;
    return '<svg viewBox="0 0 64 64" aria-hidden="true" focusable="false" xmlns="http://www.w3.org/2000/svg">'
      + '<circle cx="32" cy="32" r="31" fill="' + colors.primary + '"/>'
      + '<circle cx="32" cy="32" r="28.5" fill="none" stroke="' + colors.secondary + '" stroke-width="2"/>'
      + '<text x="32" y="33.5" text-anchor="middle" dominant-baseline="central" '
      + 'font-family="\'Helvetica Neue\',Helvetica,Arial,sans-serif" font-weight="700" '
      + 'font-size="' + font + '" letter-spacing=".5" fill="' + onColor(colors.primary) + '">'
      + escapeHtml(t) + '</text></svg>';
  }

  // Portrait chip chain for client apps: face SVG asset -> monogram roundel.
  // (Photos/imgURL are not in app-data; the onerror hook keeps it unbreakable.)
  function hydrateFaces(container, byPid, teamsByTid) {
    container.querySelectorAll('[data-face-pid]').forEach((span) => {
      const p = byPid[span.dataset.facePid];
      if (!p) return;
      const colors = teamColors(p.tid, teamsByTid);
      const size = parseInt(span.dataset.faceSize || '24', 10);
      const img = document.createElement('img');
      img.src = rootPath() + 'assets/faces/' + p.pid + '.svg';
      img.alt = '';
      img.loading = 'lazy';
      img.decoding = 'async';
      img.width = size;
      img.height = size;
      img.onerror = () => { span.innerHTML = monogramSvg(initialsOf(p.name), colors); };
      span.appendChild(img);
    });
  }

  function facePlaceholder(pid, size) {
    return '<span class="app-face" data-face-pid="' + pid + '" data-face-size="' + size + '" aria-hidden="true"></span>';
  }

  // Filterable combobox (ARIA 1.2 combobox pattern, modeled on the header
  // search). Expects the server-rendered skeleton: .combo > .combo-input +
  // .combo-list. opts: { options() -> [{id,label,sub,search[]}], onSelect(id),
  //                      committed(option) -> input text, maxResults }
  function createCombobox(container, opts) {
    const input = container.querySelector('.combo-input');
    const list = container.querySelector('.combo-list');
    const maxResults = opts.maxResults || 12;
    let committedText = '';
    let selected = -1;
    let items = [];

    function score(q, option) {
      const terms = option.search && option.search.length ? option.search : [option.label];
      let best = -1;
      terms.forEach((term) => {
        const n = norm(term);
        let s = -1;
        if (n.startsWith(q)) s = 0;
        else if (n.split(' ').some((w) => w.startsWith(q))) s = 1;
        else if (n.includes(q)) s = 2;
        if (s >= 0 && (best < 0 || s < best)) best = s;
      });
      return best;
    }

    function matches(q) {
      const options = opts.options();
      if (!q) return options.slice(0, maxResults);
      const scored = [];
      options.forEach((o, i) => {
        const s = score(q, o);
        if (s >= 0) scored.push([s, i, o]);
      });
      scored.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
      return scored.slice(0, maxResults).map((x) => x[2]);
    }

    function close() {
      list.hidden = true;
      selected = -1;
      input.setAttribute('aria-expanded', 'false');
      input.setAttribute('aria-activedescendant', '');
    }

    function syncSelected() {
      Array.from(list.querySelectorAll('[role="option"]')).forEach((el, i) => {
        const on = i === selected;
        el.classList.toggle('selected', on);
        el.setAttribute('aria-selected', on ? 'true' : 'false');
        if (on) el.scrollIntoView({ block: 'nearest' });
      });
      const active = selected >= 0 ? list.querySelectorAll('[role="option"]')[selected] : null;
      input.setAttribute('aria-activedescendant', active ? active.id : '');
    }

    function pick(option) {
      committedText = opts.committed ? opts.committed(option) : option.label;
      input.value = committedText;
      close();
      opts.onSelect(option.id);
    }

    function openList() {
      items = matches(norm(input.value.trim()));
      if (!items.length) {
        list.innerHTML = '<div class="combo-empty" role="option" aria-disabled="true">No matches.</div>';
      } else {
        list.innerHTML = items.map((o, i) =>
          '<div class="combo-option" id="' + list.id + '-opt-' + i + '" role="option" aria-selected="false">'
          + '<span>' + escapeHtml(o.label) + '</span>'
          + (o.sub ? '<span class="muted">' + escapeHtml(o.sub) + '</span>' : '')
          + '</div>').join('');
        Array.from(list.querySelectorAll('.combo-option')).forEach((el, i) => {
          // mousedown beats the input's focusout, so the pick lands first
          el.addEventListener('mousedown', (event) => { event.preventDefault(); pick(items[i]); });
        });
      }
      list.hidden = false;
      selected = -1;
      input.setAttribute('aria-expanded', 'true');
    }

    input.addEventListener('input', () => {
      openList();
      if (input.value.trim() === '' && committedText !== '') {
        committedText = '';
        opts.onSelect(null);
      }
    });
    input.addEventListener('focus', () => { input.select(); openList(); });
    input.addEventListener('keydown', (event) => {
      if (event.key === 'Escape') { input.value = committedText; close(); return; }
      if (event.key === 'Tab') { input.value = committedText; close(); return; }
      if (list.hidden && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) { event.preventDefault(); openList(); return; }
      if (list.hidden || !items.length) return;
      if (event.key === 'ArrowDown') { event.preventDefault(); selected = Math.min(selected + 1, items.length - 1); syncSelected(); }
      else if (event.key === 'ArrowUp') { event.preventDefault(); selected = Math.max(selected - 1, 0); syncSelected(); }
      else if (event.key === 'Enter') {
        event.preventDefault();
        const target = items[Math.max(0, selected)];
        if (target) pick(target);
      }
    });
    input.addEventListener('blur', () => { input.value = committedText; close(); });

    return {
      input,
      enable() { input.disabled = false; },
      setSelection(option) {
        committedText = option ? (opts.committed ? opts.committed(option) : option.label) : '';
        input.value = committedText;
      },
    };
  }

  window.SMPApps = {
    loadAppData, escapeHtml, norm, fmtSalary, playerUrl, teamAbbrevFor,
    teamColors, monogramSvg, initialsOf, hydrateFaces, facePlaceholder,
    createCombobox, rootPath,
  };

  // ---------- Compare page ----------
  const out = document.querySelector('[data-compare-out]');
  const comboEls = Array.from(document.querySelectorAll('[data-compare-combo]'));
  if (!out || !comboEls.length) return;

  const extraEl = document.getElementById('compare-extra');
  const extras = extraEl ? JSON.parse(extraEl.textContent) : { ratingKeys: [], stats: {} };
  const radarBlock = document.querySelector('[data-compare-radar]');
  const radarOut = document.querySelector('[data-radar-out]');

  // Spoke -> subrating mapping (keep in sync with the docstring in
  // scripts/smp/pages/compare.py; oiq/diq intentionally feed two spokes each).
  const SPOKES = [
    ['Shooting', ['tp', 'fg', 'ft']],
    ['Finishing', ['ins', 'dnk']],
    ['Athleticism', ['spd', 'jmp', 'stre', 'endu']],
    ['Playmaking', ['pss', 'drb', 'oiq']],
    ['Defense', ['diq', 'reb', 'hgt']],
    ['IQ', ['oiq', 'diq']],
  ];

  loadAppData().then((data) => {
    const players = data.players;
    const byPid = {};
    players.forEach((p) => { byPid[p.pid] = p; });
    const teamsByTid = {};
    data.teams.forEach((t) => { teamsByTid[t.tid] = t; });

    const picked = [null, null, null];

    const comboOptions = players.map((p) => ({
      id: p.pid,
      label: p.name,
      sub: teamAbbrevFor(p.tid, teamsByTid) + ' · ' + p.pos + ' · ' + p.ovr + ' ovr',
      search: [p.name, teamAbbrevFor(p.tid, teamsByTid) + ' ' + p.name],
    }));
    const optionByPid = {};
    comboOptions.forEach((o) => { optionByPid[o.id] = o; });

    const combos = comboEls.map((el, i) => createCombobox(el, {
      options: () => comboOptions,
      onSelect: (pid) => { picked[i] = pid === null ? null : byPid[pid] || null; syncHash(); render(); },
    }));

    // Initial picks: the URL hash (share/permalink state, "#pid,pid,pid"),
    // else two computed defaults — the top-overall rostered player vs the
    // highest-potential rostered 23-and-under player.
    const fromHash = (location.hash || '').replace(/^#/, '').split(',').filter(Boolean);
    if (fromHash.length && fromHash.some((pid) => byPid[pid])) {
      fromHash.slice(0, 3).forEach((pid, i) => { if (byPid[pid]) picked[i] = byPid[pid]; });
    } else {
      const topOvr = players.find((p) => p.tid >= 0) || players[0];
      const young = players
        .filter((p) => p !== topOvr && p.tid >= 0 && p.age !== null && p.age <= 23)
        .sort((a, b) => (b.pot - a.pot) || (b.ovr - a.ovr) || (a.pid - b.pid))[0]
        || players.find((p) => p !== topOvr);
      picked[0] = topOvr || null;
      picked[1] = young || null;
    }
    combos.forEach((combo, i) => {
      combo.setSelection(picked[i] ? optionByPid[picked[i].pid] : null);
      combo.enable();
    });

    function syncHash() {
      const pids = picked.filter(Boolean).map((p) => p.pid);
      history.replaceState(null, '', pids.length ? '#' + pids.join(',') : location.pathname + location.search);
    }

    function extraOf(p) {
      return extras.stats[String(p.pid)] || [0, null, null, null, null];
    }

    function statRows(chosen) {
      // [label, values, {pct: format as %, lower: lower is better}]
      const pgRow = (key) => chosen.map((p) => p.pg[key]);
      const exRow = (idx) => chosen.map((p) => extraOf(p)[idx]);
      return [
        ['Games', exRow(0), {}],
        ['MP/G', pgRow('min'), {}],
        ['PTS/G', pgRow('pts'), {}],
        ['TRB/G', pgRow('trb'), {}],
        ['AST/G', pgRow('ast'), {}],
        ['STL/G', pgRow('stl'), {}],
        ['BLK/G', pgRow('blk'), {}],
        ['TOV/G', pgRow('tov'), { lower: true }],
        ['FG%', pgRow('fg_pct'), {}],
        ['3P%', pgRow('tp_pct'), {}],
        ['FT%', pgRow('ft_pct'), {}],
        ['FPTS/G', pgRow('fpts'), { int: true }],
        ['TS%', exRow(1), {}],
        ['PER', exRow(2), {}],
        ['BPM', exRow(3), {}],
        ['WS', exRow(4), {}],
      ];
    }

    function render() {
      const chosen = picked.filter(Boolean);
      if (chosen.length < 2) {
        if (radarBlock) radarBlock.hidden = true;
        out.innerHTML = '<p class="muted">Pick at least two players.</p>';
        return;
      }
      let html = '<div class="table-wrap fit-table"><table class="cmp-players"><thead><tr><th scope="col"></th>';
      chosen.forEach((p) => {
        const ageText = p.age === null ? '—' : p.age + 'y';
        html += '<th scope="col">' + facePlaceholder(p.pid, 26)
          + '<a href="' + playerUrl(p) + '">' + escapeHtml(p.name) + '</a>'
          + '<span class="muted"> ' + escapeHtml(teamAbbrevFor(p.tid, teamsByTid)) + ' · ' + escapeHtml(p.pos) + ' · ' + ageText + '</span></th>';
      });
      html += '</tr></thead><tbody>';
      const row = (label, values, options) => {
        const withBar = options && options.bar;
        const lower = options && options.lower;
        const asInt = options && options.int; // display rounded; best-value ties break on the raw float
        html += '<tr><td class="cmp-label">' + label + '</td>';
        const nums = values.map(Number).filter(Number.isFinite);
        const best = nums.length > 1 ? (lower ? Math.min(...nums) : Math.max(...nums)) : null;
        values.forEach((v) => {
          const num = Number(v);
          const isBest = Number.isFinite(num) && best !== null && num === best;
          let cell = (v === null || v === undefined || v === '') ? '—'
            : (asInt && Number.isFinite(num) ? String(Math.round(num)) : escapeHtml(v));
          if (withBar && Number.isFinite(num)) {
            cell = '<span class="cmp-bar"><i style="width:' + Math.max(2, Math.min(100, num)) + '%"></i></span>' + cell;
          }
          html += '<td class="' + (isBest ? 'cmp-best' : '') + '">' + cell + '</td>';
        });
        html += '</tr>';
      };
      row('Overall', chosen.map((p) => p.ovr), { bar: true });
      row('Potential', chosen.map((p) => p.pot), { bar: true });
      row('Contract', chosen.map((p) => fmtSalary(p.salary) + '/' + (p.exp === null ? '—' : p.exp)), {});
      row('Trade value', chosen.map((p) => p.value), {});
      extras.ratingKeys.forEach(([key, label]) => row(label, chosen.map((p) => p.ratings[key]), { bar: true }));
      statRows(chosen).forEach(([label, values, options]) => row(label, values, options));
      html += '</tbody></table></div>';
      out.innerHTML = html;
      hydrateFaces(out, byPid, teamsByTid);
      renderRadar(chosen);
    }

    function spokeValues(p) {
      return SPOKES.map(([, keys]) => Math.round(keys.reduce((s, k) => s + (p.ratings[k] || 0), 0) / keys.length));
    }

    function renderRadar(chosen) {
      if (!radarBlock || !radarOut) return;
      radarBlock.hidden = false;
      const cx = 230, cy = 190, R = 130;
      const pt = (i, v) => {
        const ang = (Math.PI / 180) * (-90 + i * 60);
        const r = (v / 100) * R;
        return (cx + r * Math.cos(ang)).toFixed(1) + ',' + (cy + r * Math.sin(ang)).toFixed(1);
      };
      let svg = '<svg class="radar-svg" viewBox="0 0 460 400" role="img" aria-label="Skill radar comparing '
        + escapeHtml(chosen.map((p) => p.name).join(', ')) + '">';
      [20, 40, 60, 80, 100].forEach((ring) => {
        svg += '<polygon class="radar-grid" points="' + SPOKES.map((_, i) => pt(i, ring)).join(' ') + '"/>';
      });
      SPOKES.forEach(([label], i) => {
        svg += '<line class="radar-axis" x1="' + cx + '" y1="' + cy + '" x2="' + pt(i, 100).replace(',', '" y2="') + '"/>';
        const ang = (Math.PI / 180) * (-90 + i * 60);
        const lx = cx + (R + 16) * Math.cos(ang);
        const ly = cy + (R + 16) * Math.sin(ang);
        const anchor = Math.abs(Math.cos(ang)) < 0.3 ? 'middle' : (Math.cos(ang) > 0 ? 'start' : 'end');
        svg += '<text class="radar-label" x="' + lx.toFixed(1) + '" y="' + (ly + 4).toFixed(1) + '" text-anchor="' + anchor + '">' + label + '</text>';
      });
      const seenColors = [];
      chosen.forEach((p) => {
        const color = teamColors(p.tid, teamsByTid).chart;
        // repeat colors (teammates) get dashed outlines so polygons stay tellable-apart
        const dupes = seenColors.filter((c) => c === color).length;
        seenColors.push(color);
        const dash = dupes === 0 ? '' : ' stroke-dasharray="' + (dupes === 1 ? '7 4' : '2 5') + '"';
        const values = spokeValues(p);
        const points = values.map((v, i) => pt(i, v)).join(' ');
        svg += '<polygon class="radar-poly" points="' + points + '" fill="' + color + '" stroke="' + color + '"' + dash + '/>';
        values.forEach((v, i) => {
          const [x, y] = pt(i, v).split(',');
          svg += '<circle class="radar-dot" cx="' + x + '" cy="' + y + '" r="3.2" fill="' + color + '">'
            + '<title>' + escapeHtml(p.name) + ' — ' + SPOKES[i][0] + ' ' + v + '</title></circle>';
        });
      });
      svg += '</svg>';
      let legend = '<div class="radar-legend">';
      chosen.forEach((p, idx) => {
        const color = teamColors(p.tid, teamsByTid).chart;
        legend += '<span class="radar-chip">'
          + '<i class="radar-swatch' + (idx > 0 && seenColors.slice(0, idx).includes(color) ? ' radar-swatch--dashed' : '') + '" style="background:' + color + '"></i>'
          + facePlaceholder(p.pid, 28)
          + '<a href="' + playerUrl(p) + '">' + escapeHtml(p.name) + '</a>'
          + '<span class="muted">' + escapeHtml(teamAbbrevFor(p.tid, teamsByTid)) + '</span>'
          + '</span>';
      });
      legend += '</div>';
      radarOut.innerHTML = svg + legend;
      hydrateFaces(radarOut, byPid, teamsByTid);
    }

    if (location.hash) syncHash(); // normalize away any invalid pids; keep clean URLs clean
    render();
  }).catch(() => {
    out.innerHTML = '<p class="app-error">Couldn’t load player data (assets/app-data.json). Check your connection and refresh to retry.</p>';
  });
})();
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
          ? fmtM(-room) + ' OVER the ' + fmtM(tax) + ' cap — trade is illegal'
          : fmtM(room) + ' under the ' + fmtM(tax) + ' cap';
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
// ---------- Win-Out Machine (simulator.html) ----------
// Self-contained IIFE: appended after the main site bundle's closing wrapper,
// so it guards on its own root element and no-ops on every other page.
(function () {
  const app = document.querySelector('[data-wo-app]');
  if (!app) return;
  const root = document.body.dataset.root || '';

  const N_SIMS = 5000;
  // Deterministic PRNG. The stream is mulberry32 seeded with
  //   seed = 20290101 ^ fnv1a(lockString)
  // where 20290101 is the same constant the server-side Monte Carlo seeds with
  // (simmodel.simulate_league) and lockString is the canonical picks encoding
  // ("3h,17a", also the URL hash). Identical picks therefore always replay the
  // identical 5,000 simulations; changing any pick starts a fresh but equally
  // reproducible stream.
  function fnv1a(str) {
    let h = 0x811c9dc5;
    for (let i = 0; i < str.length; i += 1) {
      h ^= str.charCodeAt(i);
      h = Math.imul(h, 0x01000193);
    }
    return h >>> 0;
  }
  function mulberry32(seed) {
    let a = seed >>> 0;
    return function () {
      a = (a + 0x6d2b79f5) | 0;
      let t = Math.imul(a ^ (a >>> 15), 1 | a);
      t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
      return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
    };
  }

  // Client-side port of core.heat_style: red (worst) -> green (best) tint.
  // Same hsla convention as the server-rendered heat cells (exempt from theming).
  function heatStyle(value, lo, hi, direction) {
    if (!direction || value === null || value === undefined) return '';
    const v = Number(value);
    if (!Number.isFinite(v) || hi - lo <= 1e-12) return '';
    let frac = Math.max(0, Math.min(1, (v - lo) / (hi - lo)));
    if (direction < 0) frac = 1 - frac;
    const hue = 4 + frac * 126;
    return 'background-color: hsla(' + hue.toFixed(0) + ', 55%, 41%, .45)';
  }

  const escapeHtml = (value) => String(value).replace(/[&<>"]/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
  const fmtPct = (p) => (p * 100).toFixed(1) + '%';

  const gamesEl = app.querySelector('[data-wo-games]');
  const oddsEl = app.querySelector('[data-wo-odds]');
  const countEl = app.querySelector('[data-wo-count]');
  const resetBtn = app.querySelector('[data-wo-reset]');

  let payload = null;
  let teams = [];        // payload team entries, index == tid order of tidList
  let tidList = [];      // tids in payload order
  let tidIndex = {};     // tid -> index into tidList
  let schedule = [];     // [[day, homeTid, awayTid], ...] chronological
  let pHome = [];        // per-game home-win probability (model, unlocked)
  let state = [];        // per-game: 's' (simulate) | 'h' (home locked) | 'a' (away locked)
  let pending = false;

  // --- lock-state <-> URL hash ("3h,17a" — game index + winner) --------------
  function lockString() {
    const parts = [];
    state.forEach((s, i) => { if (s !== 's') parts.push(i + s); });
    return parts.join(',');
  }

  function syncHash() {
    const str = lockString();
    history.replaceState(null, '', str ? '#' + str : location.pathname + location.search);
  }

  function readHash() {
    (location.hash || '').replace(/^#/, '').split(',').forEach((part) => {
      const m = /^(\d+)([ha])$/.exec(part.trim());
      if (m) {
        const idx = Number(m[1]);
        if (idx >= 0 && idx < state.length) state[idx] = m[2];
      }
    });
  }

  // --- Monte Carlo over the unlocked games -----------------------------------
  // Mirrors simmodel.simulate_league's regular-season loop over the payload's
  // strengths: p(home) = 1 / (1 + exp(-(diff + hca) * k)), random tie-break on
  // equal win totals, top four seeds make the playoffs.
  function runSims() {
    const n = tidList.length;
    const baseWins = new Float64Array(n);
    teams.forEach((t, i) => { baseWins[i] = t.record.w; });
    const open = [];
    schedule.forEach((g, i) => {
      const hi = tidIndex[g[1]];
      const ai = tidIndex[g[2]];
      if (state[i] === 'h') baseWins[hi] += 1;
      else if (state[i] === 'a') baseWins[ai] += 1;
      else open.push([hi, ai, pHome[i]]);
    });

    const rng = mulberry32((20290101 ^ fnv1a(lockString())) >>> 0);
    const playoffCount = new Float64Array(n);
    const winTotal = new Float64Array(n);
    const seedCounts = [];
    for (let i = 0; i < n; i += 1) seedCounts.push(new Float64Array(n));

    const wins = new Float64Array(n);
    const order = new Array(n);
    const tie = new Float64Array(n);
    for (let s = 0; s < N_SIMS; s += 1) {
      wins.set(baseWins);
      for (let g = 0; g < open.length; g += 1) {
        if (rng() < open[g][2]) wins[open[g][0]] += 1;
        else wins[open[g][1]] += 1;
      }
      for (let i = 0; i < n; i += 1) { order[i] = i; tie[i] = rng(); }
      order.sort((a, b) => wins[b] - wins[a] || tie[a] - tie[b]);
      for (let seed = 0; seed < n; seed += 1) {
        const i = order[seed];
        seedCounts[i][seed] += 1;
        if (seed < 4) playoffCount[i] += 1;
        winTotal[i] += wins[i];
      }
    }

    return teams.map((t, i) => ({
      team: t,
      expWins: winTotal[i] / N_SIMS,
      playoff: playoffCount[i] / N_SIMS,
      seeds: Array.from(seedCounts[i], (c) => c / N_SIMS),
    }));
  }

  // --- rendering -------------------------------------------------------------
  function teamDot(tid) {
    const t = teams[tidIndex[tid]];
    const color = t && t.colors ? t.colors.chart : '#8899aa';
    return '<i class="wo-dot" style="background:' + escapeHtml(color) + '" aria-hidden="true"></i>';
  }

  function abbrev(tid) {
    const t = teams[tidIndex[tid]];
    return t ? t.abbrev : 'T' + tid;
  }

  function renderBoard() {
    if (!schedule.length) {
      gamesEl.innerHTML = '<p class="muted">No remaining games — the regular season is decided.</p>';
      return;
    }
    const byDay = new Map();
    schedule.forEach((g, i) => {
      if (!byDay.has(g[0])) byDay.set(g[0], []);
      byDay.get(g[0]).push(i);
    });
    let html = '';
    let first = true;
    byDay.forEach((idxs, day) => {
      html += '<details class="wo-day"' + (first ? ' open' : '') + '><summary>Day ' + day
        + ' <span class="muted">' + idxs.length + (idxs.length === 1 ? ' game' : ' games') + '</span></summary>'
        + '<div class="wo-day-games">';
      idxs.forEach((i) => {
        const g = schedule[i];
        const away = abbrev(g[2]);
        const home = abbrev(g[1]);
        const seg = (value, label, aria) =>
          '<label class="wo-seg"><input type="radio" name="wo-g' + i + '" value="' + value + '"'
          + ' data-game="' + i + '"' + (state[i] === value ? ' checked' : '') + ' aria-label="' + escapeHtml(aria) + '">'
          + '<span>' + escapeHtml(label) + '</span></label>';
        html += '<fieldset class="wo-game"><legend class="sr-only">' + escapeHtml(away + ' at ' + home + ', day ' + day) + '</legend>'
          + '<span class="wo-matchup">' + teamDot(g[2]) + escapeHtml(away)
          + ' <span class="muted">@</span> ' + teamDot(g[1]) + escapeHtml(home) + '</span>'
          + '<span class="wo-segs" role="radiogroup" aria-label="' + escapeHtml('Result of ' + away + ' at ' + home) + '">'
          + seg('a', away, away + ' wins')
          + seg('s', 'Sim', 'Simulate ' + away + ' at ' + home)
          + seg('h', home, home + ' wins')
          + '</span>'
          + '<span class="wo-hint muted">' + escapeHtml(home) + ' ' + Math.round(pHome[i] * 100) + '%</span>'
          + '</fieldset>';
      });
      html += '</div></details>';
      first = false;
    });
    gamesEl.innerHTML = html;
  }

  function syncBoardChecks() {
    gamesEl.querySelectorAll('input[data-game]').forEach((input) => {
      input.checked = state[Number(input.dataset.game)] === input.value;
    });
  }

  function renderOdds() {
    const rows = runSims().sort((a, b) => b.expWins - a.expWins || b.playoff - a.playoff
      || a.team.tid - b.team.tid);
    const n = tidList.length;
    let maxSeed = 0;
    rows.forEach((r) => r.seeds.forEach((p) => { if (p > maxSeed) maxSeed = p; }));
    let html = '<div class="table-wrap"><table class="wo-table">'
      + '<caption class="sr-only">Re-simulated playoff odds and seed distribution per team</caption>'
      + '<thead><tr><th scope="col">Team</th><th scope="col">Now</th><th scope="col">Proj W</th>'
      + '<th scope="col">Playoff %</th>';
    for (let s = 1; s <= n; s += 1) html += '<th scope="col" class="wo-seed-th">' + s + '</th>';
    html += '</tr></thead><tbody>';
    rows.forEach((r) => {
      const t = r.team;
      html += '<tr><th scope="row" class="wo-team-th">' + teamDot(t.tid) + escapeHtml(t.abbrev) + '</th>'
        + '<td>' + t.record.w + '-' + t.record.l + '</td>'
        + '<td>' + r.expWins.toFixed(1) + '</td>'
        + '<td style="' + heatStyle(r.playoff, 0, 1, 1) + '">' + fmtPct(r.playoff) + '</td>';
      r.seeds.forEach((p) => {
        // Blank out sub-0.5% cells (matches the server's seed-table convention),
        // scale the tint to the table's most likely seed so the mode pops green.
        if (p < 0.005) {
          html += '<td class="wo-seed-cell muted">·</td>';
        } else {
          html += '<td class="wo-seed-cell" style="' + heatStyle(p, 0, maxSeed, 1) + '">'
            + Math.round(p * 100) + '</td>';
        }
      });
      html += '</tr>';
    });
    html += '</tbody></table></div>'
      + '<p class="tool-note muted">Seed columns show the share of simulations ending at each seed, in percent. '
      + 'Top four seeds make the playoffs.</p>';
    oddsEl.innerHTML = html;
    const locked = state.filter((s) => s !== 's').length;
    if (countEl) countEl.textContent = locked ? locked + ' of ' + state.length + ' games locked' : '';
  }

  function scheduleUpdate() {
    if (pending) return;
    pending = true;
    // Batch rapid pick changes into one 5,000-sim run per tick. setTimeout, not
    // requestAnimationFrame: rAF stalls in hidden/background tabs and the odds
    // would silently never refresh.
    window.setTimeout(() => {
      pending = false;
      renderOdds();
    }, 30);
  }

  gamesEl.addEventListener('change', (event) => {
    const input = event.target.closest('input[data-game]');
    if (!input) return;
    state[Number(input.dataset.game)] = input.value;
    syncHash();
    scheduleUpdate();
  });

  if (resetBtn) {
    resetBtn.addEventListener('click', () => {
      state = state.map(() => 's');
      syncHash();
      syncBoardChecks();
      scheduleUpdate();
    });
  }

  fetch(root + 'assets/app-data.json')
    .then((r) => { if (!r.ok) throw new Error('HTTP ' + r.status); return r.json(); })
    .then((data) => {
      payload = data;
      teams = data.teams;
      tidList = teams.map((t) => t.tid);
      tidList.forEach((tid, i) => { tidIndex[tid] = i; });
      schedule = data.sim.schedule;
      const k = data.sim.logistic_k;
      const hca = data.sim.hca;
      const strengths = data.sim.strengths;
      pHome = schedule.map((g) => {
        const diff = (strengths[String(g[1])] || 0) - (strengths[String(g[2])] || 0) + hca;
        return 1 / (1 + Math.exp(-diff * k));
      });
      state = schedule.map(() => 's');
      readHash();
      renderBoard();
      renderOdds();
    })
    .catch(() => {
      gamesEl.innerHTML = '<p class="muted">Could not load the schedule (assets/app-data.json). Reload to try again.</p>';
      oddsEl.innerHTML = '<p class="muted">—</p>';
    });
})();
// ---------- SMP Wrapped deck (wrapped.html only) ----------
// Progressive enhancement over a plain scrolling page: opts <html> into
// scroll-snap, builds a dots rail, and adds keyboard slide navigation.
// Honors prefers-reduced-motion (instant jumps instead of smooth scrolling).
(function () {
  const deck = document.querySelector('[data-wrapped-deck]');
  if (!deck) return;
  const slides = Array.from(deck.querySelectorAll('.wr-slide'));
  if (!slides.length) return;

  document.documentElement.classList.add('wr-snap');
  const reduceMotion = matchMedia('(prefers-reduced-motion: reduce)');
  const behavior = () => (reduceMotion.matches ? 'auto' : 'smooth');

  // dots rail
  const rail = document.createElement('nav');
  rail.className = 'wr-dots';
  rail.setAttribute('aria-label', 'Wrapped slides');
  const dots = slides.map((slide, index) => {
    const dot = document.createElement('button');
    dot.type = 'button';
    dot.className = 'wr-dot';
    const title = slide.dataset.wrTitle || `Slide ${index + 1}`;
    dot.setAttribute('aria-label', title);
    dot.title = title;
    dot.addEventListener('click', () => goTo(index));
    rail.appendChild(dot);
    return dot;
  });
  document.body.appendChild(rail);

  let current = 0;
  function setActive(index) {
    current = index;
    dots.forEach((dot, i) => {
      if (i === index) dot.setAttribute('aria-current', 'true');
      else dot.removeAttribute('aria-current');
    });
  }
  function goTo(index) {
    const target = slides[Math.max(0, Math.min(slides.length - 1, index))];
    if (target) target.scrollIntoView({ behavior: behavior(), block: 'start' });
  }
  setActive(0);

  if ('IntersectionObserver' in window) {
    const visible = new Map();
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => visible.set(entry.target, entry.intersectionRatio));
      let bestIndex = current;
      let bestRatio = 0;
      slides.forEach((slide, i) => {
        const ratio = visible.get(slide) || 0;
        if (ratio > bestRatio) { bestRatio = ratio; bestIndex = i; }
      });
      if (bestRatio > 0) setActive(bestIndex);
    }, { threshold: [0.25, 0.5, 0.75] });
    slides.forEach((slide) => observer.observe(slide));
  }

  // keyboard: arrows / PageUp / PageDown step one slide at a time
  document.addEventListener('keydown', (event) => {
    if (event.defaultPrevented || event.altKey || event.ctrlKey || event.metaKey || event.shiftKey) return;
    const target = event.target;
    if (target && (target.tagName === 'INPUT' || target.tagName === 'TEXTAREA' ||
        target.tagName === 'SELECT' || target.isContentEditable)) return;
    if (event.key === 'ArrowDown' || event.key === 'PageDown') {
      event.preventDefault();
      goTo(current + 1);
    } else if (event.key === 'ArrowUp' || event.key === 'PageUp') {
      event.preventDefault();
      goTo(current - 1);
    }
  });
})();
