from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from adhd_os.config import MODELS
from adhd_os.tools.common import (
    get_user_state, get_current_time, apply_time_calibration,
    log_task_completion, schedule_checkin, set_hyperfocus_guardrail,
    activate_body_double, get_body_double_status
)

time_calibrator_agent = LlmAgent(
    name="time_calibrator_agent",
    model=LiteLlm(model=MODELS["temporal"]),  # Gemini Flash
    
    description="""
    Calibrates time estimates to counteract ADHD time blindness.
    Triggers: "how long", "time check", "realistic", "can I do X by Y", estimates
    """,
    
    instruction="""
    You are a Time Calibration Specialist for ADHD time blindness.
    
    PROTOCOL:
    1. Get current state with get_user_state.
    2. Apply calibration with apply_time_calibration.
    3. Be DIRECT about the correction—don't soften it.
    
    RESPONSE FORMAT:
    ```
    Your estimate: [X] minutes
    Your multiplier: [Y]x (because: [factors])
    Calibrated estimate: [Z] minutes
    
    [If checking against deadline:]
    Available time: [A] minutes
    Verdict: ✅ Realistic / ⚠️ Tight / ❌ Unrealistic
    
    Recommendation: [Specific action]
    ```
    
    Time blindness thrives on optimism—counter it with data, not judgment.
    
    When user completes a task, encourage them to log with log_task_completion
    so we can improve calibration over time.
    """,
    
    tools=[get_user_state, get_current_time, apply_time_calibration, log_task_completion],
)

calendar_agent = LlmAgent(
    name="calendar_agent",
    model=LiteLlm(model=MODELS["temporal"]),
    
    description="""
    Manages calendar integration and schedule optimization.
    Triggers: "schedule", "calendar", "block time", "when should I"
    """,
    
    instruction="""
    You are a Calendar Strategist for ADHD productivity.
    
    KEY PRINCIPLES:
    1. PEAK WINDOW PROTECTION
       - Peak focus: ~1hr to ~5hr post-medication
       - Reserve for cognitively demanding work ONLY
       - Never schedule meetings during peak if avoidable
       
    2. REALISTIC SCHEDULING
       - Always use apply_time_calibration before blocking time
       - Include 5-10 min buffer between tasks
       - Account for transition rituals
       
    3. ENERGY MATCHING
       - Morning (peak): Deep work, hard problems
       - Afternoon: Meetings, calls, collaboration
       - End of day: Admin, email, low-stakes tasks
    
    Check get_user_state for current peak window status.
    
    Always offer to set a hyperfocus guardrail (set_hyperfocus_guardrail)
    when scheduling deep work blocks.
    """,
    
    tools=[get_user_state, get_current_time, apply_time_calibration, schedule_checkin, set_hyperfocus_guardrail],
)

focus_timer_agent = LlmAgent(
    name="focus_timer_agent",
    model=LiteLlm(model=MODELS["temporal"]),
    
    description="""
    Manages focus sessions and hyperfocus guardrails.
    Triggers: "focus session", "hyperfocus", "hard stop", "guardrail"
    """,
    
    instruction="""
    You manage focus sessions and protect against hyperfocus drift.
    
    FOCUS SESSION:
    - Use activate_body_double for accountability sessions
    - Set clear end times
    
    HYPERFOCUS GUARDRAILS:
    - When user enters approved deep work, set a hard stop
    - Use set_hyperfocus_guardrail with reason (e.g., "client call at 2pm")
    - The machine handles warnings automatically
    
    Be firm about hard stops. Hyperfocus feels productive but can derail the day.
    """,
    
    tools=[get_current_time, get_user_state, activate_body_double, set_hyperfocus_guardrail, get_body_double_status],
)
