/*
 * Submit plumbing.
 *
 * The only thing the server requires is the shape of the POST body:
 *
 *     { "summary": "Rooftop cocktails · Friday evening",
 *       "answers": { "main": "rooftop_cocktails", "when": ["fri_pm"] } }
 *
 * `answers` is stored verbatim as JSONB and never interpreted, so you can put
 * whatever you like in it. `summary` is the one line that goes to Telegram;
 * the page writes it because the page is the only thing that knows what its
 * own answers mean.
 *
 * The collector below is a convenience, not a requirement. If a page needs
 * something this can't express, delete it and build `answers` by hand.
 */

const TOKEN = location.pathname.split('/').filter(Boolean)[1];
const API = `/api/d/${TOKEN}`;
const FORM_TITLE = document.title;

const formView = document.getElementById('form-view');
const doneView = document.getElementById('done-view');
const doneSummary = document.getElementById('done-summary');
const submitButton = document.getElementById('submit');
const errorLine = document.getElementById('error');

/* ── Selection ─────────────────────────────────────────────────────────── */

document.addEventListener('click', (event) => {
  const option = event.target.closest('[data-value]');
  if (!option) return;

  const group = option.closest('[data-question]');
  if (!group) return;

  if (group.dataset.mode === 'single') {
    group.querySelectorAll('[data-value]').forEach((el) => el.classList.remove('is-selected'));
    option.classList.add('is-selected');
  } else {
    option.classList.toggle('is-selected');
  }

  hideError();
});

/* ── Collecting answers ────────────────────────────────────────────────── */

function collect() {
  const answers = {};
  const parts = [];
  const missing = [];

  document.querySelectorAll('#form-view [data-question]').forEach((group) => {
    const key = group.dataset.question;
    const mode = group.dataset.mode;

    if (mode === 'single') {
      const chosen = group.querySelector('[data-value].is-selected');
      if (chosen) {
        answers[key] = chosen.dataset.value;
        parts.push(labelFor(chosen));
      } else if (group.hasAttribute('data-required')) {
        missing.push(group);
      }
    } else if (mode === 'multi') {
      const chosen = [...group.querySelectorAll('[data-value].is-selected')];
      if (chosen.length) {
        answers[key] = chosen.map((el) => el.dataset.value);
        parts.push(chosen.map(labelFor).join(', '));
      } else if (group.hasAttribute('data-required')) {
        missing.push(group);
      }
    } else {
      const text = (group.value || '').trim();
      if (text) {
        answers[key] = text;
      } else if (group.hasAttribute('data-required')) {
        missing.push(group);
      }
    }
  });

  return { answers, summary: parts.join(' · '), missing };
}

function labelFor(element) {
  return element.dataset.label || element.textContent.trim();
}

/* ── Submitting ────────────────────────────────────────────────────────── */

submitButton.addEventListener('click', async () => {
  const { answers, summary, missing } = collect();

  if (missing.length) {
    missing[0].scrollIntoView({ behavior: 'smooth', block: 'center' });
    showError('Pick one to send.');
    return;
  }
  if (!Object.keys(answers).length) {
    showError('Choose something first.');
    return;
  }

  setBusy(true);
  try {
    const response = await fetch(`${API}/submit`, {
      method: 'POST',
      headers: { 'content-type': 'application/json' },
      body: JSON.stringify({ summary, answers }),
    });

    if (response.status === 429) {
      showError('That went through a few times already. Give it an hour.');
      return;
    }
    if (!response.ok) {
      showError('Something went wrong. Try again in a moment?');
      return;
    }

    showDone(summary);
  } catch {
    showError('No connection. Check your signal and try again.');
  } finally {
    setBusy(false);
  }
});

/* ── Views ─────────────────────────────────────────────────────────────── */

/* Swapping `hidden` replaces the page rather than revealing something below
   it: style.css makes [hidden] win over the display rules, so the view that
   is off is gone from the document, not scrolled past. A side effect worth
   knowing: going from display:none back to displayed restarts CSS animations,
   so each swap replays that view's entrance for free. */

function showDone(summary) {
  doneSummary.textContent = summary || '';
  doneSummary.hidden = !summary;
  indexRise(doneView);
  formView.hidden = true;
  doneView.hidden = false;
  document.title = 'Sent';
  window.scrollTo(0, 0);
}

document.getElementById('change').addEventListener('click', () => {
  doneView.hidden = true;
  formView.hidden = false;
  document.title = FORM_TITLE;
  window.scrollTo(0, 0);
});

function setBusy(busy) {
  submitButton.disabled = busy;
  submitButton.textContent = busy ? 'Sending…' : 'Send it';
}

function showError(message) {
  errorLine.textContent = message;
  errorLine.hidden = false;
}

function hideError() {
  errorLine.hidden = true;
}

/* ── On load ───────────────────────────────────────────────────────────── */

/* Numbers a view's [data-rise] elements in document order, which is what
   staggers them down the page. Done here rather than in the markup so adding
   or moving a section needs no renumbering. */
function indexRise(view) {
  let index = 0;

  view.querySelectorAll('[data-rise]').forEach((element) => {
    element.style.setProperty('--i', index);
    index += 1;
  });
}

(async function init() {
  try {
    // Carry the query string across so ?mode=test still marks this as your own
    // visit: this call, not the page request, is what counts as an open.
    const response = await fetch(`${API}/context${location.search}`);
    if (!response.ok) return;

    const context = await response.json();

    const greeting = document.getElementById('greeting-name');
    if (greeting && context.display_name) {
      greeting.textContent = `, ${context.display_name.split(' ')[0]}`;
    }

    if (context.submitted) showDone('');
  } catch {
    /* Offline or the endpoint is unreachable, so leave the form as it is. */
  } finally {
    // showDone has already indexed the confirmation if that is what is showing;
    // this covers the form, whether it is showing now or reached later via
    // "Change my answer". Releasing the hold must happen whatever went wrong
    // above, or the page waits on the failsafe timer.
    indexRise(formView);
    document.documentElement.classList.remove('is-booting');
  }
})();
