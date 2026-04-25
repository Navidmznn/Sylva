/* ═══════════════════════════════════════════════════════════════════════════
   UTILS — cross-cutting helpers used by multiple modules
═══════════════════════════════════════════════════════════════════════════ */

// HTML-escape any string before innerHTML interpolation. Used at every render
// site that builds markup with template literals; LLM-derived strings (course
// titles, instructor names, etc.) are untrusted and must pass through this.
export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// Per-course color generation using golden-angle HSL rotation.
// Two adjacent courses always get visually distinct hues regardless of count.
export function getCourseColors(index) {
  const hue = Math.round((index * 137.508) % 360);
  return {
    assessment: `hsl(${hue}, 55%, 55%)`,
    week: `hsl(${hue}, 35%, 65%)`,
  };
}

// Multi-date assessment expander.
// Assessments with a `dates` array are logically one item (one pie slice, one
// weight entry) but need to appear as individual occurrences on the calendar,
// in the assessment list, and in the grade calculator.
//
// Returns a flat array where every multi-date assessment is replaced by N
// copies, each carrying:
//   _expandedIndex   – 1-based position label  ("Tutorial 1", "Tutorial 2", …)
//   _expandedTotal   – total sibling count      (used for labelling)
//   _expandedWeight  – weight_percent / N       (for grade-calc purposes)
//   _parentTitle     – original assessment title (for grouping)
//
// Single-date and range assessments are passed through unchanged (their
// _expandedIndex stays undefined so callers can detect un-expanded items).
export function expandAssessments(assessments) {
  const out = [];
  for (const a of assessments) {
    if (a.dates && a.dates.length > 1) {
      const n = a.dates.length;
      const perWeight = a.weight_percent != null
        ? Math.round((a.weight_percent / n) * 100) / 100
        : null;
      a.dates.forEach((d, i) => {
        out.push({
          ...a,
          title: `${a.title} ${i + 1}`,
          date: d,
          dates: null,           // treat as single-date from here on
          weight_percent: perWeight,
          _parentTitle: a.title,
          _expandedIndex: i + 1,
          _expandedTotal: n,
          _expandedWeight: perWeight,
        });
      });
    } else {
      out.push(a);
    }
  }
  return out;
}