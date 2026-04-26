/* ═══════════════════════════════════════════════════════════════════════════
   SYLLABUS APP — entry point
   Owns: upload flow, nav highlighting, mobile hamburger, post-upload
   orchestration of the section render functions.
   Section logic lives in: info.js, chart.js, assessments.js, calendar.js,
   gradeCalc.js. Shared state lives in state.js. Cross-cutting helpers in
   utils.js.
═══════════════════════════════════════════════════════════════════════════ */

import { addCourses, courses, removeCourse } from './state.js';
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
import { showToast, showConfirm } from './utils.js';

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
async function initFromStorage() {
  const saved = loadPersistedCourses();
  if (saved.length === 0) return;

  // No onDuplicate — fresh-load arrays can't contain dupes against an empty
  // courses[]. Async only because addCourses returns a promise.
  await addCourses(saved);
  renderAllSections();
  clearDataBtn.style.display = 'inline-flex';
  console.log(`[Syllabus App] Restored ${saved.length} course(s) from localStorage.`);
}

// ── Per-course delete ────────────────────────────────────────────────────────
// Deletes whichever course is currently displayed in the chart card.
const deleteCourseBtn = document.getElementById('delete-course-btn');
deleteCourseBtn.addEventListener('click', async () => {
  const idx = getCurrentChartIndex();
  if (idx < 0 || idx >= courses.length) return;

  const target = courses[idx];
  const label  = [target.course_code, target.section_code, target.term]
    .filter(Boolean).join(' · ') || target.course_title || 'this course';

  const ok = await showConfirm({
    title: 'Delete this course?',
    message: `${label} and all of its extracted assessments and schedule entries will be removed.`,
    confirmLabel: 'Delete',
    cancelLabel: 'Keep',
    danger: true,
  });
  if (!ok) return;

  removeCourse(idx);

  // If that was the last course, the app reverts to its empty state — easiest
  // path is the same teardown as Clear-all so all sections collapse cleanly.
  if (courses.length === 0) {
    clearPersistedCourses();
    window.location.reload();
    return;
  }

  persistCourses();
  renderAllSections();
  showToast(`Deleted ${label}.`, 'success');
});

// ── Clear saved data ─────────────────────────────────────────────────────────
clearDataBtn.addEventListener('click', async () => {
  const ok = await showConfirm({
    title: 'Clear all saved syllabi?',
    message: 'Every uploaded course and its extracted data will be removed. This cannot be undone.',
    confirmLabel: 'Clear all',
    cancelLabel: 'Keep them',
    danger: true,
  });
  if (!ok) return;

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
    showToast('File too large. PDFs must be under 20MB.', 'warning');
    fileInput.value = '';
    return;
  }

  const originalHTML = uploadBtn.innerHTML;
  uploadBtn.innerHTML = '<span>Uploading...</span>';
  uploadBtn.disabled = true;
  loadingModal.classList.add('show');

  // Hand the cosmetic-animation bar over to JS-driven mode. The CSS class
  // tells style.css to disable the infinite-loop keyframe animation so we can
  // set width: directly from real progress reports.
  const loadingBarFill = document.getElementById('loading-bar-fill');
  const loadingSubtitle = document.getElementById('loading-subtitle');
  loadingBarFill.classList.add('is-driven');
  loadingBarFill.style.width = '0%';
  if (loadingSubtitle) loadingSubtitle.textContent = 'Uploading...';

  try {
    const formData = new FormData();
    formData.append('file', file);

    // 1. Validate-and-enqueue. This returns ~immediately; the heavy
    //    extraction runs in the worker.
    const response = await fetch('http://localhost:8000/upload', {
      method: 'POST',
      body: formData,
    });

    if (!response.ok) {
      const err = await response.json().catch(() => ({}));
      throw new Error(err.detail || 'Upload failed');
    }

    const enqueue = await response.json();
    if (!enqueue.job_id) throw new Error('Server did not return a job id.');

    // 2. Poll /jobs/<id> every 2 seconds until terminal state.
    const result = await pollJobUntilDone(enqueue.job_id, {
      intervalMs: 2000,
      onProgress: (state) => {
        if (typeof state.progress === 'number') {
          loadingBarFill.style.width = `${Math.max(2, Math.min(100, state.progress))}%`;
        }
        if (state.phase && loadingSubtitle) loadingSubtitle.textContent = state.phase;
      },
    });

    if (!result || !result.data) {
      throw new Error('Job finished without a result payload.');
    }

    console.log('[Syllabus App] Raw JSON from AI:', JSON.stringify(result.data, null, 2));

    const newCourses = result.data.courses;
    if (!newCourses || newCourses.length === 0) {
      showToast('No course data could be extracted from this PDF. Try a different syllabus.', 'warning');
      return;
    }

    // Dedup hook: when an incoming course matches an existing one on
    // (course_code, section_code, term), prompt the user to replace or skip.
    const beforeCount = courses.length;
    await addCourses(newCourses, {
      onDuplicate: async (incoming) => {
        const label = [incoming.course_code, incoming.section_code, incoming.term]
          .filter(Boolean).join(' · ');
        const replace = await showConfirm({
          title: 'Course already saved',
          message: `${label || 'This course'} is already in your list. Replace the existing entry with this upload?`,
          confirmLabel: 'Replace',
          cancelLabel: 'Skip',
        });
        return replace ? 'replace' : 'skip';
      },
    });

    if (courses.length === beforeCount) {
      // Every incoming course was a duplicate the user chose to skip.
      showToast('Nothing added — duplicates skipped.', 'info');
      return;
    }

    persistCourses();
    renderAllSections();
    clearDataBtn.style.display = 'inline-flex';

    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    document.querySelector('.nav-link[href="#course-info-section"]').classList.add('active');
    document.getElementById('course-info-section').scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    console.error('[ERROR]', err);
    showToast(err.message || 'Something went wrong.', 'error');
  } finally {
    loadingModal.classList.remove('show');
    // Hand the bar back to its cosmetic CSS-animation state so the next
    // upload starts fresh. Removing the inline width lets the keyframe
    // rule take over again.
    loadingBarFill.classList.remove('is-driven');
    loadingBarFill.style.width = '';
    if (loadingSubtitle) loadingSubtitle.textContent = 'This takes about a minute. Grab a coffee!';
    uploadBtn.innerHTML = originalHTML;
    uploadBtn.disabled = false;
    fileInput.value = '';
  }
});

// ── Job polling ──────────────────────────────────────────────────────────────
// Polls GET /jobs/<id> every `intervalMs` until status is 'complete' or
// 'failed'. Resolves with `state.result` on completion; rejects with the
// server's error message on failure.
//
// Defensive timing: we re-check the time after each await rather than relying
// on setInterval, so a slow network turn doesn't pile up overlapping requests.
async function pollJobUntilDone(jobId, { intervalMs = 2000, onProgress } = {}) {
  // Hard wall-clock ceiling. Worker has its own DOCLING_TIMEOUT_SECONDS;
  // this is just so a runaway poll loop can't run forever in the browser.
  const HARD_TIMEOUT_MS = 15 * 60 * 1000;
  const started = Date.now();

  while (true) {
    if (Date.now() - started > HARD_TIMEOUT_MS) {
      throw new Error('Processing timed out. Please try again.');
    }

    const res = await fetch(`http://localhost:8000/jobs/${encodeURIComponent(jobId)}`);
    if (res.status === 404) throw new Error('Job not found — may have expired.');
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      throw new Error(err.detail || `Server returned ${res.status} while polling.`);
    }

    const state = await res.json();
    if (typeof onProgress === 'function') onProgress(state);

    if (state.status === 'complete') return state.result;
    if (state.status === 'failed')   throw new Error(state.error || 'Processing failed.');

    await new Promise(r => setTimeout(r, intervalMs));
  }
}

// ── Assessment-edit sync ──────────────────────────────────────────────────────
// assessments.js dispatches this event after writing an edit back to `courses`.
// We persist the update then surgically re-render the three views that reflect
// assessment data — avoiding a full renderAllSections() which would reset the
// chart/info course-select dropdowns to the last index.
window.addEventListener('syllabusapp:assessmentupdated', () => {
  persistCourses();
  renderAssessmentList();
  // Clamp in case a course was removed since the chart last rendered.
  const idx = Math.min(getCurrentChartIndex(), courses.length - 1);
  if (idx >= 0) renderChart(idx);
  refreshCalendarEvents();
  renderGradeCalc();
});

// ── Top-nav active-link tracking ────────────────────────────────────────────
document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', function () {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    this.classList.add('active');
  });
});

// ── Hamburger menu (mobile) ─────────────────────────────────────────────────
// Toggles a single class — all visual styling lives in style.css under
// `.nav-links--mobile-open` (dark surface, violet-dusk hover/active accents).
document.querySelector('.hamburger').addEventListener('click', () => {
  document.querySelector('.nav-links').classList.toggle('nav-links--mobile-open');
});

// ── Init ─────────────────────────────────────────────────────────────────────
initFromStorage();