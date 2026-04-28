// Entry point. Owns upload flow, nav, mobile menu, and post-upload render
// orchestration. Section logic lives in info.js / chart.js / assessments.js
// / calendar.js / gradeCalc.js. Shared state in state.js, helpers in utils.js.

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

// All backend calls go through apiFetch so the session cookie always rides
// along (credentials: 'include'). Throws on non-2xx with the server's
// `detail` message; returns parsed JSON on 2xx, null on 204.
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

// localStorage caches parsed syllabi for instant render on reload — but only
// for signed-in users. Guests are in-memory only: data lives until the tab
// closes. Two reasons: (1) prevents prior-user data from showing up to a
// guest on a shared computer, (2) keeps the privacy story crisp ("sign in
// to save your data"). The backend remains source of truth via /syllabi.
const LS_KEY        = 'syllabusApp_courses';
const LS_MAX_AGE_MS = 24 * 60 * 60 * 1000;

function persistCourses() {
  if (!authState.user) return;  // Guest mode — in-memory only.
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      savedAt: Date.now(),
      courses,
    }));
  } catch {
    // Quota or private-browsing — non-fatal.
  }
}

function loadPersistedCourses() {
  if (!authState.user) return [];  // Guests don't read the cache.
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

function renderAllSections() {
  const lastIdx = courses.length - 1;

  // Collapse the hero upload card into a compact bar once at least one
  // syllabus has been parsed. CSS handles the actual transition; we just
  // own the truthy/falsy of "is there anything to show".
  const uploadCard = document.querySelector('.upload-card');
  if (uploadCard) uploadCard.classList.toggle('is-minimized', courses.length > 0);

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

// Logged in → /syllabi is the source of truth, localStorage is a cache.
// Guest    → no persistence at all. Wipe any leftover cache from a prior
//            session so a different person on the same browser sees nothing.
async function initFromStorage() {
  if (authState.user) {
    try {
      const syllabi = await apiFetch('/syllabi');
      if (!Array.isArray(syllabi) || syllabi.length === 0) return;

      // Tag each course with its backend syllabus row id so the per-course
      // delete handler knows which row to PATCH or DELETE.
      const allCourses = syllabi.flatMap(s =>
        (s.data?.courses ?? []).map(c => ({ ...c, _syllabusId: s.id }))
      );
      if (allCourses.length === 0) return;

      await addCourses(allCourses);
      renderAllSections();
      clearDataBtn.style.display = 'inline-flex';

      persistCourses();
      console.log(`[Syllabus App] Restored ${allCourses.length} course(s) from backend.`);
      return;
    } catch (e) {
      console.warn('[Syllabus App] Backend restore failed, falling back to localStorage:', e.message);
    }

    const saved = loadPersistedCourses();
    if (saved.length === 0) return;
    await addCourses(saved);
    renderAllSections();
    clearDataBtn.style.display = 'inline-flex';
    console.log(`[Syllabus App] Restored ${saved.length} course(s) from localStorage.`);
    return;
  }

  // Guest path — nuke any leftover cache. Invariant after this line:
  // localStorage[LS_KEY] is non-empty ⇔ the current user is signed in.
  clearPersistedCourses();
}

// Per-course delete — operates on whichever course the chart card is showing.
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

  // Sync to backend if logged in. _syllabusId is set during backend hydration;
  // courses loaded from localStorage only won't have it.
  if (authState.user && target._syllabusId) {
    const syllabusId = target._syllabusId;
    const siblingsLeft = courses.filter(c => c._syllabusId === syllabusId);

    if (siblingsLeft.length === 0) {
      // Last course from this PDF — drop the whole row.
      apiFetch(`/syllabi/${syllabusId}`, { method: 'DELETE' }).catch(e => {
        console.warn('[Syllabus App] Backend delete failed:', e.message);
      });
    } else {
      // PATCH the row to remove just this course from data.courses.
      const updatedCourses = siblingsLeft.map(({ _syllabusId: _, ...c }) => c);
      apiFetch(`/syllabi/${syllabusId}`, {
        method: 'PATCH',
        body: { courses: updatedCourses },
      }).catch(e => {
        console.warn('[Syllabus App] Backend patch failed:', e.message);
      });
    }
  }

  if (courses.length === 0) {
    clearPersistedCourses();
    window.location.reload();
    return;
  }

  persistCourses();
  renderAllSections();
  showToast(`Deleted ${label}.`, 'success');
});

// Wipes the localStorage cache only. Backend deletion is handled by the
// per-syllabus delete UI and DELETE /account.
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

// Upload flow

uploadBtn.addEventListener('click', () => {
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

  // Switch the loading bar from the cosmetic CSS keyframe to JS-driven mode.
  // .is-driven disables the keyframe so we can set width: directly.
  const loadingBarFill = document.getElementById('loading-bar-fill');
  const loadingSubtitle = document.getElementById('loading-subtitle');
  loadingBarFill.classList.add('is-driven');
  loadingBarFill.style.width = '0%';
  if (loadingSubtitle) loadingSubtitle.textContent = 'Uploading...';

  try {
    const formData = new FormData();
    formData.append('file', file);

    // 1. Validate-and-enqueue. Returns immediately; heavy work runs in the worker.
    let enqueue;
    try {
      enqueue = await apiFetch('/upload', { method: 'POST', body: formData });
    } catch (e) {
      if (e.status === 401) {
        await refreshAuth();
        throw new Error(
          authState.user
            ? 'Your session expired. Please sign in again.'
            : 'Upload failed. Please try again.'
        );
      }
      throw e;
    }
    if (!enqueue?.job_id) throw new Error('Server did not return a job id.');

    // 2. Poll until terminal state.
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

    const newCourses = result.data.courses;
    if (!newCourses || newCourses.length === 0) {
      showToast('No course data could be extracted from this PDF. Try a different syllabus.', 'warning');
      return;
    }

    // Dedup on (course_code, section_code, term) — prompt to replace or skip.
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
      showToast('Nothing added — duplicates skipped.', 'info');
      return;
    }

    persistCourses();
    renderAllSections();
    clearDataBtn.style.display = 'inline-flex';

    // Guest-only: nudge once per session to upgrade to a saved account.
    // sessionStorage so the same guest doesn't get nagged on every upload,
    // but a fresh tab does see it again — the prompt is the whole point of
    // guest mode existing.
    if (!authState.user && !sessionStorage.getItem('syllabusApp_guestNudgeShown')) {
      sessionStorage.setItem('syllabusApp_guestNudgeShown', '1');
      showToast('Sign in to save your courses across sessions.', 'info');
    }

    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    document.querySelector('.nav-link[href="#course-info-section"]').classList.add('active');
    document.getElementById('course-info-section').scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    console.error('[ERROR]', err);
    showToast(err.message || 'Something went wrong.', 'error');
  } finally {
    loadingModal.classList.remove('show');
    // Hand the bar back to its cosmetic CSS-animation state for the next run.
    loadingBarFill.classList.remove('is-driven');
    loadingBarFill.style.width = '';
    if (loadingSubtitle) loadingSubtitle.textContent = 'This takes about a minute. Grab a coffee!';
    uploadBtn.innerHTML = originalHTML;
    uploadBtn.disabled = false;
    fileInput.value = '';
  }
});

// Polls /jobs/<id> until status is 'complete' or 'failed'. Re-checks the
// clock after each await rather than using setInterval, so a slow turn
// can't pile up overlapping requests.
async function pollJobUntilDone(jobId, { intervalMs = 2000, onProgress } = {}) {
  // Browser-side timeout. The worker has its own; this is a runaway-loop guard.
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

// assessments.js fires this after writing an edit. Surgically re-render the
// three views that reflect assessment data — avoids resetting the chart/info
// dropdown indices that renderAllSections() would.
window.addEventListener('syllabusapp:assessmentupdated', () => {
  persistCourses();
  renderAssessmentList();
  const idx = Math.min(getCurrentChartIndex(), courses.length - 1);
  if (idx >= 0) renderChart(idx);
  refreshCalendarEvents();
  renderGradeCalc();
});

document.querySelectorAll('.nav-link').forEach(link => {
  link.addEventListener('click', function () {
    document.querySelectorAll('.nav-link').forEach(l => l.classList.remove('active'));
    this.classList.add('active');
  });
});

document.querySelector('.hamburger').addEventListener('click', () => {
  document.querySelector('.nav-links').classList.toggle('nav-links--mobile-open');
});


// Auth — magic-link login UI in the header. The session cookie is httpOnly,
// so JS never reads or writes it; we only ever ask /auth/me "who am I?".

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
    // Best-effort. The cookie clear is server-driven; we refresh local state below regardless.
  }
  authState.user = null;
  renderAuth();
  // Wipe localStorage — cached courses belonged to the prior user.
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
  // Two confirmations because this is destructive and irreversible.
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

// Surface a toast when we land back from a magic-link redirect, then strip
// the query param so a refresh doesn't re-fire it.
if (new URLSearchParams(window.location.search).get('logged_in') === '1') {
  showToast('Signed in.', 'success');
  const url = new URL(window.location.href);
  url.searchParams.delete('logged_in');
  window.history.replaceState({}, '', url.toString());
}

(async () => {
  await refreshAuth();
  await initFromStorage();
})();