<div align="center">

<img src="./static/image/MiroFish_logo_compressed.jpeg" alt="MiroFish Logo" width="70%"/>

<a href="https://trendshift.io/repositories/16144" target="_blank"><img src="https://trendshift.io/api/badge/repositories/16144" alt="MiroFish | Trendshift" style="width: 250px; height: 55px;" width="250" height="55"/></a>

**A multi-agent social simulation engine that predicts how people will react — to anything.**

Upload documents. Describe what you want to know. Get a full simulation with hundreds of AI agents, a prediction report, and a live world you can interrogate.

[![GitHub Stars](https://img.shields.io/github/stars/666ghj/MiroFish?style=flat-square&color=DAA520)](https://github.com/666ghj/MiroFish/stargazers)
[![GitHub Forks](https://img.shields.io/github/forks/666ghj/MiroFish?style=flat-square)](https://github.com/666ghj/MiroFish/network)
[![Docker](https://img.shields.io/badge/Docker-Ready-2496ED?style=flat-square&logo=docker&logoColor=white)](https://hub.docker.com/)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/666ghj/MiroFish)
[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=flat-square&logo=discord&logoColor=white)](http://discord.gg/ePf5aPaHnA)

[English](./README.md) | [中文文档](./README-ZH.md)

</div>

---

## What is MiroFish?

MiroFish turns documents into living simulations. You feed it source material — a news article, a policy draft, a legal filing, a novel — and it:

1. **Extracts the world** from your documents: entities, relationships, events, and context, stored in a knowledge graph
2. **Populates that world** with AI agents: each agent gets a unique identity, profession, beliefs, and memory derived from the source material
3. **Runs a social simulation** across Twitter-like and Reddit-like platforms simultaneously — agents post, argue, react, and evolve
4. **Generates a prediction report** with a specialized AI analyst that has access to the full simulation history
5. **Lets you dig deeper** — ask questions of any individual agent, or interrogate the analyst about specific trends

The whole pipeline runs locally (or in Docker) and is designed for researchers, strategists, writers, and analysts who want more than a chatbot response.

---

## Example Use Cases

### Policy & Regulatory Analysis
Upload a draft regulation and ask: *"How will different stakeholder groups respond within 30 days of announcement?"*

MiroFish generates agents representing citizens, lobbyists, journalists, and officials — then simulates their social media reactions, debates, and coalition-forming. The report surfaces which provisions cause the most friction and why.

### Public Opinion Forecasting
Upload a breaking news article and ask: *"How does this spread across different community types, and does outrage peak or fade?"*

Agents representing different demographics engage with the news and with each other. Watch the simulation in real time, then read the analyst report.

### Crisis Communication Testing
Upload a draft press release for a product recall or scandal. Ask: *"How does public trust evolve over the next week under this messaging?"*

Run the simulation, then ask the analyst: *"Which groups remained sympathetic and why?"* Revise your messaging and run again.

### Literary & Historical Exploration
Upload the first 80 chapters of a novel with an ambiguous ending. Ask: *"How do the established character dynamics resolve in the missing chapters?"*

Agents derived from the characters interact in the simulation's social space. The result is an emergent, character-consistent continuation you can read and explore.

*(MiroFish has already done this with Dream of the Red Chamber — see the demo video below.)*

### Financial Event Simulation
Upload earnings reports or macro data. Ask: *"How do retail investors, institutional traders, and financial journalists respond to this over 48 hours?"*

The simulation captures sentiment contagion effects that simple sentiment analysis cannot.

---

## Screenshots

<div align="center">
<table>
<tr>
<td><img src="./static/image/Screenshot/运行截图1.png" alt="Graph Build" width="100%"/></td>
<td><img src="./static/image/Screenshot/运行截图2.png" alt="Agent Personas" width="100%"/></td>
</tr>
<tr>
<td><img src="./static/image/Screenshot/运行截图3.png" alt="Simulation Running" width="100%"/></td>
<td><img src="./static/image/Screenshot/运行截图4.png" alt="Prediction Report" width="100%"/></td>
</tr>
<tr>
<td><img src="./static/image/Screenshot/运行截图5.png" alt="Agent Interview" width="100%"/></td>
<td><img src="./static/image/Screenshot/运行截图6.png" alt="Deep Interaction" width="100%"/></td>
</tr>
</table>
</div>

---

## Demo Videos

### Public Opinion Simulation (Wuhan University)
<div align="center">
<a href="https://www.bilibili.com/video/BV1VYBsBHEMY/" target="_blank">
<img src="./static/image/武大模拟演示封面.png" alt="MiroFish Demo" width="70%"/>
</a>
<br><em>Click to watch the full walkthrough using a real public opinion report as seed material</em>
</div>

### Dream of the Red Chamber — Lost Ending Simulation
<div align="center">
<a href="https://www.bilibili.com/video/BV1cPk3BBExq" target="_blank">
<img src="./static/image/红楼梦模拟推演封面.jpg" alt="Dream of the Red Chamber Demo" width="70%"/>
</a>
<br><em>MiroFish predicts the lost ending from the first 80 chapters of a 300-year-old classic</em>
</div>

---

## How It Works

```
  Documents / URLs
        │
        ▼
  ┌─────────────────┐
  │  Step 1         │  LLM extracts ontology (entity types, relation types)
  │  Graph Build    │  LightRAG ingests text → knowledge graph
  └────────┬────────┘  (NetworkX, persisted as .graphml — survives restarts)
           │
           ▼
  ┌─────────────────┐
  │  Step 2         │  Graph nodes → Agent personas (name, profession, beliefs, bio)
  │  Environment    │  LLM generates simulation config (rounds, timing, events)
  │  Setup          │  Twitter CSV + Reddit JSON profiles written to disk
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Step 3         │  OASIS engine runs dual-platform simulation
  │  Simulation     │  Agents post, reply, follow, react — stored in SQLite
  │  Run            │  Real-time round-by-round progress visible in UI
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Step 4         │  ReportAgent reads the full simulation history
  │  Report         │  Generates a structured prediction report with tool calls
  └────────┬────────┘
           │
           ▼
  ┌─────────────────┐
  │  Step 5         │  Interview any individual agent directly
  │  Deep           │  Ask the ReportAgent follow-up questions
  │  Interaction    │  Re-run simulations from saved checkpoints
  └─────────────────┘
```

---

## Quick Start

### Option A: Docker (Recommended)

**Requirements:** Docker Desktop with at least 8 GB RAM allocated, ~5 GB free disk

**1. Clone and configure**
```bash
git clone https://github.com/666ghj/MiroFish.git
cd MiroFish
cp .env.example .env
```

Open `.env` and add at minimum one LLM API key (see [LLM Providers](#llm-providers) below).

**2. Start everything**
```bash
docker compose up -d
```

This starts two containers:
- `mirofish-app` — Flask backend + Vite frontend with hot-reload
- `mirofish-app-neo4j` — FalkorDB graph database

**3. Open the app**
```
http://localhost:3010
```

> First startup takes 2–5 minutes while the embedding model downloads (~400 MB into a Docker volume). Subsequent starts are instant.

**4. Stop**
```bash
docker compose down
```

---

### Option B: Local Development

**Requirements:** Node.js 18+, Python 3.11 or 3.12, [uv](https://docs.astral.sh/uv/) package manager

```bash
git clone https://github.com/666ghj/MiroFish.git
cd MiroFish
cp .env.example .env
# Edit .env — add your LLM key

npm run setup:all   # installs all frontend + backend dependencies
npm run dev         # starts Flask on :5001 and Vite dev server on :3000
```

Open `http://localhost:3000`. The `/api` requests are proxied to Flask automatically.

Other dev commands:
```bash
npm run backend     # start Flask only
npm run frontend    # start Vite only
npm run build       # production frontend build

cd backend && uv add <package>   # add a Python dependency
cd backend && uv sync            # sync lockfile
```

---

## LLM Providers

MiroFish supports **runtime provider switching from the UI** — no restart needed. Configure any combination in `.env` and switch between them during a session.

| Provider | Model | Key needed | Notes |
|---|---|---|---|
| **MiniMax** | MiniMax-M2.7 | `MINIMAX_API_KEY` | Default provider. Strong reasoning, good JSON output |
| **Kimi** | kimi-for-coding | `KIMI_API_KEY` | Kimi For Coding endpoint; excellent instruction following |
| **OpenRouter** | deepseek/deepseek-v4-flash:free | `OPENROUTER_API_KEY` | Free tier available; good for experimentation |
| **Custom** | any | `LLM_API_KEY` + `LLM_BASE_URL` + `LLM_MODEL_NAME` | Any OpenAI-compatible endpoint (Ollama, Azure, LM Studio, etc.) |

Add to `.env`:
```env
# Add whichever provider(s) you have access to
MINIMAX_API_KEY=your_key_here
KIMI_API_KEY=your_key_here
OPENROUTER_API_KEY=your_key_here

# Default provider on first launch (can be changed in the UI at any time)
LLM_PROVIDER=minimax
```

The active provider is saved between sessions. You can also type a custom model name in the UI provider switcher to override the default.

---

## Configuration Reference

| Variable | Default | Description |
|---|---|---|
| `LLM_PROVIDER` | `minimax` | Startup default: `minimax` / `kimi` / `openrouter` / `custom` |
| `MINIMAX_API_KEY` | — | MiniMax API key |
| `KIMI_API_KEY` | — | Kimi API key (uses the Coding Plan endpoint) |
| `OPENROUTER_API_KEY` | — | OpenRouter API key |
| `LLM_API_KEY` | — | Custom provider key |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | Custom provider base URL |
| `LLM_MODEL_NAME` | — | Custom provider model name |
| `MEMORY_BACKEND` | `graphiti` | `graphiti` (local Neo4j) or `zep` (Zep Cloud) |
| `NEO4J_URI` | `bolt://neo4j:7687` | Graph DB connection (Docker default) |
| `NEO4J_USER` | `neo4j` | Graph DB username |
| `NEO4J_PASSWORD` | `mirofish` | Graph DB password |
| `EMBEDDING_MODEL` | `BAAI/bge-small-en-v1.5` | Local sentence-transformers model |
| `RERANKER_MODEL` | `BAAI/bge-reranker-base` | Local BGE reranker |
| `JINA_API_KEY` | — | Optional — higher quota for Jina Reader URL ingestion |
| `OASIS_DEFAULT_MAX_ROUNDS` | `10` | Default simulation round limit |

---

## Supported Input Formats

| Format | Notes |
|---|---|
| PDF | Text-layer PDFs work best |
| Markdown (`.md`) | Full support |
| Plain text (`.txt`) | Full support |
| URLs | Paste any web URL — MiroFish fetches and converts via [Jina Reader](https://jina.ai/reader) |

Mix files and URLs in a single project. Longer, more detailed source material produces richer agents and more realistic simulations.

---

## System Requirements

| Resource | Minimum | Recommended |
|---|---|---|
| RAM (for Docker) | 6 GB | 8 GB+ |
| CPU cores | 2 | 4+ |
| Disk | 3 GB | 5 GB+ |
| Internet | Required (LLM API calls) | — |

The embedding model runs locally inside the container. It downloads once and caches in a Docker volume.

---

## Troubleshooting

**Graph build stuck or showing 0 nodes**

Check container logs: `docker compose logs -f mirofish`. The embedding model may still be downloading on first run — wait 2–5 minutes.

**"API key not configured" error during agent generation**

The provider selected in the UI doesn't have a key in `.env`. If you switched to Custom, you need `LLM_API_KEY`, `LLM_BASE_URL`, and `LLM_MODEL_NAME` all set.

**Simulation stuck after agent personas are generated**

The config polling will retry automatically for up to 3 minutes. If it still fails, click the Reset button in the header and restart from Step 2.

**Container killed / out of memory**

Increase Docker's memory limit. Open Docker Desktop → Settings → Resources → increase to at least 8 GB. The `docker-compose.yml` sets an 8 GB limit on the app container.

---

## Architecture Overview

```
backend/app/
  api/            Flask blueprints: graph, simulation, report, settings
  services/
    memory/       LightRAG + NetworkX graph backend (graph persisted as .graphml)
    simulation_manager.py   Orchestrates prepare → start → stop lifecycle
    simulation_runner.py    Spawns OASIS subprocess, handles IPC
    oasis_profile_generator.py   LLM-generated per-agent personas
    simulation_config_generator.py  LLM-generated time/event parameters
    report_agent.py         Post-simulation report with tool calls
  utils/
    llm_providers.py        Provider registry + runtime switching (persisted to JSON)
    llm_client.py           OpenAI SDK wrapper; strips <think> tags from chain-of-thought models
  models/         Project and Task dataclasses persisted as JSON files

frontend/src/
  views/          MainView (graph build), SimulationView, ReportView
  components/     Step1–5 workflow, GraphPanel (D3 force graph), LLMProviderSwitcher
  api/            One module per blueprint (graph.js, simulation.js, report.js, settings.js)
```

Key design decisions:
- **LightRAG + NetworkX**: Graph stored as `.graphml` files that survive container restarts without a separate graph database
- **OASIS subprocess**: The simulation engine runs as a separate process; Flask manages it via IPC so the web server stays responsive during long simulations
- **Provider-aware clients**: All LLM calls go through `llm_providers.get_active_*()` — never hardcoded env vars — so the UI switcher works correctly everywhere
- **Checkpoint persistence**: Each phase (graph, profiles, config, simulation) is saved to disk so you can resume a long job after a crash without restarting from scratch

---

## Contributing

Pull requests are welcome. Open an issue first for significant changes to discuss direction.

Areas actively being improved:
- More LLM provider integrations
- Richer agent behavior models
- Export formats (JSON, CSV, PDF reports)
- Multi-language UI

---

## Acknowledgments

MiroFish has received strategic support and incubation from **[Shanda Group](https://www.shanda.com/)**.

<div align="center">
<a href="https://www.shanda.com/" target="_blank">
<img src="./static/image/shanda_logo.png" alt="Shanda" height="40"/>
</a>
</div>

The simulation engine is built on **[OASIS](https://github.com/camel-ai/oasis)** by the CAMEL-AI team — thank you for the open-source foundation.

---

## Community & Careers

[![Discord](https://img.shields.io/badge/Discord-Join-5865F2?style=flat-square&logo=discord&logoColor=white)](http://discord.gg/ePf5aPaHnA)
[![X](https://img.shields.io/badge/X-Follow-000000?style=flat-square&logo=x&logoColor=white)](https://x.com/mirofish_ai)
[![Instagram](https://img.shields.io/badge/Instagram-Follow-E4405F?style=flat-square&logo=instagram&logoColor=white)](https://www.instagram.com/mirofish_ai/)

The team is hiring for full-time and internship positions in multi-agent simulation and LLM applications. Send a resume to **mirofish@shanda.com**.

---

## Star History

<a href="https://www.star-history.com/#666ghj/MiroFish&type=date&legend=top-left">
  <picture>
    <source media="(prefers-color-scheme: dark)" srcset="https://api.star-history.com/svg?repos=666ghj/MiroFish&type=date&theme=dark&legend=top-left" />
    <source media="(prefers-color-scheme: light)" srcset="https://api.star-history.com/svg?repos=666ghj/MiroFish&type=date&legend=top-left" />
    <img alt="Star History Chart" src="https://api.star-history.com/svg?repos=666ghj/MiroFish&type=date&legend=top-left" />
  </picture>
</a>
