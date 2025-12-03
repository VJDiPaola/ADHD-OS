from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any

@dataclass
class UserState:
    """
    Comprehensive user state with dynamic calculations.
    In production, this would be backed by Redis (ephemeral) + Firestore (persistent).
    """
    user_id: str = "vince"
    
    # Base configuration (from persistent storage)
    base_multiplier: float = 1.5
    peak_window_hours: tuple = (1, 5)
    
    # Ephemeral state (current session)
    energy_level: int = 5
    medication_time: Optional[datetime] = None
    current_task: Optional[str] = None
    focus_block_active: bool = False
    mood_indicators: List[str] = field(default_factory=list)
    
    # Historical data (for calibration)
    task_history: Dict[str, List[Dict]] = field(default_factory=dict)
    
    @property
    def dynamic_multiplier(self) -> float:
        """
        Calculates real-time multiplier based on current state.
        This is the key insight from v2.0 - multiplier isn't static.
        """
        mult = self.base_multiplier
        
        # Energy adjustment (-0.1 to +0.4)
        if self.energy_level <= 3:
            mult += 0.4  # Very low energy = much slower
        elif self.energy_level <= 5:
            mult += 0.2  # Below average
        elif self.energy_level >= 8:
            mult -= 0.1  # High energy = slightly faster
            
        # Medication adjustment
        if not self.is_in_peak_window:
            mult += 0.3  # Off-peak = slower
            
        # Time of day adjustment
        hour = datetime.now().hour
        if hour >= 15:  # Afternoon slump
            mult += 0.15
        elif hour >= 20:  # Evening
            mult += 0.25
            
        return round(max(1.0, mult), 2)
    
    @property
    def is_in_peak_window(self) -> bool:
        """Returns True if currently in medication peak window."""
        if not self.medication_time:
            return False
        now = datetime.now()
        start = self.medication_time + timedelta(hours=self.peak_window_hours[0])
        end = self.medication_time + timedelta(hours=self.peak_window_hours[1])
        return start <= now <= end
    
    @property
    def peak_window_status(self) -> Dict[str, Any]:
        """Returns detailed peak window information."""
        if not self.medication_time:
            return {"active": False, "reason": "no_medication_logged"}
        
        now = datetime.now()
        start = self.medication_time + timedelta(hours=self.peak_window_hours[0])
        end = self.medication_time + timedelta(hours=self.peak_window_hours[1])
        
        if now < start:
            mins_until = int((start - now).total_seconds() / 60)
            return {"active": False, "reason": "not_yet", "minutes_until_peak": mins_until}
        elif now > end:
            return {"active": False, "reason": "ended"}
        else:
            mins_remaining = int((end - now).total_seconds() / 60)
            return {"active": True, "minutes_remaining": mins_remaining}
    
    def load_from_db(self):
        """Loads state from database."""
        from adhd_os.infrastructure.database import DB
        
        # Load persistent config
        self.base_multiplier = DB.get_state("base_multiplier", 1.5)
        self.peak_window_hours = tuple(DB.get_state("peak_window_hours", [1, 5]))
        self.current_task = DB.get_state("current_task", None)
        self.energy_level = int(DB.get_state("energy_level", 5))
        
    def save_to_db(self):
        """Saves persistent state to database."""
        from adhd_os.infrastructure.database import DB
        DB.save_state("base_multiplier", self.base_multiplier)
        DB.save_state("peak_window_hours", list(self.peak_window_hours))
        if self.current_task:
            DB.save_state("current_task", self.current_task)
        DB.save_state("energy_level", self.energy_level)

    def get_task_type_multiplier(self, task_type: str) -> Optional[float]:
        """Returns learned multiplier from DB."""
        from adhd_os.infrastructure.database import DB
        return DB.get_task_multiplier(task_type)
        """Logs task completion to DB."""
        from adhd_os.infrastructure.database import DB
        
        # Update in-memory history for immediate feedback (optional)
        if task_type not in self.task_history:
            self.task_history[task_type] = []
        self.task_history[task_type].append({
            "estimated": estimated,
            "actual": actual,
            "timestamp": datetime.now().isoformat()
        })
        
        # Log to DB for long-term analytics
        DB.log_task_completion(
            task_type, estimated, actual, 
            self.energy_level, self.is_in_peak_window
        )

# Global state instance
USER_STATE = UserState()
