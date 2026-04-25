/* ═══════════════════════════════════════════════════════════════════════════
   ASSESSMENTS — sorted assessment list with per-row edit + calendar export
   (Google / Outlook / Apple). Owns the click flows for those buttons.
═══════════════════════════════════════════════════════════════════════════ */

import { courses } from './state.js';
import { escapeHtml, expandAssessments, getCourseColors } from './utils.js';

const sectionEl = document.getElementById('assessment-section');
const listEl    = document.querySelector('.assessment-list');
const toggleEl  = document.getElementById('hide-past-toggle');

const CLIENT_ID = '527779540782-69q8f06ust49om49b9g36cknv1pes405.apps.googleusercontent.com';
const SCOPES    = 'https://www.googleapis.com/auth/calendar.events';

// Closure ref so the hide-past toggle can re-render from the same flat list.
let _buildAssessmentRows = null;

// Flat-list index of the row currently open for editing; null = none.
let _editingIndex = null;

// ── Date helpers ─────────────────────────────────────────────────────────────

function getAssessmentDate(a) {
  const raw = a.date || a.start || (a.dates && a.dates[0]) || null;
  return raw ? new Date(raw) : null;
}

function formatDisplayDate(a) {
  const raw = a.date || a.start || (a.dates && a.dates[0]) || null;
  if (!raw) return 'No date';
  const d = new Date(raw);
  return d.toLocaleDateString('en-CA', { year: 'numeric', month: 'short', day: 'numeric' });
}

// ── Flat assessment builder ───────────────────────────────────────────────────
// Annotates every expanded item with _courseIdx, _courseLabel, and _originalIdx
// so that commitEdit() can write back to courses[courseIdx].assessments[originalIdx].
//
// Non-expanded items are pushed as their original object reference by
// expandAssessments(), so indexOf() finds them reliably.
// Expanded multi-date items carry _parentTitle which identifies the parent.

function buildFlatAssessments() {
  return courses.flatMap((course, courseIdx) => {
    const originals = course.assessments || [];
    return expandAssessments(originals).map(a => {
      const originalIdx = a._parentTitle !== undefined
        ? originals.findIndex(o => o.title === a._parentTitle)
        : originals.indexOf(a);
      return {
        ...a,
        _courseLabel: course.course_code || course.course_title || `Course ${courseIdx + 1}`,
        _courseIdx:   courseIdx,
        _originalIdx: originalIdx,
      };
    });
  }).sort((a, b) => {
    const da = getAssessmentDate(a);
    const db = getAssessmentDate(b);
    if (!da && !db) return 0;
    if (!da) return 1;
    if (!db) return -1;
    return da - db;
  });
}

// ── Commit edit to state ──────────────────────────────────────────────────────

function commitEdit(i, flatAssessments) {
  const a   = flatAssessments[i];
  const row = listEl.querySelector(`.assessment-row[data-index="${i}"]`);
  if (!row) return;

  const original = courses[a._courseIdx]?.assessments?.[a._originalIdx];
  if (!original) {
    console.error('[Assessments] Cannot resolve original assessment — index lost.');
    return;
  }

  const isExpanded = a._parentTitle !== undefined;

  // ── Title ────────────────────────────────────────────────────────────────
  const newTitle = row.querySelector('.edit-title-input')?.value.trim();
  if (newTitle) original.title = newTitle;

  // ── Weight ───────────────────────────────────────────────────────────────
  // The edit input shows per-occurrence weight for expanded items.
  // We store total weight on the original, so multiply back.
  const rawWeight = row.querySelector('.edit-weight-input')?.value;
  const newWeight = parseFloat(rawWeight);
  if (!isNaN(newWeight) && newWeight >= 0) {
    original.weight_percent = isExpanded
      ? Math.round(newWeight * a._expandedTotal * 100) / 100
      : newWeight;
  }

  // ── Date ─────────────────────────────────────────────────────────────────
  const newDate    = row.querySelector('.edit-date-input')?.value    || '';
  const newEndDate = row.querySelector('.edit-end-date-input')?.value || '';

  if (newDate) {
    if (isExpanded) {
      // Write back into the specific slot of the parent's dates array.
      if (!Array.isArray(original.dates)) original.dates = [];
      original.dates[(a._expandedIndex ?? 1) - 1] = newDate;
    } else if (original.start !== null && original.start !== undefined) {
      original.start = newDate;
      if (newEndDate) original.end = newEndDate;
    } else {
      original.date = newDate;
    }
  }

  _editingIndex = null;

  // Notify app.js: persist to localStorage + re-render affected views.
  window.dispatchEvent(new CustomEvent('syllabusapp:assessmentupdated'));
}

// ── SVG icon strings ─────────────────────────────────────────────────────────

const ICON_PENCIL = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
  <path d="M11 4H4a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h14a2 2 0 0 0 2-2v-7"/>
  <path d="M18.5 2.5a2.121 2.121 0 0 1 3 3L12 15l-4 1 1-4 9.5-9.5z"/>
</svg>`;

const ICON_CHECK = `<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round">
  <polyline points="20 6 9 17 4 12"/>
</svg>`;

// ── Row renderers ─────────────────────────────────────────────────────────────

function renderNormalRow(a, i, today, hidePast) {
  const d    = getAssessmentDate(a);
  const past = d && d < today;
  if (past && hidePast) return '';

  const weight = a.weight_percent != null ? `${a.weight_percent}%` : '';
  const colors = getCourseColors(a._courseIdx);

  return `
    <div class="assessment-row ${past ? 'is-past' : ''}" data-index="${i}">
      <div class="past-badge">Done</div>
      <div class="assessment-title">${escapeHtml(a.title || 'Untitled')}</div>
      <div class="assessment-meta">
        <span class="assessment-date">${formatDisplayDate(a)}</span>
        ${weight ? `<span class="assessment-weight">${weight}</span>` : ''}
        ${courses.length > 1
          ? `<span class="assessment-course-tag"
               style="background:${colors.assessment}15;border-color:${colors.assessment};color:${colors.assessment}">
               ${escapeHtml(a._courseLabel)}
             </span>`
          : ''}
      </div>
      <div class="cal-buttons">
        <button class="edit-btn" data-index="${i}" aria-label="Edit assessment">
          ${ICON_PENCIL}<span>Edit</span>
        </button>
        ${calBtn('google', a)}
        ${calBtn('outlook', a)}
        ${calBtn('apple', a)}
      </div>
    </div>
  `;
}

function renderEditRow(a, i) {
  const isExpanded = a._parentTitle !== undefined;

  // For a range assessment, show separate start/end date inputs.
  const hasRange   = !isExpanded && !a.date && a.start;
  const dateVal    = a.date || a.start || '';
  const endVal     = a.end  || '';

  // Show per-occurrence weight; save handler will multiply back to total.
  const weightVal  = a.weight_percent != null ? a.weight_percent : '';
  const editTitle  = isExpanded ? (a._parentTitle || '') : (a.title || '');

  const weightLabel = isExpanded
    ? `Weight per occurrence (${a._expandedTotal} total)`
    : 'Weight %';

  return `
    <div class="assessment-row is-editing" data-index="${i}">
      ${isExpanded
        ? `<div class="edit-series-note">
             Editing series — title &amp; weight changes apply to all ${a._expandedTotal} occurrences
           </div>`
        : ''}
      <div class="edit-fields">

        <div class="edit-field-group edit-field-title">
          <label class="edit-label">Title</label>
          <input
            class="edit-input edit-title-input"
            type="text"
            value="${escapeHtml(editTitle)}"
            placeholder="Assessment title"
          />
        </div>

        <div class="edit-field-group">
          <label class="edit-label">${escapeHtml(weightLabel)}</label>
          <div class="edit-weight-wrap">
            <input
              class="edit-input edit-weight-input"
              type="number"
              min="0"
              max="100"
              step="0.1"
              value="${weightVal}"
              placeholder="0"
            />
            <span class="edit-weight-unit">%</span>
          </div>
        </div>

        <div class="edit-field-group">
          <label class="edit-label">${hasRange ? 'Start Date' : 'Date'}</label>
          <input class="edit-input edit-date-input" type="date" value="${dateVal}" />
        </div>

        ${hasRange ? `
        <div class="edit-field-group">
          <label class="edit-label">End Date</label>
          <input class="edit-input edit-end-date-input" type="date" value="${endVal}" />
        </div>` : ''}

      </div>
      <div class="edit-actions">
        <button class="edit-save-btn" data-index="${i}">
          ${ICON_CHECK} Save
        </button>
        <button class="edit-cancel-btn" data-index="${i}">Cancel</button>
      </div>
    </div>
  `;
}

// ── Main export ───────────────────────────────────────────────────────────────

export function renderAssessmentList() {
  const flatAssessments = buildFlatAssessments();
  const today = new Date();
  today.setHours(0, 0, 0, 0);

  sectionEl.classList.add('show');

  _buildAssessmentRows = function buildRows() {
    const hidePast = toggleEl.checked;

    listEl.innerHTML = flatAssessments.map((a, i) =>
      i === _editingIndex
        ? renderEditRow(a, i)
        : renderNormalRow(a, i, today, hidePast)
    ).join('');

    // ── Normal row listeners ────────────────────────────────────────────────
    listEl.querySelectorAll('.assessment-row:not(.is-editing)').forEach(row => {
      const i = parseInt(row.dataset.index);
      const a = flatAssessments[i];

      // Edit button — opens edit mode; any existing open edit is discarded.
      row.querySelector('.edit-btn')
        ?.addEventListener('click', () => {
          _editingIndex = i;
          _buildAssessmentRows();
        });

      row.querySelector('.cal-btn[data-provider="google"]')
        ?.addEventListener('click', () => addToGoogleCalendar(a));

      ['outlook', 'apple'].forEach(p => {
        row.querySelector(`.cal-btn[data-provider="${p}"]`)
          ?.addEventListener('click', () => addToCalendar(p, a));
      });
    });

    // ── Edit row listeners ──────────────────────────────────────────────────
    listEl.querySelectorAll('.assessment-row.is-editing').forEach(row => {
      const i = parseInt(row.dataset.index);

      row.querySelector('.edit-save-btn')
        ?.addEventListener('click', () => commitEdit(i, flatAssessments));

      row.querySelector('.edit-cancel-btn')
        ?.addEventListener('click', () => {
          _editingIndex = null;
          _buildAssessmentRows();
        });

      // Keyboard shortcuts inside any edit input.
      row.querySelectorAll('.edit-input').forEach(input => {
        input.addEventListener('keydown', e => {
          if (e.key === 'Enter')  commitEdit(i, flatAssessments);
          if (e.key === 'Escape') {
            _editingIndex = null;
            _buildAssessmentRows();
          }
        });
      });
    });
  };

  _buildAssessmentRows();
}

// ── Calendar helpers (unchanged) ──────────────────────────────────────────────

function calBtn(provider, assessment) {
  const icons = {
    google:  `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M21.35 11.1h-9.17v2.73h6.51c-.33 3.81-3.5 5.44-6.5 5.44C8.36 19.27 5 16.25 5 12c0-4.1 3.2-7.27 7.2-7.27 3.09 0 4.9 1.97 4.9 1.97L19 4.72S16.56 2 12.1 2C6.42 2 2.03 6.8 2.03 12c0 5.05 4.13 10 10.22 10 5.33 0 9.98-3.64 9.98-9.58 0-.56-.04-1.23-.18-1.32z"/></svg>`,
    outlook: `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M7 6h10a2 2 0 012 2v8a2 2 0 01-2 2H7a2 2 0 01-2-2V8a2 2 0 012-2zm0 2v1.5l5 3 5-3V8H7zm0 3.5V16h10v-4.5l-5 3-5-3z"/></svg>`,
    apple:   `<svg width="14" height="14" viewBox="0 0 24 24" fill="currentColor"><path d="M18.71 19.5c-.83 1.24-1.71 2.45-3.05 2.47-1.34.03-1.77-.79-3.29-.79-1.53 0-2 .77-3.27.82-1.31.05-2.3-1.32-3.14-2.53C4.25 17 2.94 12.45 4.7 9.39c.87-1.52 2.43-2.48 4.12-2.51 1.28-.02 2.5.87 3.29.87.78 0 2.26-1.07 3.8-.91.65.03 2.47.26 3.64 1.98-.09.06-2.17 1.28-2.15 3.81.03 3.02 2.65 4.03 2.68 4.04-.03.07-.42 1.44-1.38 2.83M13 3.5c.73-.83 1.94-1.46 2.94-1.5.13 1.17-.34 2.35-1.04 3.19-.69.85-1.83 1.51-2.95 1.42-.15-1.15.41-2.35 1.05-3.11z"/></svg>`,
  };
  const labels = { google: 'Google', outlook: 'Outlook', apple: 'Apple' };
  return `<button class="cal-btn" data-provider="${provider}">${icons[provider]}<span>${labels[provider]}</span></button>`;
}

function buildEventDates(assessment) {
  if (assessment.date) return { start: assessment.date, end: assessment.date, allDay: true };
  if (assessment.start) return { start: assessment.start, end: assessment.end || assessment.start, allDay: true };
  if (assessment.dates && assessment.dates.length) {
    return { start: assessment.dates[0], end: assessment.dates[assessment.dates.length - 1], allDay: true };
  }
  return { start: null, end: null, allDay: true };
}

function toISOBasic(dateStr) {
  return dateStr ? dateStr.replace(/-/g, '') : null;
}

function addToCalendar(provider, assessment) {
  const { start, end } = buildEventDates(assessment);
  const title   = encodeURIComponent(assessment.title || 'Assessment');
  const details = encodeURIComponent(`Worth ${assessment.weight_percent || '?'}%`);
  const startB  = toISOBasic(start);

  let url = null;

  if (provider === 'outlook') {
    url = `https://outlook.live.com/calendar/0/deeplink/compose?subject=${title}&body=${details}&startdt=${start || ''}&enddt=${end || ''}&allday=true&path=%2Fcalendar%2Faction%2Fcompose`;
  } else if (provider === 'apple') {
    const ics = [
      'BEGIN:VCALENDAR', 'VERSION:2.0', 'PRODID:-//syllabus.ai//EN',
      'BEGIN:VEVENT',
      `SUMMARY:${assessment.title || 'Assessment'}`,
      `DESCRIPTION:Worth ${assessment.weight_percent || '?'}%`,
      `DTSTART;VALUE=DATE:${startB || '19700101'}`,
      `DTEND;VALUE=DATE:${startB || '19700101'}`,
      'END:VEVENT', 'END:VCALENDAR',
    ].join('\r\n');
    const blob = new Blob([ics], { type: 'text/calendar' });
    const link = document.createElement('a');
    link.href = URL.createObjectURL(blob);
    link.download = `${assessment.title || 'assessment'}.ics`;
    link.click();
    URL.revokeObjectURL(link.href);
    return;
  }

  if (url) window.open(url, '_blank', 'noopener');
}

function addToGoogleCalendar(assessment) {
  const { start, end, allDay } = buildEventDates(assessment);

  google.accounts.oauth2.initTokenClient({
    client_id: CLIENT_ID,
    scope: SCOPES,
    callback: (tokenResponse) => {
      const event = {
        summary: assessment.title,
        description: `Worth ${assessment.weight_percent}%`,
        ...(allDay
          ? { start: { date: start || '' }, end: { date: end || start || '' } }
          : { start: { dateTime: start }, end: { dateTime: end } }
        ),
      };

      fetch('https://www.googleapis.com/calendar/v3/calendars/primary/events', {
        method: 'POST',
        headers: {
          Authorization: `Bearer ${tokenResponse.access_token}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify(event),
      })
        .then(res => res.json())
        .then(data => {
          console.log('Event created:', data);
          alert(`"${assessment.title}" added to your Google Calendar!`);
        });
    },
  }).requestAccessToken();
}

// ── Static listeners ────────────────────────────────────────────────────────
toggleEl.addEventListener('change', () => {
  if (_buildAssessmentRows) _buildAssessmentRows();
});