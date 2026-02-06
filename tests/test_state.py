"""Tests for UserState: dynamic multiplier, peak window, persistence."""

from datetime import datetime, timedelta
from unittest.mock import patch

from adhd_os.state import UserState


class TestDynamicMultiplier:
    """Verify the dynamic_multiplier property covers all branches."""

    def _make_state(self, energy=5, med_time=None, base=1.5):
        s = UserState()
        s.energy_level = energy
        s.medication_time = med_time
        s.base_multiplier = base
        return s

    def test_low_energy_adds_04(self):
        s = self._make_state(energy=2)
        # base=1.5, energy<=3 => +0.4, no peak => +0.3, plus time-of-day
        mult = s.dynamic_multiplier
        assert mult >= 1.5 + 0.4 + 0.3  # at minimum

    def test_medium_energy_adds_02(self):
        s = self._make_state(energy=5)
        mult = s.dynamic_multiplier
        assert mult >= 1.5 + 0.2 + 0.3

    def test_high_energy_subtracts_01(self):
        s = self._make_state(energy=9)
        # energy>=8 => -0.1, no peak => +0.3
        mult = s.dynamic_multiplier
        # base(1.5) - 0.1 + 0.3 = 1.7 (before time-of-day)
        assert mult >= 1.7

    def test_normal_energy_no_adjustment(self):
        """Energy 6-7 doesn't trigger any energy adjustment."""
        s = self._make_state(energy=7)
        # base=1.5, no energy adj, no peak => +0.3
        # Minimum is 1.5 + 0.3 = 1.8 (before time-of-day)
        mult = s.dynamic_multiplier
        assert mult >= 1.8

    @patch("adhd_os.state.datetime")
    def test_evening_branch_reachable(self, mock_dt):
        """The hour >= 20 branch should fire for evening hours."""
        mock_now = datetime(2025, 1, 15, 21, 0, 0)  # 9 PM
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        s = self._make_state(energy=7)
        s.medication_time = None
        mult = s.dynamic_multiplier
        # base=1.5 + no_energy_adj + off_peak(0.3) + evening(0.25) = 2.05
        assert mult == 2.05

    @patch("adhd_os.state.datetime")
    def test_afternoon_branch(self, mock_dt):
        """The hour >= 15 but < 20 branch should fire for afternoon."""
        mock_now = datetime(2025, 1, 15, 16, 0, 0)  # 4 PM
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        s = self._make_state(energy=7)
        s.medication_time = None
        mult = s.dynamic_multiplier
        # base=1.5 + off_peak(0.3) + afternoon(0.15) = 1.95
        assert mult == 1.95

    @patch("adhd_os.state.datetime")
    def test_morning_no_time_adjustment(self, mock_dt):
        """Before 15:00, no time-of-day adjustment."""
        mock_now = datetime(2025, 1, 15, 10, 0, 0)  # 10 AM
        mock_dt.now.return_value = mock_now
        mock_dt.side_effect = lambda *a, **kw: datetime(*a, **kw)

        s = self._make_state(energy=7)
        s.medication_time = None
        mult = s.dynamic_multiplier
        # base=1.5 + off_peak(0.3) + no_time_adj = 1.8
        assert mult == 1.8

    def test_in_peak_window_no_medication_penalty(self):
        """When in peak window, the +0.3 off-peak penalty shouldn't apply."""
        s = self._make_state(energy=7)
        # Set medication time so we're in peak window (1-5 hours ago)
        s.medication_time = datetime.now() - timedelta(hours=2)
        assert s.is_in_peak_window is True
        mult = s.dynamic_multiplier
        # No off-peak penalty, so mult should be lower than without peak
        s2 = self._make_state(energy=7)
        s2.medication_time = None
        assert mult < s2.dynamic_multiplier

    def test_multiplier_floor_is_1(self):
        """Multiplier should never go below 1.0."""
        s = self._make_state(energy=10, base=0.5)
        s.medication_time = datetime.now() - timedelta(hours=2)  # in peak
        mult = s.dynamic_multiplier
        assert mult >= 1.0


class TestPeakWindow:
    def test_no_medication_returns_false(self):
        s = UserState()
        assert s.is_in_peak_window is False

    def test_no_medication_status(self):
        s = UserState()
        status = s.peak_window_status
        assert status["active"] is False
        assert status["reason"] == "no_medication_logged"

    def test_in_peak_window(self):
        s = UserState()
        s.medication_time = datetime.now() - timedelta(hours=2)
        assert s.is_in_peak_window is True
        status = s.peak_window_status
        assert status["active"] is True
        assert "minutes_remaining" in status

    def test_before_peak_window(self):
        s = UserState()
        s.medication_time = datetime.now()  # Just took it, peak starts at +1h
        assert s.is_in_peak_window is False
        status = s.peak_window_status
        assert status["reason"] == "not_yet"
        assert "minutes_until_peak" in status

    def test_after_peak_window(self):
        s = UserState()
        s.medication_time = datetime.now() - timedelta(hours=6)
        assert s.is_in_peak_window is False
        status = s.peak_window_status
        assert status["reason"] == "ended"


class TestStatePersistence:
    def test_save_and_load_roundtrip(self, tmp_db):
        """State should survive a save/load cycle."""
        s = UserState()
        s.energy_level = 8
        s.base_multiplier = 2.0
        s.current_task = "Write tests"
        s.medication_time = datetime(2025, 1, 15, 9, 0, 0)

        # Patch DB import inside state module to use our temp DB
        with patch("adhd_os.infrastructure.database.DB", tmp_db):
            s.save_to_db()

            s2 = UserState()
            s2.load_from_db()
            assert s2.energy_level == 8
            assert s2.base_multiplier == 2.0
            assert s2.current_task == "Write tests"
            assert s2.medication_time == datetime(2025, 1, 15, 9, 0, 0)

    def test_save_none_current_task(self, tmp_db):
        """current_task=None should be persisted, not skipped."""
        s = UserState()
        s.current_task = "Old task"

        with patch("adhd_os.infrastructure.database.DB", tmp_db):
            s.save_to_db()
            assert tmp_db.get_state("current_task") == "Old task"

            s.current_task = None
            s.save_to_db()
            assert tmp_db.get_state("current_task") is None

    def test_log_task_completion(self, tmp_db):
        """Task completion should be logged to both memory and DB."""
        s = UserState()
        with patch("adhd_os.infrastructure.database.DB", tmp_db):
            s.log_task_completion("coding", 30, 45)

        assert "coding" in s.task_history
        assert s.task_history["coding"][0]["estimated"] == 30
        assert s.task_history["coding"][0]["actual"] == 45
