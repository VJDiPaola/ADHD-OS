"""Tests for TaskCache: hash-based lookup, similarity matching."""

from unittest.mock import patch

from adhd_os.infrastructure.cache import TaskCache
from adhd_os.infrastructure.database import DatabaseManager
from adhd_os.models.schemas import DecompositionPlan, TaskStep


def _make_plan(name="test task"):
    return DecompositionPlan(
        task_name=name,
        original_estimate_minutes=30,
        calibrated_estimate_minutes=45,
        multiplier_applied=1.5,
        steps=[
            TaskStep(step_number=1, action="Do the thing", duration_minutes=10),
        ],
        rabbit_hole_risks=["distraction"],
        activation_phrase="I'm just going to do the thing.",
    )


class TestTaskCache:
    def test_store_and_retrieve(self, tmp_db):
        cache = TaskCache()
        plan = _make_plan()

        with patch("adhd_os.infrastructure.cache.DB", tmp_db):
            cache.store_with_energy("write unit tests", plan, 5)
            result = cache.get("write unit tests", 5)

        assert result is not None
        assert result.task_name == "test task"
        assert len(result.steps) == 1

    def test_cache_miss(self, tmp_db):
        cache = TaskCache()
        with patch("adhd_os.infrastructure.cache.DB", tmp_db):
            result = cache.get("nonexistent task", 5)
        assert result is None

    def test_normalization(self, tmp_db):
        cache = TaskCache()
        plan = _make_plan()

        with patch("adhd_os.infrastructure.cache.DB", tmp_db):
            cache.store_with_energy("  Write Unit Tests  ", plan, 5)
            # Lookup with different casing/whitespace should match
            result = cache.get("write unit tests", 5)

        assert result is not None

    def test_similar_tasks_keyword_overlap(self, tmp_db):
        cache = TaskCache()
        plan = _make_plan()

        with patch("adhd_os.infrastructure.cache.DB", tmp_db):
            cache.store_with_energy("write unit tests", plan, 5)
            cache.store_with_energy("fix database bug", plan, 5)
            cache.store_with_energy("write integration tests", plan, 5)

            similar = cache.get_similar_tasks("write tests")

        # "write unit tests" and "write integration tests" share keywords with "write tests"
        assert len(similar) >= 2

    def test_similar_tasks_limit(self, tmp_db):
        cache = TaskCache()
        plan = _make_plan()

        with patch("adhd_os.infrastructure.cache.DB", tmp_db):
            for i in range(10):
                cache.store_with_energy(f"write task {i}", plan, 5)

            similar = cache.get_similar_tasks("write task", limit=3)

        assert len(similar) <= 3

    def test_hash_deterministic(self):
        cache = TaskCache()
        h1 = cache._compute_hash("write unit tests")
        h2 = cache._compute_hash("write unit tests")
        assert h1 == h2

    def test_hash_differs_for_different_input(self):
        cache = TaskCache()
        h1 = cache._compute_hash("write unit tests")
        h2 = cache._compute_hash("fix database bug")
        assert h1 != h2
