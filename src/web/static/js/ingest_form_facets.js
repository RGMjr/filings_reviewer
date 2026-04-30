/**
 * /ingest/ form facet cascade.
 *
 * Listens for change events on the Industries and Year multi-selects and
 * fetches GET /api/v2/ingest/filter-options to refresh the OTHER axis's
 * counts and visibility. Each axis ignores its own selection (standard
 * facet pattern), so picking 2016 narrows industries; picking biotech
 * narrows years.
 *
 * Vanilla ES5 IIFE — no framework dependency. Loaded as a static asset
 * from src/web/templates/ingest_form.html.
 */
(function () {
  "use strict";

  var industriesEl = document.getElementById("industries");
  var yearEl = document.getElementById("year");
  if (!industriesEl || !yearEl) {
    return; // not on the ingest form page
  }

  function selectedValues(selectEl) {
    var out = [];
    var options = selectEl.options;
    for (var i = 0; i < options.length; i++) {
      if (options[i].selected) {
        out.push(options[i].value);
      }
    }
    return out;
  }

  function buildQuery(years, industries) {
    var parts = [];
    var i;
    for (i = 0; i < years.length; i++) {
      parts.push("year=" + encodeURIComponent(years[i]));
    }
    for (i = 0; i < industries.length; i++) {
      parts.push("industry=" + encodeURIComponent(industries[i]));
    }
    return parts.join("&");
  }

  /**
   * Update a select's options in place from a `[{value, label, count}]` list.
   * Selected options are kept enabled even when count == 0 so the user can
   * deselect them. Zero-count, unselected options are hidden.
   */
  function applyCounts(selectEl, items, valueKey, labelTemplate) {
    var byValue = {};
    var i;
    for (i = 0; i < items.length; i++) {
      byValue[String(items[i][valueKey])] = items[i];
    }
    var options = selectEl.options;
    for (i = 0; i < options.length; i++) {
      var opt = options[i];
      var item = byValue[opt.value];
      if (!item) {
        // Option no longer present in the response (shouldn't happen for our
        // server which always returns the same axis). Treat as count 0.
        opt.setAttribute("data-count", "0");
        opt.text = labelTemplate(opt.value, 0);
        opt.hidden = !opt.selected;
        opt.disabled = !opt.selected;
        continue;
      }
      var count = parseInt(item.count, 10) || 0;
      opt.setAttribute("data-count", String(count));
      opt.text = labelTemplate(item, count);
      // Hide zero-count options unless they're currently selected.
      opt.hidden = count === 0 && !opt.selected;
      opt.disabled = false; // never disable — keep selected toggleable
    }
  }

  function refresh() {
    var years = selectedValues(yearEl);
    var industries = selectedValues(industriesEl);
    var qs = buildQuery(years, industries);
    fetch("/api/v2/ingest/filter-options" + (qs ? "?" + qs : ""), {
      credentials: "same-origin",
    })
      .then(function (r) {
        if (!r.ok) {
          throw new Error("HTTP " + r.status);
        }
        return r.json();
      })
      .then(function (data) {
        applyCounts(yearEl, data.years || [], "year", function (item, count) {
          var year = typeof item === "object" ? item.year : item;
          return year + " (" + count + ")";
        });
        applyCounts(industriesEl, data.industries || [], "key", function (item, count) {
          if (typeof item !== "object") {
            // Stale option not in response — keep its current label minus count
            return String(item);
          }
          return item.label + " (" + count + ")";
        });
      })
      .catch(function (err) {
        // Non-fatal — leave the form in its current state.
        if (window.console && window.console.warn) {
          window.console.warn("filter-options fetch failed:", err);
        }
      });
  }

  industriesEl.addEventListener("change", refresh);
  yearEl.addEventListener("change", refresh);
})();
