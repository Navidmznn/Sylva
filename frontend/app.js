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

// ── Backend base URL + credentialed fetch helper ─────────────────────────────
// Every call to the backend must include credentials (the session cookie).
// `apiFetch` wraps fetch() to set credentials: 'include' uniformly, throws on
// non-2xx with the server's `detail` message, and returns parsed JSON on 2xx
// (or null for 204). Pass `parseJson: false` for endpoints with non-JSON
// responses (none currently used here, but keeps the door open).
const API_BASE = 'http://localhost:8000';

async function apiFetch(path, { method = 'GET', body, headers, parseJson = true } = {}) {
  const opts = {
    method,
    credentials: 'include',
    headers: { ...(headers || {}) },
  };
  if (body !== undefined) {
    if (body instanceof FormData) {
      opts.body = body; // browser sets Content-Type with boundary
    } else {
      opts.body = JSON.stringify(body);
      opts.headers['Content-Type'] = 'application/json';
    }
  }
  const res = await fetch(`${API_BASE}${path}`, opts);
  if (!res.ok) {
    const err = await res.json().catch(() => ({}));
    const e = new Error(err.detail || `Request failed (${res.status})`);
    e.status = res.status;
    throw e;
  }
  if (!parseJson || res.status === 204) return null;
  return res.json();
}

const uploadBtn    = document.querySelector('.upload-btn');
const fileInput    = document.querySelector('.file-input');
const loadingModal = document.getElementById('loading-modal');
const clearDataBtn = document.getElementById('clear-data-btn');

// ── localStorage persistence ─────────────────────────────────────────────────
// localStorage caches the parsed-syllabus JSON for instant render on reload.
// Server-side syllabi are managed via /syllabi (list) and DELETE /syllabi/{id}
// (single) and DELETE /account (everything). Clearing localStorage does not
// touch the backend.
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
// Strategy:
//   Logged in  → fetch GET /syllabi from the backend (source of truth).
//                Each syllabus row's `data.courses` array is merged in.
//                Also re-writes localStorage so subsequent fast-reloads
//                don't need another round-trip.
//   Logged out → fall back to localStorage (guest / offline mode).
async function initFromStorage() {
  if (authState.user) {
    try {
      const syllabi = await apiFetch('/syllabi');
      if (!Array.isArray(syllabi) || syllabi.length === 0) return;

      // Each /syllabi row has shape { id, filename, data, created_at }.
      // `data` is the full parsed syllabus object; `data.courses` is the
      // array of courses that addCourses() expects.
      // Tag each course with the backend syllabus row it came from.
      // The delete handler uses this to update or remove the right row.
      const allCourses = syllabi.flatMap(s =>
        (s.data?.courses ?? []).map(c => ({ ...c, _syllabusId: s.id }))
      );
      if (allCourses.length === 0) return;

      await addCourses(allCourses);
      renderAllSections();
      clearDataBtn.style.display = 'inline-flex';

      // Warm localStorage so a hard-reload while still logged in is instant.
      persistCourses();
      console.log(`[Syllabus App] Restored ${allCourses.length} course(s) from backend.`);
      return;
    } catch (e) {
      // Network error or 401 — fall through to localStorage.
      console.warn('[Syllabus App] Backend restore failed, falling back to localStorage:', e.message);
    }
  }

  // Logged-out path (or backend unreachable).
  const saved = loadPersistedCourses();
  if (saved.length === 0) return;
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

  // Sync deletion to the backend when logged in.
  // `target._syllabusId` is set during backend hydration (initFromStorage).
  // If the course came from localStorage only it won't be set — skip silently.
  if (authState.user && target._syllabusId) {
    const syllabusId = target._syllabusId;
    // Check how many remaining courses still belong to this syllabus row.
    const siblingsLeft = courses.filter(c => c._syllabusId === syllabusId);

    if (siblingsLeft.length === 0) {
      // No courses left from this PDF — delete the whole Syllabus row.
      apiFetch(`/syllabi/${syllabusId}`, { method: 'DELETE' }).catch(e => {
        console.warn('[Syllabus App] Backend delete failed:', e.message);
      });
    } else {
      // Other courses from the same PDF survive — patch the row to remove
      // just this one from its data.courses array.
      const updatedCourses = siblingsLeft.map(({ _syllabusId: _, ...c }) => c);
      apiFetch(`/syllabi/${syllabusId}`, {
        method: 'PATCH',
        body: { courses: updatedCourses },
      }).catch(e => {
        console.warn('[Syllabus App] Backend patch failed:', e.message);
      });
    }
  }

  // If that was the last course, the app reverts to its empty state.
  if (courses.length === 0) {
    clearPersistedCourses();
    window.location.reload();
    return;
  }

  persistCourses();
  renderAllSections();
  showToast(`Deleted ${label}.`, 'success');
});

// ── Clear browser data ──────────────────────────────────────────────────────
// Wipes the localStorage cache only. Backend syllabi are managed via the
// per-syllabus delete UI and DELETE /account; this button does not touch
// the server.
clearDataBtn.addEventListener('click', async () => {
  const ok = await showConfirm({
    title: 'Clear browser cache?',
    message: 'This removes the locally cached copy of your syllabi from this browser. Your account and saved syllabi on the server are not affected.',
    confirmLabel: 'Clear cache',
    cancelLabel: 'Keep them',
    danger: true,
  });
  if (!ok) return;

  clearPersistedCourses();
  window.location.reload();
});

// ── Upload flow ─────────────────────────────────────────────────────────────
uploadBtn.addEventListener('click', () => {
  if (!authState.user) {
    showToast('Please sign in first to upload a syllabus.', 'warning');
    document.getElementById('auth-email')?.focus();
    return;
  }
  fileInput.click();
});

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

    // 1. Validate-and-enqueue. Returns ~immediately; heavy work runs in the
    //    worker. apiFetch sends credentials so the server identifies the user.
    let enqueue;
    try {
      enqueue = await apiFetch('/upload', { method: 'POST', body: formData });
    } catch (e) {
      if (e.status === 401) {
        // Session expired since the page loaded — refresh widget and bail.
        await refreshAuth();
        throw new Error('Your session expired. Please sign in again.');
      }
      throw e;
    }
    if (!enqueue?.job_id) throw new Error('Server did not return a job id.');

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

    const res = await fetch(`${API_BASE}/jobs/${encodeURIComponent(jobId)}`, {
      credentials: 'include',
    });
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

// ═══════════════════════════════════════════════════════════════════════════
// AUTH — magic-link login UI in the header
// ═══════════════════════════════════════════════════════════════════════════
// Tiny module-level state. Other handlers consult `authState.user` to gate
// actions (e.g. the upload button). We never read or write the session cookie
// from JS — it's httpOnly. We only ever ask the backend "who am I?" via
// GET /auth/me.

const authState = { user: null };

const authWidget    = document.getElementById('auth-widget');
const authLoginForm = document.getElementById('auth-login-form');
const authEmailIn   = document.getElementById('auth-email');
const authUserBox   = document.getElementById('auth-user');
const authEmailPill = document.getElementById('auth-email-pill');
const authLogoutBtn = document.getElementById('auth-logout-btn');
const authDeleteBtn = document.getElementById('auth-delete-btn');

function renderAuth() {
  if (authState.user) {
    authWidget.dataset.state = 'in';
    authLoginForm.hidden = true;
    authUserBox.hidden = false;
    authEmailPill.textContent = authState.user.email;
  } else {
    authWidget.dataset.state = 'out';
    authLoginForm.hidden = false;
    authUserBox.hidden = true;
  }
}

async function refreshAuth() {
  try {
    const me = await apiFetch('/auth/me');
    authState.user = me?.authenticated ? me.user : null;
  } catch {
    authState.user = null;
  }
  renderAuth();
}

authLoginForm.addEventListener('submit', async (e) => {
  e.preventDefault();
  const email = authEmailIn.value.trim();
  if (!email) return;

  const submitBtn = authLoginForm.querySelector('button[type="submit"]');
  const original = submitBtn.textContent;
  submitBtn.disabled = true;
  submitBtn.textContent = 'Sending...';

  try {
    await apiFetch('/auth/login', { method: 'POST', body: { email } });
    showToast('Check your email for a sign-in link. (In dev mode, check the API console.)', 'success', 7000);
    authEmailIn.value = '';
  } catch (e) {
    showToast(e.message || 'Could not send link.', 'error');
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = original;
  }
});

authLogoutBtn.addEventListener('click', async () => {
  try {
    await apiFetch('/auth/logout', { method: 'POST' });
  } catch {
    // Logout is best-effort. The cookie clear is server-driven; we still
    // refresh local state below regardless.
  }
  authState.user = null;
  renderAuth();
  // Wipe localStorage too — the cached courses belonged to the prior user.
  clearPersistedCourses();
  showToast('Logged out.', 'info');
  // Reload to reset every other module's in-memory state cleanly.
  setTimeout(() => window.location.reload(), 400);
});

authDeleteBtn.addEventListener('click', async () => {
  const ok = await showConfirm({
    title: 'Delete your account?',
    message: 'This permanently deletes all your saved syllabi, sessions, and your account. This cannot be undone.',
    confirmLabel: 'Delete account',
    cancelLabel: 'Keep account',
    danger: true,
  });
  if (!ok) return;
  // Second confirmation — destructive + irreversible.
  const reallyOk = await showConfirm({
    title: 'Are you sure?',
    message: 'Last chance — this is permanent.',
    confirmLabel: 'Yes, delete it',
    cancelLabel: 'Cancel',
    danger: true,
  });
  if (!reallyOk) return;

  try {
    await apiFetch('/account', { method: 'DELETE' });
  } catch (e) {
    showToast(e.message || 'Account deletion failed.', 'error');
    return;
  }
  authState.user = null;
  clearPersistedCourses();
  showToast('Account deleted.', 'success');
  setTimeout(() => window.location.reload(), 600);
});

// ── If we just landed from a magic-link redirect, surface a success toast ──
if (new URLSearchParams(window.location.search).get('logged_in') === '1') {
  showToast('Signed in.', 'success');
  // Clean the query string so refreshing doesn't re-fire the toast.
  const url = new URL(window.location.href);
  url.searchParams.delete('logged_in');
  window.history.replaceState({}, '', url.toString());
}

// ── Init ─────────────────────────────────────────────────────────────────────
(async () => {
  await refreshAuth();
  await initFromStorage();
})();