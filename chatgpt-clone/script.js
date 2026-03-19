/**
 * ChatGPT Clone — script.js
 *
 * Posts to the local server's /api/chat endpoint.
 * The server (server.mjs) handles all Anthropic API calls.
 */

const API_URL = '/api/chat';

// ─── State ────────────────────────────────────────────────────────────────────

let chatSessions = [];
let currentSessionId = null;
let selectedModel = localStorage.getItem('selected_model') || 'claude-sonnet-4-6';

// ─── DOM refs ─────────────────────────────────────────────────────────────────

const messageInput      = document.getElementById('messageInput');
const sendButton        = document.getElementById('sendButton');
const messagesContainer = document.getElementById('messagesContainer');
const welcomeScreen     = document.getElementById('welcomeScreen');
const chatHistory       = document.getElementById('chatHistory');
const newChatBtn        = document.getElementById('newChatBtn');
const sidebarToggle     = document.getElementById('sidebarToggle');
const sidebar           = document.getElementById('sidebar');
const modelSelect       = document.getElementById('modelSelect');

// ─── Init ─────────────────────────────────────────────────────────────────────

document.addEventListener('DOMContentLoaded', () => {
  if (modelSelect) {
    modelSelect.value = selectedModel;
    modelSelect.addEventListener('change', () => {
      selectedModel = modelSelect.value;
      localStorage.setItem('selected_model', selectedModel);
    });
  }
  loadSessions();
  bindEvents();
});

// ─── Session management ───────────────────────────────────────────────────────

function createSession() {
  const id = 'session-' + Date.now();
  const session = { id, title: 'New chat', messages: [], createdAt: new Date().toISOString() };
  chatSessions.unshift(session);
  currentSessionId = id;
  saveSessions();
  renderSidebar();
  return session;
}

function currentSession() {
  return chatSessions.find(s => s.id === currentSessionId) || createSession();
}

function saveSessions() {
  try { localStorage.setItem('chat_sessions', JSON.stringify(chatSessions)); } catch {}
}

function loadSessions() {
  try {
    const saved = JSON.parse(localStorage.getItem('chat_sessions') || '[]');
    chatSessions = saved;
  } catch { chatSessions = []; }
  if (chatSessions.length === 0) { createSession(); }
  else { currentSessionId = chatSessions[0].id; }
  renderSidebar();
  renderMessages();
}

function renderSidebar() {
  chatHistory.innerHTML = '';
  chatSessions.forEach(session => {
    const item = document.createElement('div');
    item.className = 'chat-history-item' + (session.id === currentSessionId ? ' active' : '');
    item.textContent = session.title;
    item.addEventListener('click', () => {
      currentSessionId = session.id;
      renderMessages();
      renderSidebar();
    });
    chatHistory.appendChild(item);
  });
}

// ─── Render messages ──────────────────────────────────────────────────────────

function renderMessages() {
  const session = currentSession();
  messagesContainer.innerHTML = '';
  if (session.messages.length === 0) {
    welcomeScreen.style.display = 'flex';
    messagesContainer.style.display = 'none';
  } else {
    welcomeScreen.style.display = 'none';
    messagesContainer.style.display = 'block';
    session.messages.forEach(msg => appendMessageDOM(msg.role, msg.content));
    messagesContainer.scrollTop = messagesContainer.scrollHeight;
  }
}

function renderMarkdown(text) {
  if (window.marked) {
    try { return window.marked.parse(text); } catch {}
  }
  // Fallback: escape HTML and preserve whitespace
  return '<pre style="white-space:pre-wrap;word-break:break-word;font-family:inherit">' +
    text.replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;') +
    '</pre>';
}

function appendMessageDOM(role, content) {
  const div = document.createElement('div');
  div.className = `message ${role}-message`;
  const bubble = document.createElement('div');
  bubble.className = 'message-content';
  if (role === 'assistant') {
    bubble.innerHTML = renderMarkdown(content);
  } else {
    bubble.textContent = content;
  }
  div.appendChild(bubble);
  messagesContainer.appendChild(div);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function showTypingIndicator() {
  const div = document.createElement('div');
  div.className = 'message assistant-message typing-indicator-wrapper';
  div.id = 'typingIndicator';
  div.innerHTML = '<div class="message-content typing-indicator"><span></span><span></span><span></span></div>';
  messagesContainer.appendChild(div);
  messagesContainer.scrollTop = messagesContainer.scrollHeight;
}

function removeTypingIndicator() {
  const el = document.getElementById('typingIndicator');
  if (el) el.remove();
}

// ─── Send message ─────────────────────────────────────────────────────────────

async function sendMessage(text) {
  const session = currentSession();
  if (!text.trim()) return;

  welcomeScreen.style.display = 'none';
  messagesContainer.style.display = 'block';

  session.messages.push({ role: 'user', content: text });
  if (session.title === 'New chat') {
    session.title = text.slice(0, 40) + (text.length > 40 ? '…' : '');
  }
  saveSessions();
  appendMessageDOM('user', text);
  renderSidebar();

  showTypingIndicator();
  sendButton.disabled = true;

  try {
    const resp = await fetch(API_URL, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        model: selectedModel,
        messages: session.messages.map(m => ({ role: m.role, content: m.content })),
      }),
    });

    removeTypingIndicator();

    if (!resp.ok) {
      const err = await resp.json().catch(() => ({ error: `HTTP ${resp.status}` }));
      throw new Error(err.error || `HTTP ${resp.status}`);
    }

    const data = await resp.json();
    const reply = data.reply || JSON.stringify(data, null, 2);

    session.messages.push({ role: 'assistant', content: reply });
    saveSessions();
    appendMessageDOM('assistant', reply);

  } catch (err) {
    removeTypingIndicator();
    const errMsg = `**Error:** ${err.message}\n\nMake sure the server is running:\n\`\`\`\ncd chatgpt-clone && npm install && node server.mjs\n\`\`\``;
    session.messages.push({ role: 'assistant', content: errMsg });
    saveSessions();
    appendMessageDOM('assistant', errMsg);
  }

  sendButton.disabled = !messageInput.value.trim();
  messageInput.focus();
}

// ─── Event bindings ───────────────────────────────────────────────────────────

function adjustTextarea() {
  messageInput.style.height = 'auto';
  messageInput.style.height = Math.min(messageInput.scrollHeight, 200) + 'px';
}

function bindEvents() {
  sendButton.addEventListener('click', () => {
    const text = messageInput.value.trim();
    if (!text) return;
    messageInput.value = '';
    adjustTextarea();
    sendMessage(text);
  });

  messageInput.addEventListener('keydown', e => {
    if (e.key === 'Enter' && !e.shiftKey) {
      e.preventDefault();
      sendButton.click();
    }
  });

  messageInput.addEventListener('input', () => {
    sendButton.disabled = !messageInput.value.trim();
    adjustTextarea();
  });

  newChatBtn.addEventListener('click', () => {
    createSession();
    renderMessages();
  });

  sidebarToggle.addEventListener('click', () => {
    sidebar.classList.toggle('collapsed');
  });

  document.querySelectorAll('.prompt-card').forEach(card => {
    card.addEventListener('click', () => {
      messageInput.value = card.dataset.prompt;
      sendButton.disabled = false;
      messageInput.focus();
    });
  });
}
