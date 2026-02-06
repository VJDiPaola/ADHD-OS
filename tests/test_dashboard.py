"""Tests for the dashboard FastAPI endpoints against real DB schema."""

import json
import pytest
from unittest.mock import patch

from fastapi.testclient import TestClient

from adhd_os.dashboard.backend import app
from adhd_os.infrastructure.database import DatabaseManager


@pytest.fixture()
def client(tmp_path):
    """Provides a test client with a temporary database."""
    db_path = str(tmp_path / "test_dashboard.db")
    db = DatabaseManager(db_path=db_path)

    # Seed some test data
    db.save_state("energy_level", 7)
    db.save_state("base_multiplier", 1.8)
    db.log_task_completion("coding", 30, 45, 7, True)
    db.log_task_completion("admin", 10, 12, 5, False)

    # Insert a session
    db.execute_write(
        "INSERT INTO sessions (id, user_id, app_name, created_at, last_updated_at, state_json) VALUES (?, ?, ?, ?, ?, ?)",
        ("sess-001", "vince", "adhd_os", "2025-01-15T10:00:00", "2025-01-15T12:00:00", '{}')
    )

    with patch("adhd_os.dashboard.backend.DB_PATH", db_path):
        yield TestClient(app)


class TestStatsEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200

    def test_returns_correct_energy(self, client):
        data = client.get("/api/stats").json()
        assert data["current_energy"] == 7

    def test_returns_multiplier(self, client):
        data = client.get("/api/stats").json()
        assert data["current_multiplier"] == 1.8

    def test_returns_task_count(self, client):
        data = client.get("/api/stats").json()
        # Tasks may or may not be "today" depending on when test runs
        assert isinstance(data["tasks_completed_today"], int)

    def test_empty_db_returns_defaults(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        DatabaseManager(db_path=db_path)  # Just initialize schema
        with patch("adhd_os.dashboard.backend.DB_PATH", db_path):
            c = TestClient(app)
            data = c.get("/api/stats").json()
            assert data["current_energy"] == 5  # default
            assert data["current_multiplier"] == 1.5  # default


class TestHistoryEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/history")
        assert resp.status_code == 200

    def test_returns_list(self, client):
        data = client.get("/api/history").json()
        assert isinstance(data, list)

    def test_history_items_have_correct_fields(self, client):
        data = client.get("/api/history").json()
        if len(data) > 0:
            item = data[0]
            assert "id" in item
            assert "task_type" in item
            assert "estimated_minutes" in item
            assert "actual_minutes" in item
            assert "energy_level" in item
            assert "timestamp" in item

    def test_empty_history(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        DatabaseManager(db_path=db_path)
        with patch("adhd_os.dashboard.backend.DB_PATH", db_path):
            c = TestClient(app)
            data = c.get("/api/history").json()
            assert data == []


class TestSessionsEndpoint:
    def test_returns_200(self, client):
        resp = client.get("/api/sessions")
        assert resp.status_code == 200

    def test_returns_session_data(self, client):
        data = client.get("/api/sessions").json()
        assert len(data) >= 1
        session = data[0]
        assert session["id"] == "sess-001"
        assert "created_at" in session
        assert "last_active" in session

    def test_empty_sessions(self, tmp_path):
        db_path = str(tmp_path / "empty.db")
        DatabaseManager(db_path=db_path)
        with patch("adhd_os.dashboard.backend.DB_PATH", db_path):
            c = TestClient(app)
            data = c.get("/api/sessions").json()
            assert data == []
