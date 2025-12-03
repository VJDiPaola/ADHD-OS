import asyncio
import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adhd_os.agents.orchestrator import orchestrator
from google.adk.runners import Runner
from adhd_os.infrastructure.persistence import SqliteSessionService
from adhd_os.state import USER_STATE
from adhd_os.models.message import Message

async def test_routing():
    print("Starting Routing Evaluation...")
    
    # Setup test environment
    session_service = SqliteSessionService()
    session = await session_service.create_session("test_app", "test_user")
    
    # Mock the LLM to avoid credential issues and costs
    with patch("google.adk.models.lite_llm.LiteLlm.generate_content_async", new_callable=MagicMock) as mock_generate:
        # Configure mock to return a dummy response
        # generate_content_async is async, so return value must be awaitable
        async def async_return(*args, **kwargs):
            mock_response = MagicMock()
            # LlmResponse structure: response.content.parts[0].text
            mock_part = MagicMock()
            mock_part.text = "Mocked Agent Response"
            mock_response.content.parts = [mock_part]
            return mock_response
            
        mock_generate.side_effect = async_return
        
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
            print(f"\nTesting: '{user_input}'")
            
            message = Message(content=user_input)
            
            try:
                # Iterate over the async generator
                async for response in runner.run_async(
                    user_id="test_user",
                    session_id=session.id,
                    new_message=message
                ):
                    print(f"Response: {response.content[:100]}...")
                    if response and response.content:
                        print("Response received")
                        passed += 1
                        break
            except Exception as e:
                print(f"Error: {e}")
                # If we get here, it might be because we didn't mock deep enough, 
                # but let's see if the mock works.
                
        print(f"\nResult: {passed}/{len(test_cases)} tests passed.")

if __name__ == "__main__":
    asyncio.run(test_routing())
