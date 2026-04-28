// Shared state — `courses` is the canonical list of every parsed syllabus.
// Mutated only via the helpers exported here; all other modules read it.
// Per-module state (calendar instance, filter selections, grade-calc
// selections) lives inside the module that owns it.
//
// Every course and every assessment carries a stable `id` field assigned
// at ingestion. Downstream lookups use ids, not titles, so renaming an
// assessment can't strand a flat-list row from its underlying object.

import { uid } from './utils.js';

export const courses = [];

// Tag missing ids on a course and its assessments. Idempotent.
function tagIds(course) {
  if (!course.id) course.id = uid();
  (course.assessments || []).forEach(a => {
    if (!a.id) a.id = uid();
  });
}

// Dedup key: same course_code AND same section_code AND same term. Two
// unnamed courses are never considered duplicates.
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
 *        Called once per detected duplicate. Resolves to 'replace' (overwrite
 *        in place) or 'skip' (drop incoming). When omitted, duplicates are
 *        silently skipped.
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
      // Preserve the existing id so any UI references survive.
      incoming.id = courses[dupIdx].id;
      courses.splice(dupIdx, 1, incoming);
    }
  }
}

export function removeCourse(index) {
  if (index < 0 || index >= courses.length) return;
  courses.splice(index, 1);
}