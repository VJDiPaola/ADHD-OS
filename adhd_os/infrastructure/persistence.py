import os
import json
import pickle
from typing import Optional, List, Dict, Any
from datetime import datetime

from google.adk.sessions import BaseSessionService, Session, Event

class FileSessionService(BaseSessionService):
    """
    File-based session service for simple persistence.
    Saves sessions as pickle files in a local directory.
    """
    def __init__(self, storage_dir: str = "sessions"):
        self.storage_dir = storage_dir
        os.makedirs(self.storage_dir, exist_ok=True)
    
    def _get_path(self, session_id: str) -> str:
        return os.path.join(self.storage_dir, f"{session_id}.pkl")
    
    async def create_session(
        self,
        app_name: str,
        user_id: str,
        state: Optional[Dict[str, Any]] = None,
        session_id: Optional[str] = None
    ) -> Session:
        """Creates a new session and saves it."""
        if not session_id:
            import uuid
            session_id = str(uuid.uuid4())
            
        session = Session(
            id=session_id,
            app_name=app_name,
            user_id=user_id,
            state=state or {},
            events=[],
            created_time=datetime.now(),
            last_update_time=datetime.now()
        )
        
        await self._save_session(session)
        return session
    
    async def get_session(
        self,
        app_name: str,
        user_id: str,
        session_id: str,
        config: Optional[Any] = None
    ) -> Optional[Session]:
        """Retrieves a session from disk."""
        path = self._get_path(session_id)
        if not os.path.exists(path):
            return None
            
        try:
            with open(path, "rb") as f:
                session = pickle.load(f)
            return session
        except Exception as e:
            print(f"⚠️ Error loading session {session_id}: {e}")
            return None
            
    async def list_sessions(self, app_name: str, user_id: str) -> Any:
        """Lists all sessions (simplified implementation)."""
        # In a real implementation, we'd filter by app_name and user_id
        # For now, just return empty list as it's not critical for this CLI
        return []
        
    async def delete_session(self, app_name: str, user_id: str, session_id: str):
        """Deletes a session file."""
        path = self._get_path(session_id)
        if os.path.exists(path):
            os.remove(path)
            
    async def append_event(self, session: Session, event: Event) -> Event:
        """Appends an event and saves the session."""
        # Update the session object
        session.events.append(event)
        session.last_update_time = datetime.now()
        
        # Save to disk
        await self._save_session(session)
        return event
        
    async def update_session_state(self, session_id: str, updates: Dict[str, Any]):
        """Updates session state and saves."""
        # This is inefficient for files (load-modify-save), but functional
        # We need to find the session first. 
        # Since we only have session_id here, we assume we can find it by filename.
        path = self._get_path(session_id)
        if not os.path.exists(path):
            return
            
        with open(path, "rb") as f:
            session = pickle.load(f)
            
        session.state.update(updates)
        session.last_update_time = datetime.now()
        
        await self._save_session(session)
        
    async def _save_session(self, session: Session):
        """Helper to save session to disk."""
        path = self._get_path(session.id)
        with open(path, "wb") as f:
            pickle.dump(session, f)
