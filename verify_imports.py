try:
    import sys
    import os
    sys.path.append(os.getcwd())
    
    print("Verifying imports...")
    import adhd_os.main
    import adhd_os.agents.orchestrator
    import adhd_os.agents.pattern_analysis
    import adhd_os.tools.common
    import adhd_os.agents.reflector
    print("All modules imported successfully!")
except Exception as e:
    print(f"Import failed: {e}")
    import traceback
    traceback.print_exc()
