// Tab switching
document.querySelectorAll('.tab').forEach(btn => {
  btn.addEventListener('click', () => {
    document.querySelectorAll('.tab').forEach(b => b.classList.remove('active'));
    btn.classList.add('active');
    const tab = btn.getAttribute('data-tab');
    document.querySelectorAll('.panel').forEach(p => p.classList.remove('active'));
    document.getElementById(tab).classList.add('active');
  });
});

const setOutput = (el, data) => {
  if (typeof data === 'string') {
    el.textContent = data;
  } else {
    el.textContent = JSON.stringify(data, null, 2);
  }
};

const post = async (path, payload) => {
  const r = await fetch(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(payload || {})
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}`);
  return r.json();
};

// Router
document.getElementById('runRouter').addEventListener('click', async () => {
  const text = document.getElementById('routerText').value.trim();
  const account_email = document.getElementById('routerEmail').value.trim() || null;
  const calendly_key = document.getElementById('routerCalKey').value.trim() || null;
  const out = document.getElementById('routerOut');
  out.textContent = 'Working...';
  try {
    const res = await post('/route', { text, account_email, calendly_key });
    setOutput(out, res.reply || res);
  } catch (e) {
    setOutput(out, String(e));
  }
});

// Gmail: List
document.getElementById('btnList').addEventListener('click', async () => {
  const account_email = document.getElementById('listEmail').value.trim() || null;
  const max_results = parseInt(document.getElementById('listMax').value, 10) || 10;
  const list = document.getElementById('gmailList');
  const out = document.getElementById('gmailOut');
  list.innerHTML = ''; out.textContent = 'Loading...';
  try {
    const res = await post('/gmail/list', { account_email, max_results });
    out.textContent = '';
    res.forEach(m => {
      const div = document.createElement('div');
      div.className = 'item';
      div.textContent = `${m.subject || '(no subject)'} — ${m.from || ''}`;
      div.addEventListener('click', async () => {
        out.textContent = 'Fetching message...';
        try {
          const detail = await post('/gmail/get', { message_id: m.id, account_email, download_attachments: false });
          setOutput(out, detail);
        } catch (e) {
          setOutput(out, String(e));
        }
      });
      list.appendChild(div);
    });
    if (!res.length) out.textContent = 'No messages.';
  } catch (e) {
    setOutput(out, String(e));
  }
});

// Gmail: Search
document.getElementById('btnSearch').addEventListener('click', async () => {
  const query = document.getElementById('searchQuery').value.trim();
  const account_email = document.getElementById('searchEmail').value.trim() || null;
  const max_results = parseInt(document.getElementById('searchMax').value, 10) || 10;
  const list = document.getElementById('gmailList');
  const out = document.getElementById('gmailOut');
  list.innerHTML = ''; out.textContent = 'Searching...';
  try {
    const res = await post('/gmail/search', { query, account_email, max_results });
    out.textContent = '';
    res.forEach(m => {
      const div = document.createElement('div');
      div.className = 'item';
      div.textContent = `${m.subject || '(no subject)'} — ${m.from || ''}`;
      div.addEventListener('click', async () => {
        out.textContent = 'Fetching message...';
        try {
          const detail = await post('/gmail/get', { message_id: m.id, account_email, download_attachments: false });
          setOutput(out, detail);
        } catch (e) {
          setOutput(out, String(e));
        }
      });
      list.appendChild(div);
    });
    if (!res.length) out.textContent = 'No results.';
  } catch (e) {
    setOutput(out, String(e));
  }
});

// Gmail: Send
document.getElementById('btnSend').addEventListener('click', async () => {
  const to = document.getElementById('sendTo').value.split(',').map(x => x.trim()).filter(Boolean);
  const subject = document.getElementById('sendSubject').value;
  const body_text = document.getElementById('sendBody').value;
  const account_email = document.getElementById('sendEmailAcct').value.trim() || null;
  const out = document.getElementById('gmailOut');
  out.textContent = 'Sending...';
  try {
    const res = await post('/gmail/send', { to, subject, body_text, account_email });
    setOutput(out, res);
  } catch (e) {
    setOutput(out, String(e));
  }
});

// Calendly: List Events
document.getElementById('btnCalList').addEventListener('click', async () => {
  const date = document.getElementById('calDate').value || new Date().toISOString().slice(0,10);
  const windowSel = document.getElementById('calWindow').value;
  const tz = document.getElementById('calTZ').value || 'Europe/London';
  const account_key = document.getElementById('calKey').value.trim() || null;
  const out = document.getElementById('calOut');
  out.textContent = 'Loading...';
  try {
    const res = await post('/calendly/events', { date, window: windowSel, tz, account_key });
    setOutput(out, res);
  } catch (e) {
    setOutput(out, String(e));
  }
});

// Calendly: Create Link
document.getElementById('btnCalLink').addEventListener('click', async () => {
  const account_key = document.getElementById('calKeyLink').value.trim() || null;
  const owner_type = document.getElementById('calOwnerType').value || 'EventType';
  const out = document.getElementById('calOut');
  out.textContent = 'Creating link...';
  try {
    const res = await post('/calendly/link', { account_key, owner_type, max_count: 1 });
    setOutput(out, res);
  } catch (e) {
    setOutput(out, String(e));
  }
});

// Prefill date and tz
(() => {
  const d = new Date();
  document.getElementById('calDate').value = d.toISOString().slice(0,10);
  document.getElementById('calTZ').value = Intl.DateTimeFormat().resolvedOptions().timeZone || 'UTC';
})();

