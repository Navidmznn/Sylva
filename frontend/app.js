// Entry point. Owns upload flow, nav, mobile menu, and post-upload render
// orchestration. Section logic lives in the other modules.

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

// wrapper so credentials always ride along
const API_BASE = (location.hostname === 'localhost' || location.hostname === '127.0.0.1')
  ? 'http://localhost:8000'
  : 'https://sylva-production-2d10.up.railway.app';

async function apiFetch(path, { method = 'GET', body, headers, parseJson = true } = {}) {
  const opts = {
    method,
    credentials: 'include',
    headers: { ...(headers || {}) },
  };
  if (body !== undefined) {
    if (body instanceof FormData) {
      opts.body = body;
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

// signed-in users get localStorage cache, guests are memory-only
const LS_KEY        = 'sylva_courses';
const LS_MAX_AGE_MS = 24 * 60 * 60 * 1000;

function persistCourses() {
  if (!authState.user) return; // guests don't persist
  try {
    localStorage.setItem(LS_KEY, JSON.stringify({
      savedAt: Date.now(),
      courses,
    }));
  } catch {
    // quota or private browsing — fine
  }
}

function loadPersistedCourses() {
  if (!authState.user) return [];
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

// restore courses from backend or localStorage cache
async function initFromStorage() {
  if (authState.user) {
    try {
      const syllabi = await apiFetch('/syllabi');
      if (!Array.isArray(syllabi) || syllabi.length === 0) return;

      const allCourses = syllabi.flatMap(s =>
        (s.data?.courses ?? []).map(c => ({ ...c, _syllabusId: s.id }))
      );
      if (allCourses.length === 0) return;

      await addCourses(allCourses);
      renderAllSections();
      clearDataBtn.style.display = 'inline-flex';

      persistCourses();
      console.log(`[Sylva] Restored ${allCourses.length} course(s) from backend.`);
      return;
    } catch (e) {
      console.warn('[Sylva] Backend restore failed, falling back to localStorage:', e.message);
    }

    const saved = loadPersistedCourses();
    if (saved.length === 0) return;
    await addCourses(saved);
    renderAllSections();
    clearDataBtn.style.display = 'inline-flex';
    console.log(`[Sylva] Restored ${saved.length} course(s) from localStorage.`);
    return;
  }

  // wipe cache — guests don't get prior user's data
  clearPersistedCourses();
}

// per-course delete
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

  if (authState.user && target._syllabusId) {
    const syllabusId = target._syllabusId;
    const siblingsLeft = courses.filter(c => c._syllabusId === syllabusId);

    if (siblingsLeft.length === 0) {
      apiFetch(`/syllabi/${syllabusId}`, { method: 'DELETE' }).catch(e => {
        console.warn('[Sylva] Backend delete failed:', e.message);
      });
    } else {
      const updatedCourses = siblingsLeft.map(({ _syllabusId: _, ...c }) => c);
      apiFetch(`/syllabi/${syllabusId}`, {
        method: 'PATCH',
        body: { courses: updatedCourses },
      }).catch(e => {
        console.warn('[Sylva] Backend patch failed:', e.message);
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

  const loadingBarFill = document.getElementById('loading-bar-fill');
  const loadingSubtitle = document.getElementById('loading-subtitle');
  if (loadingSubtitle) loadingSubtitle.textContent = 'Reading your syllabus...';

  // fake-progress bar: fills toward ~90% over ~12s, then jumps to 100% when done
  loadingBarFill.classList.add('is-driven');
  loadingBarFill.style.width = '0%';
  const fakeStart = Date.now();
  const fakeDuration = 12000;
  const fakeProgressTimer = setInterval(() => {
    const elapsed = Date.now() - fakeStart;
    const t = Math.min(1, elapsed / fakeDuration);
    const pct = 90 * (1 - Math.pow(1 - t, 2)); // ease-out, caps near 90
    loadingBarFill.style.width = `${pct.toFixed(1)}%`;
  }, 100);

  try {
    const formData = new FormData();
    formData.append('file', file);

    let result;
    try {
      result = await apiFetch('/upload-sync', { method: 'POST', body: formData });
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

    if (!result || !result.data) {
      throw new Error('Server did not return a result payload.');
    }

    // jump to 100% when the request actually completes
    clearInterval(fakeProgressTimer);
    loadingBarFill.style.width = '100%';

    const newCourses = result.data.courses;
    if (!newCourses || newCourses.length === 0) {
      showToast('No course data could be extracted from this PDF. Try a different syllabus.', 'warning');
      return;
    }

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

    // nudge guests once per session
    if (!authState.user && !sessionStorage.getItem('sylva_guestNudgeShown')) {
      sessionStorage.setItem('sylva_guestNudgeShown', '1');
      showToast('Sign in to save your courses across sessions.', 'info');
    }

    document.querySelectorAll('.nav-link').forEach(link => link.classList.remove('active'));
    document.querySelector('.nav-link[href="#course-info-section"]').classList.add('active');
    document.getElementById('course-info-section').scrollIntoView({ behavior: 'smooth' });

  } catch (err) {
    console.error('[ERROR]', err);
    showToast(err.message || 'Something went wrong.', 'error');
  } finally {
    clearInterval(fakeProgressTimer);
    loadingModal.classList.remove('show');
    loadingBarFill.classList.remove('is-driven');
    loadingBarFill.style.width = '';
    if (loadingSubtitle) loadingSubtitle.textContent = 'This takes about a minute. Grab a coffee!';
    uploadBtn.innerHTML = originalHTML;
    uploadBtn.disabled = false;
    fileInput.value = '';
  }
});

// re-render only the assessment-related views after an edit
window.addEventListener('sylva:assessmentupdated', () => {
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


// auth UI — session is httpOnly so we just ask /auth/me

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
    showToast('Check your email for a sign-in link.', 'success', 7000);
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
    // best-effort
  }
  authState.user = null;
  renderAuth();
  clearPersistedCourses();
  showToast('Logged out.', 'info');
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