import os
import asyncio
from datetime import datetime

from google.adk.runners import Runner

from adhd_os.config import MODEL_MODE, get_model
from adhd_os.state import USER_STATE
from adhd_os.infrastructure.event_bus import EVENT_BUS, EventType
from adhd_os.infrastructure.persistence import SqliteSessionService
from adhd_os.infrastructure.logging import logger
from adhd_os.agents.orchestrator import orchestrator
from adhd_os.models.message import Message

async def run_adhd_os():
    """Main interaction loop for ADHD-OS v2.1."""
    
    # Initialize state from DB
    USER_STATE.load_from_db()
    
    # Initialize session with persistence
    session_service = SqliteSessionService()
    session = await session_service.create_session(
        app_name="adhd_os",
        user_id=USER_STATE.user_id
    )
    
    # Initialize runner
    runner = Runner(
        agent=orchestrator,
        app_name="adhd_os",
        session_service=session_service
    )
    
    logger.info("ADHD Operating System v2.1 Started")
    logger.info(f"Model Mode: {MODEL_MODE.value}")
    
    print("=" * 70)
    print("  ADHD Operating System v2.1")
    print("  Merged: Full Agent Roster + Optimized Infrastructure")
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
    
    # Subscribe to events for demo visibility
    async def on_task_completed(data):
        ratio = data.get("ratio", 1.0)
        if ratio > 1.5:
            logger.warning(f"Task took {ratio:.1f}x longer than estimated", extra={"data": data})
            print(f"📊 [PATTERN] Task took {ratio:.1f}x longer than estimated. Adjusting multiplier...")
    
    EVENT_BUS.subscribe(EventType.TASK_COMPLETED, on_task_completed)
    
    while True:
        try:
            user_input = input("\nYou: ").strip()
            
            if not user_input:
                continue
            
            if user_input.lower() == 'quit':
                print("\n👋 Work mode complete. See you tomorrow!")
                break
            
            if user_input.lower() == 'shutdown':
                print("\n💾 Summarizing session...")
                # In production, run session_summarizer here
                await EVENT_BUS.publish(EventType.SESSION_SUMMARIZED, {
                    "timestamp": datetime.now().isoformat(),
                    "session_id": session.id
                })
                
                # Save persistent state
                USER_STATE.save_to_db()
                
                print("👋 Session saved. Work mode complete!")
                break
            
            # Process through orchestrator
            response = await runner.run_async(
                user_id=USER_STATE.user_id,
                session_id=session.id,
                new_message=Message(content=user_input)
            )
            
            # Extract and print response
            if response and response.content:
                print(f"\nADHD-OS: {response.content}")
            else:
                print("\n[Processing... check for deterministic machine output above]")
                
        except KeyboardInterrupt:
            print("\n\n⚡ Interrupted. Running quick shutdown...")
            await EVENT_BUS.publish(EventType.SESSION_SUMMARIZED, {"status": "interrupted"})
            USER_STATE.save_to_db()
            break
        except Exception as e:
            logger.error(f"Runtime error: {e}", exc_info=True)
            print(f"\n⚠️ Error: {e}")

if __name__ == "__main__":
    # Verify API keys
    missing_keys = []
    if not os.environ.get("GOOGLE_API_KEY"):
        missing_keys.append("GOOGLE_API_KEY")
    if not os.environ.get("ANTHROPIC_API_KEY"):
        missing_keys.append("ANTHROPIC_API_KEY")
    
    if missing_keys:
        print(f"⚠️  Missing API keys: {', '.join(missing_keys)}")
        print("   Set them in your environment to enable all agents.")
        print()
    
    print("🚀 Starting ADHD-OS v2.1...")
    print()
    
    asyncio.run(run_adhd_os())
