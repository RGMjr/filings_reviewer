/**
 * /ingest/ form 3-axis facet cascade.
 *
 * Listens for change events on the Industries multi-select, Year
 * multi-select, and Form-type checkboxes. On each change, fetches
 * GET /api/v2/ingest/filter-options with the current selections, and
 * rewrites the OTHER two axes' option counts + visibility.
 *
 * Each axis ignores its own selection (standard facet pattern), so
 * picking 2016 narrows industries + form-types; picking biotech narrows
 * years + form-types; picking a form-type narrows years + industries.
 *
 * Vanilla ES5 IIFE — no framework dependency. Loaded as a static asset
 * from src/web/templates/ingest_form.html.
 */
(function () {
  "use strict";

  var industriesEl = document.getElementById("industries");
  var yearEl = document.getElementById("year");
  var formTypeEls = document.querySelectorAll('input[name="form_types"]');
  if (!industriesEl || !yearEl || formTypeEls.length === 0) {
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

  function selectedFormTypes() {
    var out = [];
    for (var i = 0; i < formTypeEls.length; i++) {
      if (formTypeEls[i].checked) {
        out.push(formTypeEls[i].value);
      }
    }
    return out;
  }

  function buildQuery(years, industries, formTypes) {
    var parts = [];
    var i;
    for (i = 0; i < years.length; i++) {
      parts.push("year=" + encodeURIComponent(years[i]));
    }
    for (i = 0; i < industries.length; i++) {
      parts.push("industry=" + encodeURIComponent(industries[i]));
    }
    for (i = 0; i < formTypes.length; i++) {
      parts.push("form_type=" + encodeURIComponent(formTypes[i]));
    }
    return parts.join("&");
  }

  /**
   * Update a <select>'s options in place from a `[{value, label, count}]` list.
   * Selected options stay enabled even when count == 0 so the user can
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
        opt.setAttribute("data-count", "0");
        opt.text = labelTemplate(opt.value, 0);
        opt.hidden = !opt.selected;
        opt.disabled = !opt.selected;
        continue;
      }
      var count = parseInt(item.count, 10) || 0;
      opt.setAttribute("data-count", String(count));
      opt.text = labelTemplate(item, count);
      opt.hidden = count === 0 && !opt.selected;
      opt.disabled = false;
    }
  }

  /**
   * Update form-type checkbox row counts + disabled state.
   *
   * Per UX choice: zero-count unchecked checkboxes are disabled+greyed
   * (not hidden) so the small fixed set of form-types stays visually
   * stable. Checked checkboxes always stay enabled so the user can
   * uncheck them.
   */
  function applyFormTypeCounts(items) {
    var byKey = {};
    for (var i = 0; i < items.length; i++) {
      byKey[String(items[i].key)] = items[i];
    }
    for (var j = 0; j < formTypeEls.length; j++) {
      var input = formTypeEls[j];
      var item = byKey[input.value];
      var count = item ? parseInt(item.count, 10) || 0 : 0;
      var label = input.parentNode.querySelector("label.form-check-label");
      var baseLabel = item ? item.label : (label ? label.textContent.replace(/\s*\(\d+\)\s*$/, "") : input.value);
      input.setAttribute("data-count", String(count));
      if (label) {
        label.textContent = baseLabel + " (" + count + ")";
      }
      var shouldDisable = count === 0 && !input.checked;
      input.disabled = shouldDisable;
      if (label) {
        if (shouldDisable) {
          label.classList.add("text-muted");
        } else {
          label.classList.remove("text-muted");
        }
      }
    }
  }

  function refresh() {
    var years = selectedValues(yearEl);
    var industries = selectedValues(industriesEl);
    var formTypes = selectedFormTypes();
    var qs = buildQuery(years, industries, formTypes);
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
            return String(item);
          }
          return item.label + " (" + count + ")";
        });
        applyFormTypeCounts(data.form_types || []);
      })
      .catch(function (err) {
        if (window.console && window.console.warn) {
          window.console.warn("filter-options fetch failed:", err);
        }
      });
  }

  industriesEl.addEventListener("change", refresh);
  yearEl.addEventListener("change", refresh);
  for (var k = 0; k < formTypeEls.length; k++) {
    formTypeEls[k].addEventListener("change", refresh);
  }
})();
