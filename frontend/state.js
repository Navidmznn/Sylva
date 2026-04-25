/* ═══════════════════════════════════════════════════════════════════════════
   STATE — shared across all modules
   ═══════════════════════════════════════════════════════════════════════════
   `courses` is the canonical list of every parsed syllabus. Mutated only via
   `addCourses` from the upload handler in app.js. All other modules read it.
   Intentionally small: per-module state (calendar instance, filter selections,
   grade-calc UI selections) lives inside the module that owns it.
═══════════════════════════════════════════════════════════════════════════ */

export const courses = [];

export function addCourses(newCourses) {
  courses.push(...newCourses);
}