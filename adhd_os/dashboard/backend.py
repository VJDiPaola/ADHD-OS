import json
import os
import sqlite3
from typing import List, Optional
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="ADHD-OS Dashboard API")

# Restrict CORS to localhost by default; override via ADHD_OS_CORS_ORIGINS env var
_default_origins = ["http://localhost:5173", "http://localhost:8000", "http://127.0.0.1:5173"]
_cors_origins = os.environ.get("ADHD_OS_CORS_ORIGINS", "").split(",") if os.environ.get("ADHD_OS_CORS_ORIGINS") else _default_origins

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "adhd_os.db"

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

class StatsResponse(BaseModel):
    current_energy: int
    tasks_completed_today: int
    current_multiplier: float

class TaskHistoryItem(BaseModel):
    id: int
    task_type: str
    estimated_minutes: int
    actual_minutes: int
    energy_level: int
    timestamp: str

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Get current energy from user_state key-value store
    cursor.execute("SELECT value FROM user_state WHERE key = 'energy_level'")
    energy_row = cursor.fetchone()
    energy = int(json.loads(energy_row['value'])) if energy_row else 5

    # Get base_multiplier from user_state (dynamic_multiplier is computed at runtime, not stored)
    cursor.execute("SELECT value FROM user_state WHERE key = 'base_multiplier'")
    mult_row = cursor.fetchone()
    multiplier = float(json.loads(mult_row['value'])) if mult_row else 1.5

    # Get tasks completed today — task_history uses 'timestamp' column
    cursor.execute("SELECT COUNT(*) as count FROM task_history WHERE date(timestamp) = date('now')")
    task_count = cursor.fetchone()['count']

    conn.close()

    return StatsResponse(
        current_energy=energy,
        current_multiplier=multiplier,
        tasks_completed_today=task_count
    )

@app.get("/api/history", response_model=List[TaskHistoryItem])
async def get_history():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Use actual column names from task_history schema:
    # id, task_type, estimated_minutes, actual_minutes, energy_level, in_peak_window, timestamp
    cursor.execute("""
        SELECT id, task_type, estimated_minutes, actual_minutes, energy_level, timestamp
        FROM task_history
        ORDER BY timestamp DESC
        LIMIT 50
    """)
    rows = cursor.fetchall()

    history = []
    for row in rows:
        history.append(TaskHistoryItem(
            id=row['id'],
            task_type=row['task_type'] or "unknown",
            estimated_minutes=row['estimated_minutes'] or 0,
            actual_minutes=row['actual_minutes'] or 0,
            energy_level=row['energy_level'] or 5,
            timestamp=str(row['timestamp'] or ""),
        ))

    conn.close()
    return history

@app.get("/api/sessions")
async def get_sessions():
    conn = get_db_connection()
    cursor = conn.cursor()

    # Use actual column name: last_updated_at (not last_update_time)
    cursor.execute("SELECT id, created_at, last_updated_at FROM sessions ORDER BY last_updated_at DESC LIMIT 10")
    rows = cursor.fetchall()

    sessions = []
    for row in rows:
        sessions.append({
            "id": row['id'],
            "created_at": row['created_at'],
            "last_active": row['last_updated_at']
        })

    conn.close()
    return sessions

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
