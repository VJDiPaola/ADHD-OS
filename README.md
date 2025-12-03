# ADHD-OS v2.1: The Executive Function Prosthetic

> **"A second brain that doesn't just store information, but initiates action."**

## 🚨 The Problem
Traditional productivity tools (Notion, Todoist, Calendars) assume you have the **executive function** to use them. They are passive repositories. For an ADHD brain, the problem isn't *knowing* what to do—it's **bridging the gap between intention and action**.

We don't need another list. We need a **co-pilot**.

## 🧠 The Solution: Agentic AI
ADHD-OS is not a static app. It is a **multi-agent system** that acts as a prosthetic for specific executive dysfunctions. It doesn't just wait for you; it proactively helps you:
1.  **Initiate**: Overcome "Wall of Awful" paralysis.
2.  **Decompose**: Break overwhelming projects into microscopic steps.
3.  **Regulate**: Manage rejection sensitivity (RSD) and anxiety.
4.  **Calibrate**: Fix time blindness with historical data.

## 🏗️ Architecture
The system runs on a local Python backend (`adhd_os/`) powered by state-of-the-art LLMs:
- **Google Gemini 2.0 Flash**: High-speed orchestration and real-time responses.
- **Google Gemini 2.0 Pro**: Deep pattern analysis and data correlation.
- **Anthropic Claude 4.5 Sonnet & Opus**: Nuanced emotional regulation and complex task decomposition.

It features a **React frontend** (`dashboard/`) for visualizing energy and task history.

### ✨ Key Capabilities (v2.1)
- **Context Recovery**: Remembers your state even after a restart (12h window).
- **Proactive Notifications**: Sends desktop alerts for body double check-ins.
- **Pattern Learning**: Analyzes your history to find "energy vs. task" correlations.
- **Safety Layer**: Hard-coded intervention for crisis keywords (bypassing LLMs).
- **Interactive Calibration**: Learns from your actual vs. estimated time.

### The Agent Roster
| Agent | Role | Specialization |
|-------|------|----------------|
| **Orchestrator** | The Boss | Routes requests, maintains context, manages state. |
| **Task Initiator** | The Starter | Identifies barriers (fear, boredom) and generates the *tiniest* next step. |
| **Decomposer** | The Planner | Breaks "Do Taxes" into 40 distinct, 5-minute actions. |
| **Body Double** | The Partner | Deterministic machine that holds space and demands check-ins. |
| **Time Calibrator** | The Realist | "You said 10 mins, history says 45. Let's block an hour." |
| **Reflector** | The Critic | Reviews plans for blind spots and future-proofs them. |
| **Pattern Analyst** | The Scientist | Finds hidden correlations (e.g., "Low energy = Admin avoidance"). |

## 🚀 Getting Started

### Prerequisites
- Python 3.10+
- Node.js 18+ (for Dashboard)
- API Keys: `GOOGLE_API_KEY` (Gemini), `ANTHROPIC_API_KEY` (Claude)

### Installation
1.  **Clone the repo**:
    ```bash
    git clone https://github.com/yourusername/ADHD-OS.git
    cd ADHD-OS
    ```
2.  **Install Python dependencies**:
    ```bash
    pip install -r requirements.txt
    ```
3.  **Setup Dashboard** (Optional but recommended):
    ```bash
    cd adhd_os/dashboard/frontend
    npm install
    ```

### Usage

#### 1. Run the CLI Agent
This is the core experience.
```bash
python -m adhd_os.main
```
**Commands to try:**
- `"I'm stuck on the QBR report."` (Triggers Task Initiator)
- `"Break down cleaning the garage."` (Triggers Decomposer)
- `"Body double me for 30 mins."` (Triggers Body Double)
- `"Review my plan for tomorrow."` (Triggers Reflector)
- `"Shutdown"` (Runs Pattern Analysis & Summary)

#### 2. Run the Dashboard
Visualize your energy and history.
**Backend:**
```bash
uvicorn adhd_os.dashboard.backend:app --reload --port 8000
```
**Frontend:**
```bash
cd adhd_os/dashboard/frontend
npm run dev
```
Open `http://localhost:5173` in your browser.

## 🛡️ Safety & Privacy
- **Local First**: Your data (tasks, journals) lives in a local SQLite database (`adhd_os.db`).
- **Crisis Intervention**: A hard-coded safety layer detects crisis keywords and provides immediate resources (988/Crisis Text Line) without LLM latency.


## ⚙️ Configuration
Set these environment variables in your `.env` or shell:

| Variable | Description | Default |
|----------|-------------|---------|
| `GOOGLE_API_KEY` | Required for Gemini models. | - |
| `ANTHROPIC_API_KEY` | Required for Claude models. | - |
| `ADHD_OS_MODEL_MODE` | `production` (fast/cheap), `quality` (smarter), or `ab_test`. | `production` |

## 🔧 Troubleshooting
- **Notifications not showing?**
  - Ensure `plyer` is installed. On Linux, you may need `libnotify-bin`.
  - On macOS, allow Terminal to send notifications in System Settings.
- **"ImportError: List"**?
  - Ensure you are running Python 3.10+.
- **Database locked?**
  - Only one process can write to `adhd_os.db` at a time. Ensure no other instances are running.

## 📂 Project Structure
```
ADHD-OS/
├── adhd_os/
│   ├── agents/          # Specialist agents (activation, emotional, etc.)
│   ├── dashboard/       # React frontend + FastAPI backend
│   ├── infrastructure/  # DB, Logging, Event Bus
│   ├── tools/           # Tools for agents (time, state, files)
│   ├── config.py        # Model configuration
│   ├── main.py          # CLI Entry point
│   └── state.py         # User state management
├── tests/               # Integration tests
├── adhd_os.db           # Local SQLite database (auto-created)
└── requirements.txt     # Python dependencies
```

## 📄 License
This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

## 🤝 Contributing
We welcome PRs! Please see `CONTRIBUTING.md` (coming soon).

---
*Built with ❤️ (and hyperfocus) by Vince.*
