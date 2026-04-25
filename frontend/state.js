/* ═══════════════════════════════════════════════════════════════════════════
   STATE — shared across all modules
   ═══════════════════════════════════════════════════════════════════════════
   `courses` is the canonical list of every parsed syllabus. Mutated only via
   the helpers exported from this module. All other modules read it.
   Intentionally small: per-module state (calendar instance, filter selections,
   grade-calc UI selections) lives inside the module that owns it.

   Stable IDs
   ──────────
   Every course and every assessment is tagged with an `id` field at ingestion
   (idempotent — pre-existing IDs from localStorage are preserved). Downstream
   lookups use these IDs instead of titles, so renaming an assessment can't
   strand a flat-list row from its underlying object.

   Dedup
   ─────
   New uploads matching an existing course on (course_code, section_code,
   term) trigger the optional `onDuplicate` callback, which resolves to
   'replace' or 'skip'. Without a callback, duplicates are silently skipped.
═══════════════════════════════════════════════════════════════════════════ */

import { uid } from './utils.js';

export const courses = [];

/**
 * Ensure `course` and every assessment under it carries an `id` field.
 * Safe to call repeatedly — only assigns when missing.
 */
function tagIds(course) {
  if (!course.id) course.id = uid();
  (course.assessments || []).forEach(a => {
    if (!a.id) a.id = uid();
  });
}

/**
 * Identifies a course's "logical identity" for dedup purposes. A course only
 * collides with another when it has a non-empty course_code AND matches on
 * section_code + term. Two unnamed courses are never considered duplicates.
 */
function findDuplicateIndex(incoming) {
  if (!incoming.course_code) return -1;
  return courses.findIndex(existing =>
    existing.course_code === incoming.course_code &&
    (existing.section_code || null) === (incoming.section_code || null) &&
    (existing.term         || null) === (incoming.term         || null)
  );
}

/**
 * Add new courses to the canonical list.
 *
 * @param {Array<object>}  newCourses
 * @param {object} [opts]
 * @param {(incoming: object, existing: object) => Promise<'replace'|'skip'>} [opts.onDuplicate]
 *        Called once per duplicate detected. Resolves to 'replace' (overwrite
 *        existing entry in place) or 'skip' (drop the incoming course). When
 *        omitted, duplicates are silently skipped.
 */
export async function addCourses(newCourses, { onDuplicate } = {}) {
  for (const incoming of newCourses) {
    tagIds(incoming);
    const dupIdx = findDuplicateIndex(incoming);

    if (dupIdx === -1) {
      courses.push(incoming);
      continue;
    }

    const choice = onDuplicate
      ? await onDuplicate(incoming, courses[dupIdx])
      : 'skip';

    if (choice === 'replace') {
      // Preserve the existing course's id so any UI references survive.
      incoming.id = courses[dupIdx].id;
      courses.splice(dupIdx, 1, incoming);
    }
    // 'skip' (or anything else): drop incoming, leave existing untouched.
  }
}

/**
 * Remove a course by its index in the array. Safe no-op for out-of-range.
 */
export function removeCourse(index) {
  if (index < 0 || index >= courses.length) return;
  courses.splice(index, 1);
}