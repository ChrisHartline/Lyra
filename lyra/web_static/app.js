const state = { sessions: [], current: null, streaming: false };
const el = id => document.getElementById(id);

function escapeHtml(value) {
  return value.replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
}

function markdown(value) {
  const code = [];
  let safe = escapeHtml(value).replace(/```(?:\w+)?\n([\s\S]*?)```/g, (_, body) => {
    code.push(`<pre><code>${body}</code></pre>`);
    return `@@CODE${code.length - 1}@@`;
  });
  safe = safe
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>')
    .replace(/\*([^*]+)\*/g, '<em>$1</em>')
    .split(/\n{2,}/).map(block => `<p>${block.replace(/\n/g, '<br>')}</p>`).join('');
  return safe.replace(/<p>@@CODE(\d+)@@<\/p>/g, (_, index) => code[Number(index)]);
}

async function api(path, options = {}) {
  const response = await fetch(path, {headers: {'Content-Type':'application/json'}, ...options});
  if (!response.ok) throw new Error((await response.json().catch(() => ({}))).detail || `HTTP ${response.status}`);
  if (response.status === 204) return null;
  return response.json();
}

function renderSessions() {
  el('sessions').innerHTML = '';
  for (const session of state.sessions) {
    const button = document.createElement('button');
    button.className = `session${state.current === session.session_id ? ' active' : ''}`;
    button.textContent = session.name;
    button.onclick = () => openSession(session.session_id);
    el('sessions').appendChild(button);
  }
}

function appendMessage(role, content) {
  const empty = el('messages').querySelector('.empty');
  if (empty) empty.remove();
  const article = document.createElement('article');
  article.className = `message ${role}`;
  article.innerHTML = `<div class="role">${role === 'assistant' ? 'Lyra' : 'You'}</div><div class="body">${markdown(content)}</div>`;
  el('messages').appendChild(article);
  el('messages').scrollTop = el('messages').scrollHeight;
  return article.querySelector('.body');
}

function setStatus(text) {
  let status = el('messages').querySelector('.status-line');
  if (!status) {
    status = document.createElement('div');
    status.className = 'status-line';
    el('messages').appendChild(status);
  }
  status.textContent = text;
}

async function loadSessions() {
  const result = await api('/api/sessions');
  state.sessions = result.sessions;
  renderSessions();
}

async function openSession(id) {
  state.current = id;
  const session = state.sessions.find(item => item.session_id === id) || await api(`/api/sessions/${id}`);
  el('session-title').textContent = session.name;
  el('prompt').disabled = false;
  el('send').disabled = false;
  el('delete-session').disabled = false;
  const result = await api(`/api/sessions/${id}/messages`);
  el('messages').innerHTML = '';
  if (!result.messages.length) el('messages').innerHTML = '<div class="empty"><div class="orb"></div><h3>I’m here.</h3><p>What are we working on?</p></div>';
  for (const message of result.messages) appendMessage(message.role, message.content);
  renderSessions();
}

function parseSseBlock(block) {
  const lines = block.split('\n');
  const event = (lines.find(line => line.startsWith('event:')) || 'event: message').slice(6).trim();
  const data = lines.filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
  return {event, data: data ? JSON.parse(data) : {}};
}

async function sendTurn(content) {
  state.streaming = true;
  el('send').disabled = true;
  appendMessage('user', content);
  const assistant = appendMessage('assistant', '');
  let assistantText = '';
  let hadError = false;
  try {
    const response = await fetch(`/api/sessions/${state.current}/turns`, {
      method: 'POST', headers: {'Content-Type':'application/json'}, body: JSON.stringify({content})
    });
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const {value, done} = await reader.read();
      buffer += decoder.decode(value || new Uint8Array(), {stream: !done}).replace(/\r\n/g, '\n');
      const blocks = buffer.split('\n\n');
      buffer = blocks.pop() || '';
      for (const block of blocks) {
        if (!block.trim()) continue;
        const item = parseSseBlock(block);
        if (item.event === 'text') {
          assistantText += item.data.text || '';
          assistant.innerHTML = markdown(assistantText);
        } else if (item.event === 'tool') {
          setStatus(`Using ${item.data.name}…`);
        } else if (item.event === 'error') {
          hadError = true;
          setStatus(item.data.text || 'The turn failed.');
        } else if (item.event === 'status') {
          if (!(hadError && item.data.status === 'failed')) {
            setStatus(item.data.status === 'completed' ? 'Complete' : item.data.status);
          }
        }
      }
      if (done) break;
    }
  } catch (error) {
    setStatus('Connection interrupted. Reloading the saved conversation…');
    await openSession(state.current);
  } finally {
    if (!assistantText) assistant.closest('.message')?.remove();
    state.streaming = false;
    el('send').disabled = false;
    el('prompt').focus();
  }
}

el('new-session').onclick = async () => {
  const name = window.prompt('Conversation name', 'New conversation');
  if (!name) return;
  const session = await api('/api/sessions', {method:'POST', body:JSON.stringify({name})});
  await loadSessions();
  await openSession(session.session_id);
};

el('delete-session').onclick = async () => {
  if (!state.current || !window.confirm('Delete this conversation and its raw history?')) return;
  await api(`/api/sessions/${state.current}`, {method:'DELETE'});
  state.current = null;
  location.reload();
};

el('composer').onsubmit = async event => {
  event.preventDefault();
  const content = el('prompt').value.trim();
  if (!content || state.streaming || !state.current) return;
  el('prompt').value = '';
  await sendTurn(content);
};

el('prompt').onkeydown = event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    el('composer').requestSubmit();
  }
};

api('/api/health').then(() => { el('connection').textContent = 'Local link ready'; }).catch(() => { el('connection').textContent = 'Local link unavailable'; });
loadSessions().then(() => {
  if (state.sessions.length) openSession(state.sessions[0].session_id);
}).catch(error => { el('connection').textContent = error.message; });
