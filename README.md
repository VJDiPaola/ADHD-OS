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
The system runs on a local Python backend (`adhd_os/`) powered by Google Gemini 2.0 Flash (fast) and Anthropic Claude 3.5 Sonnet (nuanced), with a React frontend (`dashboard/`) for visualization.

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

## 🤝 Contributing
We welcome PRs! Please see `CONTRIBUTING.md` (coming soon).

---
*Built with ❤️ (and hyperfocus) by Vince.*
