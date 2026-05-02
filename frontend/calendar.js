// FullCalendar wrapper — type/course filters and event detail modal.

import { courses } from './state.js';
import { escapeHtml, expandAssessments, getCourseColors, addDays } from './utils.js';

const calendarSectionEl = document.getElementById('calendar-section');
const calendarHostEl    = document.getElementById('calendar');
const filterGroupEl     = document.getElementById('course-filter-group');
const filterPillsEl     = document.getElementById('course-filter-pills');
const modalEl           = document.getElementById('event-modal');
const modalCloseEl      = document.getElementById('modal-close');
const modalOverlayEl    = document.getElementById('modal-overlay');

let calendarInstance = null;

const filterState = {
  types: new Set(['assessment', 'week']),
  courses: new Set(),
};

function applyFilters() {
  if (!calendarInstance) return;
  calendarInstance.getEvents().forEach(e => {
    const typeOk   = filterState.types.has(e.extendedProps.type);
    const courseOk = filterState.courses.has(e.extendedProps.courseIndex);
    e.setProp('display', typeOk && courseOk ? 'auto' : 'none');
  });
}

function buildCourseEvents(course, courseIdx) {
  const colors   = getCourseColors(courseIdx);
  const expanded = expandAssessments(course.assessments || []);

  const weightStr = w => (w == null ? '?' : w);

  return [
    ...expanded
      .filter(a => a.date || a.start)
      .map(a => {
        // FullCalendar uses exclusive ends on all-day events
        const dateProps = a.date
          ? { date: a.date }
          : { start: a.start, end: a.end ? addDays(a.end, 1) : undefined };

        return {
          title: a.title,
          ...dateProps,
          backgroundColor: colors.assessment,
          borderColor: colors.assessment,
          extendedProps: {
            type: 'assessment',
            description: a._parentTitle
              ? `${a._parentTitle} (${a._expandedIndex}/${a._expandedTotal}) — Worth ${weightStr(a._expandedWeight)}% each`
              : `Worth ${weightStr(a.weight_percent)}%`,
            time: a.time || null,
            courseIndex: courseIdx,
          },
        };
      }),
    ...(course.schedule || []).map(s => ({
      title: `Week ${s.week}: ${s.topic}`,
      start: s.start,
      end: s.end ? addDays(s.end, 1) : undefined,
      backgroundColor: colors.week,
      borderColor: colors.week,
      extendedProps: { type: 'week', description: s.topic, courseIndex: courseIdx },
    })),
  ];
}

export function rebuildCourseFilters() {
  if (!filterGroupEl || !filterPillsEl) return;
  filterPillsEl.innerHTML = '';

  courses.forEach((course, i) => {
    filterState.courses.add(i);
    const colors = getCourseColors(i);
    const label  = course.course_code || course.course_title || `Course ${i + 1}`;

    const btn = document.createElement('button');
    btn.className = 'filter-pill course-pill active';
    btn.dataset.courseIndex = i;
    btn.innerHTML = `<span class="pill-dot" style="background:${colors.assessment}"></span>${escapeHtml(label)}`;

    btn.addEventListener('click', () => {
      if (filterState.courses.has(i)) {
        filterState.courses.delete(i);
        btn.classList.remove('active');
      } else {
        filterState.courses.add(i);
        btn.classList.add('active');
      }
      applyFilters();
    });

    filterPillsEl.appendChild(btn);
  });

  if (courses.length > 1) {
    filterGroupEl.classList.add('show');
  } else {
    filterGroupEl.classList.remove('show');
  }
}

export function showCalendarSection() {
  calendarSectionEl.classList.add('show');
}

export function isCalendarInitialized() {
  return calendarInstance !== null;
}

export function initCalendar() {
  calendarInstance = new FullCalendar.Calendar(calendarHostEl, {
    initialView: 'dayGridMonth',
    height: 'auto',
    events: courses.flatMap((course, i) => buildCourseEvents(course, i)),
    eventClick: function(info) {
      const e        = info.event;
      const start    = e.startStr;
      const end      = e.endStr;
      const dateText = end && end !== start ? `${start} to ${end}` : start;

      document.getElementById('modal-type').textContent = e.extendedProps.type;
      document.getElementById('modal-title').textContent = e.title;
      document.getElementById('modal-date').textContent = dateText;
      document.getElementById('modal-description').textContent = e.extendedProps.time
        ? `${e.extendedProps.description} - Due at ${e.extendedProps.time}`
        : e.extendedProps.description;
      modalEl.classList.add('show');
    },
  });
  calendarInstance.render();
}

export function refreshCalendarEvents() {
  if (!calendarInstance) return;
  calendarInstance.getEvents().forEach(e => e.remove());
  courses.forEach((course, i) => {
    buildCourseEvents(course, i).forEach(event => calendarInstance.addEvent(event));
  });
  applyFilters();
}

document.querySelectorAll('.type-pill').forEach(btn => {
  btn.addEventListener('click', () => {
    const type = btn.dataset.value;
    if (filterState.types.has(type)) {
      filterState.types.delete(type);
      btn.classList.remove('active');
    } else {
      filterState.types.add(type);
      btn.classList.add('active');
    }
    applyFilters();
  });
});

modalCloseEl.addEventListener('click', () => modalEl.classList.remove('show'));
modalOverlayEl.addEventListener('click', () => modalEl.classList.remove('show'));