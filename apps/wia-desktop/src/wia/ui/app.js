// WIA UI controller (Alpine.js)
function wia() {
  // Read the last-known Work IQ status / identity synchronously so the
  // header pill renders at its real final size on the very first paint.
  // A first-time user (no cache) falls back to the skeleton placeholder;
  // returning users get zero layout shift even if their UPN is unusually
  // long. The cache is refreshed after every successful status probe.
  let cached = null;
  try {
    const raw = window.localStorage && window.localStorage.getItem('wia-workiq-cache');
    if (raw) cached = JSON.parse(raw);
  } catch (e) { /* non-fatal */ }
  const seedReady = !!(cached && cached.ready);
  const seedUpn = (cached && cached.upn) || '';
  const seedDisplayName = (cached && cached.displayName) || '';

  return {
    workiq: { installed: seedReady, ready: seedReady, version: null, message: null },
    // True once the first /api/workiq/status probe has resolved (success or
    // failure). Used by the header to reserve space for the connection
    // pill / Enable button so its async arrival doesn't shift the theme
    // picker on first paint. Pre-set when we have a cached status so the
    // skeleton placeholder is skipped entirely for returning users.
    workiqChecked: !!cached,
    identity: { upn: seedUpn, display_name: seedDisplayName },
    identityLoading: false,
    enabling: false,
    briefing: null,
    // Entries from the previous Monday-week, fetched only when the user
    // has chosen Sunday-anchored display. The current display window
    // (Sun..Sat) spans two Monday-weeks: the Sunday cell lives in the
    // *previous* Mon-week's data. We merge these into the rendered
    // entries so the Sunday column isn't perpetually empty. Backend
    // storage stays Monday-anchored — this is a render-time join only.
    prevWeekEntries: [],
    loading: false,           // any briefing fetch in flight (cache or scan)
    scanningBriefing: false,  // a background scan (refresh=true) is running
    scanningWeekIso: null,    // which Monday-week the scan is targeting
    clearingWeek: false,      // DELETE /api/briefing in flight
    deletingCategory: null,   // category name currently being bulk-deleted
    error: null,
    copied: false,
    weekOffset: 0, // 0 = current week, -1 = last week, ...
    minWeekOffset: -52, // allow up to 1 year of history
    prefs: { theme: 'system', enabled_signals: ['calendar'], excluded_keywords: [], week_starts_on: 'sun', excluded_calendar_categories: [], high_impact_keywords: [], high_impact_calendar_categories: [], umbrella_calendar_categories: [], preserve_calendar_categories: [], exclude_private_meetings: false, organization_label: '', organization_label_auto: false },
    availableSignals: [
      { key: 'calendar', label: 'Calendar', icon: 'calendar-days' },
      { key: 'teams', label: 'Teams', icon: 'chat-bubble-left-right' },
      { key: 'email', label: 'Email', icon: 'envelope' },
    ],
    newExcludedKeyword: '',
    newExcludedCategory: '',
    newHighImpactKeyword: '',
    newHighImpactCategory: '',
    newUmbrellaCategory: '',
    newPreserveCategory: '',
    organizationDraft: '',
    // Heroicons (MIT) — see ui/icons.js. Returns inline SVG markup; consume
    // via x-html so the icon inherits currentColor like Tailwind text.
    icon(name, classes) {
      return (typeof window !== 'undefined' && window.wiaIcon)
        ? window.wiaIcon(name, classes)
        : '';
    },
    schedule: { interval_minutes: 0, allowed_intervals: [], last_scan_at: null, last_scan_status: null, last_scan_week_of: null, last_scan_trigger: null },
    history: [],
    historyOpen: false,
    historyLoading: false,
    historyLimit: 200,
    historyServerCap: 500,
    historyRange: '7d', // '7d' | '30d' | 'all'
    historyView: 'flat', // 'flat' | 'weekly'
    historyExpandedWeeks: {}, // { [week_of]: boolean }
    // Global Scans slide-over: unifies schedule + last-scan status +
    // running-scan banners + scan history + Review's missing-weeks panel
    // behind a single header icon. State lives on the root x-data so any
    // view (Briefing / Review) can open it and the panel can read the
    // shared `review`, `schedule`, `history` slices directly.
    scansOpen: false,
    scansTab: 'status', // 'status' | 'history' | 'missing'
    // Global Preferences slide-over: owns scan filters (exclusions,
    // high-impact keywords, organization). Decoupled from Briefing so
    // Review and future surfaces can reference the same controls.
    prefsOpen: false,
    prefsTab: 'exclude', // 'exclude' | 'impact' | 'org'
    appVersion: '',
    updateInfo: { update_available: false, latest_version: null, release_url: null },
    expanded: {}, // { [category]: boolean }
    notesOpen: {}, // { [entry.id]: boolean } — which entries have their notes row open
    // How the entries table groups are ordered. Defaults to a stable
    // alphabetical sort so local edits (deletes, impact changes, etc.)
    // don't shuffle rows mid-action. The user can switch to a totals sort
    // by clicking the Total header.
    //   key:  'category' | 'total'
    //   dir:  'asc' | 'desc'
    groupSort: { key: 'category', dir: 'asc' },
    // Inline "Add manual entry" form. Hidden until the user clicks the
    // Add button, lives on a single row beneath the entries table.
    manualFormOpen: false,
    manualEntry: { label: '', category: '', impact: 'medium', notes: '', daily: ['', '', '', '', '', '', ''] },
    manualSaving: false,
    // Column index → label. Backend always treats Monday as week_of, so the
    // ordering here is purely a render-time preference.
    _dayLabelsMon: ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'],
    _dayLabelsSun: ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'],
    _systemThemeMql: null,

    // ---- Review state ----------------------------------------------------
    view: 'briefing', // 'briefing' | 'review' | 'actions'
    review: null,
    reviewLoading: false,
    reviewError: null,
    reviewCopied: false,
    reviewScanning: false,
    reviewScanError: null,
    scanningWeek: null,
    missingMonthExpanded: {}, // { [YYYY-MM]: boolean }
    reviewKind: 'month', // 'month' | 'year'
    reviewMonth: '', // 'YYYY-MM'
    reviewYear: new Date().getFullYear(),
    talkingPointSections: [
      { key: 'achievements', label: 'Achievements' },
      { key: 'focus', label: 'Focus & priorities' },
      { key: 'challenges', label: 'Challenges' },
      { key: 'asks', label: 'Asks for my manager' },
    ],

    // ---- Actions state ---------------------------------------------------
    // WIA Actions: rule-based suggestions surfaced after each scan. The
    // list is loaded lazily on first tab open and refreshed manually or
    // after any state transition. ``actionBusy`` tracks per-id mutations
    // so the buttons can disable themselves without blocking the rest of
    // the list.
    actions: [],
    actionsLoading: false,
    actionsError: null,
    actionsIncludeResolved: false,
    actionBusy: {},
    _actionsLoaded: false,

    async init() {
      const now = new Date();
      this.reviewMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
      this.reviewYear = now.getFullYear();
      await this.loadPrefs();
      this.applyTheme(this.prefs.theme);
      // Cache-only briefing read doesn't need Work IQ, so fan out in parallel
      // with the status/health/schedule probes. The user sees cached data
      // (or a skeleton, then a state-aware empty card) within one round-trip
      // instead of waiting for the workiq status probe to come back first.
      await Promise.all([
        this.loadHealth(),
        this.loadSchedule(),
        this.loadStatus(),
        this.loadBriefing(false),
        this.loadUpdateInfo(),
      ]);
      setInterval(() => this.loadSchedule(), 30000);
    },

    // ---- UI state helpers ------------------------------------------------
    hasEntries() {
      // Treat the displayed table window as the source of truth so the
      // table renders in Sunday mode even when the current Mon-week is
      // empty but the prior Mon-week's Sunday has hours.
      if (this.briefing && this.briefing.entries && this.briefing.entries.length) return true;
      return this._displayEntries().length > 0;
    },

    // True before we've ever received a briefing payload (first paint).
    bootingBriefing() { return this.briefing === null; },

    // Distinguish a brand-new install (no scans on record) from a week
    // that legitimately has no activity.
    isFirstRun() {
      return !this.schedule.last_scan_at && !this.hasEntries();
    },

    // Human-friendly relative time, e.g. "2 minutes ago". Falls back to
    // a localized timestamp for anything older than ~30 days.
    timeAgo(iso) {
      if (!iso) return 'never';
      const then = new Date(iso).getTime();
      if (!Number.isFinite(then)) return 'never';
      const diffSec = Math.max(0, Math.round((Date.now() - then) / 1000));
      if (diffSec < 45) return 'just now';
      if (diffSec < 90) return '1 minute ago';
      const diffMin = Math.round(diffSec / 60);
      if (diffMin < 60) return `${diffMin} minutes ago`;
      const diffHr = Math.round(diffMin / 60);
      if (diffHr < 24) return `${diffHr} hour${diffHr === 1 ? '' : 's'} ago`;
      const diffDay = Math.round(diffHr / 24);
      if (diffDay < 30) return `${diffDay} day${diffDay === 1 ? '' : 's'} ago`;
      try { return new Date(iso).toLocaleDateString(); } catch { return iso; }
    },

    async loadHealth() {
      try {
        const r = await fetch('/api/health');
        const data = await r.json();
        this.appVersion = `v${data.version || '?'}`;
      } catch (e) { /* non-fatal */ }
    },

    async loadUpdateInfo() {
      try {
        const r = await fetch('/api/updates/check');
        if (r.ok) {
          const data = await r.json();
          this.updateInfo = data;
        }
      } catch (e) { /* non-fatal — no network access is fine */ }
    },

    // ---- Theme -----------------------------------------------------------
    applyTheme(theme) {
      const root = document.documentElement;
      const isDark =
        theme === 'dark' ||
        (theme === 'system' && window.matchMedia('(prefers-color-scheme: dark)').matches);
      root.classList.toggle('dark', isDark);
      // Always mark the resolved scheme on <html> so the inline boot CSS
      // (which uses `html:not(.light)` under `prefers-color-scheme: dark`)
      // does not override Tailwind's body color when the user picks light
      // on a system that prefers dark — that override turned `currentColor`
      // (and therefore every Heroicon) white.
      root.classList.toggle('light', !isDark);
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
      try { window.localStorage && window.localStorage.setItem('wia-theme', theme); } catch (e) { /* ignore */ }
      try {
        await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ theme }),
        });
      } catch (e) { this.error = `Save theme failed: ${e}`; }
    },

    async setWeekStartsOn(value) {
      // UI-only preference: backend ``week_of`` stays Monday-anchored, only
      // the rendered column order changes. In Sunday mode we additionally
      // merge the previous Monday-week's entries at render time so the
      // Sunday column has data — that requires re-running the briefing
      // load (or clearing the sidecar when switching back to Monday).
      if (value !== 'mon' && value !== 'sun') return;
      const prev = this.prefs.week_starts_on;
      this.prefs.week_starts_on = value;
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ week_starts_on: value }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
        if (prev !== value) {
          if (value === 'mon') this.prevWeekEntries = [];
          await this.loadBriefing(false);
        }
      } catch (e) { this.error = `Save week start failed: ${e}`; }
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

    async _saveExcludedKeywords(next) {
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ excluded_keywords: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save excluded keywords failed: ${e}`; }
    },

    async addExcludedKeyword() {
      const raw = (this.newExcludedKeyword || '').trim();
      if (!raw) return;
      const existing = (this.prefs.excluded_keywords || []).map((k) => k.toLowerCase());
      if (existing.includes(raw.toLowerCase())) {
        this.newExcludedKeyword = '';
        return;
      }
      const next = [...(this.prefs.excluded_keywords || []), raw];
      this.prefs.excluded_keywords = next;
      this.newExcludedKeyword = '';
      await this._saveExcludedKeywords(next);
    },

    async removeExcludedKeyword(kw) {
      const next = (this.prefs.excluded_keywords || []).filter((k) => k !== kw);
      this.prefs.excluded_keywords = next;
      await this._saveExcludedKeywords(next);
    },

    async _saveExcludedCategories(next) {
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ excluded_calendar_categories: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save excluded categories failed: ${e}`; }
    },

    async addExcludedCategory() {
      const raw = (this.newExcludedCategory || '').trim();
      if (!raw) return;
      const existing = (this.prefs.excluded_calendar_categories || []).map((k) => k.toLowerCase());
      if (existing.includes(raw.toLowerCase())) {
        this.newExcludedCategory = '';
        return;
      }
      const next = [...(this.prefs.excluded_calendar_categories || []), raw];
      this.prefs.excluded_calendar_categories = next;
      this.newExcludedCategory = '';
      await this._saveExcludedCategories(next);
    },

    async removeExcludedCategory(cat) {
      const next = (this.prefs.excluded_calendar_categories || []).filter((k) => k !== cat);
      this.prefs.excluded_calendar_categories = next;
      await this._saveExcludedCategories(next);
    },

    async _saveHighImpactKeywords(next) {
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ high_impact_keywords: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save high-impact keywords failed: ${e}`; }
    },

    async addHighImpactKeyword() {
      const raw = (this.newHighImpactKeyword || '').trim();
      if (!raw) return;
      const existing = (this.prefs.high_impact_keywords || []).map((k) => k.toLowerCase());
      if (existing.includes(raw.toLowerCase())) {
        this.newHighImpactKeyword = '';
        return;
      }
      const next = [...(this.prefs.high_impact_keywords || []), raw];
      this.prefs.high_impact_keywords = next;
      this.newHighImpactKeyword = '';
      await this._saveHighImpactKeywords(next);
    },

    async removeHighImpactKeyword(kw) {
      const next = (this.prefs.high_impact_keywords || []).filter((k) => k !== kw);
      this.prefs.high_impact_keywords = next;
      await this._saveHighImpactKeywords(next);
    },

    async _saveHighImpactCategories(next) {
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ high_impact_calendar_categories: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save high-impact categories failed: ${e}`; }
    },

    async addHighImpactCategory() {
      const raw = (this.newHighImpactCategory || '').trim();
      if (!raw) return;
      const existing = (this.prefs.high_impact_calendar_categories || []).map((k) => k.toLowerCase());
      if (existing.includes(raw.toLowerCase())) {
        this.newHighImpactCategory = '';
        return;
      }
      const next = [...(this.prefs.high_impact_calendar_categories || []), raw];
      this.prefs.high_impact_calendar_categories = next;
      this.newHighImpactCategory = '';
      await this._saveHighImpactCategories(next);
    },

    async removeHighImpactCategory(cat) {
      const next = (this.prefs.high_impact_calendar_categories || []).filter((k) => k !== cat);
      this.prefs.high_impact_calendar_categories = next;
      await this._saveHighImpactCategories(next);
    },

    async _saveUmbrellaCategories(next) {
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ umbrella_calendar_categories: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save umbrella categories failed: ${e}`; }
    },

    async addUmbrellaCategory() {
      const raw = (this.newUmbrellaCategory || '').trim();
      if (!raw) return;
      const existing = (this.prefs.umbrella_calendar_categories || []).map((k) => k.toLowerCase());
      if (existing.includes(raw.toLowerCase())) {
        this.newUmbrellaCategory = '';
        return;
      }
      const next = [...(this.prefs.umbrella_calendar_categories || []), raw];
      this.prefs.umbrella_calendar_categories = next;
      this.newUmbrellaCategory = '';
      await this._saveUmbrellaCategories(next);
    },

    async removeUmbrellaCategory(cat) {
      const next = (this.prefs.umbrella_calendar_categories || []).filter((k) => k !== cat);
      this.prefs.umbrella_calendar_categories = next;
      await this._saveUmbrellaCategories(next);
    },

    async _savePreserveCategories(next) {
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ preserve_calendar_categories: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save preserve categories failed: ${e}`; }
    },

    async addPreserveCategory() {
      const raw = (this.newPreserveCategory || '').trim();
      if (!raw) return;
      const existing = (this.prefs.preserve_calendar_categories || []).map((k) => k.toLowerCase());
      if (existing.includes(raw.toLowerCase())) {
        this.newPreserveCategory = '';
        return;
      }
      const next = [...(this.prefs.preserve_calendar_categories || []), raw];
      this.prefs.preserve_calendar_categories = next;
      this.newPreserveCategory = '';
      await this._savePreserveCategories(next);
    },

    async removePreserveCategory(cat) {
      const next = (this.prefs.preserve_calendar_categories || []).filter((k) => k !== cat);
      this.prefs.preserve_calendar_categories = next;
      await this._savePreserveCategories(next);
    },

    async toggleExcludePrivate(on) {
      this.prefs.exclude_private_meetings = !!on;
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ exclude_private_meetings: !!on }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
      } catch (e) { this.error = `Save private-meetings toggle failed: ${e}`; }
    },

    async loadPrefs() {
      try {
        const r = await fetch('/api/prefs');
        this.prefs = await r.json();
        this.organizationDraft = this.prefs.organization_label || '';
        // Seed the identity badge from the cached UPN so the header
        // renders immediately, before the workiq probe / identity fetch
        // round-trips complete.
        if (this.prefs.user_upn) {
          this.identity = {
            upn: this.prefs.user_upn || '',
            display_name: this.prefs.user_display_name || '',
          };
        }
        try {
          if (this.prefs && this.prefs.theme) {
            window.localStorage && window.localStorage.setItem('wia-theme', this.prefs.theme);
          }
        } catch (e) { /* ignore */ }
      } catch (e) { /* keep defaults */ }
    },

    async saveOrganization() {
      const next = (this.organizationDraft || '').trim();
      try {
        const r = await fetch('/api/prefs', {
          method: 'PUT',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ organization_label: next }),
        });
        if (!r.ok) throw new Error(await r.text());
        this.prefs = await r.json();
        this.organizationDraft = this.prefs.organization_label || '';
      } catch (e) { this.error = `Save organization failed: ${e}`; }
    },

    // ---- Impact ---------------------------------------------------------
    impactLabel(impact) {
      switch (impact) {
        case 'high': return 'High';
        case 'low': return 'Low';
        default: return 'Med';
      }
    },

    impactBadgeClass(impact) {
      switch (impact) {
        case 'high':
          return 'bg-amber-100 text-amber-800 ring-1 ring-amber-300 hover:bg-amber-200 dark:bg-amber-900/40 dark:text-amber-200 dark:ring-amber-700';
        case 'low':
          return 'bg-slate-100 text-slate-500 hover:bg-slate-200 dark:bg-slate-800 dark:text-slate-400 dark:hover:bg-slate-700';
        default:
          return 'bg-indigo-50 text-indigo-700 ring-1 ring-indigo-200 hover:bg-indigo-100 dark:bg-indigo-950/40 dark:text-indigo-200 dark:ring-indigo-800';
      }
    },

    impactSegmentClass(value, current) {
      const active = (current || 'medium') === value;
      if (!active) {
        return 'bg-white text-slate-500 hover:bg-slate-100 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-slate-800';
      }
      switch (value) {
        case 'high':
          return 'bg-amber-500 text-white dark:bg-amber-600';
        case 'low':
          return 'bg-slate-400 text-white dark:bg-slate-500';
        default:
          return 'bg-indigo-500 text-white dark:bg-indigo-600';
      }
    },

    // Compact 3-dot impact picker: each dot is a click target that sets
    // that level directly. Active dot is filled with the level's colour;
    // inactive dots are outlined and dim. Saves ~75px per row vs. the
    // old labelled segmented control while keeping one-click selection.
    impactDotClass(value, current) {
      const active = (current || 'medium') === value;
      if (!active) {
        return 'border border-slate-300 bg-transparent hover:bg-slate-100 dark:border-slate-600 dark:hover:bg-slate-700';
      }
      switch (value) {
        case 'high':
          return 'bg-amber-500 ring-2 ring-amber-200 dark:bg-amber-500 dark:ring-amber-900';
        case 'low':
          return 'bg-slate-400 ring-2 ring-slate-200 dark:bg-slate-500 dark:ring-slate-700';
        default:
          return 'bg-indigo-500 ring-2 ring-indigo-200 dark:bg-indigo-500 dark:ring-indigo-900';
      }
    },

    // ---- Signal-source badges -------------------------------------------
    // Map the source tags persisted on each entry (`calendar`, `teams`,
    // `email`, `inferred`, `manual`) to a small pill with an icon. Surfaces
    // provenance in the Briefing table without taking much room.
    sourceBadgeClass(src) {
      switch (src) {
        case 'calendar':
          return 'bg-sky-100 text-sky-700 dark:bg-sky-900/40 dark:text-sky-300';
        case 'teams':
          return 'bg-indigo-100 text-indigo-700 dark:bg-indigo-900/40 dark:text-indigo-300';
        case 'email':
          return 'bg-emerald-100 text-emerald-700 dark:bg-emerald-900/40 dark:text-emerald-300';
        case 'inferred':
          return 'bg-amber-100 text-amber-700 dark:bg-amber-900/40 dark:text-amber-300';
        case 'manual':
          return 'bg-violet-100 text-violet-700 dark:bg-violet-900/40 dark:text-violet-300';
        case 'unknown':
          // Dashed border + muted gray signals "placeholder, will be replaced".
          return 'bg-slate-50 text-slate-500 ring-1 ring-dashed ring-slate-300 dark:bg-slate-900/40 dark:text-slate-400 dark:ring-slate-700';
        default:
          return 'bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-300';
      }
    },
    sourceBadgeIcon(src) {
      switch (src) {
        case 'calendar': return 'calendar-days';
        case 'teams': return 'chat-bubble-left-right';
        case 'email': return 'envelope';
        case 'inferred': return 'light-bulb';
        case 'manual': return 'pencil-square';
        case 'unknown': return 'question-mark-circle';
        default: return 'queue-list';
      }
    },
    sourceBadgeLabel(src) {
      switch (src) {
        case 'calendar': return 'Calendar';
        case 'teams': return 'Teams';
        case 'email': return 'Email';
        case 'inferred': return 'Inferred';
        case 'manual': return 'Manual';
        case 'unknown': return 'Unknown';
        default: return src;
      }
    },
    sourceBadgeTitle(src) {
      switch (src) {
        case 'calendar': return 'Signal: Outlook calendar event';
        case 'teams': return 'Signal: Microsoft Teams activity';
        case 'email': return 'Signal: Outlook email thread';
        case 'inferred': return 'Signal: inferred (gap-fill / heuristic)';
        case 'manual': return 'Signal: manual entry added by you';
        case 'unknown': return 'Signal: unknown — placeholder for entries from before WIA tracked sources. A rescan will replace this with the real signal.';
        default: return 'Signal: ' + src;
      }
    },

    async setImpact(entry, value) {
      if (!entry) return;
      const current = entry.impact || 'medium';
      if (current === value) return;
      const previous = entry.impact;
      entry.impact = value;
      try {
        const r = await fetch(`/api/entries/${entry.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ impact: value }),
        });
        if (!r.ok) throw new Error(await r.text());
      } catch (e) {
        entry.impact = previous;
        this.error = `Save impact failed: ${e}`;
      }
    },

    groupImpactSummary(group) {
      const counts = { high: 0, medium: 0, low: 0 };
      for (const e of group.entries) {
        const k = e.impact || 'medium';
        if (counts[k] !== undefined) counts[k] += 1;
      }
      if (counts.high) return `${counts.high} high`;
      if (counts.medium) return `${counts.medium} med`;
      return `${counts.low} low`;
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
      const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + this.dayOffset(i));
      return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
    },

    dayIso(i) {
      const monday = this.briefing?.week_start
        ? new Date(this.briefing.week_start + 'T00:00:00')
        : this.weekStartFor(this.weekOffset);
      const d = new Date(monday.getFullYear(), monday.getMonth(), monday.getDate() + this.dayOffset(i));
      const y = d.getFullYear();
      const mm = String(d.getMonth() + 1).padStart(2, '0');
      const dd = String(d.getDate()).padStart(2, '0');
      return `${y}-${mm}-${dd}`;
    },

    // Map a column index (0..6) to days-from-Monday. When the user prefers
    // Sunday-start, column 0 is Sunday (= Monday − 1 day), columns 1..6 are
    // Mon..Sat. Otherwise (Monday-start) it's just the identity (0..6).
    dayOffset(i) {
      if (this.prefs.week_starts_on === 'sun') {
        return i === 0 ? -1 : i - 1;
      }
      return i;
    },

    // Column index → 3-letter weekday label, honouring week_starts_on.
    dayLabel(i) {
      const labels = this.prefs.week_starts_on === 'sun' ? this._dayLabelsSun : this._dayLabelsMon;
      return labels[i];
    },

    canGoBack() { return this.weekOffset > this.minWeekOffset; },
    canGoForward() { return this.weekOffset < 0; },

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
      finally { this.workiqChecked = true; this._persistWorkIqCache(); }
      // Best-effort: pull the cached UPN immediately, then trigger a
      // background fetch the first time so the badge fills in without
      // blocking the rest of init().
      if (this.workiq.ready) this.refreshIdentity({ background: true });
    },

    // Persist enough of the workiq + identity state to render the header
    // pill at its real size on the next boot, eliminating layout shift.
    _persistWorkIqCache() {
      try {
        if (!window.localStorage) return;
        const payload = {
          ready: !!this.workiq.ready,
          upn: (this.identity && this.identity.upn) || '',
          displayName: (this.identity && this.identity.display_name) || '',
        };
        window.localStorage.setItem('wia-workiq-cache', JSON.stringify(payload));
      } catch (e) { /* non-fatal */ }
    },

    async refreshIdentity({ force = false, background = false } = {}) {
      if (this.identityLoading) return;
      this.identityLoading = !background;
      try {
        const url = force ? '/api/workiq/identity?refresh=true' : '/api/workiq/identity';
        const r = await fetch(url);
        if (!r.ok) return;
        const data = await r.json();
        this.identity = {
          upn: data.upn || '',
          display_name: data.display_name || '',
        };
        this._persistWorkIqCache();
      } catch (e) { /* non-fatal */ }
      finally { this.identityLoading = false; }
    },

    async enableWorkIQ() {
      this.error = null; this.enabling = true;
      try {
        const r = await fetch('/api/workiq/enable', { method: 'POST' });
        this.workiq = await r.json();
        if (!this.workiq.ready && this.workiq.message) this.error = this.workiq.message;
        if (this.workiq.ready) {
          // Force-refresh the identity now that we've just signed in.
          this.refreshIdentity({ force: true, background: true });
          await this.loadBriefing(true);
        }
      } catch (e) { this.error = `Enable failed: ${e}`; }
      finally { this.enabling = false; }
    },

    async loadBriefing(refresh) {
      // Two modes:
      //   refresh=false  → quick cache read for the displayed week. Used by
      //                    init() and Prev/Next week navigation. Cheap.
      //   refresh=true   → full Work IQ scan. Long-running. We treat it as a
      //                    background task so the user can navigate weeks
      //                    while it's in flight. Only one manual scan is
      //                    allowed at a time.
      if (refresh) {
        if (this.scanningBriefing) {
          this.error = 'A scan is already running for week ' + this.scanningWeekIso + '. Please wait for it to finish.';
          return;
        }
        return this._runBackgroundScan(this.weekStartIso(this.weekOffset));
      }

      // Cache-only path. Tag the request with the requested week so a slow
      // response doesn't clobber a newer week the user has since navigated
      // to.
      const requestedWeek = this.weekStartIso(this.weekOffset);
      this.loading = true;
      this.error = null;
      try {
        const params = new URLSearchParams();
        params.set('week_of', requestedWeek);
        // In Sunday-display mode the visible week spans two Monday-weeks
        // (Sunday cell = previous Mon-week's last day). Fetch both in
        // parallel so the Sunday column reflects real data.
        const prevPromise = this._loadPrevWeekEntries(requestedWeek);
        const r = await fetch(`/api/briefing?${params.toString()}`);
        if (!r.ok) throw new Error(await r.text());
        const payload = await r.json();
        const prevEntries = await prevPromise;
        // Drop the result if the user has navigated to another week while
        // we were waiting for the cache lookup.
        if (this.weekStartIso(this.weekOffset) !== requestedWeek) return;
        this.briefing = payload;
        this.prevWeekEntries = prevEntries;
        if (this.briefing.status === 'workiq-not-enabled') {
          await this.loadStatus();
        }
      } catch (e) { this.error = String(e); }
      finally { this.loading = false; }
    },

    // Fetch entries from the Monday-week immediately before ``currentMonday``
    // so the Sunday cell of a Sunday-anchored display window has data to
    // render. Returns [] in Monday mode, on error, or when the user has
    // navigated away before the fetch resolved.
    async _loadPrevWeekEntries(currentMonday) {
      if ((this.prefs.week_starts_on || 'mon') !== 'sun') return [];
      try {
        const d = new Date(currentMonday + 'T00:00:00');
        d.setDate(d.getDate() - 7);
        const y = d.getFullYear();
        const mm = String(d.getMonth() + 1).padStart(2, '0');
        const dd = String(d.getDate()).padStart(2, '0');
        const prevIso = `${y}-${mm}-${dd}`;
        const params = new URLSearchParams({ week_of: prevIso });
        const r = await fetch(`/api/briefing?${params.toString()}`);
        if (!r.ok) return [];
        const payload = await r.json();
        return Array.isArray(payload?.entries) ? payload.entries : [];
      } catch (_e) { return []; }
    },

    async _runBackgroundScan(weekIso) {
      // Long-running Work IQ scan. Doesn't block week navigation: the user
      // can switch to another week while this runs and we'll only paint the
      // result if they come back. Sets ``scanningBriefing`` so the UI can
      // show a banner on whichever week is in flight.
      this.scanningBriefing = true;
      this.scanningWeekIso = weekIso;
      this.error = null;
      try {
        const params = new URLSearchParams({ week_of: weekIso, refresh: 'true' });
        const r = await fetch(`/api/briefing?${params.toString()}`);
        if (!r.ok) throw new Error(await r.text());
        const payload = await r.json();
        // Only swap the displayed briefing if the user is still on the
        // week we just scanned. Otherwise the next cache fetch (on
        // navigation back) will pick up the freshly persisted entries.
        if (this.weekStartIso(this.weekOffset) === weekIso) {
          this.briefing = payload;
          // Refresh the prev-week sidecar too so the Sunday column reflects
          // any data the scan persisted into the prior Mon-week.
          this.prevWeekEntries = await this._loadPrevWeekEntries(weekIso);
          if (this.briefing.status === 'workiq-not-enabled') {
            this.error = 'Click "Enable Work IQ" to connect.';
            await this.loadStatus();
          }
        }
        await this.loadSchedule();
        if (this.historyOpen) await this.loadHistory();
      } catch (e) { this.error = `Scan for week ${weekIso} failed: ${e}`; }
      finally {
        this.scanningBriefing = false;
        this.scanningWeekIso = null;
      }
    },

    // True when the *currently displayed* week is being scanned. Drives
    // the local progress bar / signal pulse / scanning caption.
    isScanningCurrent() {
      return this.scanningBriefing && this.scanningWeekIso === this.weekStartIso(this.weekOffset);
    },

    // Jump the displayed week to whichever Monday-week is currently being
    // scanned in the background, if any. Used by the "jump to it" link.
    async goToScanningWeek() {
      if (!this.scanningBriefing || !this.scanningWeekIso) return;
      // Compute the offset between today's Monday and the target Monday.
      const target = new Date(this.scanningWeekIso + 'T00:00:00');
      const todayMonday = this.weekStartFor(0);
      const diffMs = target.getTime() - todayMonday.getTime();
      const diffWeeks = Math.round(diffMs / (7 * 24 * 60 * 60 * 1000));
      this.weekOffset = diffWeeks;
      // Pull the cached version (probably empty) while the scan continues.
      await this.loadBriefing(false);
    },

    rescan() { return this.loadBriefing(true); },

    // Wipe every entry (including manual edits) and scan-history rows for
    // the displayed week, then reload the now-empty briefing. The user
    // can re-run a scan from scratch afterwards.
    async clearWeek() {
      if (this.scanningBriefing || this.clearingWeek) return;
      const weekIso = this.weekStartIso(this.weekOffset);
      const ok = window.confirm(
        `Remove all scanned and edited data for the week of ${weekIso}? ` +
        `This cannot be undone.`
      );
      if (!ok) return;
      this.clearingWeek = true;
      this.error = null;
      try {
        const params = new URLSearchParams({ week_of: weekIso });
        const r = await fetch(`/api/briefing?${params.toString()}`, { method: 'DELETE' });
        if (!r.ok) throw new Error(await r.text());
        await this.loadBriefing(false);
        await this.loadSchedule();
        if (this.historyOpen) await this.loadHistory();
        if (this.review) await this.loadReview();
      } catch (e) {
        this.error = `Failed to clear week ${weekIso}: ${e}`;
      } finally {
        this.clearingWeek = false;
      }
    },

    // ---- Grouping --------------------------------------------------------
    // Aggressive category normalizer: strips hidden format/control chars
    // (zero-width spaces, BOM, bidi marks, ASCII control codes), folds
    // Unicode compatibility forms, collapses internal whitespace, and
    // trims. Without this, two visually identical category strings can
    // sort apart because one has e.g. a leading U+200B (zero-width
    // space, code point higher than 'z'), making it sort *after* "W"
    // categories instead of "C".
    _normalizeCategory(raw) {
      if (raw == null) return 'Uncategorized';
      let s = String(raw);
      // NFKC fold: collapses compatibility variants (full-width forms etc.).
      try { s = s.normalize('NFKC'); } catch (_) { /* legacy engines */ }
      // Strip C0/C1 control codes and Unicode format chars (Cf):
      // \u200B-\u200F, \u2028-\u202F, \u2060-\u206F, \uFEFF.
      s = s.replace(/[\u0000-\u001F\u007F-\u009F\u200B-\u200F\u2028-\u202F\u2060-\u206F\uFEFF]/g, '');
      // Collapse any run of whitespace (incl. NBSP U+00A0) into a single space.
      s = s.replace(/[\s\u00A0]+/g, ' ').trim();
      return s || 'Uncategorized';
    },

    // ---- Display entries (Option B: virtualized Sunday-start) ------------
    // Returns the ISO dates of the 7 currently displayed columns, in order.
    _displayIsoList() {
      const out = new Array(7);
      for (let i = 0; i < 7; i++) out[i] = this.dayIso(i);
      return out;
    },

    // Entries to render in the table. In Monday-display mode this is just
    // ``briefing.entries`` (storage is already Monday-anchored). In
    // Sunday-display mode we additionally pull entries from the prior
    // Monday-week so the Sunday cell isn't perpetually empty; we filter
    // both lists to those that actually have hours in the visible window
    // so the prior week's Mon..Sat rows don't leak into the table.
    _displayEntries() {
      const current = this.briefing?.entries || [];
      if ((this.prefs.week_starts_on || 'mon') !== 'sun') return current;
      const isoList = this._displayIsoList();
      const hasVisibleHours = (e) => {
        const dh = e.daily_hours || {};
        for (const iso of isoList) if ((dh[iso] || 0) > 0) return true;
        return false;
      };
      const out = [];
      for (const e of current) out.push(e);
      for (const e of (this.prevWeekEntries || [])) {
        if (hasVisibleHours(e)) out.push(e);
      }
      return out;
    },

    // Sum of an entry's daily_hours over the visible 7-day window. In
    // Monday-display mode this equals ``duration_hours`` for current-week
    // entries; in Sunday mode it correctly reflects only the portion of
    // the entry that lands in the displayed window.
    entryDisplayTotal(entry) {
      const dh = entry.daily_hours || {};
      let total = 0;
      for (const iso of this._displayIsoList()) total += dh[iso] || 0;
      return total;
    },

    groupedEntries() {
      const entries = this._displayEntries();
      // Normalize category keys so "Admin", "admin", "Admin ", and
      // "\u200BAdmin" all collapse into a single group with a single
      // display label — otherwise the table renders duplicates and the
      // sort comparator can't establish a total order between them.
      const map = new Map(); // normLower -> { display, items[] }
      for (const e of entries) {
        const cleaned = this._normalizeCategory(e.category);
        const norm = cleaned.toLowerCase();
        if (!map.has(norm)) map.set(norm, { display: cleaned, items: [] });
        map.get(norm).items.push(e);
      }
      const groups = [];
      for (const [norm, { display, items }] of map.entries()) {
        const daily = {};
        let total = 0;
        for (let i = 0; i < 7; i++) {
          const iso = this.dayIso(i);
          const v = items.reduce((s, e) => s + ((e.daily_hours || {})[iso] || 0), 0);
          daily[iso] = v;
          total += v;
        }
        groups.push({ category: display, _sortKey: norm, entries: items, daily, total });
      }
      // Sort categories using the user's chosen key. Default is
      // alphabetical so deletes / hour edits don't re-rank groups
      // mid-action; the user can opt into totals-descending by clicking
      // the Total header. We compare on the normalized lowercase key
      // with a deterministic tie-breaker so the order is stable across
      // re-renders (no shuffle when an unrelated field changes).
      const { key, dir } = this.groupSort || { key: 'category', dir: 'asc' };
      const sign = dir === 'desc' ? -1 : 1;
      const tieBreak = (a, b) => (a._sortKey < b._sortKey ? -1 : a._sortKey > b._sortKey ? 1 : 0);
      if (key === 'total') {
        groups.sort((a, b) => {
          // Round to cents so floating-point drift between optimistic
          // local sums and server-rounded values doesn't flip order.
          const at = Math.round((a.total || 0) * 100);
          const bt = Math.round((b.total || 0) * 100);
          if (at !== bt) return sign * (at - bt);
          // Equal totals -> stable alphabetical fallback (not flipped).
          return tieBreak(a, b);
        });
      } else {
        groups.sort((a, b) => sign * tieBreak(a, b));
      }
      return groups;
    },

    setGroupSort(key) {
      const current = this.groupSort || { key: 'category', dir: 'asc' };
      if (current.key === key) {
        this.groupSort = { key, dir: current.dir === 'asc' ? 'desc' : 'asc' };
      } else {
        // Sensible default direction per column: A→Z for category, big→small for total.
        this.groupSort = { key, dir: key === 'total' ? 'desc' : 'asc' };
      }
    },

    groupSortIndicator(key) {
      const current = this.groupSort || { key: 'category', dir: 'asc' };
      if (current.key !== key) return '';
      return current.dir === 'asc' ? '▲' : '▼';
    },

    groupRows(group) {
      // Returns the visible rows for a group: always the summary row, plus
      // each entry as a sub-row when the group is expanded. When the user
      // has opened the notes editor for an entry, a notes row trails it.
      const rows = [{ kind: 'group', key: `g:${group.category}`, group }];
      if (this.expanded[group.category]) {
        for (const entry of group.entries) {
          rows.push({ kind: 'sub', key: `e:${entry.id}`, entry, group });
          if (this.notesOpen[entry.id]) {
            rows.push({ kind: 'notes', key: `n:${entry.id}`, entry, group });
          }
        }
      }
      return rows;
    },

    // Flattened row list across all groups. Used by the table so we can
    // iterate with a SINGLE x-for and avoid Alpine's nested-x-for DOM
    // reconciliation bug, where the outer loop reorders but the inner
    // template's <tr> siblings don't move together — which manifested
    // as the visible table showing a different group order than the
    // (correctly sorted) groupedEntries() result.
    flatTableRows() {
      const out = [];
      for (const g of this.groupedEntries()) {
        for (const r of this.groupRows(g)) out.push(r);
      }
      return out;
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
      const total = this._displayEntries().reduce(
        (sum, e) => sum + ((e.daily_hours || {})[iso] || 0), 0,
      );
      return this.hhmm(total);
    },

    weekTotal() {
      const entries = this._displayEntries();
      const isoList = this._displayIsoList();
      let total = 0;
      for (const e of entries) {
        const dh = e.daily_hours || {};
        for (const iso of isoList) total += dh[iso] || 0;
      }
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

    // ---- Inline hour editing --------------------------------------------
    // Per-entry debounce timers + pre-edit snapshots so we can coalesce
    // rapid stepper clicks into a single PATCH and roll back on failure.
    _dailySaveTimers: {},
    _dailySnapshots: {},

    adjustEntryDaily(entry, dayIndex, deltaHours) {
      if (!entry) return;
      const iso = this.dayIso(dayIndex);
      const current = Number((entry.daily_hours || {})[iso]) || 0;
      const next = Math.max(0, Math.round((current + deltaHours) * 100) / 100);
      if (next === current) return;
      // Snapshot once per debounce window so rollback restores the
      // pre-burst value, not an intermediate step.
      if (this._dailySnapshots[entry.id] === undefined) {
        this._dailySnapshots[entry.id] = {
          daily_hours: { ...(entry.daily_hours || {}) },
          duration_hours: entry.duration_hours,
        };
      }
      const updated = { ...(entry.daily_hours || {}) };
      if (next > 0) updated[iso] = next; else delete updated[iso];
      const newDuration = Object.values(updated).reduce((s, v) => s + (Number(v) || 0), 0);
      entry.daily_hours = updated;
      entry.duration_hours = Math.round(newDuration * 10000) / 10000;
      // Debounce the network save.
      const id = entry.id;
      if (this._dailySaveTimers[id]) clearTimeout(this._dailySaveTimers[id]);
      this._dailySaveTimers[id] = setTimeout(() => {
        delete this._dailySaveTimers[id];
        this._flushEntryDaily(entry);
      }, 300);
    },

    async _flushEntryDaily(entry) {
      if (!entry || entry.id == null) return;
      const snapshot = this._dailySnapshots[entry.id];
      delete this._dailySnapshots[entry.id];
      try {
        const r = await fetch(`/api/entries/${entry.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ daily_hours: entry.daily_hours || {} }),
        });
        if (!r.ok) throw new Error(await r.text());
        const saved = await r.json();
        // Trust the server's authoritative values (rounding, server-side
        // duration recompute) — but only if the user hasn't clicked again
        // in the meantime (which would have re-snapshotted).
        if (this._dailySnapshots[entry.id] === undefined) {
          entry.daily_hours = saved.daily_hours || entry.daily_hours;
          entry.duration_hours = saved.duration_hours ?? entry.duration_hours;
        }
      } catch (e) {
        if (snapshot) {
          entry.daily_hours = snapshot.daily_hours;
          entry.duration_hours = snapshot.duration_hours;
        }
        this.error = `Save hours failed: ${e}`;
      }
    },

    // ---- Live totals & top work areas ------------------------------------
    // Re-derived from ``briefing.entries`` so they stay in sync with local
    // edits (delete, hours change, etc.) without waiting for a server
    // refetch. Mirrors ``_totals_from_entries`` / ``_top_work_areas`` in
    // core/orchestrator.py so a freshly loaded briefing renders the same
    // numbers the server computed.
    liveTotals() {
      // Aggregate over the displayed 7-day window so the summary cards
      // match the entries-table totals in both Monday and Sunday display
      // modes. Entry-level rollups (meetings/collab/focus) are scaled by
      // each entry's share of hours that falls inside the window.
      const entries = this._displayEntries();
      const isoList = this._displayIsoList();
      let meetings = 0, collab = 0, focus = 0, total = 0;
      for (const e of entries) {
        const dh = e.daily_hours || {};
        let visible = 0;
        for (const iso of isoList) visible += dh[iso] || 0;
        if (visible <= 0) continue;
        total += visible;
        if (e.confidence === 'high') meetings += visible;
        else if (e.confidence === 'medium') collab += visible;
        if ((e.label || '').toLowerCase().startsWith('focus')) focus += visible;
      }
      const r = (n) => Math.round(n * 100) / 100;
      return {
        total_hours: r(total),
        meetings_hours: r(meetings),
        focus_hours: r(focus),
        collaboration_hours: r(collab),
      };
    },

    liveTopWorkAreas(limit = 5) {
      const entries = this._displayEntries();
      const isoList = this._displayIsoList();
      // Same normalization as groupedEntries() so the chips match the
      // table groups even when raw categories differ only in case or
      // surrounding whitespace.
      const by = new Map(); // norm -> { display, hours }
      for (const e of entries) {
        const raw = (e.category == null ? '' : String(e.category)).trim() || 'Uncategorized';
        const norm = raw.toLocaleLowerCase();
        const dh = e.daily_hours || {};
        let visible = 0;
        for (const iso of isoList) visible += dh[iso] || 0;
        if (visible <= 0) continue;
        const slot = by.get(norm) || { display: raw, hours: 0 };
        slot.hours += visible;
        by.set(norm, slot);
      }
      return Array.from(by.values())
        .map(({ display, hours }) => ({ label: display, hours: Math.round(hours * 100) / 100 }))
        .sort((a, b) => {
          const d = b.hours - a.hours;
          if (d !== 0) return d;
          // Deterministic tie-break so chips don't reshuffle when an
          // edit makes two areas tie on hours.
          return a.label.toLocaleLowerCase() < b.label.toLocaleLowerCase() ? -1 : 1;
        })
        .slice(0, limit);
    },

    // ---- Notes ----------------------------------------------------------
    isNotesOpen(entry) {
      return !!(entry && this.notesOpen[entry.id]);
    },

    toggleNotes(entry) {
      if (!entry) return;
      this.notesOpen = { ...this.notesOpen, [entry.id]: !this.notesOpen[entry.id] };
    },

    async saveNotes(entry) {
      if (!entry) return;
      try {
        const r = await fetch(`/api/entries/${entry.id}`, {
          method: 'PATCH',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ notes: entry.notes || '' }),
        });
        if (!r.ok) throw new Error(await r.text());
      } catch (e) { this.error = `Save notes failed: ${e}`; }
    },

    // ---- Manual entry form ----------------------------------------------
    openManualForm() {
      this.manualFormOpen = true;
      this.manualEntry = { label: '', category: '', impact: 'medium', notes: '', daily: ['', '', '', '', '', '', ''] };
    },

    cancelManualForm() {
      this.manualFormOpen = false;
    },

    async saveManualEntry() {
      const label = (this.manualEntry.label || '').trim();
      if (!label) {
        this.error = 'Enter a label for the manual entry.';
        return;
      }
      // Build daily_hours from the per-column inputs (column index → ISO day).
      const daily = {};
      let total = 0;
      for (let i = 0; i < 7; i++) {
        const raw = this.manualEntry.daily[i];
        if (raw === '' || raw === null || raw === undefined) continue;
        const num = Number(raw);
        if (!Number.isFinite(num) || num <= 0) continue;
        daily[this.dayIso(i)] = num;
        total += num;
      }
      if (total <= 0) {
        this.error = 'Enter at least one day with > 0 hours.';
        return;
      }
      this.manualSaving = true;
      this.error = null;
      try {
        const r = await fetch('/api/entries', {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            label,
            category: (this.manualEntry.category || '').trim() || null,
            week_of: this.briefing?.week_start || this.weekStartIso(this.weekOffset),
            daily_hours: daily,
            impact: this.manualEntry.impact || 'medium',
            notes: this.manualEntry.notes || '',
          }),
        });
        if (!r.ok) throw new Error(await r.text());
        const created = await r.json();
        // Splice into the current briefing so the table reflects the
        // change immediately without a full rescan.
        if (this.briefing) {
          this.briefing.entries = [...(this.briefing.entries || []), created];
          // Roll up totals naively — Total is the only one we can compute
          // without re-deriving meetings/focus/collab buckets. Manual
          // entries lack source attribution, so we just bump the total.
          if (this.briefing.totals) {
            this.briefing.totals.total_hours = Number(
              ((this.briefing.totals.total_hours || 0) + (created.duration_hours || 0)).toFixed(2),
            );
          }
        }
        // Expand the category bucket the new entry landed in so the user
        // can see it without hunting for the chevron.
        const cat = created.category || 'Uncategorized';
        this.expanded = { ...this.expanded, [cat]: true };
        this.manualFormOpen = false;
      } catch (e) {
        this.error = `Save manual entry failed: ${e}`;
      } finally {
        this.manualSaving = false;
      }
    },

    async deleteEntry(entry) {
      try {
        await fetch(`/api/entries/${entry.id}`, { method: 'DELETE' });
        this.briefing.entries = this.briefing.entries.filter(e => e.id !== entry.id);
      } catch (e) { this.error = String(e); }
    },

    async deleteCategory(group) {
      if (!group || !group.entries || !group.entries.length) return;
      const count = group.entries.length;
      const label = group.category || 'Uncategorized';
      const msg = `Delete all ${count} ${count === 1 ? 'entry' : 'entries'} in "${label}"? This cannot be undone.`;
      if (!window.confirm(msg)) return;
      this.deletingCategory = group.category;
      this.error = null;
      try {
        const ids = group.entries.map(e => e.id);
        const results = await Promise.allSettled(
          ids.map(id => fetch(`/api/entries/${id}`, { method: 'DELETE' }))
        );
        const failed = results.filter(r => r.status === 'rejected' || (r.value && !r.value.ok)).length;
        const deletedIds = new Set(
          ids.filter((_, i) => {
            const r = results[i];
            return r.status === 'fulfilled' && r.value && r.value.ok;
          })
        );
        this.briefing.entries = this.briefing.entries.filter(e => !deletedIds.has(e.id));
        if (failed) {
          this.error = `Failed to delete ${failed} of ${count} ${failed === 1 ? 'entry' : 'entries'} in "${label}".`;
        }
      } catch (e) {
        this.error = String(e);
      } finally {
        this.deletingCategory = null;
      }
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

    // ---- Scans slide-over -----------------------------------------------
    // Open the global Scans panel. Eagerly refreshes schedule + history so
    // the user sees fresh data rather than the 30s-polled snapshot.
    async openScans(tab) {
      this.scansOpen = true;
      if (tab) this.scansTab = tab;
      this.historyOpen = true;
      // Fan out: schedule is cheap, history is paged. Both are safe in
      // parallel since they hit different endpoints.
      await Promise.all([this.loadSchedule(), this.loadHistory()]);
    },

    closeScans() { this.scansOpen = false; },

    // ---- Preferences slide-over ----------------------------------------
    openPrefs(tab) {
      if (tab) this.prefsTab = tab;
      this.prefsOpen = true;
    },

    closePrefs() { this.prefsOpen = false; },

    // True when any scan-related activity is in flight. Used to draw a
    // pulsing badge on the header Scans button.
    hasActiveScan() {
      return !!(this.scanningBriefing || this.reviewScanning);
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
      if (v === 'actions' && !this._actionsLoaded && !this.actionsLoading) {
        this.loadActions();
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

    // ---- Missing weeks grouped by month --------------------------------
    // Group ``review.missing_weeks`` by their containing month so the UI
    // can collapse long lists. Returns an array sorted ascending by month
    // key (e.g. ``"2026-04"``).
    missingWeeksByMonth() {
      const weeks = this.review?.missing_weeks || [];
      const groups = new Map();
      for (const w of weeks) {
        // ``w`` is a Monday ISO date. Use its month as the bucket key.
        const monthKey = (w || '').slice(0, 7);
        if (!groups.has(monthKey)) groups.set(monthKey, []);
        groups.get(monthKey).push(w);
      }
      const out = [];
      for (const [monthKey, list] of groups.entries()) {
        if (!monthKey) continue;
        const [y, m] = monthKey.split('-').map((s) => parseInt(s, 10));
        let label = monthKey;
        try {
          label = new Date(y, (m || 1) - 1, 1).toLocaleDateString(undefined, { month: 'long', year: 'numeric' });
        } catch { /* keep YYYY-MM */ }
        out.push({ key: monthKey, label, weeks: list.sort() });
      }
      out.sort((a, b) => a.key.localeCompare(b.key));
      return out;
    },

    async scanMissingMonth(monthKey) {
      // Scan every missing week within ``monthKey`` (``YYYY-MM``).
      const group = this.missingWeeksByMonth().find((g) => g.key === monthKey);
      if (!group) return;
      this.reviewScanError = null;
      this.reviewScanning = true;
      try {
        for (const w of group.weeks) {
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

    // ---- Actions ---------------------------------------------------------
    openActionCount() {
      // Count the actions the user hasn't resolved yet. Drives the badge
      // on the Actions tab so users notice new suggestions.
      return (this.actions || []).filter(
        (a) => a.status === 'suggested' || a.status === 'accepted',
      ).length;
    },

    async loadActions() {
      this.actionsError = null;
      this.actionsLoading = true;
      try {
        const params = new URLSearchParams();
        if (this.actionsIncludeResolved) params.set('include_resolved', 'true');
        const qs = params.toString();
        const r = await fetch(`/api/actions${qs ? '?' + qs : ''}`);
        if (!r.ok) throw new Error(await r.text());
        this.actions = await r.json();
        this._actionsLoaded = true;
      } catch (e) {
        this.actionsError = `Load actions failed: ${e}`;
      } finally {
        this.actionsLoading = false;
      }
    },

    async actionTransition(id, verb) {
      // Generic helper for accept / complete / dismiss. ``verb`` maps
      // 1:1 to the API path segment.
      this.actionsError = null;
      this.actionBusy[id] = true;
      try {
        const body = verb === 'dismiss' ? JSON.stringify({}) : null;
        const r = await fetch(`/api/actions/${id}/${verb}`, {
          method: 'POST',
          headers: body ? { 'Content-Type': 'application/json' } : undefined,
          body,
        });
        if (!r.ok) throw new Error(await r.text());
        // Refresh the list rather than splicing in place — that way the
        // resolved-filter and ordering match what the server returns.
        await this.loadActions();
      } catch (e) {
        this.actionsError = `Action update failed: ${e}`;
      } finally {
        delete this.actionBusy[id];
      }
    },

    async snoozeAction(id) {
      this.actionsError = null;
      this.actionBusy[id] = true;
      try {
        // One week out — the common-case snooze. Custom durations land in
        // a later slice; keep the v0.4 UI deliberately small.
        const until = new Date(Date.now() + 7 * 24 * 60 * 60 * 1000).toISOString();
        const r = await fetch(`/api/actions/${id}/snooze`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ snoozed_until: until }),
        });
        if (!r.ok) throw new Error(await r.text());
        await this.loadActions();
      } catch (e) {
        this.actionsError = `Snooze failed: ${e}`;
      } finally {
        delete this.actionBusy[id];
      }
    },

    async draftAction(a) {
      // Generate the kind-specific artifact and deliver it.
      //
      //   follow_up      -> open ``mailto:`` in the OS default mail client
      //                     and copy the body to the clipboard as a backup
      //                     (WebView2 ``mailto:`` handling can occasionally
      //                     drop very long bodies).
      //   decision_note  -> save the Markdown via the pywebview save_file
      //                     bridge when available, otherwise download via
      //                     a Blob URL. Falls back to clipboard if both
      //                     paths fail.
      this.actionsError = null;
      this.actionBusy[a.id] = true;
      try {
        const r = await fetch(`/api/actions/${a.id}/draft`, { method: 'POST' });
        if (!r.ok) throw new Error(await r.text());
        const draft = await r.json();
        if (draft.kind === 'email') {
          try {
            await navigator.clipboard?.writeText?.(draft.body);
          } catch (_) { /* clipboard is best-effort */ }
          // Use location.href instead of window.open — WebView2 blocks
          // window.open for non-http(s) schemes by default but honours
          // navigation to ``mailto:``.
          window.location.href = draft.mailto;
          this.actionsError = null;
        } else if (draft.kind === 'markdown') {
          const filename = draft.filename || 'decision-note.md';
          if (window.pywebview?.api?.save_file) {
            await window.pywebview.api.save_file(
              filename,
              draft.body,
              ['Markdown (*.md)', 'All files (*.*)'],
            );
          } else {
            const blob = new Blob([draft.body], { type: 'text/markdown' });
            const url = URL.createObjectURL(blob);
            const link = document.createElement('a');
            link.href = url; link.download = filename;
            document.body.appendChild(link); link.click(); link.remove();
            setTimeout(() => URL.revokeObjectURL(url), 5000);
          }
        } else {
          throw new Error(`Unknown draft kind ${draft.kind}`);
        }
      } catch (e) {
        this.actionsError = `Draft failed: ${e}`;
      } finally {
        delete this.actionBusy[a.id];
      }
    },
  };
}
