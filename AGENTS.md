# AGENTS.md

This file provides guidance to WARP (warp.dev) when working with code in this repository.

## Project Overview

ADHD-OS is a multi-agent CLI system built on Google ADK that routes natural-language input to specialist AI agents, each tuned for a specific executive dysfunction (task initiation, time blindness, emotional regulation, etc.). All data stays local in SQLite (`adhd_os.db`).

## Commands

### Run the CLI
```bash
python -m adhd_os.main
```
Requires environment variables: `GOOGLE_API_KEY` and `ANTHROPIC_API_KEY`

### Run Tests
```bash
python tests/test_routing.py
```
Tests mock LLM calls to avoid API costs. The test verifies orchestrator routing to sub-agents.

### Run Dashboard (Optional)
```bash
# Backend (FastAPI)
uvicorn adhd_os.dashboard.backend:app --reload --port 8000

# Frontend (React + Vite)
cd adhd_os/dashboard/frontend
npm install   # first time only
npm run dev
```

### Docker
```bash
docker build -t adhd-os .
docker run -it -e GOOGLE_API_KEY="..." -e ANTHROPIC_API_KEY="..." adhd-os
```

## Architecture

### Agent Hierarchy
The `orchestrator` (`agents/orchestrator.py`) is the root agent that routes user input to specialist sub-agents organized into clusters:

- **Activation Cluster** (`agents/activation.py`): `task_init_agent`, `decomposer_agent`, `body_double_agent`
- **Temporal Cluster** (`agents/temporal.py`): `time_calibrator_agent`, `calendar_agent`, `focus_timer_agent`
- **Emotional Cluster** (`agents/emotional.py`): `catastrophe_agent`, `rsd_agent`, `motivation_agent`
- **Reflection Cluster**: `reflector_agent` (`agents/reflector.py`), `pattern_analysis_agent` (`agents/pattern_analysis.py`)

### Agent Pattern
All agents use `google.adk.agents.LlmAgent` with:
- `model`: LiteLlm wrapper around model from `config.MODELS`
- `description`: Used by orchestrator for routing decisions
- `instruction`: System prompt with agent-specific behavior
- `tools`: Functions decorated with `@FunctionTool` from `tools/common.py`

### Model Selection
Models are configured in `config.py`. The `ADHD_OS_MODEL_MODE` env var controls quality vs speed tradeoffs:
- `production` (default): Gemini Flash for everything
- `quality`: Claude Opus for decomposition
- `ab_test`: Random selection for comparison

### State Management
- `state.py`: Global `USER_STATE` dataclass tracks energy, medication window, current task, dynamic multiplier
- `infrastructure/database.py`: SQLite persistence via `DB` singleton (key-value user_state, task_history, task_cache, sessions)
- `infrastructure/persistence.py`: Google ADK session service backed by SQLite

### Deterministic Machines
`infrastructure/machines.py` contains state machines that operate without LLM calls:
- `BodyDoubleMachine`: Accountability check-ins on fixed intervals
- `FocusTimerMachine`: Hyperfocus guardrails with timed warnings

These run as background asyncio tasks and communicate via the event bus.

### Event System
`infrastructure/event_bus.py`: Async pub/sub for decoupled components. Events include `TASK_COMPLETED`, `CHECKIN_DUE`, `ENERGY_UPDATED`, etc. Desktop notifications subscribe to `CHECKIN_DUE`.

### Tools
All agent tools are in `tools/common.py` and decorated with `@FunctionTool`. Key tools:
- `get_user_state` / `update_user_state`: Access dynamic multiplier, energy, peak window
- `apply_time_calibration`: Adjusts time estimates using dynamic multiplier
- `check_task_cache` / `store_task_decomposition`: Semantic caching for decomposition plans
- `activate_body_double` / `get_body_double_status`: Control deterministic accountability machine
- `log_task_completion`: Records actual vs estimated time for calibration learning

### Crisis Safety
Hard-coded keyword detection in `main.py` bypasses LLMs entirely to show crisis resources (988 Lifeline). This must remain synchronous and deterministic.

## Key Patterns

- **Dynamic Multiplier**: Time estimates adjust based on energy level, medication peak window, and time of day. Never use raw user estimates.
- **Microscopic Steps**: Task decomposition should produce steps ≤10 minutes with clear completion states.
- **No LLM for Accountability**: Body double check-ins are deterministic, not LLM-generated, for reliability.
- **Event-Driven**: Use `EVENT_BUS.publish()` for cross-component communication rather than direct calls.
- **Local-First**: All data in `adhd_os.db`. Only network calls are to LLM APIs.

## Cursor Cloud specific instructions

### Services overview

| Service | How to start | Port | Notes |
|---------|-------------|------|-------|
| CLI (core) | `python3 -m adhd_os.main` | — | Requires `GOOGLE_API_KEY` and `ANTHROPIC_API_KEY` env vars |
| Dashboard backend | `python3 -m uvicorn adhd_os.dashboard.backend:app --reload --port 8000` | 8000 | Run from repo root |
| Dashboard frontend | `npm run dev` (from `adhd_os/dashboard/frontend/`) | 5173 | Connects to backend on :8000 |

### Gotchas

- Use `python3` not `python` — the VM has no `python` alias.
- Use `python3 -m uvicorn` not bare `uvicorn` — the pip-installed binary may not be on `PATH`.
- `tests/test_routing.py` currently fails (all 7 cases) due to a breaking API change in `google-adk` >=1.x where `Runner.run_async()` returns a coroutine instead of an async generator. The test is not broken by agent code changes — it is a pre-existing upstream compatibility issue.
- The CLI starts and displays its prompt without API keys, but any user input that triggers an agent will fail. Tests mock LLM calls and do not need API keys.
- The `GOOGLE_API_KEY` must be from a **paid-tier** Google AI Studio project. Free-tier keys have a quota limit of 0 for `gemini-2.0-flash` and will fail with a 429 `RESOURCE_EXHAUSTED` error immediately.
- The CLI is interactive (`input()` loop). It cannot be driven via pipe reliably because it has a "Resume session?" prompt that consumes the first line of piped input. Use a real TTY (e.g., `computerUse` subagent or background terminal) for interactive testing.
- Frontend lint: `npx eslint .` from `adhd_os/dashboard/frontend/`. No Python linter is configured in the repo.
- Frontend build: `npm run build` from `adhd_os/dashboard/frontend/`.
