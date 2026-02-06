import json
from typing import Optional, List, Dict, Any
from datetime import datetime

from google.adk.sessions import BaseSessionService, Session
from google.adk.events import Event
from adhd_os.infrastructure.database import DB

class SqliteSessionService(BaseSessionService):
    """
    SQLite-backed session service.
    Uses DatabaseManager methods for proper connection reuse and write locking.
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

        DB.execute_write(
            """
            INSERT INTO sessions (id, user_id, app_name, created_at, last_updated_at, state_json)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (session.id, user_id, app_name, now.isoformat(), now.isoformat(), json.dumps(session.state))
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
        row = DB.execute_read_one(
            "SELECT user_id, app_name, created_at, last_updated_at, state_json FROM sessions WHERE id = ?",
            (session_id,)
        )
        if not row:
            return None

        # Get events
        event_rows = DB.execute_read(
            "SELECT type, data_json, timestamp FROM events WHERE session_id = ? ORDER BY id ASC",
            (session_id,)
        )
        events = []
        for e_row in event_rows:
            if e_row[0] == "adk_event":
                events.append(Event.model_validate_json(e_row[1]))

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
        rows = DB.execute_read(
            "SELECT id, created_at FROM sessions WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,)
        )
        return [{"id": r[0], "created_at": r[1]} for r in rows]

    async def delete_session(self, app_name: str, user_id: str, session_id: str):
        """Deletes a session."""
        DB.execute_write("DELETE FROM events WHERE session_id = ?", (session_id,))
        DB.execute_write("DELETE FROM sessions WHERE id = ?", (session_id,))

    async def append_event(self, session: Session, event: Event) -> Event:
        """Appends an event to DB."""
        now = datetime.now()
        DB.execute_write(
            "INSERT INTO events (session_id, type, data_json, timestamp) VALUES (?, ?, ?, ?)",
            (
                session.id,
                "adk_event",
                event.model_dump_json(),
                datetime.fromtimestamp(event.timestamp).isoformat()
            )
        )
        DB.execute_write(
            "UPDATE sessions SET last_updated_at = ? WHERE id = ?",
            (now.isoformat(), session.id)
        )

        session.events.append(event)
        return event

    async def update_session_state(self, session_id: str, updates: Dict[str, Any]):
        """Updates session state in DB using atomic read-modify-write to prevent races."""
        DB.execute_atomic_update(
            read_sql="SELECT state_json FROM sessions WHERE id = ?",
            read_params=(session_id,),
            write_sql="UPDATE sessions SET state_json = ?, last_updated_at = ? WHERE id = ?",
            transform=lambda row: (
                json.dumps({**json.loads(row[0]), **updates}),
                datetime.now().isoformat(),
                session_id,
            ),
        )
