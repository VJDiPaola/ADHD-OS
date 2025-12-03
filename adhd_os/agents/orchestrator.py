from google.adk.agents import LlmAgent
from google.adk.models.lite_llm import LiteLlm

from adhd_os.config import MODELS
from adhd_os.tools.common import (
    get_user_state, get_current_time, update_user_state, get_body_double_status, log_task_completion
)

# Import sub-agents
from adhd_os.agents.activation import (
    task_init_agent, decomposer_agent, body_double_agent
)
from adhd_os.agents.temporal import (
    time_calibrator_agent, calendar_agent, focus_timer_agent
)
from adhd_os.agents.emotional import (
    catastrophe_agent, rsd_agent, motivation_agent
)
from adhd_os.agents.reflector import reflector_agent
from adhd_os.agents.pattern_analysis import pattern_analysis_agent

session_summarizer = LlmAgent(
    name="session_summarizer",
    model=LiteLlm(model=MODELS["temporal"]),  # Fast summarization
    
    description="Compresses session context for storage and handoff.",
    
    instruction="""
    Summarize the current session into a compact JSON object:
    
    {
        "session_date": "YYYY-MM-DD",
        "energy_trajectory": "started X, ended Y",
        "tasks_discussed": ["task1", "task2"],
        "tasks_completed": ["task1"],
        "barriers_encountered": ["type1", "type2"],
        "interventions_used": ["intervention1"],
        "open_loops": ["things still pending"],
        "notable_patterns": ["any recurring themes"],
        "tomorrow_priorities": ["if discussed"]
    }
    
    Keep it factual and compact. This is for data, not narrative.
    """,
    
    tools=[get_user_state],
)

orchestrator = LlmAgent(
    name="adhd_os_orchestrator",
    model=LiteLlm(model=MODELS["orchestrator"]),  # Gemini Flash for fast routing
    
    description="Root orchestrator for ADHD Operating System v2.1",
    
    instruction="""
    You are the central coordinator of an executive function support system
    for someone with ADHD. Route requests to the appropriate specialist.
    
    ROUTING RULES:
    
    ACTIVATION CLUSTER (getting started):
    - "stuck", "can't start", "avoiding" → task_initiation_agent
    - "break down", "too big", "decompose" → task_decomposer_agent
    - "body double", "stay with me" → body_double_agent
    
    TEMPORAL CLUSTER (time management):
    - "how long", "time check", "realistic" → time_calibrator_agent
    - "schedule", "calendar", "when should" → calendar_agent
    - "focus session", "hyperfocus", "guardrail" → focus_timer_agent
    
    REFLECTOR CLUSTER (planning & critique):
    - "review", "critique", "what am i missing", "sanity check", "plan check" → reflector_agent
    
    EMOTIONAL CLUSTER (regulation):
    - worry, anxiety, "disaster", "fail" → catastrophe_check_agent
    - "hate me", "rejected", "criticized" → rsd_shield_agent
    - "boring", "motivate", "interesting" → motivation_agent
    
    SPECIAL COMMANDS:
    - "morning activation" → Run morning protocol (ask energy, meds, priorities)
    - "shutdown" → Run pattern_analysis_agent, then session_summarizer, then end
    - "status" → Report current state and any active sessions
    
    TASK COMPLETION:
    - If the user says "I finished [task]" or "Done with [task]":
      1. CELEBRATE! (Dopamine hit)
      2. ASK: "How long did that actually take?" (Crucial for calibration)
      3. Once they answer, use `log_task_completion` tool.
    
    For morning activation, ask:
    1. Energy level (1-10)?
    2. Did you take medication? What time?
    3. What are today's top 3 priorities?
    4. Any anxiety or blockers?
    
    Then create a day structure optimized for their peak window.
    
    CONTEXT AWARENESS:
    - Check get_user_state before routing emotional issues (low energy amplifies anxiety)
    - If user seems to be spiraling (repeated questions), gently note the pattern
    - If user is avoiding (long gaps, topic-switching), name it compassionately
    
    Be warm but direct. Prefer action over discussion.
    """,
    
    sub_agents=[
        # Activation Cluster
        task_init_agent,
        decomposer_agent,
        body_double_agent,
        
        # Temporal Cluster
        time_calibrator_agent,
        calendar_agent,
        focus_timer_agent,
        
        # Reflector Cluster
        reflector_agent,
        pattern_analysis_agent,
        
        # Emotional Cluster
        catastrophe_agent,
        rsd_agent,
        motivation_agent,
        
        # Utility
        session_summarizer,
    ],
    
    tools=[get_user_state, get_current_time, update_user_state, get_body_double_status, log_task_completion],
)
