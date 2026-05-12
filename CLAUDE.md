# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Development Commands

### Local (without Docker)
```bash
# Install all dependencies
npm run setup:all          # frontend npm install + backend uv sync

# Run both services concurrently (recommended for dev)
npm run dev                # Flask on :5001, Vite dev server on :3000

# Run individually
npm run backend            # cd backend && uv run python run.py
npm run frontend           # cd frontend && npm run dev

# Production frontend build
npm run build
```

### Docker
```bash
docker compose up -d --build   # Build image and start mirofish-app + mirofish-app-neo4j
docker compose logs -f mirofish # Tail app logs
```

The compose file mounts `./backend/app`, `./frontend/src`, `./frontend/index.html`, and `./locales` for hot-reload during development (no rebuild needed for code changes; Flask reloader and Vite HMR handle restarts). The host port mapping is **3010 → 3000** (frontend) and **7475 → 7474** / **7688 → 7687** (Neo4j browser/bolt).

### Backend dependency management
```bash
cd backend && uv add <package>   # Add a new dependency
cd backend && uv sync            # Sync lockfile to .venv
```

## Architecture

### Stack
- **Backend**: Flask 3 (Python 3.11+, `uv` package manager), runs on port 5001
- **Frontend**: Vue 3 + Vite, runs on port 3000; `/api/*` requests are proxied to 5001
- **Memory**: Graphiti + local Neo4j (default, `MEMORY_BACKEND=graphiti`) or Zep Cloud (`MEMORY_BACKEND=zep`)
- **Simulation engine**: CAMEL-AI OASIS (Twitter + Reddit platforms), runs as background subprocess via `SimulationRunner`
- **LLM**: Runtime-switchable via UI; providers defined in `backend/app/utils/llm_providers.py`

### Backend layout

```
backend/app/
  api/            Flask blueprints: graph.py, simulation.py, report.py, settings.py
  services/
    memory/       Abstract MemoryBackend + graphiti_backend.py + zep_backend.py
    graph_builder.py          Text chunking → Graphiti episodes → knowledge graph
    simulation_manager.py     Orchestrates prepare/start/stop; writes sim files
    simulation_runner.py      Spawns/manages OASIS subprocess, IPC
    simulation_config_generator.py  LLM-generated agent configs and time/event params
    report_agent.py           Post-simulation report generation with tool calls
    zep_tools.py              Entity/fact retrieval used during simulation
    zep_entity_reader.py      Reads + filters graph nodes for agent profile generation
    zep_graph_memory_updater.py  Writes simulation actions back into the graph
  utils/
    llm_providers.py          Provider registry + runtime state file (.llm_provider_state.json)
    llm_client.py             Thin OpenAI-SDK wrapper; strips <think> tags; used everywhere
    url_fetcher.py            Jina Reader integration for URL ingestion
    zep_paging.py             Thin shim over memory.get_all_nodes/edges (kept for compat)
  models/         Project and Task persistence (JSON files in uploads/)
  config.py       All env-var config; Config.validate() runs at startup
```

Blueprints are registered in `backend/app/__init__.py`:
- `/api/graph/*` — project CRUD, file upload, ontology generation, graph build
- `/api/simulation/*` — simulation lifecycle (prepare → start → status → stop)
- `/api/report/*` — report generation and agent interaction
- `/api/settings/*` — LLM provider read/write

### Frontend layout

```
frontend/src/
  api/           One module per backend blueprint (graph.js, simulation.js, report.js, settings.js)
  components/    Step-based workflow: Step1GraphBuild, Step2EnvSetup, Step3Simulation, Step4Report, Step5Interaction
                 Plus: GraphPanel.vue (D3 force graph), LLMProviderSwitcher.vue
  views/         MainView.vue, Process.vue (graph build progress + D3 render), SimulationView.vue, etc.
  store/         pendingUpload.js — passes files+URLs from Home to Process
  i18n/          vue-i18n setup loading from /locales/en.json + zh.json
```

`frontend/src/api/index.js` sets `baseURL: ''` so all `/api` calls are relative, relying on Vite's proxy in dev and the same origin in Docker.

### Localization
All user-visible strings live in `locales/en.json` and `locales/zh.json`. The backend uses its own `backend/app/utils/locale.py` (`t()` and `get_locale()`) for API response strings.

### LLM provider switching
`llm_providers.py` defines a registry of named profiles (`minimax`, `kimi`, `custom`). The active provider is persisted to `backend/app/uploads/.llm_provider_state.json`. **All services must use `llm_providers.get_active_*()` functions** — never read `Config.LLM_API_KEY` directly for the active provider (that field is only for the `custom` profile).

### Memory backend
`backend/app/services/memory/` contains:
- `backend.py` — abstract `MemoryBackend` with methods: `add_episode`, `search`, `get_all_nodes`, `get_all_edges`, `get_node`, `get_entity_edges`
- `graphiti_backend.py` — wraps Graphiti's async API via a dedicated `_AsyncRunner` event loop thread. `_ThinkStrippingClient` is used instead of `OpenAIGenericClient` to handle `<think>` tags from MiniMax/Kimi before JSON parsing.
- `zep_backend.py` — Zep Cloud fallback

The singleton is accessed via `from .services.memory import get_memory_backend`. The `group_id` passed to Graphiti corresponds to the project's `graph_id` (format: `mirofish_{16-hex}`).

### Simulation data
Each simulation lives in `backend/uploads/simulations/{simulation_id}/`:
- `state.json` — `SimulationState` (status, graph_id, config flags)
- `simulation_config.json` — LLM-generated agent/time/event parameters
- `reddit_profiles.json` + `twitter_profiles.csv` — per-agent OASIS profiles
- `reddit_db/` + `twitter_db/` — SQLite databases written by OASIS during simulation

### Key cross-cutting patterns

1. **JSON from LLMs**: MiniMax M2 and Kimi K2 emit `<think>...</think>` reasoning before JSON output and sometimes append trailing text. All JSON parsing uses `json.JSONDecoder().raw_decode()` rather than `json.loads()` to tolerate trailing content, plus a `<think>` strip regex.

2. **Background tasks**: Long operations (graph build, simulation prepare, report generation) run in `threading.Thread(daemon=True)` threads. Progress is written to a `TaskManager` (JSON in uploads/) and polled by the frontend.

3. **Async Graphiti in sync Flask**: `graphiti_backend.py` creates one dedicated asyncio event loop thread (`_AsyncRunner`). All async Graphiti calls go through `self._runner.run(coroutine)`, which uses `asyncio.run_coroutine_threadsafe().result()` (blocking).

## Environment Variables

Key variables (see `.env.example` for full list):

| Variable | Purpose |
|---|---|
| `LLM_PROVIDER` | Startup default provider (`minimax` / `kimi` / `custom`) |
| `MINIMAX_API_KEY` | MiniMax M2 key |
| `KIMI_API_KEY` | Kimi For Coding key (endpoint: `api.kimi.com/coding/v1`, requires `User-Agent: claude-cli/1.0.0`) |
| `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL_NAME` | Custom/generic OpenAI-compatible provider |
| `MEMORY_BACKEND` | `graphiti` (default) or `zep` |
| `NEO4J_URI` / `NEO4J_USER` / `NEO4J_PASSWORD` | Neo4j connection (Docker default: `bolt://neo4j:7687`, `neo4j/mirofish`) |
| `EMBEDDING_MODEL` | Local sentence-transformers model (default: `BAAI/bge-small-en-v1.5`) |
| `RERANKER_MODEL` | Local BGE reranker (default: `BAAI/bge-reranker-base`) |
| `JINA_API_KEY` | Optional — higher quota for Jina Reader URL ingestion |
| `OASIS_DEFAULT_MAX_ROUNDS` | Simulation round limit (default: 10) |

`Config.validate()` runs at startup and exits if the active provider's key or the memory backend credentials are missing.

## Skill routing

When the user's request matches an available skill, invoke it via the Skill tool. When in doubt, invoke the skill.

Key routing rules:
- Product ideas/brainstorming → invoke /office-hours
- Strategy/scope → invoke /plan-ceo-review
- Architecture → invoke /plan-eng-review
- Design system/plan review → invoke /design-consultation or /plan-design-review
- Full review pipeline → invoke /autoplan
- Bugs/errors → invoke /investigate
- QA/testing site behavior → invoke /qa or /qa-only
- Code review/diff check → invoke /review
- Visual polish → invoke /design-review
- Ship/deploy/PR → invoke /ship or /land-and-deploy
- Save progress → invoke /context-save
- Resume context → invoke /context-restore
