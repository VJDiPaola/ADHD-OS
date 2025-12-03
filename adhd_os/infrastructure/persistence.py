import os
import json
import pickle
from typing import Optional, List, Dict, Any
from datetime import datetime



from google.adk.sessions import BaseSessionService, Session
from google.adk.events import Event
from adhd_os.infrastructure.database import DB

class SqliteSessionService(BaseSessionService):
    """
    SQLite-backed session service.
    Robust, queryable, and safe.
    """
    async def create_session(
        self,
        app_name: str,
        user_id: str,
        state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Session:
        """Creates a new session in DB."""
        if not session_id:
            import uuid
            session_id = str(uuid.uuid4())
            
        now = datetime.now()
        session = Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=state or {},
            events=[],
            last_update_time=now.timestamp()
        )
        
        with DB._get_conn() as conn:
            conn.execute(
                """
                INSERT INTO sessions (id, user_id, app_name, created_at, last_updated_at, state_json)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (session.id, user_id, app_name, now, now, json.dumps(session.state))
            )
            
        return session
    
    async def get_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[Any] = None
    ) -> Optional[Session]:
        """Retrieves a session from DB."""
        with DB._get_conn() as conn:
            # Get session
            cursor = conn.execute(
                "SELECT user_id, app_name, created_at, last_updated_at, state_json FROM sessions WHERE id = ?",
                (session_id,)
            )
            row = cursor.fetchone()
            if not row:
                return None
                
            # Get events
            cursor = conn.execute(
                "SELECT type, data_json, timestamp FROM events WHERE session_id = ? ORDER BY id ASC",
                (session_id,)
            )
            events = []
            for e_row in cursor.fetchall():
                events.append(Event(
                    type=e_row[0],
                    data=json.loads(e_row[1]),
                    timestamp=datetime.fromisoformat(e_row[2]) if isinstance(e_row[2], str) else e_row[2]
                ))
            
            # last_updated_at from DB is timestamp string or datetime, convert to float
            last_update = row[3]
            if isinstance(last_update, str):
                last_update_ts = datetime.fromisoformat(last_update).timestamp()
            elif isinstance(last_update, datetime):
                last_update_ts = last_update.timestamp()
            else:
                last_update_ts = float(last_update)

            return Session(
                id=session_id,
                app_name=row[1],
                user_id=row[0],
                state=json.loads(row[4]),
                events=events,
                last_update_time=last_update_ts
            )
            
    async def list_sessions(self, app_name: str, user_id: str) -> Any:
        """Lists sessions for user."""
        with DB._get_conn() as conn:
            cursor = conn.execute(
                "SELECT id, created_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
                (user_id,)
            )
            return [{"id": r[0], "created_at": r[1]} for r in cursor.fetchall()]
        
    async def delete_session(self, app_name: str, user_id: str, session_id: str):
        """Deletes a session."""
        with DB._get_conn() as conn:
            conn.execute("DELETE FROM events WHERE session_id = ?", (session_id,))
            conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
            
    async def append_event(self, session: Session, event: Event) -> Event:
        """Appends an event to DB."""
        with DB._get_conn() as conn:
            conn.execute(
                "INSERT INTO events (session_id, type, data_json, timestamp) VALUES (?, ?, ?, ?)",
                (session.id, event.type, json.dumps(event.data), event.timestamp.isoformat())
            )
            conn.execute(
                "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
                (datetime.now(), session.id)
            )
            
        session.events.append(event)
        return event
        
    async def update_session_state(self, session_id: str, updates: Dict[str, Any]):
        """Updates session state in DB."""
        # We need to fetch current state first to merge (or just patch if we supported JSON patch)
        # For simplicity, we'll just update the whole blob if we had the object, but here we only have ID.
        # Let's do a read-modify-write
        with DB._get_conn() as conn:
            cursor = conn.execute("SELECT state_json FROM sessions WHERE id = ?", (session_id,))
            row = cursor.fetchone()
            if not row:
                return
                
            current_state = json.loads(row[0])
            current_state.update(updates)
            
            conn.execute(
                "UPDATE sessions SET state_json = ?, last_updated_at = ? WHERE id = ?",
                (json.dumps(current_state), datetime.now(), session_id)
            )
