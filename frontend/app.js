/* ═══════════════════════════════════════════════════════════════════════════
   SYLLABUS APP — entry point
   Owns: upload flow, nav highlighting, mobile hamburger, post-upload
   orchestration of the section render functions.
   Section logic lives in: info.js, chart.js, assessments.js, calendar.js,
   gradeCalc.js. Shared state lives in state.js. Cross-cutting helpers in
   utils.js.
═══════════════════════════════════════════════════════════════════════════ */

import { addCourses, courses } from './state.js';
import { renderCourseInfo, updateInfoDropdown } from './info.js';
import { renderChart, updateDropdown, getCurrentChartIndex } from './chart.js';
import { renderAssessmentList } from './assessments.js';
import {
  initCalendar,
  refreshCalendarEvents,
  rebuildCourseFilters,
  isCalendarInitialized,
  showCalendarSection,
} from './calendar.js';
import { renderGradeCalc } from './gradeCalc.js';

const uploadBtn    = document.querySelector('.upload-btn');
const fileInput    = document.querySelector('.file-input');
const loadingModal = document.getElementById('loading-modal');
const clearDataBtn = document.getElementById('clear-data-btn');

// ── localStorage persistence ─────────────────────────────────────────────────
// The backend SQLite DB stores every upload as the source of truth.
// localStorage is the restore layer — it's synchronous, zero-network, and
// survives hard refreshes without a backend round-trip.
const LS_KEY        = 'syllabusApp_courses';
const LS_MAX_AGE_MS = 24 * 60 * 60 * 1000; // 24 hours

function persistCourses() {
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      savedAt: Date.now(),
      courses,
    }));
  } catch {
    // Storage quota exceeded or private-browsing restriction — non-fatal.
  }
}

function loadPersistedCourses() {
  try {
    const raw = localStorage.getItem(LS_KEY);
    if (!raw) return [];
    const { savedAt, courses: saved } = JSON.parse(raw);
    if (!Array.isArray(saved) || saved.length === 0) return [];
    if (Date.now() - savedAt > LS_MAX_AGE_MS) {
      localStorage.removeItem(LS_KEY);
      return [];
    }
    return saved;
  } catch {
    return [];
  }
}

function clearPersistedCourses() {
  localStorage.removeItem(LS_KEY);
}

// ── Shared render orchestration ──────────────────────────────────────────────
function renderAllSections() {
  const lastIdx = courses.length - 1;

  updateDropdown();
  updateInfoDropdown();
  rebuildCourseFilters();
  renderCourseInfo(lastIdx);
  renderChart(lastIdx);
  renderAssessmentList();
  renderGradeCalc();

  if (!isCalendarInitialized()) {
    showCalendarSection();
    initCalendar();
  } else {
    refreshCalendarEvents();
  }
}

// ── Restore saved data on page load ─────────────────────────────────────────
function initFromStorage() {
  const saved = loadPersistedCourses();
  if (saved.length === 0) return;

  addCourses(saved);
  renderAllSections();
  clearDataBtn.style.display = 'inline-flex';
  console.log(`[Syllabus App] Restored ${saved.length} course(s) from localStorage.`);
}

// ── Clear saved data ─────────────────────────────────────────────────────────
clearDataBtn.addEventListener('click', async () => {
  if (!confirm('Clear all saved syllabi? This cannot be undone.')) return;

  clearPersistedCourses();

  // Best-effort backend clear — does not block or fail the UI reset.
  fetch('http://localhost:8000/results/clear', { method: 'DELETE' }).catch(() => {});

  window.location.reload();
});

// ── Upload flow ─────────────────────────────────────────────────────────────
uploadBtn.addEventListener('click', () => fileInput.click());

fileInput.addEventListener('change', async () => {
  const file = fileInput.files[0];
  if (!file) return;

  if (file.size > 20 * 1024 * 1024) {
    alert('File too large. Please upload a PDF under 20MB.');
    fileInput.value = '';
    return;
  }

  const originalHTML = uploadBtn.innerHTML;
  uploadBtn.innerHTML = '<span>Uploading...</span>';
  uploadBtn.disabled = true;
  loadingModal.classList.add('show');

  try {
    const formData = new FormData();
    formData.append('file', file);

    const response = await fetch('http://localhost:8000/upload', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const err = await response.json();
      throw new Error(err.detail || 'Upload failed');
    }

    let result;
    try {
      result = await response.json();
    } catch (e) {
      throw new Error('Failed to parse JSON response: ' + e.message);
    }

    if (!result.data) {
      throw new Error('Response missing "data" field.');
    }

    console.log('[Syllabus App] Raw JSON from AI:', JSON.stringify(result.data, null, 2));

    const newCourses = result.data.courses;
    if (!newCourses || newCourses.length === 0) {
      alert('No course data extracted. Please try a different syllabus format.');
      return;
    }

    addCourses(newCourses);
    persistCourses();   // write the updated courses array to localStorage
    renderAllSections();
    clearDataBtn.style.display = 'inline-flex';

    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    document.querySelector('.nav-link[href="#course-info-section"]').classList.add('active');
    document.getElementById('course-info-section').scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    console.error('[ERROR]', err);
    alert('Error: ' + err.message);
  } finally {
    loadingModal.classList.remove('show');
    uploadBtn.innerHTML = originalHTML;
    uploadBtn.disabled = false;
    fileInput.value = '';
  }
});

// ── Assessment-edit sync ──────────────────────────────────────────────────────
// assessments.js dispatches this event after writing an edit back to `courses`.
// We persist the update then surgically re-render the three views that reflect
// assessment data — avoiding a full renderAllSections() which would reset the
// chart/info course-select dropdowns to the last index.
window.addEventListener('syllabusapp:assessmentupdated', () => {
  persistCourses();
  renderAssessmentList();              // rebuild flat list from updated courses
  renderChart(getCurrentChartIndex()); // weights may have changed; redraw what the user is viewing
  refreshCalendarEvents();             // titles/dates may have changed
  renderGradeCalc();                   // weight changes affect grade targets
});

// ── Top-nav active-link tracking ────────────────────────────────────────────
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', function () {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    this.classList.add('active');
  });
});

// ── Hamburger menu (mobile) ─────────────────────────────────────────────────
document.querySelector('.hamburger').addEventListener('click', function () {
  const nav = document.querySelector('.nav-links');
  if (nav.style.display === 'flex') {
    nav.style.display = 'none';
  } else {
    nav.style.display = 'flex';
    nav.style.flexDirection = 'column';
    nav.style.position = 'absolute';
    nav.style.top = '72px';
    nav.style.right = '16px';
    nav.style.background = '#fff';
    nav.style.padding = '16px';
    nav.style.borderRadius = '16px';
    nav.style.boxShadow = '0 8px 30px rgba(0,0,0,0.15)';
  }
});

// ── Init ─────────────────────────────────────────────────────────────────────
initFromStorage();