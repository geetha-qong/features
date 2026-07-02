"""Neo4j Agent Memory Service.

Two-layer memory backed by Neo4j:

  Layer 1 — Episodes  (:Episode)
    Raw conversation turns (user + assistant). Used for session-level
    continuity and fulltext search over past conversations.

  Layer 2 — Memories  (:Memory)
    Structured extractions from conversations: facts, preferences, decisions,
    and tasks. Extracted by the LLM after each exchange and stored as typed
    nodes. Retrieved on every subsequent query so the agent never forgets
    important context.

Neo4j schema:
  (:Episode {id, session_id, role, content, job_id, created_at})
  (:Memory  {id, job_id, session_id, type, content, tags, status, created_at})
    type   : "fact" | "preference" | "decision" | "task"
    status : "open" | "done"  (tasks only; facts/prefs/decisions are always "open")
    tags   : list of instrument tag strings mentioned in the memory

  FULLTEXT INDEX episode_content  ON Episode(content)
  FULLTEXT INDEX memory_content   ON Memory(content)
  CONSTRAINT episode_id_unique    ON Episode(id) IS UNIQUE
  CONSTRAINT memory_id_unique     ON Memory(id)  IS UNIQUE
"""
from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_NEO4J_URI      = os.environ.get("NEO4J_URI",  "bolt://neo4j:7687")
_NEO4J_USER     = os.environ.get("NEO4J_USER", "neo4j")
_NEO4J_PASSWORD = os.environ.get("NEO4J_PASSWORD")

_OPENROUTER_BASE  = "https://openrouter.ai/api/v1"
_EXTRACTION_MODEL = "google/gemini-2.0-flash-001"   # cheap + fast for extraction


def _neo4j_enabled() -> bool:
    """Neo4j is opt-in (removed from the runtime, FEATURES #118). When
    NEO4J_PASSWORD is unset, skip all Neo4j work WITHOUT touching the driver —
    resolving the absent ``neo4j`` host is slow (~30s DNS failure) and would
    block the worker pool, slowing every page (FEATURES #119)."""
    return bool(os.environ.get("NEO4J_PASSWORD"))


def _get_driver():
    if not _neo4j_enabled():
        raise RuntimeError("neo4j disabled (NEO4J_PASSWORD unset)")
    from neo4j import GraphDatabase
    return GraphDatabase.driver(_NEO4J_URI, auth=(_NEO4J_USER, _NEO4J_PASSWORD))


# ── Schema bootstrap ──────────────────────────────────────────────────────────

def initialize_schema() -> None:
    """Create Neo4j constraints + fulltext indexes. Idempotent."""
    if not _neo4j_enabled():
        logger.info("agent_memory: Neo4j disabled (NEO4J_PASSWORD unset); skipping schema init")
        return
    try:
        drv = _get_driver()
        with drv.session() as s:
            s.run("""
                CREATE CONSTRAINT episode_id_unique IF NOT EXISTS
                FOR (e:Episode) REQUIRE e.id IS UNIQUE
            """)
            s.run("""
                CREATE FULLTEXT INDEX episode_content IF NOT EXISTS
                FOR (e:Episode) ON EACH [e.content]
            """)
            s.run("""
                CREATE CONSTRAINT memory_id_unique IF NOT EXISTS
                FOR (m:Memory) REQUIRE m.id IS UNIQUE
            """)
            s.run("""
                CREATE FULLTEXT INDEX memory_content IF NOT EXISTS
                FOR (m:Memory) ON EACH [m.content]
            """)
        drv.close()
        logger.info("agent_memory: Neo4j schema initialized")
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: schema init failed (non-fatal): %s", exc)


# ── Episode write / read ──────────────────────────────────────────────────────

def store_episode(session_id: str, role: str, content: str, job_id: int) -> str:
    """Store one conversation turn as an (:Episode) node. Returns episode id."""
    ep_id = str(uuid.uuid4())
    try:
        drv = _get_driver()
        with drv.session() as s:
            s.run(
                """
                CREATE (e:Episode {
                    id:         $id,
                    session_id: $session_id,
                    role:       $role,
                    content:    $content,
                    job_id:     $job_id,
                    created_at: datetime()
                })
                """,
                id=ep_id, session_id=session_id,
                role=role, content=content, job_id=int(job_id),
            )
        drv.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: store_episode failed: %s", exc)
    return ep_id


def get_session_history(session_id: str, job_id: int, limit: int = 20) -> List[Dict[str, Any]]:
    """Conversation history for a session, oldest → newest. Scoped to (session_id, job_id)."""
    try:
        drv = _get_driver()
        with drv.session() as s:
            result = s.run(
                """
                MATCH (e:Episode {session_id: $session_id, job_id: $job_id})
                RETURN e.role AS role, e.content AS content,
                       toString(e.created_at) AS created_at
                ORDER BY e.created_at ASC
                LIMIT $limit
                """,
                session_id=session_id, job_id=int(job_id), limit=limit,
            )
            rows = [{"role": r["role"], "content": r["content"],
                     "created_at": r["created_at"]} for r in result]
        drv.close()
        return rows
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: get_session_history failed: %s", exc)
        return []


def clear_session(session_id: str, job_id: int) -> int:
    """Delete all Episode nodes for a session. Returns count deleted."""
    try:
        drv = _get_driver()
        with drv.session() as s:
            result = s.run(
                """
                MATCH (e:Episode {session_id: $session_id, job_id: $job_id})
                WITH count(e) AS n, collect(e) AS eps
                FOREACH (e IN eps | DETACH DELETE e)
                RETURN n
                """,
                session_id=session_id, job_id=int(job_id),
            )
            rec = result.single()
            count = int(rec["n"]) if rec else 0
        drv.close()
        return count
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: clear_session failed: %s", exc)
        return 0


def list_sessions(job_id: int) -> List[Dict[str, Any]]:
    """List all sessions for a job with message count and timestamps."""
    try:
        drv = _get_driver()
        with drv.session() as s:
            result = s.run(
                """
                MATCH (e:Episode {job_id: $job_id})
                WITH e.session_id AS session_id,
                     count(e)     AS message_count,
                     toString(min(e.created_at)) AS started_at,
                     toString(max(e.created_at)) AS last_message_at
                RETURN session_id, message_count, started_at, last_message_at
                ORDER BY last_message_at DESC
                """,
                job_id=int(job_id),
            )
            return [dict(r) for r in result]
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: list_sessions failed: %s", exc)
        return []


def search_memory(query: str, job_id: int, limit: int = 5) -> List[str]:
    """Fulltext search over stored Episodes for this job."""
    try:
        drv = _get_driver()
        with drv.session() as s:
            result = s.run(
                """
                CALL db.index.fulltext.queryNodes('episode_content', $search_query)
                YIELD node, score
                WHERE node.job_id = $job_id
                RETURN node.content AS content, score
                ORDER BY score DESC
                LIMIT $limit
                """,
                search_query=query, job_id=int(job_id), limit=limit,
            )
            rows = [r["content"] for r in result]
        drv.close()
        return rows
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: search_memory failed: %s", exc)
        return []


# ── Memory (structured extractions) write / read ──────────────────────────────

def store_memory(
    job_id: int,
    session_id: str,
    memory_type: str,
    content: str,
    tags: Optional[List[str]] = None,
) -> str:
    """Store a single extracted memory node. Returns memory id.

    memory_type must be one of: fact | preference | decision | task
    """
    mem_id = str(uuid.uuid4())
    try:
        drv = _get_driver()
        with drv.session() as s:
            s.run(
                """
                CREATE (m:Memory {
                    id:         $id,
                    job_id:     $job_id,
                    session_id: $session_id,
                    type:       $type,
                    content:    $content,
                    tags:       $tags,
                    status:     'open',
                    created_at: datetime()
                })
                """,
                id=mem_id, job_id=int(job_id), session_id=session_id,
                type=memory_type, content=content,
                tags=tags or [],
            )
        drv.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: store_memory failed: %s", exc)
    return mem_id


def retrieve_memories(query: str, job_id: int, limit: int = 10) -> List[Dict[str, Any]]:
    """Search Memory nodes by fulltext AND return all open tasks.

    Returns a list of dicts: {id, type, content, tags, status}
    Tasks are always included regardless of query relevance.
    """
    memories: List[Dict[str, Any]] = []
    seen_ids: set = set()

    try:
        drv = _get_driver()
        with drv.session() as s:
            # Always load open tasks so agent tracks them across turns
            task_result = s.run(
                """
                MATCH (m:Memory {job_id: $job_id, type: 'task', status: 'open'})
                RETURN m.id AS id, m.type AS type, m.content AS content,
                       m.tags AS tags, m.status AS status
                ORDER BY m.created_at ASC
                """,
                job_id=int(job_id),
            )
            for r in task_result:
                memories.append({
                    "id": r["id"], "type": r["type"],
                    "content": r["content"], "tags": r["tags"] or [],
                    "status": r["status"],
                })
                seen_ids.add(r["id"])

            # Fulltext search over all Memory nodes for this job
            try:
                ft_result = s.run(
                    """
                    CALL db.index.fulltext.queryNodes('memory_content', $search_query)
                    YIELD node, score
                    WHERE node.job_id = $job_id AND node.status = 'open'
                    RETURN node.id AS id, node.type AS type, node.content AS content,
                           node.tags AS tags, node.status AS status
                    ORDER BY score DESC
                    LIMIT $limit
                    """,
                    search_query=query, job_id=int(job_id), limit=limit,
                )
                for r in ft_result:
                    if r["id"] not in seen_ids:
                        memories.append({
                            "id": r["id"], "type": r["type"],
                            "content": r["content"], "tags": r["tags"] or [],
                            "status": r["status"],
                        })
                        seen_ids.add(r["id"])
            except Exception:
                pass  # fulltext index not ready yet — tasks still returned

        drv.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: retrieve_memories failed: %s", exc)

    return memories


def complete_task(memory_id: str, job_id: int) -> bool:
    """Mark a task Memory node as done."""
    try:
        drv = _get_driver()
        with drv.session() as s:
            s.run(
                """
                MATCH (m:Memory {id: $id, job_id: $job_id, type: 'task'})
                SET m.status = 'done'
                """,
                id=memory_id, job_id=int(job_id),
            )
        drv.close()
        return True
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: complete_task failed: %s", exc)
        return False


def get_all_memories(job_id: int) -> List[Dict[str, Any]]:
    """List all stored memories for a job (for the /memory endpoint)."""
    try:
        drv = _get_driver()
        with drv.session() as s:
            result = s.run(
                """
                MATCH (m:Memory {job_id: $job_id})
                RETURN m.id AS id, m.type AS type, m.content AS content,
                       m.tags AS tags, m.status AS status,
                       toString(m.created_at) AS created_at
                ORDER BY m.created_at DESC
                """,
                job_id=int(job_id),
            )
            return [dict(r) for r in result]
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: get_all_memories failed: %s", exc)
        return []


# ── Memory extraction ─────────────────────────────────────────────────────────

_EXTRACTION_SYSTEM = (
    "You are a memory extraction assistant for a P&ID engineering agent. "
    "Given a conversation exchange, extract any facts, preferences, decisions, "
    "or tasks worth remembering for future conversations. "
    "Return ONLY a valid JSON array (no markdown, no explanation). "
    "Each element: {\"type\": \"fact|preference|decision|task\", "
    "\"content\": \"<one concise sentence>\", "
    "\"tags\": [\"<instrument tag>\", ...]}. "
    "If nothing important, return []."
)

_EXTRACTION_EXAMPLES = (
    "Examples:\n"
    "- User says 'remember I prefer metric units' → "
    "{\"type\":\"preference\",\"content\":\"User prefers metric units\",\"tags\":[]}\n"
    "- Discussion confirms valve 8-VB-017 is normally closed → "
    "{\"type\":\"fact\",\"content\":\"Valve 8-VB-017 is normally closed\",\"tags\":[\"8-VB-017\"]}\n"
    "- Team decides to replace CV-201 → "
    "{\"type\":\"decision\",\"content\":\"Team decided to replace CV-201\",\"tags\":[\"CV-201\"]}\n"
    "- User says 'check if PI-305 is calibrated' → "
    "{\"type\":\"task\",\"content\":\"Check if PI-305 is calibrated\",\"tags\":[\"PI-305\"]}\n"
    "Only extract genuinely important information — skip generic Q&A."
)


def extract_and_store_memories(
    user_message: str,
    assistant_reply: str,
    job_id: int,
    session_id: str,
) -> List[str]:
    """Call LLM to extract memories from a conversation exchange and store them.

    Uses a cheap/fast model (gemini-2.0-flash-001) to minimise latency.
    Returns list of stored memory IDs (empty if nothing extracted or on error).
    """
    api_key = os.environ.get("OPENROUTER_API_KEY")
    if not api_key:
        return []

    prompt = (
        f"{_EXTRACTION_EXAMPLES}\n\n"
        f"Now extract from this exchange:\n"
        f"User: {user_message[:500]}\n"
        f"Assistant: {assistant_reply[:800]}\n\n"
        "Return JSON array only:"
    )

    try:
        from openai import OpenAI
        client = OpenAI(api_key=api_key, base_url=_OPENROUTER_BASE)
        resp = client.chat.completions.create(
            model=_EXTRACTION_MODEL,
            messages=[
                {"role": "system", "content": _EXTRACTION_SYSTEM},
                {"role": "user",   "content": prompt},
            ],
            max_tokens=512,
            temperature=0,
        )
        raw = (resp.choices[0].message.content or "").strip()
        # Strip markdown fences if present
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        extracted = json.loads(raw)
        if not isinstance(extracted, list):
            return []
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: extraction LLM call failed: %s", exc)
        return []

    stored_ids: List[str] = []
    valid_types = {"fact", "preference", "decision", "task"}
    for item in extracted:
        if not isinstance(item, dict):
            continue
        mem_type = str(item.get("type", "")).lower()
        content  = str(item.get("content", "")).strip()
        tags     = [str(t) for t in (item.get("tags") or []) if t]
        if mem_type not in valid_types or not content:
            continue
        mem_id = store_memory(job_id, session_id, mem_type, content, tags)
        stored_ids.append(mem_id)
        logger.info("agent_memory: stored %s memory: %s", mem_type, content[:80])

    return stored_ids


# ── P&ID graph context ────────────────────────────────────────────────────────

def get_pid_context(job_id: int, query: str) -> Dict[str, Any]:
    """Fetch P&ID context from Neo4j — same source as the digital twin.

    Always returns:
      class_counts   — {class_name: count} for every node class (accurate totals)
      total_edges    — total number of PIPE connections in this P&ID
      matching_nodes — all nodes whose tag/class/label matches query keywords (up to 500)
      connections    — PIPE neighbours of the first 30 matched nodes
    """
    try:
        drv = _get_driver()
        with drv.session() as s:
            # 1. Class-level aggregation — always present so "how many X" is accurate
            class_counts: Dict[str, int] = {}
            for r in s.run(
                """
                MATCH (n:Node {job_id: $job_id, source: 'auto'})
                WHERE n.class IS NOT NULL
                RETURN n.class AS cls, count(n) AS cnt
                ORDER BY cnt DESC
                """,
                job_id=int(job_id),
            ):
                if r["cls"]:
                    class_counts[r["cls"]] = r["cnt"]

            # 2. Total edge count
            edge_rec = s.run(
                """
                MATCH ()-[e:PIPE {job_id: $job_id, source: 'auto'}]->()
                RETURN count(e) AS cnt
                """,
                job_id=int(job_id),
            ).single()
            total_edges = int(edge_rec["cnt"]) if edge_rec else 0

            # 3. Keyword match — cap at 500 so full class lists come through
            words = [w for w in query.lower().split() if len(w) > 2]
            matching: List[Dict] = []
            if words:
                pattern = "(?i)" + "|".join(words)
                for r in s.run(
                    """
                    MATCH (n:Node {job_id: $job_id, source: 'auto'})
                    WHERE n.tag =~ $pattern
                       OR n.class =~ $pattern
                       OR n.label =~ $pattern
                    RETURN n.id AS id, n.tag AS tag, n.class AS cls, n.label AS label
                    ORDER BY n.class, n.tag
                    LIMIT 500
                    """,
                    job_id=int(job_id), pattern=pattern,
                ):
                    matching.append({"id": r["id"], "tag": r["tag"],
                                     "class": r["cls"], "label": r["label"]})

            # 4. Connections for first 30 matched nodes
            connections: List[Dict] = []
            for node in matching[:30]:
                for r in s.run(
                    """
                    MATCH (n:Node {id: $node_id, job_id: $job_id})-[e:PIPE]-(other:Node)
                    RETURN other.tag AS tag, other.class AS cls,
                           e.line_type AS line_type
                    LIMIT 10
                    """,
                    node_id=node["id"], job_id=int(job_id),
                ):
                    connections.append({
                        "from_tag": node["tag"],
                        "from_class": node["class"],
                        "to_tag": r["tag"],
                        "to_class": r["cls"],
                        "line_type": r["line_type"] or "pipe",
                    })

        drv.close()
        return {
            "class_counts": class_counts,
            "total_edges": total_edges,
            "matching_nodes": matching,
            "connections": connections,
        }
    except Exception as exc:  # noqa: BLE001
        logger.warning("agent_memory: get_pid_context failed: %s", exc)
        return {"class_counts": {}, "total_edges": 0, "matching_nodes": [], "connections": []}
