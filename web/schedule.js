/* ══ THE FREQUENCY · shared schedule (station time = America/New_York) ══
 * One source of truth for the lineup, used by every page. SCHEDULE is the
 * everyday base; TAKEOVERS are day-gated blocks (live sports, election night,
 * …) that pre-empt the base on their days. To add a takeover, append one entry
 * to TAKEOVERS — it slots into the grid and the now/next readout automatically.
 * Mirrors src/schedule.yaml (day-gated blocks win their window on their days).
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

  // is hour h inside slot s (handles windows that wrap past midnight, end > 24)
  F.inWin = function (h, s) {
    return s.end > 24 ? (h >= s.start || h < s.end - 24)
                      : (h >= s.start && h < s.end);
  };

  // the takeover live on `day` at hour `h`, or null
  F.activeTakeover = function (day, h) {
    for (var i = 0; i < F.TAKEOVERS.length; i++) {
      var t = F.TAKEOVERS[i];
      if (t.days.indexOf(day) !== -1 && F.inWin(h, t)) return t;
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
      if (t.days.indexOf(day) === -1) return;
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

  root.FREQ = F;
})(typeof window !== "undefined" ? window : globalThis);
