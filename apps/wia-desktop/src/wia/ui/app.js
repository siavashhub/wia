// WIA UI controller (Alpine.js)
function wia() {
  return {
    workiq: { installed: false, ready: false, version: null, message: null },
    enabling: false,
    briefing: null,
    loading: false,
    error: null,
    copied: false,
    weekOffset: 0, // 0 = current week, -1 = last week, ... down to -4
    prefs: { theme: 'system', enabled_signals: ['calendar'] },
    availableSignals: [
      { key: 'calendar', label: '🗓 Calendar' },
      { key: 'teams', label: '💬 Teams' },
      { key: 'email', label: '✉️ Email' },
    ],
    schedule: { interval_minutes: 0, allowed_intervals: [], last_scan_at: null, last_scan_status: null, last_scan_week_of: null, last_scan_trigger: null },
    history: [],
    historyOpen: false,
    historyLoading: false,
    historyLimit: 200,
    historyServerCap: 500,
    historyRange: '7d', // '7d' | '30d' | 'all'
    historyView: 'flat', // 'flat' | 'weekly'
    historyExpandedWeeks: {}, // { [week_of]: boolean }
    appVersion: '',
    expanded: {}, // { [category]: boolean }
    dayLabels: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    _systemThemeMql: null,

    // ---- Review state ----------------------------------------------------
    view: 'briefing', // 'briefing' | 'review'
    review: null,
    reviewLoading: false,
    reviewError: null,
    reviewCopied: false,
    reviewScanning: false,
    reviewScanError: null,
    scanningWeek: null,
    reviewKind: 'month', // 'month' | 'year'
    reviewMonth: '', // 'YYYY-MM'
    reviewYear: new Date().getFullYear(),
    talkingPointSections: [
      { key: 'achievements', label: 'Achievements' },
      { key: 'focus', label: 'Focus & priorities' },
      { key: 'challenges', label: 'Challenges' },
      { key: 'asks', label: 'Asks for my manager' },
    ],

    async init() {
      const now = new Date();
      this.reviewMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      this.reviewYear = now.getFullYear();
      await this.loadPrefs();
      this.applyTheme(this.prefs.theme);
      await Promise.all([this.loadHealth(), this.loadSchedule(), this.loadStatus()]);
      if (this.workiq.ready) {
        await this.loadBriefing(false);
      }
      setInterval(() => this.loadSchedule(), 30000);
    },

    async loadHealth() {
      try {
        const r = await fetch('/api/health');
        const data = await r.json();
        this.appVersion = `v${data.version || '?'}`;
      } catch (e) { /* non-fatal */ }
    },

    // ---- Theme -----------------------------------------------------------
    applyTheme(theme) {
      const root = document.documentElement;
      const isDark =
        theme === 'dark' ||
        (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
      root.classList.toggle('dark', isDark);
      if (!this._systemThemeMql) {
        this._systemThemeMql = window.matchMedia('(prefers-color-scheme: dark)');
        this._systemThemeMql.addEventListener('change', () => {
          if (this.prefs.theme === 'system') this.applyTheme('system');
        });
      }
    },

    async setTheme(theme) {
      this.prefs.theme = theme;
      this.applyTheme(theme);
      try {
        await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ theme }),
        });
      } catch (e) { this.error = `Save theme failed: ${e}`; }
    },

    async toggleSignal(key, on) {
      const current = new Set(this.prefs.enabled_signals || []);
      if (on) current.add(key); else current.delete(key);
      // Always keep at least one signal selected so a scan has something to do.
      if (current.size === 0) {
        current.add(key);
        this.error = 'Keep at least one signal enabled.';
        setTimeout(() => { if (this.error === 'Keep at least one signal enabled.') this.error = null; }, 2500);
      }
      const next = Array.from(current);
      this.prefs.enabled_signals = next;
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ enabled_signals: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save signals failed: ${e}`; }
    },

    async loadPrefs() {
      try {
        const r = await fetch('/api/prefs');
        this.prefs = await r.json();
      } catch (e) { /* keep defaults */ }
    },

    // ---- Week navigation -------------------------------------------------
    weekStartFor(offset) {
      const today = new Date();
      const day = today.getDay();
      const mondayDelta = (day + 6) % 7;
      return new Date(today.getFullYear(), today.getMonth(), today.getDate() - mondayDelta + offset * 7);
    },

    weekStartIso(offset) {
      const d = this.weekStartFor(offset);
      const yyyy = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      return `${yyyy}-${mm}-${dd}`;
    },

    weekLabel() {
      if (this.briefing?.week_start) return this.briefing.week_start;
      return this.weekStartIso(this.weekOffset);
    },

    dayDate(i) {
      const monday = this.briefing?.week_start
        ? new Date(this.briefing.week_start + 'T00:00:00')
        : this.weekStartFor(this.weekOffset);
      const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i);
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    },

    dayIso(i) {
      const monday = this.briefing?.week_start
        ? new Date(this.briefing.week_start + 'T00:00:00')
        : this.weekStartFor(this.weekOffset);
      const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + i);
      const y = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      return `${y}-${mm}-${dd}`;
    },

    canGoBack() { return this.weekOffset > -4 && !this.loading; },
    canGoForward() { return this.weekOffset < 0 && !this.loading; },

    async prevWeek() {
      if (!this.canGoBack()) return;
      this.weekOffset -= 1;
      await this.loadBriefing(false);
    },

    async nextWeek() {
      if (!this.canGoForward()) return;
      this.weekOffset += 1;
      await this.loadBriefing(false);
    },

    async goCurrentWeek() {
      this.weekOffset = 0;
      await this.loadBriefing(false);
    },

    // ---- Work IQ + briefing ---------------------------------------------
    async loadStatus() {
      try {
        const r = await fetch('/api/workiq/status');
        this.workiq = await r.json();
      } catch (e) { this.error = String(e); }
    },

    async enableWorkIQ() {
      this.error = null; this.enabling = true;
      try {
        const r = await fetch('/api/workiq/enable', { method: 'POST' });
        this.workiq = await r.json();
        if (!this.workiq.ready && this.workiq.message) this.error = this.workiq.message;
        if (this.workiq.ready) await this.loadBriefing(true);
      } catch (e) { this.error = `Enable failed: ${e}`; }
      finally { this.enabling = false; }
    },

    async loadBriefing(refresh) {
      this.loading = true; this.error = null;
      try {
        const params = new URLSearchParams();
        params.set('week_of', this.weekStartIso(this.weekOffset));
        if (refresh) params.set('refresh', 'true');
        const r = await fetch(`/api/briefing?${params.toString()}`);
        if (!r.ok) throw new Error(await r.text());
        this.briefing = await r.json();
        if (this.briefing.status === 'workiq-not-enabled') {
          this.error = 'Click "Enable Work IQ" to connect.';
          await this.loadStatus();
        }
        if (refresh) {
          await this.loadSchedule();
          if (this.historyOpen) await this.loadHistory();
        }
      } catch (e) { this.error = String(e); }
      finally { this.loading = false; }
    },

    rescan() { return this.loadBriefing(true); },

    // ---- Grouping --------------------------------------------------------
    groupedEntries() {
      const entries = this.briefing?.entries || [];
      const map = new Map();
      for (const e of entries) {
        const key = e.category || 'Uncategorized';
        if (!map.has(key)) map.set(key, []);
        map.get(key).push(e);
      }
      const groups = [];
      for (const [category, items] of map.entries()) {
        const daily = {};
        for (let i = 0; i < 7; i++) {
          const iso = this.dayIso(i);
          daily[iso] = items.reduce((s, e) => s + ((e.daily_hours || {})[iso] || 0), 0);
        }
        const total = items.reduce((s, e) => s + (e.duration_hours || 0), 0);
        groups.push({ category, entries: items, daily, total });
      }
      // Sort categories by total descending so the biggest buckets surface first.
      groups.sort((a, b) => b.total - a.total);
      return groups;
    },

    groupRows(group) {
      // Returns the visible rows for a group: always the summary row, plus
      // each entry as a sub-row when the group is expanded.
      const rows = [{ kind: 'group', key: `g:${group.category}` }];
      if (this.expanded[group.category]) {
        for (const entry of group.entries) {
          rows.push({ kind: 'sub', key: `e:${entry.id}`, entry });
        }
      }
      return rows;
    },

    toggleGroup(category) {
      this.expanded = { ...this.expanded, [category]: !this.expanded[category] };
    },

    allExpanded() {
      const groups = this.groupedEntries();
      return groups.length > 0 && groups.every(g => this.expanded[g.category]);
    },

    expandAll() {
      const groups = this.groupedEntries();
      const target = !this.allExpanded();
      const next = {};
      for (const g of groups) next[g.category] = target;
      this.expanded = next;
    },

    // ---- Day breakdown helpers ------------------------------------------
    hoursForDay(entry, i) {
      return this.hhmm((entry.daily_hours || {})[this.dayIso(i)] || 0);
    },

    dayTotal(i) {
      const iso = this.dayIso(i);
      const total = (this.briefing?.entries || []).reduce(
        (sum, e) => sum + ((e.daily_hours || {})[iso] || 0), 0,
      );
      return this.hhmm(total);
    },

    weekTotal() {
      const total = (this.briefing?.entries || []).reduce(
        (sum, e) => sum + (e.duration_hours || 0), 0,
      );
      return this.hhmm(total);
    },

    hhmm(hours) {
      if (!hours) return '';
      const totalMin = Math.round(hours * 60);
      const h = Math.floor(totalMin / 60);
      const m = totalMin % 60;
      return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`;
    },

    // ---- Entries CRUD ----------------------------------------------------
    async patchEntry(entry) {
      try {
        await fetch(`/api/entries/${entry.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ label: entry.label, category: entry.category, duration_hours: entry.duration_hours }),
        });
      } catch (e) { this.error = String(e); }
    },

    async deleteEntry(entry) {
      try {
        await fetch(`/api/entries/${entry.id}`, { method: 'DELETE' });
        this.briefing.entries = this.briefing.entries.filter(e => e.id !== entry.id);
      } catch (e) { this.error = String(e); }
    },

    // ---- Export ---------------------------------------------------------
    async copyTable() {
      this.error = null;
      try {
        const week = this.briefing?.week_start || this.weekStartIso(this.weekOffset);
        const r = await fetch(`/api/export/html?week_of=${encodeURIComponent(week)}`);
        const { html: htmlPayload, text } = await r.json();
        // Word picks up the HTML flavour; the plain-text fallback keeps
        // things sensible when pasting into terminals or Markdown editors.
        if (window.ClipboardItem && navigator.clipboard?.write) {
          const item = new ClipboardItem({
            'text/html': new Blob([htmlPayload], { type: 'text/html' }),
            'text/plain': new Blob([text], { type: 'text/plain' }),
          });
          await navigator.clipboard.write([item]);
        } else {
          await navigator.clipboard.writeText(text);
        }
        this.copied = true;
        setTimeout(() => { this.copied = false; }, 2000);
      } catch (e) { this.error = `Copy failed: ${e}`; }
    },

    async downloadCsv() {
      this.error = null;
      try {
        const week = this.briefing?.week_start || this.weekStartIso(this.weekOffset);
        const r = await fetch(`/api/export/csv/text?week_of=${encodeURIComponent(week)}`);
        if (!r.ok) throw new Error(await r.text());
        const { text } = await r.json();
        const filename = `wia-briefing-${week}.csv`;
        // WebView2 ignores blob downloads, so prefer the pywebview bridge
        // which pops a native Save-As dialog and writes the file from Python.
        if (window.pywebview?.api?.save_file) {
          const saved = await window.pywebview.api.save_file(filename, text, ['CSV (*.csv)', 'All files (*.*)']);
          if (saved) {
            this.error = null;
            this.copied = false;
          }
          return;
        }
        // Browser fallback (e.g., when running the UI outside pywebview).
        const blob = new Blob([text], { type: 'text/csv' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      } catch (e) { this.error = `Export failed: ${e}`; }
    },

    // ---- Schedule --------------------------------------------------------
    async loadSchedule() {
      try {
        const r = await fetch('/api/schedule');
        this.schedule = await r.json();
      } catch (e) { /* non-fatal */ }
    },

    async setSchedule(minutes) {
      try {
        const r = await fetch('/api/schedule', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ interval_minutes: Number(minutes) }),
        });
        this.schedule = await r.json();
      } catch (e) { this.error = `Save schedule failed: ${e}`; }
    },

    formatDateTime(iso) {
      try { return new Date(iso).toLocaleString(); } catch { return iso; }
    },

    // ---- Scan history ----------------------------------------------------
    async loadHistory() {
      this.historyLoading = true;
      try {
        const r = await fetch(`/api/schedule/history?limit=${this.historyLimit}`);
        if (!r.ok) throw new Error(await r.text());
        this.history = await r.json();
      } catch (e) { this.error = `Load history failed: ${e}`; }
      finally { this.historyLoading = false; }
    },

    async toggleHistory() {
      this.historyOpen = !this.historyOpen;
      if (this.historyOpen) await this.loadHistory();
    },

    setHistoryRange(range) {
      this.historyRange = range;
    },

    setHistoryView(view) {
      this.historyView = view;
    },

    canLoadMoreHistory() {
      return this.history.length >= this.historyLimit && this.historyLimit < this.historyServerCap;
    },

    async loadMoreHistory() {
      if (!this.canLoadMoreHistory()) return;
      this.historyLimit = Math.min(this.historyServerCap, this.historyLimit + 100);
      await this.loadHistory();
    },

    filteredHistory() {
      const rows = this.history || [];
      if (this.historyRange === 'all') return rows;
      const days = this.historyRange === '7d' ? 7 : 30;
      const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
      return rows.filter((r) => {
        const t = Date.parse(r.ran_at);
        return Number.isFinite(t) && t >= cutoff;
      });
    },

    groupedHistory() {
      const rows = this.filteredHistory();
      const map = new Map();
      for (const r of rows) {
        const key = r.week_of || '(unknown)';
        if (!map.has(key)) {
          map.set(key, { week_of: key, scans: [], last_ran_at: r.ran_at, last_status: r.status, last_entry_count: r.entry_count, max_duration_ms: r.duration_ms || 0 });
        }
        const g = map.get(key);
        g.scans.push(r);
        // rows arrive newest first; keep first seen as "last"
        if (g.max_duration_ms < (r.duration_ms || 0)) g.max_duration_ms = r.duration_ms || 0;
      }
      return Array.from(map.values());
    },

    toggleHistoryWeek(week) {
      this.historyExpandedWeeks[week] = !this.historyExpandedWeeks[week];
    },

    historyCaption() {
      const shown = this.historyView === 'flat' ? this.filteredHistory().length : this.groupedHistory().length;
      const total = this.history.length;
      const unit = this.historyView === 'weekly' ? 'weeks' : 'scans';
      if (this.historyRange === 'all') return `Showing ${shown} ${unit} (of ${total} loaded)`;
      return `Showing ${shown} ${unit} in last ${this.historyRange} (of ${total} loaded)`;
    },

    formatDuration(ms) {
      if (!ms || ms < 0) return '';
      if (ms < 1000) return `${ms} ms`;
      return `${(ms / 1000).toFixed(1)} s`;
    },

    // ---- Review ----------------------------------------------------------
    setView(v) {
      this.view = v;
      if (v === 'review' && !this.review && !this.reviewLoading) {
        this.loadReview();
      }
    },

    setReviewKind(kind) {
      this.reviewKind = kind;
      this.loadReview();
    },

    reviewPeriod() {
      return this.reviewKind === 'month' ? this.reviewMonth : String(this.reviewYear);
    },

    async loadReview() {
      this.reviewError = null;
      this.reviewLoading = true;
      try {
        const period = this.reviewPeriod();
        if (!period) return;
        const r = await fetch(`/api/review?period=${encodeURIComponent(period)}`);
        if (!r.ok) throw new Error(await r.text());
        this.review = await r.json();
      } catch (e) {
        this.reviewError = `Load review failed: ${e}`;
        this.review = null;
      } finally {
        this.reviewLoading = false;
      }
    },

    // ---- Missing-week scans (Review) ------------------------------------
    async scanMissingWeek(weekIso) {
      // Trigger a Briefing rescan for ``weekIso`` (Monday) and refresh
      // the review when it completes so the new data shows up.
      this.reviewScanError = null;
      this.scanningWeek = weekIso;
      try {
        const params = new URLSearchParams({ week_of: weekIso, refresh: 'true' });
        const r = await fetch(`/api/briefing?${params.toString()}`);
        if (!r.ok) throw new Error(await r.text());
        await this.loadReview();
        // Schedule + history may have new entries too.
        await this.loadSchedule();
        if (this.historyOpen) await this.loadHistory();
      } catch (e) {
        this.reviewScanError = `Scan for week ${weekIso} failed: ${e}`;
      } finally {
        this.scanningWeek = null;
      }
    },

    async scanAllMissing() {
      const weeks = (this.review?.missing_weeks || []).slice();
      if (!weeks.length) return;
      this.reviewScanError = null;
      this.reviewScanning = true;
      try {
        for (const w of weeks) {
          this.scanningWeek = w;
          const params = new URLSearchParams({ week_of: w, refresh: 'true' });
          const r = await fetch(`/api/briefing?${params.toString()}`);
          if (!r.ok) {
            this.reviewScanError = `Scan for week ${w} failed: ${await r.text()}`;
            break;
          }
        }
        await this.loadReview();
        await this.loadSchedule();
        if (this.historyOpen) await this.loadHistory();
      } finally {
        this.scanningWeek = null;
        this.reviewScanning = false;
      }
    },

    formatSigned(n) {
      if (n === undefined || n === null || isNaN(n)) return '0';
      const sign = n > 0 ? '+' : (n < 0 ? '−' : '±');
      return `${sign}${Math.abs(n).toFixed(1)}`;
    },

    insightBorder(kind) {
      switch (kind) {
        case 'trend': return 'border-indigo-400';
        case 'highlight': return 'border-emerald-400';
        case 'balance': return 'border-amber-400';
        case 'anomaly': return 'border-rose-400';
        default: return 'border-slate-400';
      }
    },

    weeklyMax() {
      const arr = this.review?.weekly_trend || [];
      let m = 0;
      for (const w of arr) if (w.total_hours > m) m = w.total_hours;
      return m;
    },

    groupedTalkingPoints() {
      const out = { achievements: [], focus: [], challenges: [], asks: [] };
      for (const p of (this.review?.talking_points || [])) {
        if (out[p.section]) out[p.section].push(p);
      }
      return out;
    },

    autosizeTextarea(ev) {
      const el = ev.target;
      el.style.height = 'auto';
      el.style.height = el.scrollHeight + 'px';
    },

    async copyReview() {
      this.reviewError = null;
      try {
        const period = this.reviewPeriod();
        const r = await fetch(`/api/export/review/html?period=${encodeURIComponent(period)}`);
        if (!r.ok) throw new Error(await r.text());
        const { html: htmlPayload, text } = await r.json();
        if (window.ClipboardItem && navigator.clipboard?.write) {
          const item = new ClipboardItem({
            'text/html': new Blob([htmlPayload], { type: 'text/html' }),
            'text/plain': new Blob([text], { type: 'text/plain' }),
          });
          await navigator.clipboard.write([item]);
        } else {
          await navigator.clipboard.writeText(text);
        }
        this.reviewCopied = true;
        setTimeout(() => { this.reviewCopied = false; }, 2000);
      } catch (e) { this.reviewError = `Copy failed: ${e}`; }
    },

    async downloadReview() {
      this.reviewError = null;
      try {
        const period = this.reviewPeriod();
        const r = await fetch(`/api/export/review/markdown?period=${encodeURIComponent(period)}`);
        if (!r.ok) throw new Error(await r.text());
        const { text } = await r.json();
        const filename = `wia-review-${period}.md`;
        if (window.pywebview?.api?.save_file) {
          await window.pywebview.api.save_file(filename, text, ['Markdown (*.md)', 'All files (*.*)']);
          return;
        }
        const blob = new Blob([text], { type: 'text/markdown' });
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url; a.download = filename;
        document.body.appendChild(a); a.click(); a.remove();
        setTimeout(() => URL.revokeObjectURL(url), 5000);
      } catch (e) { this.reviewError = `Export failed: ${e}`; }
    },
  };
}
