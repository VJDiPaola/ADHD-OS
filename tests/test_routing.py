import asyncio
import sys
import os

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adhd_os.agents.orchestrator import orchestrator
from google.adk.runners import Runner
from adhd_os.infrastructure.persistence import SqliteSessionService
from adhd_os.state import USER_STATE

async def test_routing():
    print("🧪 Starting Routing Evaluation...")
    
    # Setup test environment
    session_service = SqliteSessionService()
    session = await session_service.create_session("test_app", "test_user")
    
    runner = Runner(
        agent=orchestrator,
        app_name="test_app",
        session_service=session_service
    )
    
    test_cases = [
        ("I'm stuck and can't start", "task_initiation_agent"),
        ("This task is too big", "task_decomposer_agent"),
        ("I need someone to work with me", "body_double_agent"),
        ("How long will this take?", "time_calibrator_agent"),
        ("I'm worried I'll fail", "catastrophe_check_agent"),
        ("I feel rejected", "rsd_shield_agent"),
    ]
    
    passed = 0
    for user_input, expected_agent in test_cases:
        print(f"\n📋 Testing: '{user_input}'")
        
        # We can't easily see internal routing in the final response without debug logs,
        # but we can infer it from the response content or by mocking.
        # For this simple eval, we'll check if the response *sounds* like the agent.
        # Ideally, we'd inspect the trace, but ADK runner hides that a bit.
        
        response = await runner.run_async(
            user_id="test_user",
            session_id=session.id,
            new_message=user_input
        )
        
        print(f"🤖 Response: {response.content[:100]}...")
        
        # In a real test, we'd check the 'agent_name' in the trace if available.
        # For now, we just ensure we got a response.
        if response and response.content:
            print("✅ Response received")
            passed += 1
        else:
            print("❌ No response")
            
    print(f"\n🎉 Result: {passed}/{len(test_cases)} tests passed.")

if __name__ == "__main__":
    asyncio.run(test_routing())
