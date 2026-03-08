import os
import sys
import tempfile
import unittest

from unittest.mock import patch

from google.adk.models.llm_response import LlmResponse
from google.adk.runners import Runner
from google.genai import types

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from adhd_os.agents.activation import body_double_agent, decomposer_agent, task_init_agent
from adhd_os.agents.emotional import catastrophe_agent, rsd_agent
from adhd_os.agents.orchestrator import orchestrator
from adhd_os.agents.reflector import reflector_agent
from adhd_os.agents.temporal import time_calibrator_agent
from adhd_os.infrastructure.database import DatabaseManager
from adhd_os.infrastructure.persistence import SqliteSessionService


ROUTING_CASES = [
    ("I'm stuck and can't start", "task_initiation_agent"),
    ("This task is too big", "task_decomposer_agent"),
    ("I need someone to work with me", "body_double_agent"),
    ("How long will this take?", "time_calibrator_agent"),
    ("I'm worried I'll fail", "catastrophe_check_agent"),
    ("I feel rejected", "rsd_shield_agent"),
    ("Review my plan to build a rocket", "reflector_agent"),
]


def _event_texts(event):
    parts = getattr(getattr(event, "content", None), "parts", None) or []
    return [part.text for part in parts if getattr(part, "text", None)]


class RoutingRunnerTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
        self.temp.close()
        self.db = DatabaseManager(db_path=self.temp.name)
        self.session_service = SqliteSessionService(db=self.db)
        self.runner = Runner(
            agent=orchestrator,
            app_name="test_app",
            session_service=self.session_service,
        )
        self.agent_models = {
            task_init_agent.name: task_init_agent.model,
            decomposer_agent.name: decomposer_agent.model,
            body_double_agent.name: body_double_agent.model,
            time_calibrator_agent.name: time_calibrator_agent.model,
            catastrophe_agent.name: catastrophe_agent.model,
            rsd_agent.name: rsd_agent.model,
            reflector_agent.name: reflector_agent.model,
        }

    def tearDown(self):
        os.unlink(self.temp.name)

    async def test_runner_transfers_canonical_prompts_to_expected_agents(self):
        prompt_to_agent = dict(ROUTING_CASES)
        orchestrator_model = orchestrator.model
        agent_models = self.agent_models

        async def fake_generate(model_self, llm_request, stream=False):
            if model_self is orchestrator_model:
                prompt_text = llm_request.model_dump()["contents"][-1]["parts"][0]["text"]
                target_agent = prompt_to_agent[prompt_text]
                yield LlmResponse(
                    content=types.Content(
                        role="model",
                        parts=[
                            types.Part(
                                function_call=types.FunctionCall(
                                    name="transfer_to_agent",
                                    args={"agent_name": target_agent},
                                )
                            )
                        ],
                    ),
                    partial=False,
                    turn_complete=True,
                )
                return

            for agent_name, model in agent_models.items():
                if model_self is model:
                    yield LlmResponse(
                        content=types.Content(
                            role="model",
                            parts=[types.Part(text=f"{agent_name} handled the request")],
                        ),
                        partial=False,
                        turn_complete=True,
                    )
                    return

            raise AssertionError(f"Unexpected LiteLlm instance encountered: {model_self!r}")

        with patch("google.adk.models.lite_llm.LiteLlm.generate_content_async", new=fake_generate):
            for prompt, expected_agent in ROUTING_CASES:
                with self.subTest(prompt=prompt, expected_agent=expected_agent):
                    session = await self.session_service.create_session(
                        app_name="test_app",
                        user_id="test_user",
                    )
                    events = []
                    async for event in self.runner.run_async(
                        user_id="test_user",
                        session_id=session.id,
                        new_message=types.Content(
                            role="user",
                            parts=[types.Part(text=prompt)],
                        ),
                    ):
                        events.append(event)

                    transfer_events = [
                        event
                        for event in events
                        if getattr(getattr(event, "actions", None), "transfer_to_agent", None) == expected_agent
                    ]
                    self.assertTrue(
                        transfer_events,
                        msg=f"Expected a transfer event to {expected_agent!r} for prompt {prompt!r}.",
                    )

                    agent_events = [
                        event for event in events if getattr(event, "author", None) == expected_agent
                    ]
                    self.assertTrue(
                        agent_events,
                        msg=f"Expected {expected_agent!r} to author at least one event for prompt {prompt!r}.",
                    )

                    agent_texts = [
                        text
                        for event in agent_events
                        for text in _event_texts(event)
                    ]
                    self.assertIn(f"{expected_agent} handled the request", agent_texts)


if __name__ == "__main__":
    unittest.main()
