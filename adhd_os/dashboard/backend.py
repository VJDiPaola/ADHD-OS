import json
import os
import sqlite3
from contextlib import contextmanager
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="ADHD-OS Dashboard API")

# CORS: read allowed origins from env, default to local dev frontend
_cors_origins_raw = os.environ.get("ADHD_OS_CORS_ORIGINS", "http://localhost:5173")
CORS_ORIGINS = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "adhd_os.db"


@contextmanager
def get_db_connection():
    """Context manager that guarantees the connection is closed."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

class StatsResponse(BaseModel):
    current_energy: int
    tasks_completed_today: int
    current_multiplier: float

class TaskHistoryItem(BaseModel):
    id: int
    task_type: str
    completed_at: str
    duration_minutes: float

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    with get_db_connection() as conn:
        cursor = conn.cursor()

        cursor.execute(
            "SELECT key, value FROM user_state WHERE key IN ('energy_level', 'base_multiplier')"
        )
        rows = cursor.fetchall()
        state = {}
        for row in rows:
            try:
                state[row["key"]] = json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                pass

        cursor.execute(
            "SELECT COUNT(*) as count FROM task_history "
            "WHERE date(timestamp) = date('now', 'localtime')"
        )
        task_count = cursor.fetchone()["count"]

    return StatsResponse(
        current_energy=int(state.get("energy_level", 5)),
        current_multiplier=float(state.get("base_multiplier", 1.5)),
        tasks_completed_today=task_count,
    )


@app.get("/api/history", response_model=List[TaskHistoryItem])
async def get_history():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT id, task_type, timestamp, actual_minutes
            FROM task_history
            ORDER BY timestamp DESC
            LIMIT 50
            """
        )
        rows = cursor.fetchall()

    return [
        TaskHistoryItem(
            id=row["id"],
            task_type=row["task_type"],
            completed_at=row["timestamp"],
            duration_minutes=float(row["actual_minutes"] or 0),
        )
        for row in rows
    ]


@app.get("/api/sessions")
async def get_sessions():
    with get_db_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, created_at, last_updated_at "
            "FROM sessions ORDER BY last_updated_at DESC LIMIT 10"
        )
        rows = cursor.fetchall()

    return [
        {
            "id": row["id"],
            "created_at": row["created_at"],
            "last_active": row["last_updated_at"],
        }
        for row in rows
    ]

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
