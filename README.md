# ADHD-OS Agentic System v2.1

This is a modular implementation of the ADHD-OS Agentic System.

## Structure

- `adhd_os/`: Main package
  - `agents/`: Agent definitions (Activation, Temporal, Emotional, Orchestrator)
  - `infrastructure/`: Core infrastructure (Event Bus, Cache, Deterministic Machines)
  - `tools/`: Tools used by agents
  - `models/`: Pydantic schemas
  - `config.py`: Configuration and Model Registry
  - `state.py`: User State Management
  - `main.py`: Entry point

## Prerequisites

1.  **Install Dependencies**:
    ```bash
    pip install -r requirements.txt
    ```

2.  **Set Environment Variables**:
    You need to set the following environment variables for the LLMs to work:
    - `GOOGLE_API_KEY`: Your Google AI API Key
    - `ANTHROPIC_API_KEY`: Your Anthropic API Key
    - `ADHD_OS_MODEL_MODE`: (Optional) "production", "quality", or "ab_test" (default: "production")

## Running the System

To start the ADHD-OS system:

```bash
python -m adhd_os.main
```

## Features

- **Infrastructure Optimizations**: Deterministic machines for body doubling and focus timers, semantic caching for task decomposition, and dynamic state management.
- **Full Agent Roster**: 9 specialist agents including Task Initiation, Decomposer, Body Double, Time Calibrator, Calendar, Focus Timer, Catastrophe Check, RSD Shield, and Motivation.
- **Async Patterns**: Proper async event bus and structured outputs.
- **Emotional Support**: Warm emotional support with CBT guardrails.

## Deployment

### Docker

1.  **Build the image**:
    ```bash
    docker build -t adhd-os .
    ```

2.  **Run the container**:
    ```bash
    docker run -it \
      -e GOOGLE_API_KEY=your_key \
      -e ANTHROPIC_API_KEY=your_key \
      -v $(pwd)/sessions:/app/sessions \
      adhd-os
    ```

### Persistence

The system now uses file-based persistence by default. Sessions are saved to the `sessions/` directory.
- In Docker, mount a volume to `/app/sessions` to persist data across restarts.
- Locally, data is saved to `sessions/` in the project root.

### Vertex AI Agent Engine

1.  **Prerequisites**:
    - Google Cloud Project with Vertex AI API enabled.
    - `gcloud` CLI installed and authenticated.
    - GCS bucket for staging.

2.  **Deploy**:
    ```bash
    adk deploy agent_engine \
      --project=YOUR_PROJECT_ID \
      --staging-bucket=gs://YOUR_BUCKET_NAME \
      --display-name=adhd-os \
      --agent=adhd_os.agents.orchestrator:orchestrator
    ```
