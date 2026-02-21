import sqlite3
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
import os

class DatabaseManager:
    """
    Manages SQLite connection and schema for ADHD-OS.
    Handles user state, sessions, and task history.
    """
    def __init__(self, db_path: str = "adhd_os.db"):
        self.db_path = db_path
        self._init_db()
    
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn
    
    def _init_db(self):
        """Initialize database schema."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            
            # User State Table (Key-Value store for flexibility)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS user_state (
                    key TEXT PRIMARY KEY,
                    value TEXT,
                    updated_at TIMESTAMP
                )
            """)
            
            # Sessions Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY,
                    user_id TEXT,
                    app_name TEXT,
                    created_at TIMESTAMP,
                    last_updated_at TIMESTAMP,
                    state_json TEXT
                )
            """)
            
            # Events Table (Linked to Sessions)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT,
                    type TEXT,
                    data_json TEXT,
                    timestamp TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)
            
            # Task History Table (For analytics/learning)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_history (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_type TEXT,
                    estimated_minutes INTEGER,
                    actual_minutes INTEGER,
                    energy_level INTEGER,
                    in_peak_window BOOLEAN,
                    timestamp TIMESTAMP
                )
            """)

            # Task Cache Table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_cache (
                    hash TEXT PRIMARY KEY,
                    task_description TEXT,
                    plan_json TEXT,
                    energy_level INTEGER,
                    created_at TIMESTAMP
                )
            """)
            
            conn.commit()
    
    # --- User State Methods ---
    
    def save_state(self, key: str, value: Any):
        """Saves a value to user_state."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO user_state (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), datetime.now().isoformat())
            )
            
    def get_state(self, key: str, default: Any = None) -> Any:
        """Retrieves a value from user_state."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT value FROM user_state WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    # --- Task Cache Methods ---

    def get_cached_plan(self, task_hash: str) -> Optional[Dict]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT plan_json FROM task_cache WHERE hash = ?", 
                (task_hash,)
            )
            row = cursor.fetchone()
            return json.loads(row[0]) if row else None

    def cache_plan(self, task_hash: str, description: str, plan_json: str, energy: int):
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO task_cache (hash, task_description, plan_json, energy_level, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (task_hash, description, plan_json, energy, datetime.now())
            )

    def get_similar_tasks(self, keywords: List[str]) -> List[str]:
        # Simple fetch all for now
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT task_description FROM task_cache")
            return [r[0] for r in cursor.fetchall()]

    # --- Task History Methods ---
    
    def log_task_completion(self, task_type: str, estimated: int, actual: int, energy: int, in_peak: bool):
        """Logs a completed task for analytics."""
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO task_history 
                (task_type, estimated_minutes, actual_minutes, energy_level, in_peak_window, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (task_type, estimated, actual, energy, in_peak, datetime.now().isoformat())
            )
            
    def get_task_multiplier(self, task_type: str, limit: int = 20) -> Optional[float]:
        """Calculates historical multiplier for a task type."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT estimated_minutes, actual_minutes 
                FROM task_history 
                WHERE task_type = ? AND estimated_minutes > 0
                ORDER BY timestamp DESC LIMIT ?
                """,
                (task_type, limit)
            )
            rows = cursor.fetchall()
            
            if len(rows) < 3:  # Need minimal data
                return None
                
            ratios = [actual / est for est, actual in rows]
            return sum(ratios) / len(ratios)

# Global DB instance
DB = DatabaseManager()
