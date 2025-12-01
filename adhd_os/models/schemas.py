from typing import List, Optional
from pydantic import BaseModel, Field

class TaskStep(BaseModel):
    """Single step in a task decomposition."""
    step_number: int = Field(..., description="Step sequence number")
    action: str = Field(..., description="Specific actionable instruction")
    duration_minutes: int = Field(..., description="Estimated duration")
    is_checkpoint: bool = Field(False, description="Is this a break/checkpoint?")
    energy_required: str = Field("medium", description="low/medium/high")

class DecompositionPlan(BaseModel):
    """Complete task decomposition output."""
    task_name: str
    original_estimate_minutes: int
    calibrated_estimate_minutes: int
    multiplier_applied: float
    steps: List[TaskStep]
    rabbit_hole_risks: List[str]
    activation_phrase: str

class CatastropheAnalysis(BaseModel):
    """Structured output for catastrophe checking."""
    stated_worry: str
    cognitive_distortion: Optional[str] = None
    probability_estimate: str  # "low/medium/high" or percentage
    actual_impact_if_true: str
    in_your_control: List[str]
    not_in_your_control: List[str]
    one_action_now: str

class TimeCalibration(BaseModel):
    """Structured output for time estimates."""
    original_estimate: int
    base_multiplier: float
    energy_adjustment: float
    medication_adjustment: float
    final_multiplier: float
    calibrated_estimate: int
    similar_past_tasks: List[str] = []
    recommendation: str
