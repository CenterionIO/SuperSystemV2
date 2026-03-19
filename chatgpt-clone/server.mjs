#!/usr/bin/env node
/**
 * chatgpt-clone/server.mjs
 *
 * Local HTTP server — serves the UI and proxies chat to Anthropic API.
 *
 * Usage:
 *   ANTHROPIC_API_KEY=sk-... node server.mjs
 *
 * Endpoints:
 *   GET  /           → index.html
 *   GET  /styles.css → styles.css
 *   GET  /script.js  → script.js
 *   POST /api/chat   → { messages, model? } → { reply }
 *   GET  /health     → { status: "ok" }
 */

import http from 'node:http';
import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import Anthropic from '@anthropic-ai/sdk';

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const PORT = parseInt(process.env.PORT || '4134', 10);
const DEFAULT_MODEL = 'claude-sonnet-4-6';

const client = new Anthropic({ apiKey: process.env.ANTHROPIC_API_KEY });

const MIME = {
  '.html': 'text/html; charset=utf-8',
  '.css':  'text/css; charset=utf-8',
  '.js':   'application/javascript; charset=utf-8',
  '.json': 'application/json',
};

// ─── Helpers ──────────────────────────────────────────────────────────────────

function readBody(req) {
  return new Promise((resolve, reject) => {
    let data = '';
    req.on('data', c => { data += c; });
    req.on('end', () => {
      try { resolve(JSON.parse(data || '{}')); }
      catch { resolve({}); }
    });
    req.on('error', reject);
  });
}

function json(res, status, body) {
  const payload = JSON.stringify(body);
  res.writeHead(status, {
    'Content-Type': 'application/json',
    'Access-Control-Allow-Origin': '*',
  });
  res.end(payload);
}

function serveStatic(res, relPath) {
  const filePath = path.join(__dirname, relPath);
  const ext = path.extname(filePath);
  try {
    const content = fs.readFileSync(filePath);
    res.writeHead(200, { 'Content-Type': MIME[ext] || 'text/plain' });
    res.end(content);
  } catch {
    res.writeHead(404);
    res.end('Not found');
  }
}

// ─── Chat handler ─────────────────────────────────────────────────────────────

async function handleChat(req, res) {
  const body = await readBody(req);
  const messages = body.messages;
  const model = body.model || DEFAULT_MODEL;

  if (!Array.isArray(messages) || messages.length === 0) {
    return json(res, 400, { error: '`messages` array is required' });
  }

  const valid = messages.every(
    m => (m.role === 'user' || m.role === 'assistant') && typeof m.content === 'string'
  );
  if (!valid) {
    return json(res, 400, { error: 'Each message must have role (user|assistant) and string content' });
  }

  if (!process.env.ANTHROPIC_API_KEY) {
    return json(res, 500, { error: 'ANTHROPIC_API_KEY is not set. Start the server with: ANTHROPIC_API_KEY=sk-... node server.mjs' });
  }

  try {
    const response = await client.messages.create({
      model,
      max_tokens: 8096,
      messages: messages.map(m => ({ role: m.role, content: m.content })),
    });

    const reply = response.content
      .filter(b => b.type === 'text')
      .map(b => b.text)
      .join('');

    return json(res, 200, { reply, model });
  } catch (err) {
    console.error('[server] Anthropic error:', err.message);
    const status = err.status ?? 500;
    return json(res, status, { error: err.message });
  }
}

// ─── Router ───────────────────────────────────────────────────────────────────

const server = http.createServer(async (req, res) => {
  const { method, url } = req;

  if (method === 'OPTIONS') {
    res.writeHead(204, {
      'Access-Control-Allow-Origin': '*',
      'Access-Control-Allow-Methods': 'GET, POST, OPTIONS',
      'Access-Control-Allow-Headers': 'Content-Type',
    });
    return res.end();
  }

  if (method === 'GET' && url === '/health') {
    return json(res, 200, { status: 'ok', model: DEFAULT_MODEL });
  }

  if (method === 'POST' && url === '/api/chat') {
    return handleChat(req, res);
  }

  const staticMap = {
    '/':           'index.html',
    '/index.html': 'index.html',
    '/styles.css': 'styles.css',
    '/script.js':  'script.js',
  };

  const target = staticMap[url];
  if (method === 'GET' && target) {
    return serveStatic(res, target);
  }

  res.writeHead(404);
  res.end('Not found');
});

server.listen(PORT, '127.0.0.1', () => {
  console.log('');
  console.log('  ChatGPT Clone  →  http://localhost:' + PORT);
  console.log('');
  if (!process.env.ANTHROPIC_API_KEY) {
    console.warn('  ⚠  ANTHROPIC_API_KEY not set — chat will return an error.');
    console.warn('     Restart with: ANTHROPIC_API_KEY=sk-... node server.mjs');
  } else {
    console.log('  API key: set ✓   model: ' + DEFAULT_MODEL);
  }
  console.log('');
});

server.on('error', err => {
  console.error('[server] Fatal:', err.message);
  process.exit(1);
});
