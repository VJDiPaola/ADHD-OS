import os
import sqlite3
from typing import List, Dict, Any
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="ADHD-OS Dashboard API")

# Enable CORS for frontend
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, restrict this
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
    task_id: str
    description: str
    completed_at: str
    duration_minutes: float

@app.get("/api/stats", response_model=StatsResponse)
async def get_stats():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get current energy and multiplier
    cursor.execute("SELECT key, value FROM user_state WHERE key IN ('energy_level', 'dynamic_multiplier')")
    rows = cursor.fetchall()
    state = {row['key']: row['value'] for row in rows}
    
    # Get tasks completed today
    cursor.execute("SELECT COUNT(*) as count FROM task_history WHERE date(completed_at) = date('now')")
    task_count = cursor.fetchone()['count']
    
    conn.close()
    
    return StatsResponse(
        current_energy=int(state.get('energy_level', 5)),
        current_multiplier=float(state.get('dynamic_multiplier', 1.0)),
        tasks_completed_today=task_count
    )

@app.get("/api/history", response_model=List[TaskHistoryItem])
async def get_history():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT task_id, description, completed_at, actual_duration 
        FROM task_history 
        ORDER BY completed_at DESC 
        LIMIT 50
    """)
    rows = cursor.fetchall()
    
    history = []
    for row in rows:
        history.append(TaskHistoryItem(
            task_id=row['task_id'],
            description=row['description'],
            completed_at=row['completed_at'],
            duration_minutes=float(row['actual_duration'] or 0)
        ))
        
    conn.close()
    return history

@app.get("/api/sessions")
async def get_sessions():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, created_at, last_update_time FROM sessions ORDER BY last_update_time DESC LIMIT 10")
    rows = cursor.fetchall()
    
    sessions = []
    for row in rows:
        sessions.append({
            "id": row['id'],
            "created_at": row['created_at'],
            "last_active": row['last_update_time']
        })
        
    conn.close()
    return sessions

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
