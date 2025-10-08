const form = document.querySelector('#query-form');
const queryInput = document.querySelector('#query');
const statusEl = document.querySelector('#status');
const responsesEl = document.querySelector('#responses');
const template = document.querySelector('#response-template');
const submitBtn = document.querySelector('#submit-btn');

const KIND_LABELS = {
  send_email: 'Email sent',
  summarize_emails: 'Email summary',
  calendly_lookup: 'Calendly events',
  send_scheduling_link: 'Calendly link',
  other: 'Assistant reply'
};

const setStatus = (text = '', tone = 'info') => {
  statusEl.textContent = text;
  statusEl.className = 'status';
  if (tone !== 'info' && text) {
    statusEl.classList.add(tone);
  }
};

const describe = (payload) => {
  const { kind, details } = payload;
  const label = KIND_LABELS[kind] || 'Assistant reply';
  if (!details) return label;

  if (kind === 'send_email' && Array.isArray(details.to) && details.to.length) {
    return `${label} to ${details.to.join(' | ')}`;
  }

  if (kind === 'summarize_emails' && typeof details.messages_considered === 'number') {
    return `${label} (${details.messages_considered} messages)`;
  }

  if (kind === 'send_scheduling_link' && details.link && details.link.url) {
    return `${label}: ${details.link.url}`;
  }

  if (kind === 'calendly_lookup' && Array.isArray(details.events)) {
    return `${label} (${details.events.length} events)`;
  }

  return label;
};

const renderResponse = (payload) => {
  const clone = template.content.firstElementChild.cloneNode(true);
  const titleEl = clone.querySelector('.response-title');
  const intentEl = clone.querySelector('.response-intent');
  const textEl = clone.querySelector('.response-text');
  const detailsEl = clone.querySelector('.response-details');
  const detailsPre = detailsEl.querySelector('pre');

  titleEl.textContent = payload.query || 'Request';

  const subtitleBits = [describe(payload)];
  if (payload.status && payload.status !== 'ok') {
    subtitleBits.push(`status: ${payload.status}`);
  }
  if (payload.timestamp) {
    const ts = new Date(payload.timestamp);
    if (!Number.isNaN(ts.valueOf())) {
      subtitleBits.push(ts.toLocaleString());
    }
  }
  intentEl.textContent = subtitleBits.filter(Boolean).join(' | ');

  const text = (payload.text || '').trim();
  textEl.textContent = text || '(no reply)';

  const detailPayload = {};
  if (payload.intent) detailPayload.intent = payload.intent;
  if (payload.details) detailPayload.details = payload.details;
  if (Object.keys(detailPayload).length) {
    detailsPre.textContent = JSON.stringify(detailPayload, null, 2);
  } else {
    detailsEl.remove();
  }

  responsesEl.prepend(clone);
  while (responsesEl.children.length > 6) {
    responsesEl.removeChild(responsesEl.lastElementChild);
  }
};

const submitQuery = async (query) => {
  const res = await fetch('/route', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ text: query })
  });
  const data = await res.json().catch(() => ({}));
  if (!res.ok || data.ok === false) {
    const message = (data && data.detail) || (data && data.error) || `${res.status} ${res.statusText}`;
    throw new Error(message);
  }
  return data;
};

form.addEventListener('submit', async (event) => {
  event.preventDefault();
  const query = queryInput.value.trim();
  if (!query) {
    setStatus('Please enter a request.', 'error');
    queryInput.focus();
    return;
  }

  setStatus('Working...');
  submitBtn.disabled = true;

  try {
    const payload = await submitQuery(query);
    renderResponse(payload);
    setStatus('Done', 'success');
    setTimeout(() => setStatus(''), 1800);
    queryInput.value = '';
  } catch (error) {
    console.error(error);
    setStatus(error.message || 'Something went wrong', 'error');
  } finally {
    submitBtn.disabled = false;
  }
});










