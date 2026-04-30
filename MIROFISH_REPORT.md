# MiroFish — Full Technical Report & Walkthrough

> **Date:** 2026-04-30  
> **Purpose:** Understand the codebase, plan local Zep-free operation, and prepare for Chinese → English translation.

---

## Table of Contents

1. [What MiroFish Is](#1-what-mirofish-is)
2. [High-Level Architecture](#2-high-level-architecture)
3. [Five-Step Pipeline Walkthrough](#3-five-step-pipeline-walkthrough)
4. [Directory & File Map](#4-directory--file-map)
5. [Key Dependencies](#5-key-dependencies)
6. [What Zep Does — and How to Replace It](#6-what-zep-does--and-how-to-replace-it)
7. [Running Locally Without Zep (Migration Plan)](#7-running-locally-without-zep-migration-plan)
8. [Environment Variables Reference](#8-environment-variables-reference)
9. [Phase 2 — Chinese → English Translation Plan](#9-phase-2--chinese--english-translation-plan)

---

## 1. What MiroFish Is

MiroFish is a **swarm-intelligence prediction engine**. Given a document (news article, report, PDF), it:

1. Extracts a structured ontology — the entities and relationships that matter.
2. Builds a **knowledge graph** from that ontology.
3. Populates thousands of AI agents with personalities derived from graph entities.
4. Runs a **social-media simulation** (Twitter and/or Reddit style) where agents interact.
5. Generates a **prediction report** by querying the simulation results against the graph.

The stated use cases are policy rehearsal ("what happens if we pass this law?"), PR crisis simulation, market sentiment forecasting, and creative scenario exploration.

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────┐
│                       FRONTEND                           │
│         Vue 3 + Vite  (localhost:3000)                   │
│   Step1  Step2  Step3  Step4  Step5  (wizard UI)         │
└───────────────────┬──────────────────────────────────────┘
                    │ axios (HTTP, 5-min timeout)
┌───────────────────▼──────────────────────────────────────┐
│                    FLASK BACKEND                          │
│         Python 3.11–3.12  (localhost:5001)               │
│  /api/graph/*   /api/simulation/*   /api/report/*        │
│                                                          │
│  ┌──────────────┐  ┌────────────────┐  ┌─────────────┐  │
│  │ graph_builder│  │simulation_runner│  │report_agent │  │
│  │ ontology_gen │  │ simulation_mgr  │  │ zep_tools   │  │
│  │ zep_entity_  │  │ profile_gen     │  │             │  │
│  │  _reader     │  │ config_gen      │  │             │  │
│  └──────┬───────┘  └──────┬─────────┘  └──────┬──────┘  │
│         │                 │                    │         │
└─────────┼─────────────────┼────────────────────┼─────────┘
          │                 │                    │
   ┌──────▼──────┐   ┌──────▼──────┐    ┌───────▼──────┐
   │  ZEP CLOUD  │   │   OASIS     │    │  LLM API     │
   │ (knowledge  │   │ (CAMEL-AI   │    │ (OpenAI-     │
   │   graphs)   │   │  simulation)│    │  compatible) │
   └─────────────┘   └─────────────┘    └──────────────┘
```

### Data flow summary

```
Document Upload
    → Text Extraction (PDF/MD/TXT)
    → Ontology Generation (LLM)        ← Step 1
    → Knowledge Graph Build (Zep)      ← Step 2
    → Entity Reading / Filtering (Zep) ← Step 3 prep
    → Agent Persona Generation (LLM + Zep)
    → Simulation Config Generation
    → OASIS Simulation (subprocess)    ← Step 3 run
    → Report Generation (LLM + Zep)    ← Step 4
    → Deep Agent Interaction           ← Step 5
```

---

## 3. Five-Step Pipeline Walkthrough

### Step 1 — Ontology Generation (`Step1GraphBuild.vue`)

**What happens:**
- User uploads one or more PDF/MD/TXT files (≤50 MB each).
- Backend extracts raw text using `FileParser` (PyMuPDF for PDF).
- `OntologyGenerator` sends chunks of text to the LLM with a structured prompt asking it to identify entity types (e.g. Person, Organization, Event) and relationship types (e.g. "employs", "opposes").
- Returns a JSON schema defining the ontology.

**Key files:**
- `backend/app/api/graph.py` — upload + ontology endpoints
- `backend/app/services/ontology_generator.py` — LLM-powered schema generator
- `backend/app/utils/file_parser.py` — multi-format text extraction
- `frontend/src/components/Step1GraphBuild.vue`

---

### Step 2 — Knowledge Graph Build (`graph_builder.py`)

**What happens:**
- Text is chunked (default 500 chars, 50-char overlap).
- Each chunk is submitted to Zep as a text "episode" referencing the ontology.
- Zep extracts entities/relationships from each chunk and builds a property graph.
- Backend polls `client.graph.status()` until processing is complete.
- Graph UUID is stored in `project.json`.

**Key files:**
- `backend/app/services/graph_builder.py`
- `backend/app/models/project.py` (stores graph_id)
- `backend/app/models/task.py` (tracks async build progress)

---

### Step 3 — Simulation (`Step3Simulation.vue`)

**What happens:**
1. **Entity reading**: `ZepEntityReader` fetches all graph nodes via `client.graph.node.get_by_graph_id()` with cursor-based pagination (max 2000 nodes). Filters by predefined entity types.
2. **Config generation**: `SimulationConfigGenerator` converts user parameters (rounds, platforms, topic) into OASIS simulation config JSON.
3. **Profile generation**: `OasisProfileGenerator` builds each agent's persona — personality traits, memory, role — by querying Zep for entity context.
4. **Simulation run**: `SimulationRunner` spawns a subprocess that runs OASIS. Actions stream into `actions.jsonl`. Both Twitter and Reddit simulations can run in parallel.
5. **Memory updates** (optional): `ZepGraphMemoryUpdater` converts each agent action to natural language and submits it back to Zep as a new episode — the graph "learns" from the simulation.

**Key files:**
- `backend/app/api/simulation.py` (largest API file — 94 KB)
- `backend/app/services/simulation_runner.py` (69 KB)
- `backend/app/services/oasis_profile_generator.py` (49 KB)
- `backend/app/services/simulation_config_generator.py` (39 KB)
- `backend/app/services/zep_graph_memory_updater.py`
- `backend/app/services/zep_entity_reader.py`

---

### Step 4 — Report Generation (`report_agent.py`)

**What happens:**
- `ReportAgent` drives a multi-round LLM conversation with tool-calling.
- Tools available to the agent:
  - **InsightForge**: generates sub-questions → semantic search + entity node retrieval
  - **PanoramaSearch**: broad search including temporally expired edges
  - **QuickSearch**: simple one-shot semantic search
- Agent reflects, refines, and writes a structured prediction report.
- Reports are stored as artifacts (JSON) under the simulation directory.

**Key files:**
- `backend/app/services/report_agent.py` (99 KB — largest service)
- `backend/app/services/zep_tools.py` (66 KB — all three retrieval strategies)
- `backend/app/api/report.py`

---

### Step 5 — Deep Interaction (`Step5Interaction.vue`)

**What happens:**
- User selects specific agents from the simulation.
- Sends freeform questions; backend routes them to the agent's persona + memory context.
- Agent responds in character, referencing the simulation history.
- Interview prompt can be optimized via an LLM call.

**Key files:**
- `backend/app/api/simulation.py` (interview endpoints)
- `frontend/src/components/Step5Interaction.vue`

---

## 4. Directory & File Map

```
MiroFish/
├── .env.example                    # Required config template
├── docker-compose.yml              # Prod deployment
├── package.json                    # Root npm scripts (dev, build, setup)
│
├── backend/
│   ├── run.py                      # Flask entry point
│   ├── requirements.txt            # pip-compatible dependency list
│   ├── pyproject.toml              # uv project config
│   ├── app/
│   │   ├── __init__.py             # Flask app factory
│   │   ├── config.py               # All env var loading + validation
│   │   ├── api/
│   │   │   ├── graph.py            # /api/graph/* — project + graph CRUD
│   │   │   ├── simulation.py       # /api/simulation/* — run + query sims
│   │   │   └── report.py           # /api/report/* — generate + fetch reports
│   │   ├── models/
│   │   │   ├── project.py          # Project state machine (JSON file storage)
│   │   │   └── task.py             # Async task tracker (in-memory)
│   │   ├── services/
│   │   │   ├── graph_builder.py          # Zep graph construction
│   │   │   ├── ontology_generator.py     # LLM schema generation
│   │   │   ├── zep_entity_reader.py      # Read/filter graph nodes
│   │   │   ├── zep_graph_memory_updater.py  # Write sim events → Zep
│   │   │   ├── zep_tools.py              # 3 retrieval strategies for reports
│   │   │   ├── oasis_profile_generator.py   # Agent persona building
│   │   │   ├── simulation_config_generator.py
│   │   │   ├── simulation_runner.py         # Subprocess OASIS runner
│   │   │   ├── simulation_manager.py        # Sim state tracker
│   │   │   ├── report_agent.py              # Multi-round report writer
│   │   │   └── text_processor.py            # Chunking utility
│   │   └── utils/
│   │       ├── llm_client.py         # OpenAI-compatible wrapper
│   │       ├── zep_paging.py         # Cursor pagination + retry for Zep
│   │       ├── file_parser.py        # PDF/MD/TXT extraction
│   │       ├── locale.py             # i18n message lookup
│   │       ├── logger.py             # Colored logging
│   │       └── retry.py              # Generic exponential backoff
│   └── scripts/
│       ├── twitter_sim.py            # Twitter simulation runner
│       └── reddit_sim.py             # Reddit simulation runner
│
├── frontend/
│   ├── vite.config.js
│   ├── package.json
│   └── src/
│       ├── main.js
│       ├── App.vue
│       ├── router/index.js
│       ├── store/index.js
│       ├── api/
│       │   ├── index.js              # Axios instance + interceptors
│       │   ├── graph.js
│       │   ├── simulation.js
│       │   └── report.js
│       ├── views/
│       │   ├── Home.vue
│       │   ├── Process.vue           # Main 5-step wizard
│       │   └── Simulation.vue
│       ├── components/
│       │   ├── Step1GraphBuild.vue
│       │   ├── Step2EnvSetup.vue
│       │   ├── Step3Simulation.vue
│       │   ├── Step4Report.vue
│       │   └── Step5Interaction.vue
│       └── i18n/
│           └── index.js              # Vue-i18n setup
│
└── locales/
    ├── zh.json                       # Chinese UI strings (2500+ entries)
    ├── en.json                       # English UI strings
    └── languages.json
```

---

## 5. Key Dependencies

| Layer | Package | Version | Purpose |
|-------|---------|---------|---------|
| Backend | `flask` | ≥3.0 | HTTP server |
| Backend | `openai` | ≥1.0 | LLM calls (any compatible API) |
| Backend | `zep-cloud` | 3.13.0 | Knowledge graph + memory |
| Backend | `camel-oasis` | 0.2.5 | Social media agent simulation |
| Backend | `camel-ai` | 0.2.78 | Agent framework underpinning OASIS |
| Backend | `PyMuPDF` | ≥1.24 | PDF text extraction |
| Backend | `pydantic` | ≥2.0 | Data validation |
| Frontend | `vue` | ^3.5 | UI framework |
| Frontend | `d3` | ^7.9 | Graph visualization |
| Frontend | `axios` | ^1.14 | HTTP client |
| Frontend | `vue-i18n` | ^11.3 | Internationalization |

---

## 6. What Zep Does — and How to Replace It

Zep is the **only external cloud service** in the backend (aside from the LLM API). Understanding exactly what it provides is the key to removing it.

### Zep's roles in MiroFish

| Role | Zep API called | Used in |
|------|---------------|---------|
| Store text as episodes, extract entities/relationships via LLM | `client.graph.add()` | `graph_builder.py` |
| Check when graph processing is done | `client.graph.status()` | `graph_builder.py` |
| List all nodes in a graph (with cursor pagination) | `client.graph.node.get_by_graph_id()` | `zep_entity_reader.py`, `zep_paging.py` |
| List all edges in a graph | `client.graph.edge.get_by_graph_id()` | `zep_paging.py`, `zep_tools.py` |
| Semantic search over nodes/edges | `client.graph.search()` | `zep_tools.py` |
| Get a single node by UUID | `client.graph.node.get()` | `zep_tools.py` |
| Get a single edge by UUID | `client.graph.edge.get()` | `zep_tools.py` |
| Dynamically add new nodes/edges during simulation | `client.graph.add_entity()`, `client.graph.add_edge()` | `zep_graph_memory_updater.py` |

### What Zep is NOT doing here

- No user session memory (Zep's main consumer product feature).
- No authentication — it's only used as a graph database + semantic search engine.

### Local replacement strategy

The cleanest drop-in replacement uses three pieces:

#### A. Graph Storage + Entity Extraction → **LLM + SQLite/JSON**

Zep ingests raw text and uses an internal LLM to extract entities and relationships. We replicate this:

1. Call the same LLM API (already configured) with a structured extraction prompt.
2. Store nodes and edges in a local SQLite database (or even JSON files matching the existing `project.json` pattern).

#### B. Semantic Search → **ChromaDB (local vector DB)**

Zep's `graph.search()` is a semantic vector search. ChromaDB is:
- 100% local (no API key, no account)
- pip-installable (`chromadb`)
- Has an identical query interface to what's needed

#### C. Temporal / Relational Queries → **NetworkX**

For graph traversal (get edges for a node, find neighbors), Python's `networkx` library is sufficient and is already implicitly available.

### Replacement summary

| Zep feature | Local replacement |
|------------|-------------------|
| Text → entities/relationships | LLM extraction prompt (same API you already use) |
| Graph node/edge storage | SQLite (`nodes` + `edges` tables) or JSON |
| Semantic search | ChromaDB (local, no account) |
| Cursor-based pagination | Local cursor over SQLite query results |
| Real-time episode updates | Append new rows to SQLite during simulation |

**New required dependencies (all local, no API key):**

```
chromadb>=0.4.0        # Vector store for semantic search
networkx>=3.0          # Graph traversal
sentence-transformers>=2.0  # OR use your LLM API for embeddings
```

---

## 7. Running Locally Without Zep (Migration Plan)

### Phase A — Make it run today (minimal changes)

1. **Get a free Zep API key** at https://app.getzep.com/ (free tier covers typical usage). This is the fastest path to a running system for evaluation.
2. Copy `.env.example` → `.env`, fill in `LLM_API_KEY` and `ZEP_API_KEY`.
3. Run:
   ```bash
   npm run setup:all
   npm run dev
   ```
4. Open http://localhost:3000.

### Phase B — Replace Zep with local storage (implementation plan)

#### Step 1: Create a `LocalGraphClient` wrapper

Create `backend/app/utils/local_graph_client.py` that mirrors the Zep client interface used throughout the codebase. This is the only file all other services need to change — they currently do `self.client = Zep(api_key=...)`.

**Interface to implement:**

```python
class LocalGraphClient:
    def graph(self): ...       # returns GraphNamespace

class GraphNamespace:
    def add(self, graph_id, type, data): ...      # ingest text episode
    def status(self, graph_id): ...               # return processing status
    def search(self, graph_id, query, limit): ... # semantic search → list[SearchResult]

class NodeNamespace:
    def get_by_graph_id(self, graph_id, limit, uuid_cursor): ...
    def get(self, graph_id, uuid): ...

class EdgeNamespace:
    def get_by_graph_id(self, graph_id, limit, uuid_cursor): ...
    def get(self, graph_id, uuid): ...
```

#### Step 2: Swap the client in `config.py`

```python
# Current:
from zep_cloud.client import Zep
zep_client = Zep(api_key=ZEP_API_KEY)

# New:
from app.utils.local_graph_client import LocalGraphClient
zep_client = LocalGraphClient(storage_dir=UPLOAD_FOLDER)
```

#### Step 3: Implement entity extraction

In `LocalGraphClient.graph.add()`, call the existing `LLMClient` with this prompt pattern (the ontology JSON from Step 1 of the pipeline gives you the schema):

```python
system_prompt = """Extract all entities and relationships from this text.
Return JSON: {"nodes": [{"uuid": "...", "name": "...", "type": "...", "summary": "..."}],
              "edges": [{"uuid": "...", "source_uuid": "...", "target_uuid": "...", 
                         "fact": "...", "name": "..."}]}"""
```

#### Step 4: Store in SQLite

```sql
CREATE TABLE nodes (
    uuid TEXT PRIMARY KEY,
    graph_id TEXT,
    name TEXT,
    type TEXT,
    summary TEXT,
    created_at TIMESTAMP,
    embedding BLOB  -- stored as JSON float array
);

CREATE TABLE edges (
    uuid TEXT PRIMARY KEY,
    graph_id TEXT,
    source_uuid TEXT,
    target_uuid TEXT,
    name TEXT,
    fact TEXT,
    created_at TIMESTAMP,
    valid_at TIMESTAMP,
    invalid_at TIMESTAMP
);
```

#### Step 5: Add ChromaDB for semantic search

```python
import chromadb
chroma = chromadb.PersistentClient(path=f"{storage_dir}/chroma")
collection = chroma.get_or_create_collection(graph_id)

# On insert:
collection.add(documents=[node.summary], ids=[node.uuid])

# On search:
results = collection.query(query_texts=[query], n_results=limit)
```

#### Step 6: Remove `zep-cloud` from `requirements.txt`, add new deps

```diff
-zep-cloud==3.13.0
+chromadb>=0.4.0
+networkx>=3.0
```

### Files to modify (ordered by effort)

| File | Change |
|------|--------|
| `backend/app/utils/local_graph_client.py` | **Create** — the new client (150–300 lines) |
| `backend/app/config.py` | Swap `Zep` for `LocalGraphClient` (5 lines) |
| `backend/app/services/graph_builder.py` | Minor — use new status/add methods |
| `backend/app/utils/zep_paging.py` | Rewrite to page SQLite instead of Zep |
| `backend/app/services/zep_entity_reader.py` | Minor — pagination interface change |
| `backend/app/services/zep_tools.py` | Minor — swap `client.graph.search()` → ChromaDB |
| `backend/app/services/zep_graph_memory_updater.py` | Minor — use new `add_entity/add_edge` |
| `backend/requirements.txt` | Remove zep-cloud, add chromadb/networkx |

**Estimated effort: 2–3 focused sessions.**

---

## 8. Environment Variables Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_KEY` | Yes | — | API key for LLM provider |
| `LLM_BASE_URL` | Yes | — | Base URL (e.g. OpenAI, Alibaba Qwen) |
| `LLM_MODEL_NAME` | Yes | — | Model name (e.g. `gpt-4o`, `qwen-plus`) |
| `ZEP_API_KEY` | Yes* | — | Zep Cloud API key (*removed in Phase B) |
| `LLM_BOOST_API_KEY` | No | — | Optional faster/cheaper model for simple tasks |
| `LLM_BOOST_BASE_URL` | No | — | Base URL for boost model |
| `LLM_BOOST_MODEL_NAME` | No | — | Boost model name |
| `FLASK_DEBUG` | No | `false` | Enable Flask debug mode |

**Recommended LLM:** Any OpenAI-compatible API. The repo's original config points at Alibaba's Qwen-plus via Bailian. OpenAI `gpt-4o-mini` or Anthropic via an OpenAI-compatible proxy also work. Note: simulations can be LLM-heavy (thousands of agent calls).

---

## 9. Phase 2 — Chinese → English Translation Plan

The codebase has Chinese text in three layers, each requiring a different approach.

### Layer 1: UI Strings (Easy — already i18n'd)

The frontend uses `vue-i18n`. All visible UI strings are already externalized in:
- `locales/zh.json` — 2,500+ Chinese strings
- `locales/en.json` — English counterparts

**Status:** The English file already exists. Verify completeness:
```bash
# Compare key counts
cat locales/zh.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))"
cat locales/en.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d))"
```
Any keys present in `zh.json` but missing from `en.json` need translation. This is the lowest-risk translation work.

### Layer 2: Python Code Comments & Docstrings (Medium effort)

All 13 service files and 3 API files contain Chinese comments. These do not affect functionality — they are developer documentation only. Translation approach:

1. Work file by file.
2. Search for comment lines: `grep -n "^[[:space:]]*#" file.py | grep -P "[\x{4e00}-\x{9fff}]"`
3. Translate in place with `Edit` tool.

**Priority order (highest value first):**
1. `backend/app/api/simulation.py` — largest API file, most comments
2. `backend/app/services/report_agent.py` — complex logic, comments are load-bearing
3. `backend/app/services/zep_tools.py` — retrieval strategies, important to understand
4. `backend/app/services/simulation_runner.py`
5. All others

### Layer 3: LLM Prompts (High risk — test carefully)

Several service files embed Chinese text **inside LLM prompts**. Changing these affects model behavior.

Files with Chinese in prompts:
- `backend/app/services/ontology_generator.py` — generation prompt
- `backend/app/services/oasis_profile_generator.py` — persona prompts
- `backend/app/services/simulation_config_generator.py` — config prompts
- `backend/app/services/report_agent.py` — report writing prompts

**Approach:** Translate prompts to English, but test each end-to-end before committing. English prompts with English-language LLMs typically perform as well or better.

### Layer 4: `locale.py` Backend Messages

`backend/app/utils/locale.py` reads from `locales/` for backend-generated messages. Check that all keys used in Python code have English translations in `locales/en.json`.

### Translation Execution Plan

```
Phase 2a: locales/en.json completeness check + gap fill     (1 session)
Phase 2b: Python comments — api/ directory                   (1 session)
Phase 2c: Python comments — services/ directory              (2–3 sessions)
Phase 2d: LLM prompts translation + testing                  (2 sessions)
Phase 2e: Final audit — grep for remaining CJK characters    (1 session)
```

**Final verification command (after translation complete):**
```bash
grep -rn --include="*.py" $'[\x{4e00}-\x{9fff}]' backend/
# Should return empty
```

---

## Quick Start (Today)

```bash
# 1. Clone / navigate to project
cd /Users/gabbytee/Projects/Claude/MiroFish

# 2. Set up environment
cp .env.example .env
# Edit .env: add LLM_API_KEY, LLM_BASE_URL, LLM_MODEL_NAME, ZEP_API_KEY

# 3. Install dependencies
npm run setup:all

# 4. Start dev servers
npm run dev

# Frontend → http://localhost:3000
# Backend  → http://localhost:5001
# Health   → http://localhost:5001/health
```

---

*Generated 2026-04-30. Next steps: (A) implement LocalGraphClient to remove Zep dependency, (B) translate Python comments file-by-file, (C) translate LLM prompts with testing.*
