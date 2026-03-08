import json
import sqlite3
from datetime import datetime
from typing import Any, Dict, List, Optional

class ManagedConnection(sqlite3.Connection):
    """sqlite3 connection that closes itself when used as a context manager."""

    def __exit__(self, exc_type, exc_val, exc_tb):
        try:
            return super().__exit__(exc_type, exc_val, exc_tb)
        finally:
            self.close()


class DatabaseManager:
    """
    Manages SQLite connection and schema for ADHD-OS.
    Handles user state, sessions, task history, and normalized UI transcripts.
    """
    def __init__(self, db_path: str = "adhd_os.db"):
        self.db_path = db_path
        self._init_db()
    
    def _get_conn(self):
        conn = sqlite3.connect(self.db_path, factory=ManagedConnection)
        conn.execute("PRAGMA journal_mode=WAL;")
        return conn

    def get_connection(self):
        """Returns a new database connection. Caller is responsible for closing it."""
        return self._get_conn()
    
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

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS app_settings (
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

            # Bus Events Table (persistent event log)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS bus_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    data_json TEXT,
                    timestamp TIMESTAMP
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    kind TEXT NOT NULL,
                    text TEXT NOT NULL,
                    created_at TIMESTAMP NOT NULL,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS machine_state (
                    name TEXT PRIMARY KEY,
                    state_json TEXT NOT NULL,
                    updated_at TIMESTAMP NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    source TEXT NOT NULL,
                    session_id TEXT,
                    estimated_minutes INTEGER,
                    activation_phrase TEXT,
                    created_at TIMESTAMP NOT NULL,
                    updated_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    FOREIGN KEY(session_id) REFERENCES sessions(id)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS task_steps (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id INTEGER NOT NULL,
                    step_number INTEGER NOT NULL,
                    text TEXT NOT NULL,
                    duration_minutes INTEGER,
                    is_checkpoint BOOLEAN NOT NULL DEFAULT 0,
                    completed BOOLEAN NOT NULL DEFAULT 0,
                    created_at TIMESTAMP NOT NULL,
                    completed_at TIMESTAMP,
                    FOREIGN KEY(task_id) REFERENCES tasks(id)
                )
            """)

            # Indexes for performance
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_sessions_last_updated
                ON sessions (last_updated_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_history_timestamp
                ON task_history (timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_bus_events_type
                ON bus_events (event_type, timestamp)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_conversation_messages_session
                ON conversation_messages (session_id, created_at, id)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_machine_state_updated
                ON machine_state (updated_at)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_tasks_status_updated
                ON tasks (status, updated_at DESC)
            """)
            cursor.execute("""
                CREATE INDEX IF NOT EXISTS idx_task_steps_task
                ON task_steps (task_id, step_number)
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

    # --- App Settings Methods ---

    def save_app_setting(self, key: str, value: Any):
        """Saves a local application setting."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT OR REPLACE INTO app_settings (key, value, updated_at) VALUES (?, ?, ?)",
                (key, json.dumps(value), datetime.now().isoformat()),
            )

    def get_app_setting(self, key: str, default: Any = None) -> Any:
        """Retrieves a local application setting."""
        with self._get_conn() as conn:
            cursor = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,))
            row = cursor.fetchone()
            if row:
                return json.loads(row[0])
            return default

    def get_app_settings(self, keys: List[str]) -> Dict[str, Any]:
        """Retrieves multiple app settings at once."""
        if not keys:
            return {}

        placeholders = ", ".join("?" for _ in keys)
        with self._get_conn() as conn:
            cursor = conn.execute(
                f"SELECT key, value FROM app_settings WHERE key IN ({placeholders})",
                tuple(keys),
            )
            values: Dict[str, Any] = {}
            for key, raw_value in cursor.fetchall():
                try:
                    values[key] = json.loads(raw_value)
                except (TypeError, json.JSONDecodeError):
                    values[key] = raw_value
            return values

    def delete_app_setting(self, key: str):
        """Deletes a local application setting."""
        with self._get_conn() as conn:
            conn.execute("DELETE FROM app_settings WHERE key = ?", (key,))

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

    def get_similar_tasks(self, keywords: List[str], limit: int = 50) -> List[str]:
        """Returns task descriptions matching any keyword, with a row limit."""
        with self._get_conn() as conn:
            if keywords:
                conditions = " OR ".join(
                    "task_description LIKE ?" for _ in keywords
                )
                params = [f"%{kw}%" for kw in keywords] + [limit]
                cursor = conn.execute(
                    f"SELECT task_description FROM task_cache WHERE {conditions} LIMIT ?",
                    params,
                )
            else:
                cursor = conn.execute(
                    "SELECT task_description FROM task_cache LIMIT ?", (limit,)
                )
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

    def prune_old_sessions(self, max_age_days: int = 90) -> int:
        """Deletes sessions and their events older than *max_age_days*. Returns count deleted."""
        with self._get_conn() as conn:
            from datetime import timedelta as _td
            cutoff = datetime.now() - _td(days=max_age_days)
            cutoff_iso = cutoff.isoformat()
            # Delete orphaned events first
            conn.execute(
                "DELETE FROM events WHERE session_id IN "
                "(SELECT id FROM sessions WHERE last_updated_at < ?)",
                (cutoff_iso,),
            )
            cursor = conn.execute(
                "DELETE FROM sessions WHERE last_updated_at < ?",
                (cutoff_iso,),
            )
            deleted = cursor.rowcount
            conn.commit()
            return deleted

    # --- Bus Event Persistence ---

    def persist_bus_event(self, event_type: str, data_json: str):
        """Writes an event-bus event to the persistent bus_events table."""
        with self._get_conn() as conn:
            conn.execute(
                "INSERT INTO bus_events (event_type, data_json, timestamp) VALUES (?, ?, ?)",
                (event_type, data_json, datetime.now().isoformat()),
            )

    def get_recent_history(self, limit: int = 50) -> List[Dict]:
        """Retrieves recent task history for pattern analysis."""
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT task_type, estimated_minutes, actual_minutes,
                       energy_level, in_peak_window, timestamp
                FROM task_history
                ORDER BY timestamp DESC LIMIT ?
                """,
                (limit,)
            )
            return [
                {
                    "type": r[0],
                    "est": r[1],
                    "act": r[2],
                    "energy": r[3],
                    "peak": bool(r[4]),
                    "date": r[5][:10] if r[5] else None,
                }
                for r in cursor.fetchall()
            ]

    # --- Dashboard / UI transcript methods ---

    def get_state_values(self, keys: List[str]) -> Dict[str, Any]:
        """Retrieves multiple user state values at once."""
        if not keys:
            return {}

        placeholders = ", ".join("?" for _ in keys)
        with self._get_conn() as conn:
            cursor = conn.execute(
                f"SELECT key, value FROM user_state WHERE key IN ({placeholders})",
                tuple(keys),
            )
            values: Dict[str, Any] = {}
            for key, raw_value in cursor.fetchall():
                try:
                    values[key] = json.loads(raw_value)
                except (TypeError, json.JSONDecodeError):
                    values[key] = raw_value
            return values

    def get_tasks_completed_today(self) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT
                    (
                        SELECT COUNT(*)
                        FROM task_history
                        WHERE date(timestamp) = date('now', 'localtime')
                    ) +
                    (
                        SELECT COUNT(*)
                        FROM tasks
                        WHERE completed_at IS NOT NULL
                          AND date(completed_at) = date('now', 'localtime')
                    )
                """
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)

    def get_task_history_items(self, limit: int = 50) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT history_id, task_type, completed_at, duration_minutes
                FROM (
                    SELECT
                        'history-' || id AS history_id,
                        task_type,
                        timestamp AS completed_at,
                        actual_minutes AS duration_minutes
                    FROM task_history
                    UNION ALL
                    SELECT
                        'task-' || id AS history_id,
                        title AS task_type,
                        completed_at,
                        estimated_minutes AS duration_minutes
                    FROM tasks
                    WHERE completed_at IS NOT NULL
                )
                ORDER BY completed_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "id": row[0],
                    "task_type": row[1],
                    "completed_at": row[2],
                    "duration_minutes": float(row[3] or 0),
                }
                for row in cursor.fetchall()
            ]

    def get_recent_sessions(self, limit: int = 10) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT id, created_at, last_updated_at
                FROM sessions
                ORDER BY last_updated_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "id": row[0],
                    "created_at": row[1],
                    "last_active": row[2],
                }
                for row in cursor.fetchall()
            ]

    def store_conversation_message(
        self,
        session_id: str,
        role: str,
        kind: str,
        text: str,
        created_at: Optional[str] = None,
    ) -> Dict[str, Any]:
        created_at = created_at or datetime.now().isoformat()
        clean_text = (text or "").strip()
        if not clean_text:
            raise ValueError("Conversation message text cannot be empty.")

        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO conversation_messages (session_id, role, kind, text, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (session_id, role, kind, clean_text, created_at),
            )
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (created_at, session_id),
            )
            return {
                "id": cursor.lastrowid,
                "session_id": session_id,
                "role": role,
                "kind": kind,
                "text": clean_text,
                "created_at": created_at,
            }

    def store_conversation_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        stored: List[Dict[str, Any]] = []
        for message in messages:
            stored.append(
                self.store_conversation_message(
                    session_id=message["session_id"],
                    role=message["role"],
                    kind=message["kind"],
                    text=message["text"],
                    created_at=message.get("created_at"),
                )
            )
        return stored

    def get_conversation_messages(self, session_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT id, session_id, role, kind, text, created_at
                FROM conversation_messages
                WHERE session_id = ?
                ORDER BY created_at ASC, id ASC
                """,
                (session_id,),
            )
            return [
                {
                    "id": row[0],
                    "session_id": row[1],
                    "role": row[2],
                    "kind": row[3],
                    "text": row[4],
                    "created_at": row[5],
                }
                for row in cursor.fetchall()
            ]

    def conversation_message_count(self, session_id: str) -> int:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM conversation_messages WHERE session_id = ?",
                (session_id,),
            )
            row = cursor.fetchone()
            return int(row[0] if row else 0)

    def get_session_event_payloads(self, session_id: str) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT id, type, data_json, timestamp
                FROM events
                WHERE session_id = ?
                ORDER BY id ASC
                """,
                (session_id,),
            )
            rows = []
            for row in cursor.fetchall():
                rows.append(
                    {
                        "id": row[0],
                        "type": row[1],
                        "data_json": row[2],
                        "timestamp": row[3],
                    }
                )
            return rows

    def get_recent_bus_events(self, limit: int = 25) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT id, event_type, data_json, timestamp
                FROM bus_events
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            )
            return [
                {
                    "id": row[0],
                    "event_type": row[1],
                    "data_json": row[2],
                    "timestamp": row[3],
                }
                for row in cursor.fetchall()
            ]

    def save_machine_state(self, name: str, state: Dict[str, Any]):
        with self._get_conn() as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO machine_state (name, state_json, updated_at)
                VALUES (?, ?, ?)
                """,
                (name, json.dumps(state), datetime.now().isoformat()),
            )

    def get_machine_state(self, name: str) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                "SELECT state_json FROM machine_state WHERE name = ?",
                (name,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            return json.loads(row[0])

    def clear_machine_state(self, name: str):
        with self._get_conn() as conn:
            conn.execute("DELETE FROM machine_state WHERE name = ?", (name,))

    # --- Task Board Methods ---

    def create_task(
        self,
        *,
        title: str,
        description: Optional[str] = None,
        status: str = "inbox",
        source: str = "manual",
        session_id: Optional[str] = None,
        estimated_minutes: Optional[int] = None,
        activation_phrase: Optional[str] = None,
    ) -> Dict[str, Any]:
        now = datetime.now().isoformat()
        clean_title = (title or "").strip()
        if not clean_title:
            raise ValueError("Task title cannot be empty.")

        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                INSERT INTO tasks (
                    title, description, status, source, session_id,
                    estimated_minutes, activation_phrase, created_at, updated_at, completed_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    clean_title,
                    (description or "").strip() or None,
                    status,
                    source,
                    session_id,
                    estimated_minutes,
                    activation_phrase,
                    now,
                    now,
                    now if status == "done" else None,
                ),
            )
            task_id = cursor.lastrowid

        return self.get_task(task_id)

    def get_task(self, task_id: int) -> Optional[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT id, title, description, status, source, session_id,
                       estimated_minutes, activation_phrase, created_at, updated_at, completed_at
                FROM tasks
                WHERE id = ?
                """,
                (task_id,),
            )
            row = cursor.fetchone()
            if not row:
                return None
            task = self._serialize_task_row(row)
            task["steps"] = self.get_task_steps(task_id)
            return task

    def get_tasks(self, statuses: Optional[List[str]] = None, limit: int = 200) -> List[Dict[str, Any]]:
        params: List[Any] = []
        query = """
            SELECT id, title, description, status, source, session_id,
                   estimated_minutes, activation_phrase, created_at, updated_at, completed_at
            FROM tasks
        """
        if statuses:
            placeholders = ", ".join("?" for _ in statuses)
            query += f" WHERE status IN ({placeholders})"
            params.extend(statuses)
        query += " ORDER BY CASE status WHEN 'doing' THEN 0 WHEN 'today' THEN 1 WHEN 'inbox' THEN 2 WHEN 'done' THEN 3 ELSE 4 END, updated_at DESC LIMIT ?"
        params.append(limit)

        with self._get_conn() as conn:
            cursor = conn.execute(query, tuple(params))
            tasks = [self._serialize_task_row(row) for row in cursor.fetchall()]

        steps_by_task = self.get_task_steps_by_task_ids([task["id"] for task in tasks])
        for task in tasks:
            task["steps"] = steps_by_task.get(task["id"], [])
        return tasks

    def update_task(
        self,
        task_id: int,
        *,
        title: Optional[str] = None,
        description: Optional[str] = None,
        status: Optional[str] = None,
        estimated_minutes: Optional[int] = None,
        activation_phrase: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        existing = self.get_task(task_id)
        if not existing:
            return None

        next_status = status or existing["status"]
        completed_at = existing["completed_at"]
        if status == "done" and not completed_at:
            completed_at = datetime.now().isoformat()
        elif status and status != "done":
            completed_at = None

        with self._get_conn() as conn:
            conn.execute(
                """
                UPDATE tasks
                SET title = ?, description = ?, status = ?, estimated_minutes = ?,
                    activation_phrase = ?, updated_at = ?, completed_at = ?
                WHERE id = ?
                """,
                (
                    (title.strip() if title is not None else existing["title"]),
                    (description.strip() if description is not None else existing["description"]) or None,
                    next_status,
                    estimated_minutes if estimated_minutes is not None else existing["estimated_minutes"],
                    activation_phrase if activation_phrase is not None else existing["activation_phrase"],
                    datetime.now().isoformat(),
                    completed_at,
                    task_id,
                ),
            )

        return self.get_task(task_id)

    def create_task_steps(self, task_id: int, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            for index, step in enumerate(steps, start=1):
                text = (step.get("text") or step.get("action") or "").strip()
                if not text:
                    continue
                conn.execute(
                    """
                    INSERT INTO task_steps (
                        task_id, step_number, text, duration_minutes, is_checkpoint,
                        completed, created_at, completed_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        task_id,
                        int(step.get("step_number") or index),
                        text,
                        step.get("duration_minutes"),
                        int(bool(step.get("is_checkpoint"))),
                        int(bool(step.get("completed"))),
                        now,
                        now if step.get("completed") else None,
                    ),
                )
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE id = ?",
                (now, task_id),
            )

        return self.get_task_steps(task_id)

    def replace_task_steps(self, task_id: int, steps: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            conn.execute("DELETE FROM task_steps WHERE task_id = ?", (task_id,))
        return self.create_task_steps(task_id, steps)

    def get_task_steps(self, task_id: int) -> List[Dict[str, Any]]:
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                SELECT id, task_id, step_number, text, duration_minutes,
                       is_checkpoint, completed, created_at, completed_at
                FROM task_steps
                WHERE task_id = ?
                ORDER BY step_number ASC, id ASC
                """,
                (task_id,),
            )
            return [self._serialize_task_step_row(row) for row in cursor.fetchall()]

    def get_task_steps_by_task_ids(self, task_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        if not task_ids:
            return {}

        placeholders = ", ".join("?" for _ in task_ids)
        with self._get_conn() as conn:
            cursor = conn.execute(
                f"""
                SELECT id, task_id, step_number, text, duration_minutes,
                       is_checkpoint, completed, created_at, completed_at
                FROM task_steps
                WHERE task_id IN ({placeholders})
                ORDER BY task_id ASC, step_number ASC, id ASC
                """,
                tuple(task_ids),
            )
            grouped: Dict[int, List[Dict[str, Any]]] = {task_id: [] for task_id in task_ids}
            for row in cursor.fetchall():
                step = self._serialize_task_step_row(row)
                grouped.setdefault(step["task_id"], []).append(step)
            return grouped

    def update_task_step(self, task_id: int, step_id: int, *, completed: bool) -> Optional[Dict[str, Any]]:
        now = datetime.now().isoformat()
        with self._get_conn() as conn:
            cursor = conn.execute(
                """
                UPDATE task_steps
                SET completed = ?, completed_at = ?
                WHERE id = ? AND task_id = ?
                """,
                (
                    int(bool(completed)),
                    now if completed else None,
                    step_id,
                    task_id,
                ),
            )
            if cursor.rowcount == 0:
                return None
            conn.execute(
                "UPDATE tasks SET updated_at = ? WHERE id = ?",
                (now, task_id),
            )

        task = self.get_task(task_id)
        if not task:
            return None

        actionable_steps = [step for step in task["steps"] if not step["is_checkpoint"]]
        if actionable_steps and all(step["completed"] for step in actionable_steps):
            task = self.update_task(task_id, status="done")

        return task

    @staticmethod
    def _serialize_task_row(row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "title": row[1],
            "description": row[2],
            "status": row[3],
            "source": row[4],
            "session_id": row[5],
            "estimated_minutes": row[6],
            "activation_phrase": row[7],
            "created_at": row[8],
            "updated_at": row[9],
            "completed_at": row[10],
        }

    @staticmethod
    def _serialize_task_step_row(row) -> Dict[str, Any]:
        return {
            "id": row[0],
            "task_id": row[1],
            "step_number": row[2],
            "text": row[3],
            "duration_minutes": row[4],
            "is_checkpoint": bool(row[5]),
            "completed": bool(row[6]),
            "created_at": row[7],
            "completed_at": row[8],
        }

# Global DB instance
DB = DatabaseManager()
