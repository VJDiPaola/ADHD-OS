import os
import tempfile
import pytest

from adhd_os.infrastructure.database import DatabaseManager
from adhd_os.infrastructure.event_bus import EventBus
from adhd_os.state import UserState


@pytest.fixture()
def tmp_db(tmp_path):
    """Provides a DatabaseManager backed by a temporary SQLite file."""
    db_path = str(tmp_path / "test.db")
    return DatabaseManager(db_path=db_path)


@pytest.fixture()
def event_bus():
    """Provides a fresh EventBus instance."""
    return EventBus()


@pytest.fixture()
def user_state():
    """Provides a fresh UserState (not connected to global DB)."""
    return UserState()
