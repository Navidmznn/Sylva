// Shared course list. Every course and assessment gets a stable `id` so
// lookups survive renames.

import { uid } from './utils.js';

export const courses = [];

function tagIds(course) {
  if (!course.id) course.id = uid();
  (course.assessments || []).forEach(a => {
    if (!a.id) a.id = uid();
  });
}

// dedup key — code + section + term
function findDuplicateIndex(incoming) {
  if (!incoming.course_code) return -1;
  return courses.findIndex(existing =>
    existing.course_code === incoming.course_code &&
    (existing.section_code || null) === (incoming.section_code || null) &&
    (existing.term         || null) === (incoming.term         || null)
  );
}

// onDuplicate resolves to 'replace' or 'skip'; defaults to skip
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
      // keep the old id so UI references still resolve
      incoming.id = courses[dupIdx].id;
      courses.splice(dupIdx, 1, incoming);
    }
  }
}

export function removeCourse(index) {
  if (index < 0 || index >= courses.length) return;
  courses.splice(index, 1);
}