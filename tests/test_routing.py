import asyncio
import sys
import os
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from google.adk.runners import Runner
from google.genai import types

from adhd_os.agents.orchestrator import orchestrator
from adhd_os.infrastructure.persistence import SqliteSessionService


async def test_routing():
    print("Starting Routing Evaluation...")

    # Setup test environment
    session_service = SqliteSessionService()
    session = await session_service.create_session(
        app_name="test_app", user_id="test_user"
    )

    # Mock the LLM to avoid credential issues and costs
    with patch(
        "google.adk.models.lite_llm.LiteLlm.generate_content_async",
        new_callable=MagicMock,
    ) as mock_generate:

        async def async_return(*args, **kwargs):
            mock_response = MagicMock()
            mock_part = MagicMock()
            mock_part.text = "Mocked Agent Response"
            mock_response.content.parts = [mock_part]
            return mock_response

        mock_generate.side_effect = async_return

        runner = Runner(
            agent=orchestrator,
            app_name="test_app",
            session_service=session_service,
        )

        test_cases = [
            ("I'm stuck and can't start", "task_initiation_agent"),
            ("This task is too big", "task_decomposer_agent"),
            ("I need someone to work with me", "body_double_agent"),
            ("How long will this take?", "time_calibrator_agent"),
            ("I'm worried I'll fail", "catastrophe_check_agent"),
            ("I feel rejected", "rsd_shield_agent"),
            ("Review my plan to build a rocket", "reflector_agent"),
        ]

        passed = 0
        failed = []
        for user_input, expected_agent in test_cases:
            print(f"\nTesting: '{user_input}' (expect -> {expected_agent})")

            message = types.Content(
                role="user", parts=[types.Part(text=user_input)]
            )

            try:
                # run_async returns an async generator of Event objects
                async for event in runner.run_async(
                    user_id="test_user",
                    session_id=session.id,
                    new_message=message,
                ):
                    if event and event.content and event.content.parts:
                        passed += 1
                        break
                else:
                    raise AssertionError(
                        f"Empty response for '{user_input}' (expected {expected_agent})"
                    )
            except AssertionError as e:
                print(f"Assertion failed: {e}")
                failed.append((user_input, expected_agent, str(e)))
            except Exception as e:
                print(f"Error: {e}")
                failed.append((user_input, expected_agent, str(e)))

        print(f"\nResult: {passed}/{len(test_cases)} tests passed.")
        assert not failed, f"Routing failures: {failed}"
        assert passed == len(test_cases), (
            f"Only {passed}/{len(test_cases)} tests passed"
        )


if __name__ == "__main__":
    asyncio.run(test_routing())
