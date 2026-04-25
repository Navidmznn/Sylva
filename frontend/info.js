/* ═══════════════════════════════════════════════════════════════════════════
   COURSE INFO — renders the course information card and its dropdown
═══════════════════════════════════════════════════════════════════════════ */

import { courses } from './state.js';
import { escapeHtml } from './utils.js';

const sectionEl  = document.getElementById('course-info-section');
const bodyEl     = document.getElementById('course-info-body');
const dropdownEl = document.getElementById('info-course-select');

export function renderCourseInfo(index) {
  const course = courses[index];
  if (!course) return;

  sectionEl.classList.add('show');

  const codeAndTitle = [course.course_code, course.course_title]
    .filter(Boolean).map(escapeHtml).join(' — ');

  const metaItems = [];
  if (course.term) {
    metaItems.push(`<span class="ci-meta-item"><span class="ci-meta-label">Term</span>${escapeHtml(course.term)}</span>`);
  }
  if (course.section_code) {
    metaItems.push(`<span class="ci-meta-item"><span class="ci-meta-label">Section</span>${escapeHtml(course.section_code)}</span>`);
  }

  const instructorRows = [];
  if (course.instructor) {
    instructorRows.push({ label: 'Instructor', value: escapeHtml(course.instructor) });
  }
  if (course.email) {
    const safe = escapeHtml(course.email);
    instructorRows.push({ label: 'Email', value: `<a href="mailto:${safe}" class="ci-link">${safe}</a>` });
  }
  if (course.office_hours) {
    instructorRows.push({ label: 'Office Hours', value: escapeHtml(course.office_hours) });
  }

  const meetings = (course.class_meetings || []).filter(
    m => m && (m.day || m.start_time || m.end_time || m.location || m.type)
  );

  let html = '';

  if (codeAndTitle || metaItems.length) {
    html += `<div class="ci-header">
      ${codeAndTitle ? `<div class="ci-course-title">${codeAndTitle}</div>` : ''}
      ${metaItems.length ? `<div class="ci-meta-row">${metaItems.join('')}</div>` : ''}
    </div>`;
  }

  if (instructorRows.length) {
    html += `<div class="ci-section">
      <div class="ci-section-title">Instructor</div>
      <div class="ci-info-grid">
        ${instructorRows.map(r => `
          <div class="ci-info-row">
            <span class="ci-info-label">${r.label}</span>
            <span class="ci-info-value">${r.value}</span>
          </div>`).join('')}
      </div>
    </div>`;
  }

  if (meetings.length) {
    html += `<div class="ci-section">
      <div class="ci-section-title">Class Meetings</div>
      <div class="ci-meetings-list">
        ${meetings.map(m => {
          const time = m.start_time && m.end_time
            ? `${escapeHtml(m.start_time)}–${escapeHtml(m.end_time)}`
            : escapeHtml(m.start_time || m.end_time || '');
          const parts = [];
          if (m.day)      parts.push(`<span class="ci-meeting-day">${escapeHtml(m.day)}</span>`);
          if (time)       parts.push(`<span class="ci-meeting-time">${time}</span>`);
          if (m.location) parts.push(`<span class="ci-meeting-location">${escapeHtml(m.location)}</span>`);
          return `<div class="ci-meeting-row">
            <div class="ci-meeting-main">${parts.join('')}</div>
            ${m.type ? `<span class="ci-meeting-type">${escapeHtml(m.type)}</span>` : ''}
          </div>`;
        }).join('')}
      </div>
    </div>`;
  }

  if (!html) {
    html = '<div class="ci-empty">No course information was extracted from this syllabus.</div>';
  }

  bodyEl.innerHTML = html;
}

export function updateInfoDropdown() {
  if (courses.length <= 1) {
    dropdownEl.classList.remove('show');
    return;
  }
  dropdownEl.classList.add('show');
  dropdownEl.innerHTML = '';
  courses.forEach((course, i) => {
    const opt = document.createElement('option');
    opt.value = i;
    opt.textContent = `${course.course_code || ''} ${course.course_title || ''}`.trim() || `Course ${i + 1}`;
    dropdownEl.appendChild(opt);
  });
  dropdownEl.value = courses.length - 1;
}

// ── Static listeners ────────────────────────────────────────────────────────
dropdownEl.addEventListener('change', e => {
  renderCourseInfo(parseInt(e.target.value));
});