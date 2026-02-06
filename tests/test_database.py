"""Tests for DatabaseManager: CRUD, task history, connection reuse, locking."""

import threading
from adhd_os.infrastructure.database import DatabaseManager


class TestConnectionReuse:
    def test_same_thread_returns_same_connection(self, tmp_db):
        conn1 = tmp_db._get_conn()
        conn2 = tmp_db._get_conn()
        assert conn1 is conn2

    def test_wal_mode_enabled(self, tmp_db):
        conn = tmp_db._get_conn()
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        assert mode == "wal"


class TestUserState:
    def test_save_and_get_string(self, tmp_db):
        tmp_db.save_state("name", "Alice")
        assert tmp_db.get_state("name") == "Alice"

    def test_save_and_get_int(self, tmp_db):
        tmp_db.save_state("energy", 7)
        assert tmp_db.get_state("energy") == 7

    def test_save_and_get_none(self, tmp_db):
        tmp_db.save_state("task", None)
        assert tmp_db.get_state("task") is None

    def test_get_missing_key_returns_default(self, tmp_db):
        assert tmp_db.get_state("missing", 42) == 42

    def test_overwrite_value(self, tmp_db):
        tmp_db.save_state("key", "old")
        tmp_db.save_state("key", "new")
        assert tmp_db.get_state("key") == "new"


class TestTaskCache:
    def test_cache_and_retrieve_plan(self, tmp_db):
        plan = {"task_name": "test", "steps": []}
        tmp_db.cache_plan("abc123", "test task", '{"task_name":"test","steps":[]}', 5)
        result = tmp_db.get_cached_plan("abc123")
        assert result is not None
        assert result["task_name"] == "test"

    def test_cache_miss_returns_none(self, tmp_db):
        assert tmp_db.get_cached_plan("nonexistent") is None

    def test_get_similar_tasks(self, tmp_db):
        tmp_db.cache_plan("h1", "write unit tests", '{}', 5)
        tmp_db.cache_plan("h2", "fix database bug", '{}', 5)
        results = tmp_db.get_similar_tasks(["write"])
        assert len(results) == 2


class TestTaskHistory:
    def test_log_and_retrieve(self, tmp_db):
        tmp_db.log_task_completion("coding", 30, 45, 7, True)
        tmp_db.log_task_completion("coding", 20, 25, 5, False)
        tmp_db.log_task_completion("coding", 15, 22, 6, True)

        mult = tmp_db.get_task_multiplier("coding")
        assert mult is not None
        # Average of 45/30, 25/20, 22/15
        expected = (45/30 + 25/20 + 22/15) / 3
        assert abs(mult - expected) < 0.01

    def test_multiplier_needs_minimum_data(self, tmp_db):
        tmp_db.log_task_completion("coding", 30, 45, 7, True)
        # Only 1 data point, need 3
        assert tmp_db.get_task_multiplier("coding") is None

    def test_get_recent_history(self, tmp_db):
        tmp_db.log_task_completion("coding", 30, 45, 7, True)
        tmp_db.log_task_completion("admin", 10, 15, 5, False)

        history = tmp_db.get_recent_history(10)
        assert len(history) == 2
        assert history[0]["type"] == "admin"  # Most recent first
        assert history[1]["type"] == "coding"

    def test_get_recent_history_respects_limit(self, tmp_db):
        for i in range(5):
            tmp_db.log_task_completion(f"task_{i}", 10, 15, 5, False)

        history = tmp_db.get_recent_history(3)
        assert len(history) == 3


class TestAtomicUpdate:
    def test_atomic_read_modify_write(self, tmp_db):
        """execute_atomic_update should perform read-modify-write atomically."""
        import json
        # Set up initial session state
        tmp_db.execute_write(
            "INSERT INTO sessions (id, user_id, app_name, created_at, last_updated_at, state_json) VALUES (?, ?, ?, ?, ?, ?)",
            ("sess1", "user1", "app", "2025-01-01", "2025-01-01", '{"count": 0}')
        )

        # Atomically increment
        result = tmp_db.execute_atomic_update(
            read_sql="SELECT state_json FROM sessions WHERE id = ?",
            read_params=("sess1",),
            write_sql="UPDATE sessions SET state_json = ? WHERE id = ?",
            transform=lambda row: (json.dumps({"count": json.loads(row[0])["count"] + 1}), "sess1"),
        )
        assert result is not None

        # Verify
        row = tmp_db.execute_read_one("SELECT state_json FROM sessions WHERE id = ?", ("sess1",))
        assert json.loads(row[0])["count"] == 1

    def test_atomic_update_missing_row_returns_none(self, tmp_db):
        result = tmp_db.execute_atomic_update(
            read_sql="SELECT state_json FROM sessions WHERE id = ?",
            read_params=("nonexistent",),
            write_sql="UPDATE sessions SET state_json = ? WHERE id = ?",
            transform=lambda row: ("new", "nonexistent"),
        )
        assert result is None


class TestConcurrentWrites:
    def test_concurrent_writes_dont_corrupt(self, tmp_db):
        """Multiple threads writing should not cause database corruption."""
        errors = []

        def writer(thread_id):
            try:
                for i in range(20):
                    tmp_db.save_state(f"thread_{thread_id}_key_{i}", i)
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=writer, args=(t,)) for t in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(errors) == 0
        # Verify some writes persisted correctly
        assert tmp_db.get_state("thread_0_key_19") == 19
        assert tmp_db.get_state("thread_3_key_0") == 0
