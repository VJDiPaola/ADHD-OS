# ADHD-OS v2.1 - Codebase Evaluation

## Executive Summary

ADHD-OS is a well-conceived multi-agent AI system serving as an "executive function prosthetic" for people with ADHD. The domain modeling is strong — the agent specializations (initiation, decomposition, emotional regulation, temporal calibration) map directly to real ADHD challenges. The architecture leverages Google ADK's multi-agent routing effectively, and the local-first SQLite approach is appropriate for the privacy-sensitive use case.

However, the codebase has a number of concrete bugs, architectural gaps, and maintainability concerns that would need to be addressed before production use. This evaluation categorizes findings by severity and provides actionable recommendations.

---

## Critical Bugs

### 1. Dashboard API queries reference non-existent columns
**Files:** `adhd_os/dashboard/backend.py:44,64-68,89`

The dashboard backend queries columns that don't exist in the actual database schema defined in `adhd_os/infrastructure/database.py`:

- `/api/stats` queries `dynamic_multiplier` from `user_state` — but this is a computed property on the `UserState` dataclass, never stored in the DB.
- `/api/history` queries `task_id`, `description`, `completed_at`, `actual_duration` — but `task_history` has columns `id`, `task_type`, `estimated_minutes`, `actual_minutes`, `energy_level`, `in_peak_window`, `timestamp`.
- `/api/sessions` queries `last_update_time` — but the column is `last_updated_at`.

**Impact:** Every dashboard endpoint will crash with `sqlite3.OperationalError` at runtime.

### 2. `save_to_db` silently drops `current_task` when it's `None`
**File:** `adhd_os/state.py:107-108`

```python
if self.current_task:
    DB.save_state("current_task", self.current_task)
```

When the user finishes a task and `current_task` is set to `None`, the old value persists in the database. On next session load, it incorrectly reports the old task as still active. This should unconditionally save the value (including `None`).

### 3. Time-of-day multiplier logic has unreachable branch
**File:** `adhd_os/state.py:48-52`

```python
if hour >= 15:      # Afternoon slump
    mult += 0.15
elif hour >= 20:    # Evening
    mult += 0.25
```

The `elif hour >= 20` branch is unreachable because `hour >= 20` is always also `>= 15`, so the first branch catches it. Evening hours get the smaller afternoon adjustment instead of the intended larger one. The conditions should be reversed: check `hour >= 20` first.

### 4. `get_recent_history` accesses private DB internals
**File:** `adhd_os/tools/common.py:204`

```python
with DB._get_conn() as conn:
```

This bypasses the `DatabaseManager` API and directly accesses its private `_get_conn()` method, breaking encapsulation. If the DB layer changes (e.g., connection pooling), this will silently break. Should be a proper method on `DatabaseManager`.

### 5. `asyncio.create_task` called without a running event loop guarantee
**File:** `adhd_os/tools/common.py:51,140,165`

`asyncio.create_task()` is called inside synchronous `@FunctionTool` functions. If these tools are ever called from a synchronous context (or a different event loop), this will raise `RuntimeError: no running event loop`. The `activate_body_double` function at line 173 uses `asyncio.get_event_loop()` which is deprecated and may return a closed loop.

---

## Architectural Issues

### 6. New SQLite connection per operation — no connection reuse
**File:** `adhd_os/infrastructure/database.py:16-17`

Every method call creates a new `sqlite3.connect()`. While SQLite handles this reasonably for single-user local use, it adds unnecessary overhead and prevents connection-level features like WAL mode or shared cache. A single connection (or a small pool) per process would be more appropriate.

### 7. Race condition in `update_session_state` (read-modify-write)
**File:** `adhd_os/infrastructure/persistence.py:142-154`

The method does a read-modify-write on `state_json` without any locking. If two concurrent async tasks update session state, one update can be lost. Since this is an async system with background tasks (body double, focus timer), this is a real risk, not theoretical.

### 8. Global mutable singletons everywhere
**Files:** `state.py:138`, `database.py:164`, `event_bus.py:58`, `cache.py:64`, `machines.py:231-232`

Nearly every module exports a global singleton (`USER_STATE`, `DB`, `EVENT_BUS`, `TASK_CACHE`, `BODY_DOUBLE`, `FOCUS_TIMER`). This makes testing difficult (tests share state), prevents multi-user scenarios, and creates hidden import-time side effects (e.g., `DB` creates the database file on import). Consider dependency injection or at minimum a factory function that can be reset.

### 9. No unsubscribe mechanism on EventBus
**File:** `adhd_os/infrastructure/event_bus.py:27-31`

Subscribers can be added but never removed. In a long-running session, if handlers are re-registered (e.g., on reconnect), they accumulate and fire multiple times per event. The bus should support unsubscribe or use weak references.

### 10. Hardcoded user ID
**File:** `adhd_os/state.py:11`

```python
user_id: str = "vince"
```

The user ID is hardcoded. While this is a local-first single-user app, it creates a problem if the system is ever deployed for multiple users and makes tests share state unnecessarily.

---

## Security Concerns

### 11. Path traversal vulnerability in `safe_read_file` and `safe_list_dir`
**File:** `adhd_os/tools/common.py:227-255`

The path check `target_path.startswith(base_path)` is insufficient. A symlink inside the project directory could point outside it, and `os.path.abspath` doesn't resolve symlinks. For example, if there's a symlink `project/link -> /etc`, then `safe_read_file("link/passwd")` resolves to `/home/user/ADHD-OS/link/passwd` which passes the startswith check but follows the symlink to `/etc/passwd`. Use `os.path.realpath()` instead of `os.path.abspath()`.

### 12. CORS allows all origins
**File:** `adhd_os/dashboard/backend.py:13`

```python
allow_origins=["*"]
```

The comment says "In production, restrict this" but there's no mechanism to do so. This should at minimum default to `localhost` origins.

### 13. MD5 used for cache hashing
**File:** `adhd_os/infrastructure/cache.py:22`

MD5 is used with truncation to 12 hex chars. While this isn't a security-critical use (just cache keys), collisions are more likely with truncation and could cause incorrect cache hits. SHA-256 truncated to the same length would be more collision-resistant for negligible cost.

---

## Code Quality & Maintainability

### 14. Demo/hardcoded timing values embedded in production code
**Files:** `adhd_os/infrastructure/machines.py:64,205`

```python
demo_interval = 3  # seconds (BodyDoubleMachine)
demo_multiplier = 0.1  # (FocusTimerMachine)
```

The body double checks in every 3 seconds instead of the actual interval, and the focus timer compresses all warnings to sub-second intervals. These demo shortcuts are not behind a flag or environment variable, so the system cannot function correctly in actual use.

### 15. `motivation_agent` passes `api_key=None` explicitly
**File:** `adhd_os/agents/emotional.py:113`

```python
model=LiteLlm(model=MODELS["motivation"], api_key=None)
```

This is the only agent that passes `api_key=None`. It's unclear why — LiteLlm should pick up the API key from the environment. This inconsistency suggests a debugging leftover that could cause the agent to fail if `None` overrides the environment key.

### 16. `pattern_analysis_agent` uses wrong model key
**File:** `adhd_os/agents/pattern_analysis.py:9`

```python
model=LiteLlm(model=MODELS["temporal"])  # Comment says Gemini Flash for data analysis
```

The agent is described as a "Pattern Recognition Specialist" using Gemini Pro for deeper analysis (per `config.py:17`), but actually uses the `temporal` model (Gemini Flash). The config has a dedicated `pattern_analysis` key pointing to Gemini Pro that's never used.

### 17. Test file doesn't use a test framework
**File:** `tests/test_routing.py`

The test uses raw `asyncio.run()` and `print()` statements instead of `pytest` or `unittest`. Tests don't verify routing to the correct sub-agent — they only check that *some* response was received. The test name `test_routing` implies routing verification but doesn't actually assert which agent handled each input.

### 18. `schedule_checkin` is a no-op
**File:** `adhd_os/tools/common.py:190-198`

The function returns a dict saying the check-in is scheduled, but doesn't actually schedule anything. The comment says "In production, use Cloud Tasks" — but this means the feature is entirely non-functional. Agents that rely on this tool (calendar agent) are giving users false promises.

### 19. `get_similar_tasks` fetches entire table
**File:** `adhd_os/infrastructure/database.py:123-127`

```python
def get_similar_tasks(self, keywords: List[str]) -> List[str]:
    cursor = conn.execute("SELECT task_description FROM task_cache")
    return [r[0] for r in cursor.fetchall()]
```

The `keywords` parameter is completely ignored. The method fetches every cached task description, then the caller in `cache.py` does keyword matching in Python. This should at minimum use SQL `LIKE` or `INSTR` filtering.

### 20. No log rotation or size limits
**File:** `adhd_os/infrastructure/logging.py:37`

The file handler writes to `logs/adhd_os.jsonl` with no rotation. For a long-running application, this file will grow unboundedly. Use `RotatingFileHandler` or `TimedRotatingFileHandler`.

### 21. Unused import
**File:** `adhd_os/infrastructure/persistence.py:3`

`import pickle` is imported but never used.

---

## Testing Gaps

- **No unit tests** for `UserState`, `DatabaseManager`, `EventBus`, `TaskCache`, `BodyDoubleMachine`, or `FocusTimerMachine`.
- **No integration test** for the dashboard API endpoints.
- **No test for crisis keyword detection** — this is a safety-critical feature.
- **No test for the dynamic multiplier calculation** — the time-of-day bug (item #3) would have been caught.
- **No pytest configuration** (`pyproject.toml`, `pytest.ini`, or `setup.cfg`).

---

## Missing Error Handling

- **No graceful degradation** if one LLM provider is down. If the Anthropic API is unreachable, all emotional agents fail with no fallback.
- **No retry logic** for LLM API calls. Network blips cause immediate failures.
- **Database operations** don't handle `sqlite3.OperationalError` (e.g., disk full, locked database).
- **Session recovery** at `main.py:30` calls `datetime.fromtimestamp(last_session.last_update_time)` — if `last_update_time` is somehow `None` or corrupted, the entire startup crashes.

---

## Prioritized Recommendations

### P0 — Fix before any use
1. Fix dashboard API queries to match actual DB schema
2. Fix time-of-day multiplier ordering (`hour >= 20` before `hour >= 15`)
3. Fix `save_to_db` to persist `current_task = None`
4. Replace demo timing with configurable values behind an env flag
5. Fix `pattern_analysis_agent` to use `MODELS["pattern_analysis"]`

### P1 — Fix before production
6. Add `os.path.realpath()` to path traversal checks
7. Restrict CORS to localhost by default
8. Add proper unit tests with pytest (at minimum: state, database, multiplier, crisis keywords)
9. Replace `asyncio.get_event_loop()` with proper async patterns
10. Add a `get_recent_history` method to `DatabaseManager` instead of accessing `_get_conn()`

### P2 — Improve maintainability
11. Extract demo/production timing into configuration
12. Add connection reuse or WAL mode to SQLite
13. Implement actual `schedule_checkin` functionality (even a simple asyncio-based version)
14. Add log rotation
15. Remove unused `pickle` import
16. Remove `api_key=None` from motivation agent
17. Add unsubscribe to EventBus
18. Use SHA-256 instead of MD5 for cache keys

### P3 — Improve architecture
19. Replace global singletons with dependency injection (or at minimum, add `reset()` methods for testing)
20. Add model fallback logic (if Claude is down, fall back to Gemini for emotional agents)
21. Add a proper test framework and CI pipeline
22. Add SQL filtering to `get_similar_tasks`
23. Make user ID configurable

---

## What's Done Well

- **Domain modeling**: The agent specializations genuinely map to ADHD executive function deficits. The decomposition protocol, RSD shield, and time calibration are well-designed.
- **Deterministic state machines**: Using state machines for body double and focus timer instead of LLM calls is a good architectural decision — low latency, predictable behavior.
- **Event-driven design**: The event bus enables loose coupling between components.
- **Crisis intervention**: Hard-coded safety checks that bypass the LLM are critical and correctly implemented (though they need tests).
- **Prompt engineering**: The agent instructions are thorough, compassionate, and include concrete examples of good vs. bad outputs. The "never say" lists in emotional agents are particularly well-considered.
- **Multi-model routing**: Using different models for different tasks (Claude for empathy, Gemini for speed) is a smart cost/quality optimization.
