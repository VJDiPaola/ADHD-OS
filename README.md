# ADHD-OS v2.1 — The Executive Function Prosthetic

> A multi-agent AI co-pilot that helps ADHD brains **start tasks, manage time, regulate emotions, and build momentum** — not another to-do list.

---

## ⚡ 30-Second Quickstart

```bash
git clone https://github.com/vjdipaola/adhd-os.git
cd adhd-os
pip install -r requirements.txt

# Set your API keys (both required for full agent roster)
export GOOGLE_API_KEY="your-google-api-key"
export ANTHROPIC_API_KEY="your-anthropic-api-key"

# Launch
python -m adhd_os.main
```

> **Windows?** Use `set` instead of `export`, or add the keys to your system environment variables.

---

## 🧠 What Is ADHD-OS?

Traditional productivity apps assume you have the executive function to use them. ADHD-OS doesn't.

It's a **CLI agent system** built on [Google ADK](https://github.com/google/adk-python) that routes your natural-language input to specialist AI agents — each tuned for a specific executive dysfunction. You talk to it like a co-worker, and it figures out what you actually need:

- Stuck? It finds the *tiny* next step.
- Overwhelmed? It decomposes the task into 5-minute chunks.
- Anxious? It reality-tests the catastrophe.
- Time-blind? It calibrates your estimate with historical data.

All data stays local in a SQLite database. No cloud sync, no accounts.

---

## ✨ Features

| Feature | Description |
|---------|-------------|
| **Task Initiation** | Identifies the real barrier (fear, boredom, overwhelm) and generates a ≤5-minute first step |
| **Task Decomposition** | Breaks big tasks into microscopic, checkpointed steps with rabbit-hole warnings |
| **Body Doubling** | Deterministic accountability machine — no LLM needed, just timed check-ins and desktop notifications |
| **Time Calibration** | Applies a dynamic multiplier based on energy, medication window, and task history |
| **Hyperfocus Guardrails** | Sets hard stops with 30/10/5-minute warnings so deep work doesn't derail the day |
| **Emotional Regulation** | Anxiety reality-testing, RSD shielding, and dopamine-based motivation strategies |
| **Pattern Analysis** | Finds correlations in your history (e.g., "low energy → admin avoidance") |
| **Plan Review** | Reflector agent that sanity-checks your plans for blind spots |
| **Context Recovery** | Resumes your last session within a 12-hour window |
| **Crisis Safety Layer** | Hard-coded keyword detection → immediate 988/Crisis Text Line resources (bypasses LLMs) |
| **Dashboard** | Optional React + FastAPI UI for visualizing energy, task history, and sessions |

---

## 🤖 Agent Roster

| Agent | Cluster | What It Does | Model |
|-------|---------|-------------|-------|
| **Orchestrator** | Core | Routes input to the right specialist, manages state | Gemini 3 Flash Preview |
| **Task Initiator** | Activation | Overcomes "Wall of Awful" paralysis with a tiny next step | Claude Sonnet 4.6 |
| **Decomposer** | Activation | Breaks tasks into ≤10-min steps with checkpoints | Claude Sonnet 4.6 (quality) / Gemini 3 Flash Preview (production) |
| **Body Double** | Activation | Deterministic check-in machine for accountability | Gemini 3 Flash Preview |
| **Time Calibrator** | Temporal | Corrects time blindness with dynamic multipliers | Gemini 3 Flash Preview |
| **Calendar Strategist** | Temporal | Schedules around peak medication window | Gemini 3 Flash Preview |
| **Focus Timer** | Temporal | Hyperfocus guardrails with hard-stop warnings | Gemini 3 Flash Preview |
| **Catastrophe Check** | Emotional | Reality-tests anxiety spirals | Claude Sonnet 4.6 |
| **RSD Shield** | Emotional | Reframes perceived rejection | Claude Sonnet 4.6 |
| **Motivation Engineer** | Emotional | Makes boring tasks interesting (speedruns, streaks, rewards) | Gemini 3 Flash Preview |
| **Pattern Analyst** | Reflection | Finds hidden correlations in task history | Gemini 3 Flash Preview |
| **Reflector** | Reflection | Reviews plans for blind spots | Gemini 3 Flash Preview |
| **Session Summarizer** | Utility | Compresses session into a narrative summary on shutdown | Gemini 3 Flash Preview |

---

## 📦 Installation

### Prerequisites

- **Python 3.10+**
- **Node.js 18+** (only if using the dashboard)
- API keys for [Google AI (Gemini)](https://aistudio.google.com/apikey) and [Anthropic (Claude)](https://console.anthropic.com/)

### Step-by-Step

```bash
# 1. Clone
git clone https://github.com/vjdipaola/adhd-os.git
cd adhd-os

# 2. Install Python dependencies
pip install -r requirements.txt

# 3. Set API keys
# Linux / macOS:
export GOOGLE_API_KEY="your-key"
export ANTHROPIC_API_KEY="your-key"

# Windows (Command Prompt):
set GOOGLE_API_KEY=your-key
set ANTHROPIC_API_KEY=your-key

# Windows (PowerShell):
$env:GOOGLE_API_KEY="your-key"
$env:ANTHROPIC_API_KEY="your-key"
```

### Docker (Alternative)

```bash
docker build -t adhd-os .
docker run -it \
  -e GOOGLE_API_KEY="your-key" \
  -e ANTHROPIC_API_KEY="your-key" \
  adhd-os
```

---

## 🚀 Usage

### CLI (Core Experience)

```bash
python -m adhd_os.main
```

Then just talk to it. Here are real commands you can try:

```
You: I'm stuck on the QBR report
     → Task Initiator finds the barrier and gives you one tiny step

You: Break down cleaning the garage
     → Decomposer creates a checkpointed plan with time calibration

You: Body double me for 30 mins
     → Starts a deterministic check-in loop (with desktop notifications)

You: I'm worried I'll fail the presentation
     → Catastrophe Check reality-tests the anxiety

You: My boss hates me after that email
     → RSD Shield reframes the perceived rejection

You: Make filing expenses fun
     → Motivation Engineer suggests speedruns, streaks, or rewards

You: How long will this coding task take? I think 20 minutes
     → Time Calibrator applies your dynamic multiplier

You: Review my plan for tomorrow
     → Reflector sanity-checks for blind spots

You: morning activation
     → Asks energy level, medication time, priorities → builds day structure

You: shutdown
     → Runs pattern analysis, summarizes session, saves state

You: quit
     → Exits immediately
```

### Dashboard (Optional)

Visualize your energy levels, task history, and session data.

**Start the backend:**
```bash
uvicorn adhd_os.dashboard.backend:app --reload --port 8000
```

**Start the frontend:**
```bash
cd adhd_os/dashboard/frontend
npm install   # first time only
npm run dev
```

Open [http://localhost:5173](http://localhost:5173) in your browser.

---

## ⚙️ Configuration

Set these as environment variables (or in a `.env` file):

| Variable | Required | Description | Default |
|----------|----------|-------------|---------|
| `GOOGLE_API_KEY` | Yes | API key for Google Gemini models | — |
| `ANTHROPIC_API_KEY` | Yes | API key for Anthropic Claude models | — |
| `ADHD_OS_MODEL_MODE` | No | `production` (fast/cheap), `quality` (smarter), or `ab_test` (random) | `production` |

**Model mode details:**

- **`production`** — Uses `gemini/gemini-3-flash-preview` for the orchestrator, temporal agents, motivation, reflector, summarizer, and the decomposer. Empathy-heavy agents still use `anthropic/claude-sonnet-4-6`.
- **`quality`** — Same as `production`, except the decomposer switches to `anthropic/claude-sonnet-4-6`.
- **`ab_test`** — Same as `production`, except the decomposer randomly picks between `gemini/gemini-3-flash-preview` and `anthropic/claude-sonnet-4-6`.

---

## 📂 Project Structure

```
ADHD-OS/
├── adhd_os/
│   ├── agents/             # Specialist agents
│   │   ├── activation.py   #   Task Initiator, Decomposer, Body Double
│   │   ├── emotional.py    #   Catastrophe Check, RSD Shield, Motivation
│   │   ├── orchestrator.py #   Root orchestrator + Session Summarizer
│   │   ├── pattern_analysis.py
│   │   ├── reflector.py    #   Plan reviewer
│   │   └── temporal.py     #   Time Calibrator, Calendar, Focus Timer
│   ├── dashboard/
│   │   ├── backend.py      # FastAPI API (stats, history, sessions)
│   │   └── frontend/       # React + Vite app
│   ├── infrastructure/
│   │   ├── cache.py        # Semantic task cache
│   │   ├── database.py     # SQLite persistence
│   │   ├── event_bus.py    # Async event system
│   │   ├── logging.py      # Structured logging
│   │   ├── machines.py     # Body Double & Focus Timer state machines
│   │   └── persistence.py  # Session persistence (Google ADK)
│   ├── models/
│   │   ├── message.py      # Message schema
│   │   └── schemas.py      # Pydantic models
│   ├── tools/
│   │   └── common.py       # All agent tools (state, time, calibration, etc.)
│   ├── config.py           # Model registry and mode selection
│   ├── main.py             # CLI entry point
│   └── state.py            # User state (energy, medication, multiplier)
├── tests/                  # Tests
├── logs/                   # Runtime logs
├── adhd_os.db              # SQLite database (auto-created)
├── Dockerfile
├── requirements.txt
└── README.md
```

---

## ❓ FAQ & Troubleshooting

### FAQ

**Q: Do I need both API keys?**
A: The system will start with only `GOOGLE_API_KEY`, but agents that use Claude (Task Initiator, Catastrophe Check, RSD Shield, and quality-mode Decomposer) will fail. For the full experience, set both.

**Q: Does it send my data anywhere?**
A: Your task history, journal, and state live in a local SQLite file (`adhd_os.db`). The only network calls are to the LLM APIs (Google Gemini and Anthropic Claude) for agent responses.

**Q: What's the "dynamic multiplier"?**
A: A real-time adjustment to your time estimates based on your current energy level, medication peak window, and time of day. It starts at 1.5× and adjusts up or down automatically.

**Q: Can I use it without the dashboard?**
A: Yes. The CLI (`python -m adhd_os.main`) is the core experience. The dashboard is optional.

**Q: What does "morning activation" do?**
A: It asks your energy level (1–10), medication time, top 3 priorities, and any blockers — then structures your day around your peak focus window.

### Troubleshooting

**Notifications not showing?**
- Ensure `plyer` is installed (`pip install plyer`).
- Linux: you may need `libnotify-bin` (`sudo apt install libnotify-bin`).
- macOS: allow Terminal to send notifications in System Settings → Notifications.

**`ImportError` or syntax errors?**
- Ensure Python 3.10+ (`python --version`). This project uses features not available in older versions.

**"Database locked" error?**
- Only one process can write to `adhd_os.db` at a time. Make sure no other instance of ADHD-OS or the dashboard backend is running.

**Agent returns empty / `[Processing...]`?**
- Check that your API keys are set and valid.
- Check `logs/` for detailed error output.

**Dashboard won't start?**
- Backend: make sure port 8000 is free (`uvicorn adhd_os.dashboard.backend:app --port 8000`).
- Frontend: run `npm install` in `adhd_os/dashboard/frontend/` first, then `npm run dev`.

---

## 🛡️ Safety & Privacy

- **Local-first**: All data lives in `adhd_os.db` (SQLite). No cloud storage, no accounts.
- **Crisis intervention**: A hard-coded safety layer detects crisis keywords and immediately provides 988 Suicide & Crisis Lifeline and Crisis Text Line resources — no LLM latency, no AI interpretation.
- **LLM calls**: The only data sent externally is your conversation text, sent to Google Gemini and Anthropic Claude APIs for agent responses.

---

## 🤝 Contributing

PRs welcome! Please open an issue first to discuss what you'd like to change.

## 📄 License

MIT — see [LICENSE](LICENSE).

---

*Built with ❤️ (and hyperfocus) by Vince.*
