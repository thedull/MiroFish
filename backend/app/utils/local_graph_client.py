"""
Local Knowledge Graph Client — drop-in replacement for zep-cloud.

Stores graph data in SQLite, uses the configured LLM for entity/relationship
extraction from text, and performs keyword-based search. The public interface
mirrors the subset of the Zep Cloud SDK used by MiroFish so no other service
needs to know which backend is active.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .logger import get_logger

logger = get_logger('mirofish.local_graph')


# ---------------------------------------------------------------------------
# Public exceptions (mirror zep_cloud exceptions used in zep_paging.py)
# ---------------------------------------------------------------------------

class LocalGraphError(Exception):
    """Mirrors zep_cloud.InternalServerError for retry-logic compatibility."""
    pass


class LocalSearchUnavailable(Exception):
    """Raised by graph.search() to trigger keyword-search fallback."""
    pass


# ---------------------------------------------------------------------------
# Data objects (mirror Zep SDK response objects)
# ---------------------------------------------------------------------------

@dataclass
class LocalNode:
    uuid_: str
    name: str
    labels: List[str]
    summary: str
    attributes: Dict[str, Any]
    created_at: Optional[str] = None


@dataclass
class LocalEdge:
    uuid_: str
    name: str
    fact: str
    source_node_uuid: str
    target_node_uuid: str
    attributes: Dict[str, Any]
    created_at: Optional[str] = None
    valid_at: Optional[str] = None
    invalid_at: Optional[str] = None
    expired_at: Optional[str] = None


@dataclass
class LocalEpisode:
    uuid_: str
    data: str
    type: str = "text"
    processed: bool = True  # always immediately processed locally


@dataclass
class LocalEpisodeData:
    """Input episode for add_batch — mirrors zep_cloud.EpisodeData."""
    data: str
    type: str = "text"


# ---------------------------------------------------------------------------
# SQLite storage
# ---------------------------------------------------------------------------

_SCHEMA = """
CREATE TABLE IF NOT EXISTS graphs (
    graph_id    TEXT PRIMARY KEY,
    name        TEXT,
    description TEXT,
    ontology    TEXT,
    created_at  TEXT
);
CREATE TABLE IF NOT EXISTS nodes (
    uuid          TEXT PRIMARY KEY,
    graph_id      TEXT NOT NULL,
    name          TEXT NOT NULL,
    name_lower    TEXT NOT NULL,
    primary_label TEXT,
    labels        TEXT,
    summary       TEXT,
    attributes    TEXT,
    created_at    TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_node_identity
    ON nodes (graph_id, name_lower, primary_label);
CREATE INDEX IF NOT EXISTS idx_node_graph ON nodes (graph_id);
CREATE TABLE IF NOT EXISTS edges (
    uuid             TEXT PRIMARY KEY,
    graph_id         TEXT NOT NULL,
    name             TEXT,
    fact             TEXT,
    source_node_uuid TEXT,
    target_node_uuid TEXT,
    attributes       TEXT,
    created_at       TEXT,
    valid_at         TEXT,
    invalid_at       TEXT,
    expired_at       TEXT
);
CREATE INDEX IF NOT EXISTS idx_edge_graph   ON edges (graph_id);
CREATE INDEX IF NOT EXISTS idx_edge_source  ON edges (source_node_uuid);
CREATE INDEX IF NOT EXISTS idx_edge_target  ON edges (target_node_uuid);
CREATE TABLE IF NOT EXISTS episodes (
    uuid       TEXT PRIMARY KEY,
    graph_id   TEXT NOT NULL,
    data       TEXT,
    type       TEXT DEFAULT 'text',
    processed  INTEGER DEFAULT 1,
    created_at TEXT
);
"""


class LocalGraphDB:
    """Thread-safe SQLite backend for graph storage."""

    def __init__(self, db_path: str):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._write_lock = threading.Lock()
        with self._open() as conn:
            conn.executescript(_SCHEMA)

    def _open(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        return conn

    # --- Graph ---

    def create_graph(self, graph_id: str, name: str, description: str):
        with self._write_lock, self._open() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO graphs (graph_id, name, description, created_at) VALUES (?,?,?,?)",
                (graph_id, name, description, _now()),
            )

    def set_ontology(self, graph_id: str, ontology: dict):
        with self._write_lock, self._open() as conn:
            conn.execute(
                "UPDATE graphs SET ontology=? WHERE graph_id=?",
                (json.dumps(ontology, ensure_ascii=False), graph_id),
            )

    def get_ontology(self, graph_id: str) -> Optional[dict]:
        with self._open() as conn:
            row = conn.execute(
                "SELECT ontology FROM graphs WHERE graph_id=?", (graph_id,)
            ).fetchone()
        if row and row["ontology"]:
            return json.loads(row["ontology"])
        return None

    def delete_graph(self, graph_id: str):
        with self._write_lock, self._open() as conn:
            for table in ("edges", "nodes", "episodes", "graphs"):
                conn.execute(f"DELETE FROM {table} WHERE graph_id=?", (graph_id,))

    # --- Nodes ---

    def upsert_node(
        self, graph_id: str, name: str, labels: List[str], summary: str, attributes: dict
    ) -> str:
        primary_label = next((l for l in labels if l not in ("Entity", "Node")), "Entity")
        name_lower = name.lower().strip()
        node_uuid = _stable_uuid(graph_id, name_lower, primary_label)
        with self._write_lock, self._open() as conn:
            existing = conn.execute(
                "SELECT summary FROM nodes WHERE uuid=?", (node_uuid,)
            ).fetchone()
            if existing:
                old = existing["summary"] or ""
                merged = summary if len(summary) > len(old) else old
                conn.execute("UPDATE nodes SET summary=? WHERE uuid=?", (merged, node_uuid))
            else:
                conn.execute(
                    """INSERT INTO nodes
                       (uuid, graph_id, name, name_lower, primary_label, labels,
                        summary, attributes, created_at)
                       VALUES (?,?,?,?,?,?,?,?,?)""",
                    (
                        node_uuid, graph_id, name, name_lower, primary_label,
                        json.dumps(labels), summary, json.dumps(attributes), _now(),
                    ),
                )
        return node_uuid

    def get_nodes(
        self, graph_id: str, limit: int = 100, cursor: Optional[str] = None
    ) -> List[LocalNode]:
        with self._open() as conn:
            if cursor:
                rows = conn.execute(
                    "SELECT * FROM nodes WHERE graph_id=? AND uuid > ? ORDER BY uuid LIMIT ?",
                    (graph_id, cursor, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM nodes WHERE graph_id=? ORDER BY uuid LIMIT ?",
                    (graph_id, limit),
                ).fetchall()
        return [_row_to_node(r) for r in rows]

    def get_node(self, node_uuid: str) -> Optional[LocalNode]:
        with self._open() as conn:
            row = conn.execute("SELECT * FROM nodes WHERE uuid=?", (node_uuid,)).fetchone()
        return _row_to_node(row) if row else None

    def get_node_edges(self, node_uuid: str) -> List[LocalEdge]:
        with self._open() as conn:
            rows = conn.execute(
                "SELECT * FROM edges WHERE source_node_uuid=? OR target_node_uuid=?",
                (node_uuid, node_uuid),
            ).fetchall()
        return [_row_to_edge(r) for r in rows]

    # --- Edges ---

    def insert_edge(
        self,
        graph_id: str,
        name: str,
        fact: str,
        source_uuid: str,
        target_uuid: str,
        attributes: dict,
    ) -> str:
        edge_uuid = str(uuid.uuid4())
        with self._write_lock, self._open() as conn:
            conn.execute(
                """INSERT INTO edges
                   (uuid, graph_id, name, fact, source_node_uuid, target_node_uuid,
                    attributes, created_at, valid_at)
                   VALUES (?,?,?,?,?,?,?,?,?)""",
                (
                    edge_uuid, graph_id, name, fact, source_uuid, target_uuid,
                    json.dumps(attributes), _now(), _now(),
                ),
            )
        return edge_uuid

    def get_edges(
        self, graph_id: str, limit: int = 100, cursor: Optional[str] = None
    ) -> List[LocalEdge]:
        with self._open() as conn:
            if cursor:
                rows = conn.execute(
                    "SELECT * FROM edges WHERE graph_id=? AND uuid > ? ORDER BY uuid LIMIT ?",
                    (graph_id, cursor, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    "SELECT * FROM edges WHERE graph_id=? ORDER BY uuid LIMIT ?",
                    (graph_id, limit),
                ).fetchall()
        return [_row_to_edge(r) for r in rows]

    def get_edge(self, edge_uuid: str) -> Optional[LocalEdge]:
        with self._open() as conn:
            row = conn.execute("SELECT * FROM edges WHERE uuid=?", (edge_uuid,)).fetchone()
        return _row_to_edge(row) if row else None

    # --- Episodes ---

    def insert_episode(self, graph_id: str, data: str, ep_type: str = "text") -> str:
        ep_uuid = str(uuid.uuid4())
        with self._write_lock, self._open() as conn:
            conn.execute(
                "INSERT INTO episodes (uuid, graph_id, data, type, processed, created_at) VALUES (?,?,?,?,1,?)",
                (ep_uuid, graph_id, data, ep_type, _now()),
            )
        return ep_uuid

    def get_episode(self, ep_uuid: str) -> Optional[LocalEpisode]:
        with self._open() as conn:
            row = conn.execute("SELECT * FROM episodes WHERE uuid=?", (ep_uuid,)).fetchone()
        if not row:
            return None
        return LocalEpisode(
            uuid_=row["uuid"],
            data=row["data"] or "",
            type=row["type"] or "text",
            processed=bool(row["processed"]),
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_uuid(graph_id: str, name_lower: str, label: str) -> str:
    """Deterministic UUID so the same entity always gets the same id."""
    key = f"{graph_id}:{label}:{name_lower}"
    digest = hashlib.md5(key.encode()).hexdigest()
    return str(uuid.UUID(digest))


def _row_to_node(row) -> LocalNode:
    return LocalNode(
        uuid_=row["uuid"],
        name=row["name"],
        labels=json.loads(row["labels"] or "[]"),
        summary=row["summary"] or "",
        attributes=json.loads(row["attributes"] or "{}"),
        created_at=row["created_at"],
    )


def _row_to_edge(row) -> LocalEdge:
    return LocalEdge(
        uuid_=row["uuid"],
        name=row["name"] or "",
        fact=row["fact"] or "",
        source_node_uuid=row["source_node_uuid"] or "",
        target_node_uuid=row["target_node_uuid"] or "",
        attributes=json.loads(row["attributes"] or "{}"),
        created_at=row["created_at"],
        valid_at=row["valid_at"],
        invalid_at=row["invalid_at"],
        expired_at=row["expired_at"],
    )


def _parse_json_from_text(text: str) -> dict:
    """Extract JSON object from LLM response, handling markdown fences."""
    cleaned = re.sub(r"^```(?:json)?\s*\n?", "", text.strip(), flags=re.IGNORECASE)
    cleaned = re.sub(r"\n?```\s*$", "", cleaned)
    cleaned = cleaned.strip()
    # Find the outermost { ... }
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start != -1 and end != -1:
        cleaned = cleaned[start : end + 1]
    return json.loads(cleaned)


# ---------------------------------------------------------------------------
# LLM extraction
# ---------------------------------------------------------------------------

_EXTRACTION_SYSTEM = (
    "You are a knowledge graph extractor. Extract named entities and relationships from text.\n\n"
    "Return ONLY a valid JSON object with this exact structure:\n"
    '{"nodes":[{"name":"exact name from text","label":"EntityType","summary":"one sentence"}],'
    '"edges":[{"name":"relationship_type","fact":"natural language statement","source":"entity name","target":"entity name"}]}\n\n'
    "Rules:\n"
    "- Only extract entities matching the given entity types\n"
    "- Every edge source/target must exactly match a node name\n"
    "- Return {\"nodes\":[],\"edges\":[]} if nothing found\n"
    "- Keep summaries under 120 characters"
)


def _extract_entities(llm, text: str, ontology: Optional[dict]) -> dict:
    """Call LLM to extract entities and relationships. Returns {nodes, edges}."""
    entity_types: List[str] = []
    edge_types: List[str] = []
    if ontology:
        entity_types = [e.get("name", "") for e in ontology.get("entity_types", [])]
        edge_types = [e.get("name", "") for e in ontology.get("edge_types", [])]

    schema_hint = ""
    if entity_types or edge_types:
        schema_hint = (
            f"\n\nOntology:\nEntity types: {', '.join(filter(None, entity_types))}"
            f"\nRelationship types: {', '.join(filter(None, edge_types))}"
        )

    messages = [
        {"role": "system", "content": _EXTRACTION_SYSTEM},
        {"role": "user", "content": f"{schema_hint}\n\nText:\n{text}"},
    ]

    try:
        return llm.chat_json(messages=messages, temperature=0.0)
    except Exception:
        # Fallback: try without JSON mode
        try:
            raw = llm.chat(messages=messages, temperature=0.0)
            return _parse_json_from_text(raw)
        except Exception as e2:
            logger.debug(f"LLM extraction fallback also failed: {e2}")
            return {"nodes": [], "edges": []}


# ---------------------------------------------------------------------------
# Namespace classes (mirror Zep SDK nested namespaces)
# ---------------------------------------------------------------------------

class _EpisodeNamespace:
    def __init__(self, db: LocalGraphDB):
        self._db = db

    def get(self, uuid_: str) -> Optional[LocalEpisode]:
        return self._db.get_episode(uuid_)


class _NodeNamespace:
    def __init__(self, db: LocalGraphDB):
        self._db = db

    def get_by_graph_id(
        self, graph_id: str, limit: int = 100, uuid_cursor: Optional[str] = None
    ) -> List[LocalNode]:
        return self._db.get_nodes(graph_id, limit=limit, cursor=uuid_cursor)

    def get(self, uuid_: str) -> Optional[LocalNode]:
        return self._db.get_node(uuid_)

    def get_entity_edges(self, node_uuid: str) -> List[LocalEdge]:
        return self._db.get_node_edges(node_uuid)


class _EdgeNamespace:
    def __init__(self, db: LocalGraphDB):
        self._db = db

    def get_by_graph_id(
        self, graph_id: str, limit: int = 100, uuid_cursor: Optional[str] = None
    ) -> List[LocalEdge]:
        return self._db.get_edges(graph_id, limit=limit, cursor=uuid_cursor)

    def get(self, uuid_: str) -> Optional[LocalEdge]:
        return self._db.get_edge(uuid_)


class _GraphNamespace:
    def __init__(self, db: LocalGraphDB):
        self._db = db
        self.node = _NodeNamespace(db)
        self.edge = _EdgeNamespace(db)
        self.episode = _EpisodeNamespace(db)
        self._llm = None

    def _get_llm(self):
        if self._llm is None:
            from .llm_client import LLMClient
            self._llm = LLMClient()
        return self._llm

    # --- Graph lifecycle ---

    def create(self, graph_id: str, name: str = "", description: str = ""):
        self._db.create_graph(graph_id, name, description)
        logger.info(f"Local graph created: {graph_id}")

    def set_ontology(
        self,
        graph_ids: List[str],
        raw_ontology: Optional[dict] = None,
        **_kwargs,
    ):
        """Store the raw ontology dict; Zep-specific kwargs are ignored."""
        if raw_ontology:
            for gid in graph_ids:
                self._db.set_ontology(gid, raw_ontology)

    def add_batch(self, graph_id: str, episodes: List[Any]) -> List[LocalEpisode]:
        """Ingest text episodes: runs LLM extraction and stores nodes/edges."""
        results: List[LocalEpisode] = []
        ontology = self._db.get_ontology(graph_id)
        llm = self._get_llm()

        for ep in episodes:
            data: str = getattr(ep, "data", "") or ""
            ep_type: str = getattr(ep, "type", "text") or "text"
            ep_uuid = self._db.insert_episode(graph_id, data, ep_type)
            if data and ep_type == "text":
                self._extract_and_store(graph_id, data, ontology, llm)
            results.append(
                LocalEpisode(uuid_=ep_uuid, data=data, type=ep_type, processed=True)
            )
        return results

    def add(self, graph_id: str, type: str = "text", data: str = "") -> LocalEpisode:
        """Single episode add — used by the memory updater for activity streams.

        Stores agent activity lines as lightweight edge records without a full
        LLM extraction call to avoid slowing down live simulations.
        """
        ep_uuid = self._db.insert_episode(graph_id, data, type)
        if data and type == "text":
            self._store_activity_text(graph_id, data)
        return LocalEpisode(uuid_=ep_uuid, data=data, type=type, processed=True)

    def search(
        self,
        graph_id: str,
        query: str,
        limit: int = 10,
        scope: str = "edges",
        **_kwargs,
    ):
        """Raises LocalSearchUnavailable so callers fall back to keyword search."""
        raise LocalSearchUnavailable(
            "Local graph client has no semantic search; falling back to keyword search."
        )

    def delete(self, graph_id: str):
        self._db.delete_graph(graph_id)
        logger.info(f"Local graph deleted: {graph_id}")

    # --- Internal helpers ---

    def _extract_and_store(
        self,
        graph_id: str,
        text: str,
        ontology: Optional[dict],
        llm,
    ):
        try:
            extracted = _extract_entities(llm, text, ontology)
            nodes_data: list = extracted.get("nodes", [])
            edges_data: list = extracted.get("edges", [])

            name_to_uuid: Dict[str, str] = {}
            for nd in nodes_data:
                name = (nd.get("name") or "").strip()
                label = (nd.get("label") or "Entity").strip()
                summary = (nd.get("summary") or "").strip()
                if not name:
                    continue
                labels = (["Entity", label] if label != "Entity" else ["Entity"])
                node_uuid = self._db.upsert_node(graph_id, name, labels, summary, {})
                name_to_uuid[name.lower()] = node_uuid

            for ed in edges_data:
                rel_name = (ed.get("name") or "related_to").strip()
                fact = (ed.get("fact") or "").strip()
                src = (ed.get("source") or ed.get("source_name") or "").strip().lower()
                tgt = (ed.get("target") or ed.get("target_name") or "").strip().lower()
                src_uuid = name_to_uuid.get(src)
                tgt_uuid = name_to_uuid.get(tgt)
                if fact and src_uuid and tgt_uuid:
                    self._db.insert_edge(graph_id, rel_name, fact, src_uuid, tgt_uuid, {})

        except Exception as e:
            logger.warning(f"Entity extraction failed for graph {graph_id}: {e}")

    def _store_activity_text(self, graph_id: str, text: str):
        """Store simulation activity lines as raw edge facts for search."""
        for line in text.strip().splitlines():
            line = line.strip()
            if ":" not in line:
                continue
            agent_name, _, activity = line.partition(":")
            agent_name = agent_name.strip()
            activity = activity.strip()
            if not agent_name or not activity:
                continue
            agent_uuid = self._db.upsert_node(
                graph_id, agent_name, ["Entity", "Agent"],
                f"Simulation agent: {agent_name}", {}
            )
            self._db.insert_edge(
                graph_id, "activity",
                f"{agent_name}: {activity}",
                agent_uuid, agent_uuid, {}
            )


# ---------------------------------------------------------------------------
# Public client (mirrors zep_cloud.client.Zep)
# ---------------------------------------------------------------------------

class LocalGraphClient:
    """Drop-in local replacement for ``zep_cloud.client.Zep``.

    Usage::

        client = LocalGraphClient()          # uses Config.UPLOAD_FOLDER
        client = LocalGraphClient(storage_dir="/path/to/dir")
    """

    def __init__(self, storage_dir: Optional[str] = None, **_kwargs):
        if storage_dir is None:
            from ..config import Config
            storage_dir = Config.UPLOAD_FOLDER
        db_path = os.path.join(storage_dir, "graphs", "local_graph.db")
        self._db = LocalGraphDB(db_path)
        self.graph = _GraphNamespace(self._db)
