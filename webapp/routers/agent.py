"""Neo4j Agent Memory — chat API for P&ID jobs.

Two-layer memory:
  Layer 1 — Episodes  : raw conversation turns (session history + fulltext search)
  Layer 2 — Memories  : structured extractions — facts, preferences, decisions, tasks
                        extracted by LLM after each exchange; retrieved on every turn

Endpoints (all mounted under /api/v1/jobs/{job_id}/agent):
  POST /chat                           — send message, get AI reply
  GET  /sessions                       — list all sessions for this job
  GET  /sessions/{session_id}          — get full conversation history
  DELETE /sessions/{session_id}        — clear a session
  GET  /memory                         — list all stored memories for this job
  GET  /memory/search?q=<query>        — search stored memories directly
  POST /memory/{memory_id}/done        — mark a task memory as completed

Auth: same pattern as graph.py — 404 for foreign jobs, super_admin can read any.
"""
from __future__ import annotations

import logging
import os
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from webapp import models
from webapp.auth import get_current_user
from webapp.database import get_db
from webapp.graph.agent_memory import (
    clear_session,
    complete_task,
    extract_and_store_memories,
    get_all_memories,
    get_pid_context,
    get_session_history,
    list_sessions,
    retrieve_memories,
    search_memory,
    store_episode,
)

logger = logging.getLogger(__name__)
router = APIRouter()

_OPENROUTER_BASE = "https://openrouter.ai/api/v1"
_DEFAULT_MODEL   = os.environ.get("OPENROUTER_MODEL", "google/gemini-2.5-flash")


# ── Auth helper (mirrors graph.py) ────────────────────────────────────────────

def _load_job_or_404(
    job_id: int, db: Session, current_user: models.User
) -> models.Job:
    job = db.get(models.Job, job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Job not found")
    if job.user_id != current_user.id and current_user.role != "super_admin":
        raise HTTPException(status_code=404, detail="Job not found")
    return job


# ── LLM call ─────────────────────────────────────────────────────────────────

def _call_llm(messages: List[Dict[str, str]]) -> str:
    """Call OpenRouter with the given message list. Returns assistant reply text."""
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="OPENROUTER_API_KEY not configured")

    from openai import OpenAI
    client = OpenAI(api_key=api_key, base_url=_OPENROUTER_BASE)
    response = client.chat.completions.create(
        model=_DEFAULT_MODEL,
        messages=messages,
        max_tokens=1024,
    )
    return response.choices[0].message.content or ""


# ── Request / Response models ─────────────────────────────────────────────────

class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    pid_nodes_used: int
    memories_retrieved: int = 0
    memories_stored: int = 0
    class_counts_loaded: int = 0


class SessionSummary(BaseModel):
    session_id: str
    message_count: int
    started_at: Optional[str]
    last_message_at: Optional[str]


class MessageItem(BaseModel):
    role: str
    content: str
    created_at: Optional[str] = None


class DeleteSessionResponse(BaseModel):
    deleted_messages: int


class MemorySearchResponse(BaseModel):
    query: str
    count: int
    results: List[str]


class MemoryItem(BaseModel):
    id: str
    type: str
    content: str
    tags: List[str] = []
    status: str = "open"
    created_at: Optional[str] = None


class MemoryListResponse(BaseModel):
    count: int
    memories: List[MemoryItem]


class TaskDoneResponse(BaseModel):
    success: bool


# ── Endpoints ─────────────────────────────────────────────────────────────────

@router.post("/{job_id}/agent/chat", response_model=ChatResponse)
def chat(
    job_id: int,
    body: ChatRequest,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> ChatResponse:
    """Send a message to the P&ID agent. Stores memory in Neo4j.

    The agent enriches every reply with:
    - The job's P&ID graph (instrument tags + connections matching query keywords)
    - Past conversation memory for this job (fulltext search over Episodes)
    - Current session history (last 10 turns)
    """
    _load_job_or_404(job_id, db, current_user)

    # If the caller supplied a session_id, verify it actually belongs to this
    # job before reusing it — prevents IDOR where a user passes another job's
    # session_id to read or inject into foreign conversation history.
    if body.session_id:
        existing = get_session_history(body.session_id, job_id, limit=1)
        if existing:
            session_id = body.session_id          # verified: belongs to this job
        else:
            session_id = str(uuid.uuid4())        # unknown / foreign → fresh session
    else:
        session_id = str(uuid.uuid4())

    user_message = body.message.strip()
    if not user_message:
        raise HTTPException(status_code=422, detail="message must not be empty")

    # 1. Retrieve P&ID context from Neo4j — same data source as the digital twin
    pid_ctx = get_pid_context(job_id, user_message)
    class_counts   = pid_ctx.get("class_counts", {})
    total_edges    = pid_ctx.get("total_edges", 0)
    matching_nodes = pid_ctx.get("matching_nodes", [])
    connections    = pid_ctx.get("connections", [])

    # 2. Retrieve stored memories — facts, preferences, decisions, open tasks
    stored_memories = retrieve_memories(user_message, job_id, limit=10)

    # 3. Get current session history (last 10 turns) — scoped to this job
    history = get_session_history(session_id, job_id, limit=10)

    # 4. Build system prompt
    system_parts = [
        "You are a P&ID engineering assistant with persistent memory.",
        f"You are analyzing job #{job_id}.",
        "Answer using ONLY the data provided below — do not guess or invent values.",
    ]

    # Stored memories — highest priority: facts/preferences/decisions the user established
    if stored_memories:
        type_order = {"preference": 0, "decision": 1, "fact": 2, "task": 3}
        stored_memories.sort(key=lambda m: type_order.get(m["type"], 9))
        mem_lines = []
        for m in stored_memories:
            tag_str = f" [tags: {', '.join(m['tags'])}]" if m.get("tags") else ""
            status_str = f" [{m['status'].upper()}]" if m["type"] == "task" else ""
            mem_lines.append(f"  [{m['type'].upper()}]{status_str} {m['content']}{tag_str}")
        system_parts.append(
            "Remembered facts, preferences, decisions and tasks from past conversations:\n"
            + "\n".join(mem_lines)
        )

    # Class-level counts — so "how many X" is always accurate
    if class_counts:
        count_lines = [f"  - {cls}: {cnt}" for cls, cnt in class_counts.items()]
        system_parts.append(
            f"Complete instrument count by class (total pipe connections: {total_edges}):\n"
            + "\n".join(count_lines)
        )

    if matching_nodes:
        node_lines = [
            f"  - {n['tag'] or n['id']} (class: {n['class']})"
            for n in matching_nodes
        ]
        system_parts.append(
            f"Instruments matching the query ({len(matching_nodes)} found):\n"
            + "\n".join(node_lines)
        )

    if connections:
        conn_lines = [
            f"  - {c['from_tag']} ({c['from_class']}) ──{c['line_type']}── {c['to_tag']} ({c['to_class']})"
            for c in connections
        ]
        system_parts.append(
            "Pipe connections for the above instruments:\n" + "\n".join(conn_lines)
        )

    system_parts.append(
        "Rules: "
        "1) When asked for counts use the exact numbers from 'Complete instrument count by class'. "
        "2) When listing tags use only those from 'Instruments matching the query'. "
        "3) Always apply remembered preferences (e.g. units, detail level). "
        "4) If the user mentions completing a task, acknowledge it clearly. "
        "5) Include instrument tag numbers when referencing specific instruments."
    )

    system_prompt = "\n\n".join(system_parts)

    # 5. Assemble messages: system + history + new user message
    messages: List[Dict[str, str]] = [{"role": "system", "content": system_prompt}]
    for turn in history:
        messages.append({"role": turn["role"], "content": turn["content"]})
    messages.append({"role": "user", "content": user_message})

    # 6. Call LLM
    reply = _call_llm(messages)

    # 7. Store conversation episodes in Neo4j
    store_episode(session_id, "user",      user_message, job_id)
    store_episode(session_id, "assistant", reply,        job_id)

    # 8. Extract and store any facts/preferences/decisions/tasks from this exchange
    new_memory_ids = extract_and_store_memories(user_message, reply, job_id, session_id)

    return ChatResponse(
        session_id=session_id,
        reply=reply,
        pid_nodes_used=len(matching_nodes),
        memories_retrieved=len(stored_memories),
        memories_stored=len(new_memory_ids),
        class_counts_loaded=len(class_counts),
    )


@router.get("/{job_id}/agent/sessions", response_model=List[SessionSummary])
def get_sessions(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> List[SessionSummary]:
    """List all conversation sessions for this job."""
    _load_job_or_404(job_id, db, current_user)
    return [SessionSummary(**s) for s in list_sessions(job_id)]


@router.get("/{job_id}/agent/sessions/{session_id}", response_model=List[MessageItem])
def get_session(
    job_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> List[MessageItem]:
    """Get full conversation history for a session."""
    _load_job_or_404(job_id, db, current_user)
    history = get_session_history(session_id, job_id, limit=200)
    if not history:
        raise HTTPException(status_code=404, detail="Session not found")
    return [MessageItem(**m) for m in history]


@router.delete("/{job_id}/agent/sessions/{session_id}", response_model=DeleteSessionResponse)
def delete_session(
    job_id: int,
    session_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> DeleteSessionResponse:
    """Clear all messages in a session (wipes memory for that session)."""
    _load_job_or_404(job_id, db, current_user)
    deleted = clear_session(session_id, job_id)
    return DeleteSessionResponse(deleted_messages=deleted)


@router.get("/{job_id}/agent/ui", response_class=HTMLResponse)
def agent_ui(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> HTMLResponse:
    """Browser chat UI for the P&ID agent."""
    _load_job_or_404(job_id, db, current_user)

    # Only the tiny HTML fragments that need job_id use an f-string.
    # The CSS and JS blocks are plain strings so { } never need escaping.
    head = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>P&ID Agent — Job {job_id}</title>"""

    css = """
<style>
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#0f1117;color:#e2e8f0;
     display:flex;flex-direction:column;height:100vh}
header{background:#1a1d27;border-bottom:1px solid #2d3148;
       padding:12px 20px;display:flex;align-items:center;gap:12px;flex-shrink:0}
header h1{font-size:15px;font-weight:600;color:#a78bfa}
header span{font-size:12px;color:#64748b}
#session-bar{background:#13151f;border-bottom:1px solid #1e2235;
             padding:8px 16px;display:flex;align-items:center;
             gap:10px;flex-shrink:0;font-size:12px}
#session-bar label{color:#64748b}
#sid-display{color:#7dd3fc;font-family:monospace;font-size:11px;
             max-width:280px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.btn-sm{background:#1e2235;border:1px solid #2d3148;color:#94a3b8;
        border-radius:4px;padding:3px 10px;font-size:11px;cursor:pointer}
.btn-sm:hover{background:#252a40;color:#e2e8f0}
#messages{flex:1;overflow-y:auto;padding:20px;display:flex;flex-direction:column;gap:16px}
.msg{max-width:720px;display:flex;flex-direction:column;gap:4px}
.msg.user{align-self:flex-end;align-items:flex-end}
.msg.assistant{align-self:flex-start;align-items:flex-start}
.bubble{padding:10px 14px;border-radius:12px;font-size:14px;
        line-height:1.6;white-space:pre-wrap;word-break:break-word}
.user .bubble{background:#4f46e5;color:#fff;border-bottom-right-radius:3px}
.assistant .bubble{background:#1e2235;color:#e2e8f0;border:1px solid #2d3148;
                   border-bottom-left-radius:3px}
.meta{font-size:10px;color:#475569;padding:0 4px}
.thinking{color:#7dd3fc;font-size:12px;font-style:italic;animation:pulse 1.2s infinite}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
#input-area{background:#1a1d27;border-top:1px solid #2d3148;
            padding:14px 20px;display:flex;gap:10px;flex-shrink:0}
#msg-input{flex:1;background:#0f1117;border:1px solid #2d3148;border-radius:8px;
           color:#e2e8f0;font-size:14px;padding:10px 14px;resize:none;
           outline:none;line-height:1.5}
#msg-input:focus{border-color:#4f46e5}
#send-btn{background:#4f46e5;color:#fff;border:none;border-radius:8px;
          padding:10px 20px;font-size:14px;font-weight:600;cursor:pointer;white-space:nowrap}
#send-btn:hover{background:#4338ca}
#send-btn:disabled{background:#2d3148;color:#475569;cursor:not-allowed}
#ctx-bar{font-size:11px;color:#475569;padding:4px 20px 0;flex-shrink:0;min-height:18px}
.ctx-pill{display:inline-block;background:#1e2235;border:1px solid #2d3148;
          border-radius:10px;padding:1px 8px;margin-right:6px;color:#7dd3fc}
#sessions-panel{position:fixed;right:0;top:0;bottom:0;width:280px;
                background:#13151f;border-left:1px solid #2d3148;
                transform:translateX(100%);transition:transform .25s;
                display:flex;flex-direction:column;z-index:50}
#sessions-panel.open{transform:translateX(0)}
#sessions-panel h2{padding:16px;font-size:13px;color:#94a3b8;
                   border-bottom:1px solid #2d3148;font-weight:600}
#sessions-list{flex:1;overflow-y:auto;padding:8px}
.sitem{padding:10px 12px;border-radius:6px;cursor:pointer;
       margin-bottom:4px;border:1px solid transparent}
.sitem:hover{background:#1e2235;border-color:#2d3148}
.sitem.active{background:#1e2235;border-color:#4f46e5}
.sitem .sid{font-size:11px;font-family:monospace;color:#7dd3fc;
            overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.sitem .smeta{font-size:10px;color:#475569;margin-top:2px}
#panel-close{position:absolute;top:12px;right:12px;background:none;
             border:none;color:#64748b;cursor:pointer;font-size:18px}
</style>
</head>"""

    body_html = f"""
<body>
<header>
  <div>
    <h1>P&amp;ID Agent &mdash; Job {job_id}</h1>
    <span>Neo4j Agent Memory &bull; Ask anything about this P&amp;ID</span>
  </div>
  <div style="margin-left:auto;display:flex;gap:8px;align-items:center;">
    <button id="new-btn" class="btn-sm">+ New Session</button>
    <button id="toggle-btn" class="btn-sm">Sessions &#9776;</button>
  </div>
</header>
<div id="session-bar">
  <label>Session:</label>
  <span id="sid-display">—</span>
  <button class="btn-sm" id="copy-btn">Copy</button>
  <button class="btn-sm" id="clear-btn" style="color:#f87171">Clear</button>
</div>
<div id="ctx-bar"></div>
<div id="messages"></div>
<div id="input-area">
  <textarea id="msg-input" rows="1"
    placeholder="Ask about this P&amp;ID… e.g. Which valves connect to pressure instruments?"></textarea>
  <button id="send-btn">Send</button>
</div>
<div id="sessions-panel">
  <button id="panel-close">&times;</button>
  <h2>Past Sessions</h2>
  <div id="sessions-list"></div>
</div>
<script>
var JOB_ID = {job_id};
</script>"""

    # JS block as a plain string — no {{ }} escaping needed at all.
    js = """
<script>
var sessionId = null;

function genUUID() {
  return 'xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx'.replace(/[xy]/g, function(c) {
    var r = Math.random() * 16 | 0;
    return (c === 'x' ? r : (r & 0x3 | 0x8)).toString(16);
  });
}

function setSession(id) {
  sessionId = id;
  document.getElementById('sid-display').textContent = id;
}

function startNewSession() {
  setSession(genUUID());
  document.getElementById('messages').innerHTML = '';
  document.getElementById('ctx-bar').innerHTML = '';
}

function appendMessage(role, content, meta) {
  var box = document.getElementById('messages');
  var wrap = document.createElement('div');
  wrap.className = 'msg ' + role;
  var bubble = document.createElement('div');
  bubble.className = 'bubble';
  bubble.textContent = content;
  wrap.appendChild(bubble);
  if (meta) {
    var m = document.createElement('div');
    m.className = 'meta';
    m.textContent = meta;
    wrap.appendChild(m);
  }
  box.appendChild(wrap);
  box.scrollTop = box.scrollHeight;
}

function showThinking() {
  var box = document.getElementById('messages');
  var div = document.createElement('div');
  div.className = 'msg assistant';
  div.id = 'thinking';
  div.innerHTML = '<div class="bubble thinking">Agent is thinking…</div>';
  box.appendChild(div);
  box.scrollTop = box.scrollHeight;
}

function removeThinking() {
  var el = document.getElementById('thinking');
  if (el) el.remove();
}

function sendMessage() {
  var input = document.getElementById('msg-input');
  var text = input.value.trim();
  if (!text) return;
  input.value = '';
  input.style.height = 'auto';
  document.getElementById('send-btn').disabled = true;
  document.getElementById('ctx-bar').innerHTML = '';
  appendMessage('user', text);
  showThinking();

  fetch('/api/v1/jobs/' + JOB_ID + '/agent/chat', {
    method: 'POST',
    credentials: 'include',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({message: text, session_id: sessionId})
  })
  .then(function(res) {
    removeThinking();
    if (!res.ok) {
      return res.json().catch(function() { return {}; }).then(function(e) {
        appendMessage('assistant', '⚠ Error: ' + (e.detail || res.status));
      });
    }
    return res.json().then(function(data) {
      if (data.session_id !== sessionId) setSession(data.session_id);
      appendMessage('assistant', data.reply,
        'P&ID nodes: ' + data.pid_nodes_used + ' · Memories: ' + data.memories_retrieved + ' retrieved, ' + data.memories_stored + ' stored');
      var pills = '';
      if (data.pid_nodes_used > 0)
        pills += '<span class="ctx-pill">📍 ' + data.pid_nodes_used + ' instruments</span>';
      if (data.memories_retrieved > 0)
        pills += '<span class="ctx-pill">🧠 ' + data.memories_retrieved + ' memories</span>';
      if (data.memories_stored > 0)
        pills += '<span class="ctx-pill">💾 ' + data.memories_stored + ' stored</span>';
      document.getElementById('ctx-bar').innerHTML = pills;
      refreshSessions();
    });
  })
  .catch(function(e) {
    removeThinking();
    appendMessage('assistant', '⚠ Network error: ' + e.message);
  })
  .finally(function() {
    document.getElementById('send-btn').disabled = false;
    input.focus();
  });
}

function loadSession(sid) {
  setSession(sid);
  document.getElementById('messages').innerHTML = '';
  document.getElementById('ctx-bar').innerHTML = '';
  document.getElementById('sessions-panel').classList.remove('open');
  fetch('/api/v1/jobs/' + JOB_ID + '/agent/sessions/' + sid, {credentials: 'include'})
  .then(function(r) { return r.ok ? r.json() : []; })
  .then(function(msgs) {
    msgs.forEach(function(m) { appendMessage(m.role, m.content); });
  })
  .catch(function(e) { console.error(e); });
}

function refreshSessions() {
  fetch('/api/v1/jobs/' + JOB_ID + '/agent/sessions', {credentials: 'include'})
  .then(function(r) { return r.ok ? r.json() : []; })
  .then(function(sessions) {
    var list = document.getElementById('sessions-list');
    list.innerHTML = '';
    if (!sessions.length) {
      list.innerHTML = '<div style="padding:16px;color:#475569;font-size:12px">No sessions yet.</div>';
      return;
    }
    sessions.forEach(function(s) {
      var el = document.createElement('div');
      el.className = 'sitem' + (s.session_id === sessionId ? ' active' : '');
      var short = s.session_id.slice(0, 8) + '…';
      var dt = s.last_message_at ? new Date(s.last_message_at).toLocaleString() : '';
      el.innerHTML = '<div class="sid">' + short + '</div>' +
        '<div class="smeta">' + s.message_count + ' messages • ' + dt + '</div>';
      el.addEventListener('click', function() { loadSession(s.session_id); });
      list.appendChild(el);
    });
  })
  .catch(function(e) { console.error(e); });
}

function clearCurrentSession() {
  if (!sessionId) return;
  if (!confirm('Clear all messages in this session?')) return;
  fetch('/api/v1/jobs/' + JOB_ID + '/agent/sessions/' + sessionId,
    {method: 'DELETE', credentials: 'include'})
  .then(function() {
    document.getElementById('messages').innerHTML = '';
    document.getElementById('ctx-bar').innerHTML = '';
    refreshSessions();
  })
  .catch(function(e) { alert('Failed: ' + e.message); });
}

document.getElementById('msg-input').addEventListener('input', function() {
  this.style.height = 'auto';
  this.style.height = Math.min(this.scrollHeight, 140) + 'px';
});
document.getElementById('msg-input').addEventListener('keydown', function(ev) {
  if (ev.key === 'Enter' && !ev.shiftKey) { ev.preventDefault(); sendMessage(); }
});
document.getElementById('send-btn').addEventListener('click', sendMessage);
document.getElementById('new-btn').addEventListener('click', startNewSession);
document.getElementById('clear-btn').addEventListener('click', clearCurrentSession);
document.getElementById('copy-btn').addEventListener('click', function() {
  navigator.clipboard.writeText(sessionId || '');
});
document.getElementById('toggle-btn').addEventListener('click', function() {
  document.getElementById('sessions-panel').classList.toggle('open');
  refreshSessions();
});
document.getElementById('panel-close').addEventListener('click', function() {
  document.getElementById('sessions-panel').classList.remove('open');
});

startNewSession();
var welcomeLines = [
  'Hello! I am your P&ID assistant.',
  '',
  'I can answer questions about the instruments, valves, and connections in this drawing.',
  'I remember our past conversations so you do not need to repeat context.',
  '',
  'Try asking:',
  '• Which valves are connected to pressure instruments?',
  '• List all check valves and their connections',
  '• What instruments connect to 8-VB-017?'
];
appendMessage('assistant', welcomeLines.join('\\n'));
</script>
</body>
</html>"""

    return HTMLResponse(content=head + css + body_html + js)


@router.get("/{job_id}/agent/memory", response_model=MemoryListResponse)
def list_memories(
    job_id: int,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> MemoryListResponse:
    """List all stored memories (facts, preferences, decisions, tasks) for this job."""
    _load_job_or_404(job_id, db, current_user)
    items = get_all_memories(job_id)
    return MemoryListResponse(
        count=len(items),
        memories=[MemoryItem(**m) for m in items],
    )


@router.post("/{job_id}/agent/memory/{memory_id}/done", response_model=TaskDoneResponse)
def mark_task_done(
    job_id: int,
    memory_id: str,
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> TaskDoneResponse:
    """Mark a task memory as completed."""
    _load_job_or_404(job_id, db, current_user)
    ok = complete_task(memory_id, job_id)
    return TaskDoneResponse(success=ok)


@router.get("/{job_id}/agent/memory/search", response_model=MemorySearchResponse)
def memory_search(
    job_id: int,
    q: str = Query(..., min_length=2, description="Search query"),
    limit: int = Query(10, ge=1, le=50),
    db: Session = Depends(get_db),
    current_user: models.User = Depends(get_current_user),
) -> MemorySearchResponse:
    """Fulltext search over all stored episode memories for this job."""
    _load_job_or_404(job_id, db, current_user)
    results = search_memory(q, job_id, limit=limit)
    return MemorySearchResponse(query=q, count=len(results), results=results)
