// Minimal local stand-in for the dashboard runtime used by web/landcover.html.
// It implements only what that page calls: dash.data, dash.calc, dash.colors, dash.draw.
// Data come from window.LC_DATA (web/landcover-data.js); CSV cells stay text, as in the
// dashboard. Data values are shown with textContent by the page code, never as HTML.
(function () {
  "use strict";
  var raw = window.LC_DATA || { tables: {}, sources: [] };
  var parsed = {};
  var calcs = {};
  var draws = {};

  // Rows were parsed from the CSVs at build time (values kept as text). No d3.csvParse:
  // it builds code with new Function, which the site's security policy forbids.
  function rows(id) {
    if (!(id in parsed)) {
      var t = (raw.tables || {})[id];
      if (!t) { parsed[id] = null; }
      else { var r = t.rows.slice(); r.columns = t.columns.slice(); parsed[id] = r; }
    }
    return parsed[id];
  }

  var dash = {
    // Series colours as CSS variables, so they follow the page's light and dark themes.
    colors: ["var(--lc-c0)", "var(--lc-c1)", "var(--lc-c2)", "var(--lc-c3)", "var(--lc-c4)", "var(--lc-c5)"],

    data: function (id) {
      if (Object.prototype.hasOwnProperty.call(calcs, id)) {
        var c = calcs[id];
        if (!c.done) {
          try {
            c.value = c.fn.apply(null, c.inputs.map(function (i) { return dash.data(i).data; }));
            c.status = "ok";
          } catch (e) {
            console.error("calc " + id + " failed:", e);
            c.value = null; c.status = "error";
          }
          c.done = true;
        }
        return { status: c.status, data: c.value, refreshing: false, truncated: false, meta: null };
      }
      var r = rows(id);
      if (!r) return { status: "missing", data: [], refreshing: false, truncated: false, meta: null };
      return { status: "ok", data: r, columns: r.columns, refreshing: false, truncated: false, meta: null };
    },

    calc: function (id, spec) {
      calcs[id] = { inputs: spec.inputs || [], fn: spec.fn, title: spec.title, description: spec.description, done: false };
    },

    // dash.draw(name, fn | {mount, update}) registers; dash.draw(name) redraws.
    draw: function (name, impl) {
      if (impl === undefined) { run(name); return; }
      draws[name] = typeof impl === "function" ? { update: impl } : impl;
    },

    onData: function (fn) { fn(); },
  };

  function run(name) {
    var d = draws[name];
    if (!d) return;
    document.querySelectorAll('[data-draw="' + name + '"]').forEach(function (el) {
      try {
        if (d.mount && !el.__lcMounted) { d.mount(el); el.__lcMounted = true; }
        if (d.update) d.update(el);
      } catch (e) {
        console.error("draw " + name + " failed:", e);
        el.textContent = "—";
      }
    });
  }

  function runAll() { Object.keys(draws).forEach(run); }

  window.dash = dash;
  window.lcRunAllDraws = runAll;

  // Charts are sized from their width: redraw when it changes.
  var lastWidth = 0, timer = null;
  window.addEventListener("resize", function () {
    clearTimeout(timer);
    timer = setTimeout(function () {
      var w = document.documentElement.clientWidth;
      if (w !== lastWidth) { lastWidth = w; runAll(); }
    }, 150);
  });
  document.addEventListener("DOMContentLoaded", function () { lastWidth = document.documentElement.clientWidth; });
})();
