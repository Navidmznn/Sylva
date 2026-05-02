// Cross-cutting helpers.

// escape anything LLM-derived before innerHTML
export function escapeHtml(str) {
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

// golden-angle hue rotation gives adjacent courses distinct colors
export function getCourseColors(index) {
  const hue = Math.round((index * 137.508) % 360);
  return {
    assessment: `hsl(${hue}, 55%, 55%)`,
    week: `hsl(${hue}, 35%, 65%)`,
  };
}

// Expand multi-date assessments into one entry per occurrence so they show
// up individually on the calendar, list, and grade calculator. Single-date
// items pass through untouched.
export function expandAssessments(assessments) {
  const out = [];
  for (const a of assessments) {
    if (a.dates && a.dates.length > 1) {
      const n = a.dates.length;
      const perWeight = a.weight_percent != null
        ? Math.round((a.weight_percent / n) * 100) / 100
        : null;
      a.dates.forEach((d, i) => {
        out.push({
          ...a,
          title: `${a.title} ${i + 1}`,
          date: d,
          dates: null,
          weight_percent: perWeight,
          _parentTitle: a.title,
          _expandedIndex: i + 1,
          _expandedTotal: n,
          _expandedWeight: perWeight,
        });
      });
    } else {
      out.push(a);
    }
  }
  return out;
}

// fallback only matters on file:// where crypto.randomUUID is missing
export function uid() {
  if (typeof crypto !== 'undefined' && crypto.randomUUID) return crypto.randomUUID();
  return 'id-' + Math.random().toString(36).slice(2, 10) + Date.now().toString(36);
}

// Add n days to a YYYY-MM-DD string. FullCalendar uses exclusive ends, so
// a visual Mon–Fri event needs end=Saturday.
export function addDays(yyyyMmDd, n) {
  if (!yyyyMmDd || typeof yyyyMmDd !== 'string') return yyyyMmDd;
  // noon UTC avoids DST edge cases
  const d = new Date(yyyyMmDd + 'T12:00:00Z');
  if (isNaN(d.getTime())) return yyyyMmDd;
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}


// Toast — stacking, auto-dismiss, click-to-dismiss.

let _toastHost = null;

function ensureToastHost() {
  if (_toastHost) return _toastHost;
  _toastHost = document.createElement('div');
  _toastHost.className = 'toast-host';
  _toastHost.setAttribute('aria-live', 'polite');
  _toastHost.setAttribute('aria-atomic', 'false');
  document.body.appendChild(_toastHost);
  return _toastHost;
}

const TOAST_ICONS = {
  info:    '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="12" y1="16" x2="12" y2="12"/><line x1="12" y1="8" x2="12.01" y2="8"/></svg>',
  success: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>',
  warning: '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0z"/><line x1="12" y1="9" x2="12" y2="13"/><line x1="12" y1="17" x2="12.01" y2="17"/></svg>',
  error:   '<svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>',
};

export function showToast(message, kind = 'info', duration) {
  const host = ensureToastHost();
  const validKind = TOAST_ICONS[kind] ? kind : 'info';
  const ms = duration ?? (validKind === 'error' ? 6000 : 4000);

  const el = document.createElement('div');
  el.className = `toast toast--${validKind}`;
  el.setAttribute('role', 'status');
  el.innerHTML = `
    <span class="toast-icon">${TOAST_ICONS[validKind]}</span>
    <span class="toast-msg"></span>
    <button class="toast-close" aria-label="Dismiss">
      <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
    </button>
  `;
  // textContent — message may include LLM/user input
  el.querySelector('.toast-msg').textContent = String(message);

  let dismissed = false;
  const dismiss = () => {
    if (dismissed) return;
    dismissed = true;
    el.classList.add('toast--leaving');
    el.addEventListener('transitionend', () => el.remove(), { once: true });
    // fallback if transitionend never fires
    setTimeout(() => el.remove(), 400);
  };

  el.querySelector('.toast-close').addEventListener('click', dismiss);

  host.appendChild(el);
  requestAnimationFrame(() => el.classList.add('toast--enter'));

  setTimeout(dismiss, ms);
  return dismiss;
}


// Confirm — promise-based replacement for window.confirm(). One at a time.

let _activeConfirmReject = null;

export function showConfirm({
  title = 'Are you sure?',
  message = '',
  confirmLabel = 'Confirm',
  cancelLabel = 'Cancel',
  danger = false,
} = {}) {
  if (_activeConfirmReject) _activeConfirmReject();

  return new Promise(resolve => {
    const overlay = document.createElement('div');
    overlay.className = 'confirm-overlay';
    overlay.innerHTML = `
      <div class="confirm-box" role="dialog" aria-modal="true" aria-labelledby="confirm-title">
        <div class="confirm-title" id="confirm-title"></div>
        <div class="confirm-message"></div>
        <div class="confirm-actions">
          <button class="confirm-btn confirm-btn--cancel" type="button"></button>
          <button class="confirm-btn confirm-btn--confirm${danger ? ' confirm-btn--danger' : ''}" type="button"></button>
        </div>
      </div>
    `;
    overlay.querySelector('.confirm-title').textContent   = title;
    overlay.querySelector('.confirm-message').textContent = message;
    overlay.querySelector('.confirm-btn--cancel').textContent  = cancelLabel;
    overlay.querySelector('.confirm-btn--confirm').textContent = confirmLabel;

    const close = (result) => {
      _activeConfirmReject = null;
      document.removeEventListener('keydown', onKey);
      overlay.classList.add('confirm-overlay--leaving');
      overlay.addEventListener('transitionend', () => overlay.remove(), { once: true });
      setTimeout(() => overlay.remove(), 400);
      resolve(result);
    };

    function onKey(e) {
      if (e.key === 'Escape') close(false);
      if (e.key === 'Enter')  close(true);
    }

    overlay.querySelector('.confirm-btn--confirm').addEventListener('click', () => close(true));
    overlay.querySelector('.confirm-btn--cancel') .addEventListener('click', () => close(false));
    overlay.addEventListener('click', e => { if (e.target === overlay) close(false); });
    document.addEventListener('keydown', onKey);

    _activeConfirmReject = () => close(false);

    document.body.appendChild(overlay);
    requestAnimationFrame(() => overlay.classList.add('confirm-overlay--enter'));
    overlay.querySelector('.confirm-btn--confirm').focus();
  });
}