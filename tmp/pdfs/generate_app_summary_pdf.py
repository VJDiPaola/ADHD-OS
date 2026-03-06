from pathlib import Path
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas


ROOT = Path(__file__).resolve().parents[2]
OUT_DIR = ROOT / "output" / "pdf"
OUT_PATH = OUT_DIR / "adhd_os_app_summary_one_pager.pdf"


def wrap_text(c: canvas.Canvas, text: str, font_name: str, font_size: float, max_width: float):
    words = text.split()
    if not words:
        return [""]
    lines = []
    current = words[0]
    for word in words[1:]:
        trial = f"{current} {word}"
        if c.stringWidth(trial, font_name, font_size) <= max_width:
            current = trial
        else:
            lines.append(current)
            current = word
    lines.append(current)
    return lines


def generate() -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)

    page_w, page_h = letter
    margin = 44
    body_size = 10
    heading_size = 12
    title_size = 18
    line_h = 12.5
    section_gap = 8

    c = canvas.Canvas(str(OUT_PATH), pagesize=letter)
    y = page_h - margin
    usable_w = page_w - (margin * 2)

    def ensure_space(required: float):
        nonlocal y
        if y - required < margin:
            raise RuntimeError("Content overflowed one page. Reduce copy or spacing.")

    def draw_title(text: str):
        nonlocal y
        c.setFont("Helvetica-Bold", title_size)
        c.drawString(margin, y, text)
        y -= 22
        c.setFont("Helvetica", 9)
        c.drawString(margin, y, "Repository evidence snapshot (ADHD-OS)")
        y -= 16

    def draw_heading(text: str):
        nonlocal y
        ensure_space(18)
        c.setFont("Helvetica-Bold", heading_size)
        c.drawString(margin, y, text)
        y -= 14

    def draw_paragraph(text: str):
        nonlocal y
        c.setFont("Helvetica", body_size)
        lines = wrap_text(c, text, "Helvetica", body_size, usable_w)
        ensure_space(line_h * len(lines))
        for line in lines:
            c.drawString(margin, y, line)
            y -= line_h

    def draw_bullets(items):
        nonlocal y
        bullet_indent = 10
        text_x = margin + bullet_indent + 8
        text_width = usable_w - bullet_indent - 8
        c.setFont("Helvetica", body_size)
        for item in items:
            wrapped = wrap_text(c, item, "Helvetica", body_size, text_width)
            ensure_space(line_h * len(wrapped))
            c.drawString(margin + bullet_indent, y, "-")
            c.drawString(text_x, y, wrapped[0])
            y -= line_h
            for cont in wrapped[1:]:
                c.drawString(text_x, y, cont)
                y -= line_h

    draw_title("ADHD-OS: One-Page App Summary")

    draw_heading("What It Is")
    draw_paragraph(
        "ADHD-OS is a local-first multi-agent CLI app built on Google ADK that routes natural-language requests to "
        "specialist agents for activation, time management, emotional regulation, and reflection. It is designed as "
        "an executive-function support system, not a traditional to-do list."
    )
    y -= section_gap

    draw_heading("Who It Is For")
    draw_bullets(
        [
            "Primary persona: people with ADHD or similar executive-function challenges who need real-time support "
            "starting tasks, estimating time, and staying regulated during work."
        ]
    )
    y -= section_gap

    draw_heading("What It Does")
    draw_bullets(
        [
            "Routes each message through an orchestrator to specialist agent clusters (activation, temporal, emotional, reflection).",
            "Breaks large work into microscopic steps (<=10 minutes) with clear completion states and checkpoint prompts.",
            "Calibrates time estimates using a dynamic multiplier driven by energy, medication peak window, time of day, and task history.",
            "Runs deterministic body-double and focus-timer machines with periodic check-ins and hard-stop warnings.",
            "Publishes and consumes async events (for example, task completion and check-in due) through an internal event bus.",
            "Stores user state, sessions, events, task history, and cached decompositions in local SQLite (`adhd_os.db`).",
            "Provides a synchronous crisis safety check in the CLI that bypasses LLM routing and surfaces 988 resources."
        ]
    )
    y -= section_gap

    draw_heading("How It Works (Architecture)")
    draw_bullets(
        [
            "Entry point (`adhd_os/main.py`) loads state, restores recent session context, and runs Google ADK `Runner` with `orchestrator`.",
            "Orchestrator delegates to sub-agents defined in `adhd_os/agents/*.py`; tools in `adhd_os/tools/common.py` provide controlled operations.",
            "Deterministic machines in `adhd_os/infrastructure/machines.py` handle accountability/timers and emit events via `EVENT_BUS`.",
            "Persistence uses `DatabaseManager` and `SqliteSessionService` over SQLite; optional FastAPI dashboard reads the same DB.",
            "Data flow: User input -> Runner/orchestrator -> specialist agent + tools -> events/machines -> SQLite -> optional dashboard API/UI."
        ]
    )
    y -= section_gap

    draw_heading("How To Run (Minimal)")
    draw_bullets(
        [
            "Install dependencies: `pip install -r requirements.txt`.",
            "Set env vars: `GOOGLE_API_KEY` and `ANTHROPIC_API_KEY` (required for full agent coverage).",
            "Run CLI: `python -m adhd_os.main`.",
            "Optional dashboard: backend `uvicorn adhd_os.dashboard.backend:app --reload --port 8000`; frontend in "
            "`adhd_os/dashboard/frontend`: `npm install`, then `npm run dev`."
        ]
    )

    c.showPage()
    c.save()
    return OUT_PATH


if __name__ == "__main__":
    path = generate()
    print(str(path))
