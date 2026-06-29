# MiroFish Codebase Analysis

## 1. Project Overview

**MiroFish** is a next-generation AI prediction engine that uses multi-agent swarm intelligence to simulate social dynamics and forecast future outcomes. Users upload seed documents (news reports, novels, policy drafts, financial data), and MiroFish automatically builds a knowledge graph, populates it with intelligent agents, runs parallel social-media simulations, and produces a detailed prediction report.

Key capabilities:
- **Knowledge Graph Construction** – PDF/text extraction → LLM-based ontology design → Zep Cloud graph building
- **Dual-Platform Simulation** – parallel Twitter and Reddit agent simulations powered by [OASIS](https://github.com/camel-ai/oasis)
- **Report Agent** – ReACT-style agent with graph-search tooling that writes structured prediction reports
- **Deep Interaction** – post-simulation chat with any simulated agent or with the ReportAgent

---

## 2. High-Level Architecture

```
┌──────────────────────────────────────────────────────────────┐
│  Browser (Vue 3 SPA)                                         │
│  Home → Process (Step 1–2) → Simulation → Report →          │
│  Interaction                                                 │
└────────────────────────┬─────────────────────────────────────┘
                         │ HTTP / REST (/api/*)
┌────────────────────────▼─────────────────────────────────────┐
│  Flask Backend  (port 5001)                                  │
│  ┌──────────┐  ┌────────────┐  ┌──────────┐                 │
│  │ /graph   │  │ /simulation│  │ /report  │                 │
│  └──────────┘  └────────────┘  └──────────┘                 │
│        │              │               │                      │
│  ┌─────▼──────────────▼───────────────▼────────────────┐    │
│  │               Service Layer                          │    │
│  │  OntologyGenerator │ GraphBuilderService             │    │
│  │  ZepEntityReader   │ OasisProfileGenerator           │    │
│  │  SimulationManager │ SimulationRunner                │    │
│  │  ReportAgent       │ ZepToolsService                 │    │
│  └──────────────────────────────────────────────────────┘    │
│        │                         │                           │
│  ┌─────▼─────┐           ┌───────▼──────┐                   │
│  │ Zep Cloud │           │  OASIS Engine│                   │
│  │ (Graph DB │           │  (Twitter +  │                   │
│  │  + Memory)│           │   Reddit sim)│                   │
│  └───────────┘           └──────────────┘                   │
│        │                                                     │
│  ┌─────▼──────────────────────────────────────────────┐     │
│  │          LLM API (OpenAI-compatible)               │     │
│  └────────────────────────────────────────────────────┘     │
└──────────────────────────────────────────────────────────────┘
```

---

## 3. Directory Structure

```
MiroFish/
├── .env.example            # Environment variable template
├── .gitignore
├── docker-compose.yml      # Single-container Docker deployment
├── Dockerfile
├── package.json            # Root scripts (dev, setup, build)
├── README.md               # English documentation
├── README-ZH.md            # Chinese documentation
├── locales/
│   ├── en.json             # Backend i18n strings (English)
│   ├── zh.json             # Backend i18n strings (Chinese)
│   └── languages.json      # Language metadata
├── backend/
│   ├── run.py              # Entry point (Flask dev server)
│   ├── pyproject.toml      # Python dependencies (uv / hatchling)
│   ├── requirements.txt    # Pip-compatible requirements
│   └── app/
│       ├── __init__.py     # create_app() factory
│       ├── config.py       # Config class (dotenv + env vars)
│       ├── api/
│       │   ├── graph.py    # /api/graph/* routes
│       │   ├── simulation.py # /api/simulation/* routes
│       │   └── report.py   # /api/report/* routes
│       ├── models/
│       │   ├── project.py  # Project data model + ProjectManager
│       │   └── task.py     # Task data model + TaskManager
│       ├── services/
│       │   ├── ontology_generator.py     # LLM → ontology JSON
│       │   ├── graph_builder.py          # Text → Zep graph
│       │   ├── text_processor.py         # Chunking + file parsing
│       │   ├── zep_entity_reader.py      # Read/filter Zep entities
│       │   ├── oasis_profile_generator.py # Entities → agent profiles
│       │   ├── simulation_config_generator.py # LLM config params
│       │   ├── simulation_manager.py     # Simulation lifecycle
│       │   ├── simulation_runner.py      # OASIS subprocess + IPC
│       │   ├── simulation_ipc.py         # IPC protocol (pause/stop)
│       │   ├── zep_graph_memory_updater.py # Post-round memory sync
│       │   ├── report_agent.py           # ReACT report writer
│       │   └── zep_tools.py              # Graph retrieval tools
│       └── utils/
│           ├── llm_client.py     # OpenAI-compatible LLM wrapper
│           ├── file_parser.py    # PDF / text file reader
│           ├── logger.py         # Structured logging setup
│           ├── locale.py         # Runtime i18n helper
│           ├── retry.py          # Exponential-backoff decorator
│           └── zep_paging.py     # Paginated Zep API helpers
└── frontend/
    ├── index.html
    ├── vite.config.js
    ├── package.json
    └── src/
        ├── main.js
        ├── App.vue
        ├── router/index.js         # Vue Router configuration
        ├── store/pendingUpload.js  # Temporary upload state
        ├── i18n/index.js           # vue-i18n configuration
        ├── api/                    # Axios API clients
        │   ├── index.js
        │   ├── graph.js
        │   ├── simulation.js
        │   └── report.js
        ├── assets/                 # Static images / icons
        ├── components/
        │   ├── GraphPanel.vue          # D3 knowledge graph viewer
        │   ├── Step1GraphBuild.vue     # Upload + ontology + graph
        │   ├── Step2EnvSetup.vue       # Entity review + agent config
        │   ├── Step3Simulation.vue     # Simulation configuration
        │   ├── Step4Report.vue         # Report display + chat
        │   ├── Step5Interaction.vue    # Agent interview UI
        │   ├── HistoryDatabase.vue     # Past project browser
        │   └── LanguageSwitcher.vue    # EN/ZH toggle
        └── views/
            ├── Home.vue            # Landing page + project upload
            ├── MainView.vue        # Step 1–2 shell
            ├── SimulationView.vue  # Step 2 continuation
            ├── SimulationRunView.vue # Step 3 live simulation
            ├── ReportView.vue      # Step 4 report
            └── InteractionView.vue # Step 5 deep interaction
```

---

## 4. Technology Stack

| Layer | Technology | Version | Purpose |
|-------|-----------|---------|---------|
| Frontend framework | Vue 3 | 3.x | Reactive SPA |
| Frontend bundler | Vite | 6.x | Build tooling |
| Frontend routing | Vue Router | 4.x | Client-side routing |
| Frontend i18n | vue-i18n | 9.x | EN/ZH localisation |
| Graph visualisation | D3.js | — | Knowledge graph rendering |
| HTTP client | Axios | — | REST API calls |
| Backend framework | Flask | ≥3.0 | Python REST API |
| CORS | flask-cors | ≥6.0 | Cross-origin requests |
| LLM SDK | openai | ≥1.0 | LLM calls (any OpenAI-compatible API) |
| Memory / graph DB | zep-cloud | 3.13.0 | Knowledge graph + agent memory |
| Simulation engine | camel-oasis | 0.2.5 | Multi-agent social simulation |
| LLM agent framework | camel-ai | 0.2.78 | Agent reasoning (used by OASIS) |
| PDF parsing | PyMuPDF | ≥1.24 | Document ingestion |
| Encoding detection | charset-normalizer, chardet | — | Non-UTF-8 text handling |
| Config management | python-dotenv | ≥1.0 | `.env` loading |
| Data validation | pydantic | ≥2.0 | Schema validation |
| Package manager (Python) | uv | latest | Fast virtualenv + install |
| Package manager (JS) | npm | ≥18 | Node dependencies |
| Containerisation | Docker / docker compose | — | One-command deployment |

---

## 5. Five-Step Workflow

### Step 1 – Graph Building (`/api/graph/*`)

1. User uploads one or more documents (PDF, Markdown, TXT).
2. `TextProcessor` extracts raw text and splits it into overlapping chunks.
3. `OntologyGenerator` sends the text to an LLM and receives a JSON ontology describing entity types and relationship types suitable for social-media simulation.
4. `GraphBuilderService` pushes text episodes to Zep Cloud in batches; Zep builds a knowledge graph with typed nodes and edges.
5. A `Task` tracks progress; the frontend polls `/api/graph/task/{id}`.

### Step 2 – Environment Setup (`/api/simulation/entities/*`, `/api/simulation/profiles/*`)

1. `ZepEntityReader` fetches all nodes from the graph and filters them to only include entity types that can act as social-media accounts (people, organisations, media, etc.).
2. `OasisProfileGenerator` converts each entity and its connected edges into a rich persona description (name, bio, writing style, relationships, backstory).
3. `SimulationConfigGenerator` calls the LLM to auto-generate OASIS simulation parameters (rounds, platform weights, initial post topics, etc.) based on the user's stated prediction requirement.
4. A `SimulationState` object is persisted in memory / on disk.

### Step 3 – Simulation (`/api/simulation/run/*`)

1. `SimulationRunner` spawns an isolated subprocess that runs the OASIS engine.
2. Both Twitter-like and Reddit-like platforms run in parallel.
3. Each simulation round, agent actions are streamed back over IPC (JSON messages) and logged.
4. `ZepGraphMemoryManager` writes post-round agent actions back into the Zep graph as new episodes, keeping agent memories current.
5. The frontend receives real-time status via polling.

### Step 4 – Report Generation (`/api/report/*`)

1. `ReportAgent` uses a ReACT (reasoning + action) loop to write a multi-section prediction report.
2. It can call three specialised retrieval tools against the Zep graph:
   - **InsightForge** – deep hybrid search, auto-generates sub-questions
   - **PanoramaSearch** – broad search including expired memory
   - **QuickSearch** – fast keyword search
3. Reports are written section-by-section and saved as Markdown + JSONL agent logs.

### Step 5 – Deep Interaction (`/api/simulation/interview/*`)

1. Users choose any simulated agent or the ReportAgent to chat with.
2. Queries are prefixed with a special instruction to prevent tool calls and force direct textual responses.
3. Responses draw on the agent's Zep long-term memory.

---

## 6. Data Persistence

| Data | Storage Location |
|------|-----------------|
| Project metadata | `backend/uploads/projects/{project_id}/project.json` |
| Uploaded files | `backend/uploads/projects/{project_id}/files/` |
| Simulation configs & agent files | `backend/uploads/simulations/{simulation_id}/` |
| Reports | `backend/uploads/reports/{report_id}/` |
| Knowledge graph + agent memory | Zep Cloud (remote) |
| Task state | In-memory `TaskManager` (ephemeral, lost on restart) |

---

## 7. Internationalisation (i18n)

- **Frontend**: `vue-i18n` loads JSON message files directly from the root `locales/` directory at build time (via `import.meta.glob('../../../locales/!(languages).json')`).
- **Backend**: Custom `utils/locale.py` helper reads the same `locales/en.json` and `locales/zh.json` files at runtime; locale is set per-request based on the `Accept-Language` header.
- Language toggle is available in the UI via `LanguageSwitcher.vue`.

---

## 8. Configuration Reference

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `LLM_API_KEY` | ✅ | — | API key for the LLM provider |
| `LLM_BASE_URL` | ✅ | `https://dashscope.aliyuncs.com/compatible-mode/v1` | OpenAI-compatible base URL |
| `LLM_MODEL_NAME` | ✅ | `qwen-plus` | Model identifier |
| `ZEP_API_KEY` | ✅ | — | Zep Cloud API key |
| `LLM_BOOST_API_KEY` | — | — | Optional faster/cheaper LLM for non-critical steps |
| `LLM_BOOST_BASE_URL` | — | — | Base URL for boost LLM |
| `LLM_BOOST_MODEL_NAME` | — | — | Model name for boost LLM |
| `FLASK_DEBUG` | — | `True` | Enable Flask debug mode |
| `FLASK_HOST` | — | `0.0.0.0` | Flask bind host |
| `FLASK_PORT` | — | `5001` | Flask bind port |
| `OASIS_DEFAULT_MAX_ROUNDS` | — | `10` | Default simulation rounds |
| `REPORT_AGENT_MAX_TOOL_CALLS` | — | `5` | Max tool calls per report section |
| `REPORT_AGENT_MAX_REFLECTION_ROUNDS` | — | `2` | Max ReACT reflection rounds |
| `REPORT_AGENT_TEMPERATURE` | — | `0.5` | LLM temperature for report writing |

---

## 9. Key Design Decisions

### Subprocess-Based Simulation Isolation
OASIS simulations run in a separate OS subprocess (`simulation_runner.py`). This isolates potentially long-running, resource-heavy simulations from the Flask worker threads and allows clean termination via signals. IPC uses a lightweight JSON message protocol over `stdin`/`stdout`.

### In-Memory Project State
`ProjectManager` and `TaskManager` keep state in Python dictionaries and flush to JSON files. This keeps the dependency stack small (no database required) but means in-progress tasks are lost if the backend restarts.

### LLM as Orchestrator
Rather than hard-coding agent personas, the system uses the LLM to:
- Design the ontology for each specific input document
- Generate rich agent profiles from graph entities
- Auto-configure simulation parameters
- Write the prediction report

This makes the system document-agnostic: it works equally well for political news, literary analysis, or financial signals.

### Dual-Platform Simulation
Running Twitter and Reddit in parallel allows cross-platform diffusion modelling. Each platform has its own action vocabulary (e.g., Reddit supports `DISLIKE_POST`, `SEARCH_POSTS`, `TREND`; Twitter supports `QUOTE_POST`, `REPOST`).

---

## 10. Identified Areas for Improvement

| Area | Observation |
|------|-------------|
| **Task persistence** | `TaskManager` is in-memory only; a server restart silently drops all in-progress tasks. Using SQLite (already included in Python's standard library, requiring no extra dependencies) would improve resilience. |
| **Authentication / authorisation** | There is no user authentication layer. All projects and simulations are globally accessible to anyone who can reach the API. Adding at minimum a per-session API token would be advisable before public deployment. |
| **SECRET_KEY hardcoding** | `Config.SECRET_KEY` falls back to the literal string `'mirofish-secret-key'`. Production deployments should always set this via the environment. |
| **CORS wildcard** | `origins="*"` in the CORS configuration accepts requests from any origin. Restrict this to the known frontend origin in production. |
| **No input validation on file uploads** | `allowed_file()` checks the extension but not the MIME type. A file renamed to `.pdf` but containing malicious content would pass the check. |
| **Error detail leakage** | Several API handlers return full Python tracebacks in the JSON `error` field when `DEBUG=True`. This should be gated to non-production environments. |
| **No test suite** | The `pyproject.toml` lists `pytest` as a dev dependency but the `backend/` directory contains no test files. Adding unit tests for the service layer (ontology generation, entity reading, profile generation) would improve reliability. |
| **Frontend linting** | No ESLint or Prettier configuration is present. Adding a linter would enforce code style across the Vue components. |
| **Docker single-container** | Both frontend and backend share a single Docker container. Splitting into two containers would follow the separation-of-concerns principle and simplify independent scaling. |
| **Zep SDK version pinned tightly** | `zep-cloud==3.13.0` is pinned to an exact version. Keeping up with minor Zep releases that fix bugs or add features requires manual bumps. |

---

## 11. Running Locally (Summary)

```bash
# 1. Clone and configure
cp .env.example .env
# Edit .env with LLM_API_KEY, ZEP_API_KEY, etc.

# 2. Install all dependencies
npm run setup:all          # Node + Python (via uv)

# 3. Start both services
npm run dev
# Frontend → http://localhost:3000
# Backend  → http://localhost:5001
```

For Docker:
```bash
cp .env.example .env
# Edit .env
docker compose up -d
```
