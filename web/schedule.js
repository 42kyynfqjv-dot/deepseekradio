/* ══ THE FREQUENCY · shared schedule (station time = America/New_York) ══
 * One source of truth for the lineup, used by every page. SCHEDULE is the
 * everyday base; TAKEOVERS are day-gated blocks (live sports, election night,
 * …) that pre-empt the base on their days. To add a takeover, append one entry
 * to TAKEOVERS — it slots into the grid and the now/next readout automatically.
 * Mirrors src/schedule.yaml (day-gated blocks win their window on their days).
 *
 * Date-specific pre-empts (playoff Game 7, Election Night, a blizzard) arrive
 * as DATA: F.loadTakeovers() fetches /data/takeovers.json (no-store) and concats
 * date-keyed rows ({date:"YYYY-MM-DD", ...} instead of {days:[...]}) into
 * TAKEOVERS. A new event needs no code edit and no ?v bump — only this one-time
 * date-branch diff does.
 *
 * CACHE: Cloudflare caches this file ~4h. After editing it, bump the ?v=N on
 * the <script src="/schedule.js?v=N"> include in every HTML page (the pages
 * are served uncached, so the new version propagates immediately).
 */
(function (root) {
  var F = {};

  // everyday base lineup — index order is load-bearing (cast .when data-slot).
  F.SCHEDULE = [
    {start:6,  end:10, name:"The Morning Scramble",     hook:"Studio Court is in session. Alliances shift by the segment.",              who:"ROZ · PEACH · WESLEY"},
    {start:10, end:13, name:"Refined Palate",           hook:"Today's subject: a doorknob. The rating: argued to the death, out of seven moons.", who:"SIR REGINALD · COSIMA"},
    {start:13, end:16, name:"The Complaints Department", hook:"Your grievance, escalated to someone who does not exist.",                 who:"EMPLOYEE OF THE DAY"},
    {start:16, end:19, name:"The Handover",             hook:"Forty years of real radio trains its replacement. Live. Against its will.", who:"HANK · KAI"},
    {start:19, end:22, name:"Culture Vulture",          hook:"Earnest interviews with impossible people.",                                who:"COSIMA + TONIGHT'S GUEST"},
    {start:22, end:25, name:"The Night Shift",          hook:"Dream Court is in session. Verdicts are final.",                            who:"VIVIAN NIGHTSHADE"},
    {start:1,  end:5,  name:"The Static Hour",          hook:"Tonight's Theory, your calls, and The Numbers. The numbers will be read.",  who:"THE WATCHER"},
    {start:5,  end:6,  name:"Dawn Patrol",              hook:"One quiet hour. One quote. No bit.",                                        who:"DAWN"},
  ];

  // day-gated takeovers — pre-empt the base lineup on their days/windows.
  // `days` are full weekday names in station time.
  F.TAKEOVERS = [
    {start:20, end:23, days:["Wednesday","Saturday"], name:"Center Ice",
     hook:"Live hockey from a league that shouldn't exist. Absurd teams, real urgency.",
     who:"BUCKY · SAL"},
  ];

  var STATION_TZ = "America/New_York";
  function parts() {
    return new Intl.DateTimeFormat("en-US", {timeZone: STATION_TZ,
      weekday: "long", hour: "numeric", minute: "numeric", hour12: false})
      .formatToParts(new Date());
  }
  function get(p, t) { return p.find(function (x) { return x.type === t; }).value; }
  F.stationHM = function () {
    var p = parts();
    return (parseInt(get(p, "hour"), 10) % 24) * 60 + parseInt(get(p, "minute"), 10);
  };
  F.stationHour = function () { return Math.floor(F.stationHM() / 60); };
  F.stationDay = function () { return get(parts(), "weekday"); };

  // station-time ISO date. NEVER new Date().toISOString(): that is UTC and, at
  // 19:00-23:59 ET, already reports TOMORROW — mis-gating an evening takeover.
  // en-CA renders YYYY-MM-DD; STATION_TZ matches parts()/stationDay above so
  // this stays on station time like every other helper here.
  F.todayISO = function () {
    return new Intl.DateTimeFormat("en-CA", {timeZone: STATION_TZ,
      year: "numeric", month: "2-digit", day: "2-digit"}).format(new Date());
  };

  // is takeover t live on `day`? weekday-keyed rows gate on `days`; date-keyed
  // rows (from the feed) gate on `date === today`. Guards every `t.days` access
  // so a date-keyed row (t.days === undefined) never throws and blanks the grid.
  function onDay(t, day) {
    return t.days ? t.days.indexOf(day) !== -1 : t.date === F.todayISO();
  }
  F.onDay = onDay;

  // is hour h inside slot s (handles windows that wrap past midnight, end > 24)
  F.inWin = function (h, s) {
    return s.end > 24 ? (h >= s.start || h < s.end - 24)
                      : (h >= s.start && h < s.end);
  };

  // the takeover live on `day` at hour `h`, or null
  F.activeTakeover = function (day, h) {
    for (var i = 0; i < F.TAKEOVERS.length; i++) {
      var t = F.TAKEOVERS[i];
      if (onDay(t, day) && F.inWin(h, t)) return t;
    }
    return null;
  };

  // the effective show on the air for `day`/`h` (takeover wins over base)
  F.currentShow = function (day, h) {
    var t = F.activeTakeover(day, h);
    if (t) return t;
    for (var i = 0; i < F.SCHEDULE.length; i++) {
      if (F.inWin(h, F.SCHEDULE[i])) return F.SCHEDULE[i];
    }
    return F.SCHEDULE[0];
  };

  // the effective lineup for `day`: base blocks with takeovers spliced in
  // place (a base block overlapping a takeover is trimmed/split around it).
  // Takeovers are same-day (non-wrapping); base blocks may wrap past midnight
  // (end > 24) — for those only the pre-midnight segment [start,24) can be hit.
  F.effective = function (day) {
    function clone(o) { var c = {}; for (var k in o) c[k] = o[k]; return c; }
    var blocks = F.SCHEDULE.map(clone);
    F.TAKEOVERS.forEach(function (t) {
      if (!onDay(t, day)) return;
      var out = [], inserted = false;
      function pushTakeover() {
        if (!inserted) { var tk = clone(t); tk._takeover = true; out.push(tk); inserted = true; }
      }
      blocks.forEach(function (b) {
        var segEnd = b.end > 24 ? 24 : b.end;          // pre-midnight extent
        if (!(b.start < t.end && t.start < segEnd)) { out.push(b); return; }
        if (b.start < t.start) { var pre = clone(b); pre.end = t.start; out.push(pre); }
        pushTakeover();
        if (b.end > t.end) { var post = clone(b); post.start = t.end; out.push(post); }
      });
      pushTakeover();   // takeover on a day with no overlapping base block
      blocks = out;
    });
    return blocks;
  };

  // fetch the dynamic feed and concat date-keyed rows into TAKEOVERS, dropping
  // past ones so a stale feed can't resurrect a finished event. Feed down ->
  // the evergreen lineup still renders (the catch is a no-op). Callers pass a
  // re-render callback (the page owns render()).
  F.loadTakeovers = function (onLoaded) {
    fetch("/data/takeovers.json", {cache: "no-store"}).then(function (r) { return r.json(); })
      .then(function (j) {
        var today = F.todayISO();
        F.TAKEOVERS = F.TAKEOVERS.concat(
          (j.takeovers || []).filter(function (t) { return t.date >= today; }));
        if (typeof onLoaded === "function") onLoaded();
      })
      .catch(function () {});
  };

  root.FREQ = F;
})(typeof window !== "undefined" ? window : globalThis);
