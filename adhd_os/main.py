import asyncio
import os
from datetime import datetime

from adhd_os.infrastructure.settings import apply_saved_environment_settings

apply_saved_environment_settings()

from adhd_os.config import MODEL_MODE
from adhd_os.infrastructure.event_bus import EVENT_BUS, EventType
from adhd_os.infrastructure.logging import logger
from adhd_os.runtime import RUNTIME
from adhd_os.state import USER_STATE


def _print_messages(messages):
    for message in messages:
        if message["role"] in {"assistant", "system"}:
            speaker = "ADHD-OS" if message["role"] == "assistant" else "SYSTEM"
            print(f"\n{speaker}: {message['text']}")


def _print_live_event(prefix: str, message: str):
    if not message:
        return
    print(f"\n{prefix}: {message}")


async def run_adhd_os():
    """Main interaction loop for ADHD-OS v2.1."""
    await RUNTIME.startup()
    session = await RUNTIME.ensure_session()

    logger.info("ADHD Operating System v2.1 Started")
    logger.info("Model Mode: %s", MODEL_MODE.value)

    if RUNTIME.db.conversation_message_count(session.id) > 0:
        print(f"\nWelcome back! Resuming session {session.id[:8]}.")
        if USER_STATE.current_task:
            print(f"   You were working on: {USER_STATE.current_task}")

    print("=" * 70)
    print("  ADHD Operating System v2.1")
    print("  UI-First Runtime + Full Agent Roster")
    print("=" * 70)
    print()
    print("Quick commands:")
    print("  'morning activation' - Start your day with structure")
    print("  'stuck on [task]'    - Get unstuck with microscopic steps")
    print("  'decompose [task]'   - Break down a complex task")
    print("  'body double [task]' - Accountability partner (deterministic)")
    print("  'time check [X min]' - Calibrate a time estimate")
    print("  '[worry/anxiety]'    - Get reality-tested")
    print("  'make [task] fun'    - Motivation strategies")
    print("  'shutdown'           - Summarize and exit")
    print("  'quit'               - Exit immediately")
    print()

    async def on_task_completed(data):
        ratio = data.get("ratio", 1.0)
        if ratio > 1.5:
            logger.warning("Task took %sx longer than estimated", round(ratio, 1), extra={"data": data})
            print(f" [PATTERN] Task took {ratio:.1f}x longer than estimated. Adjusting multiplier...")

    def on_checkin_due(data):
        _print_live_event("CHECK-IN", data.get("message") or data.get("task"))

    def on_focus_warning(data):
        _print_live_event("FOCUS", data.get("message"))

    def on_system_notice(data):
        _print_live_event("SYSTEM", data.get("message"))

    EVENT_BUS.subscribe(EventType.TASK_COMPLETED, on_task_completed)
    EVENT_BUS.subscribe(EventType.CHECKIN_DUE, on_checkin_due)
    EVENT_BUS.subscribe(EventType.FOCUS_WARNING, on_focus_warning)
    EVENT_BUS.subscribe(EventType.FOCUS_BLOCK_STARTED, on_system_notice)
    EVENT_BUS.subscribe(EventType.FOCUS_BLOCK_ENDED, on_system_notice)
    EVENT_BUS.subscribe(EventType.SYSTEM_NOTICE, on_system_notice)
    EVENT_BUS.subscribe(EventType.SESSION_SUMMARIZED, on_system_notice)

    try:
        from plyer import notification

        def send_notification(data):
            notification.notify(
                title="ADHD-OS Check-in",
                message=data.get("message") or f"{data.get('task', 'Focus')}: Check-in {data.get('checkin_number', 0)}",
                app_name="ADHD-OS",
                timeout=10,
            )

        EVENT_BUS.subscribe(EventType.CHECKIN_DUE, send_notification)
    except ImportError:
        logger.warning("plyer not installed - notifications disabled")

    loop = asyncio.get_running_loop()

    while True:
        try:
            user_input = (await loop.run_in_executor(None, input, "\nYou: ")).strip()
            if not user_input:
                continue

            if user_input.lower() == "quit":
                print("\n Work mode complete. See you tomorrow!")
                break

            if user_input.lower() == "shutdown":
                result = await RUNTIME.shutdown_session(session.id)
                _print_messages(result["messages"])
                break

            result = await RUNTIME.chat_turn(user_input, session.id)
            _print_messages(result["messages"])

        except KeyboardInterrupt:
            print("\n\n Interrupted. Running quick shutdown...")
            result = await RUNTIME.shutdown_session(session.id)
            _print_messages(result["messages"])
            break
        except Exception as exc:
            err_msg = str(exc).lower()
            if "rate" in err_msg or "429" in err_msg or "quota" in err_msg:
                logger.warning("Rate limit hit: %s", exc)
                print("\n Rate limit reached. Waiting 30 seconds before retrying...")
                await asyncio.sleep(30)
            elif "auth" in err_msg or "401" in err_msg or "api_key" in err_msg or "permission" in err_msg:
                logger.error("Authentication error: %s", exc)
                print("\n Authentication error. Please check your GOOGLE_API_KEY and ANTHROPIC_API_KEY.")
            else:
                logger.error("Runtime error: %s", exc, exc_info=True)
                print(f"\n Error: {exc}")


if __name__ == "__main__":
    missing_keys = []
    if not os.environ.get("GOOGLE_API_KEY"):
        missing_keys.append("GOOGLE_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing_keys.append("ANTHROPIC_API_KEY")

    if missing_keys:
        print(f"  Missing API keys: {', '.join(missing_keys)}")
        print("   Set them in your environment to enable all agents.")
        print()

    print(f" Starting ADHD-OS v2.1... ({datetime.now().isoformat(timespec='minutes')})")
    print()

    asyncio.run(run_adhd_os())
