import {
  startTransition,
  useEffect,
  useEffectEvent,
  useRef,
  useState,
} from 'react'

import './App.css'
import {
  clearFocusGuardrail,
  createLiveStream,
  endBodyDouble,
  getBootstrap,
  getHistory,
  patchUserState,
  pauseBodyDouble,
  resumeBodyDouble,
  sendChatTurn,
  setFocusGuardrail,
  shutdownSession,
  startBodyDouble,
} from './api'

const QUICK_ACTIONS = [
  { id: 'morning', label: 'Morning Activation' },
  { id: 'decompose', label: 'Decompose Task' },
  { id: 'timeCheck', label: 'Time Check' },
  { id: 'planReview', label: 'Plan Review' },
  { id: 'support', label: 'Emotional Support' },
  { id: 'bodyDouble', label: 'Body Double' },
  { id: 'guardrail', label: 'Focus Guardrail' },
]

const LIVE_EVENT_NAMES = ['checkin_due', 'focus_warning', 'task_completed', 'energy_updated', 'system_notice']

const EMPTY_FORMS = {
  morning: {
    energy: '5',
    medicationTime: '',
    priorities: '',
    blockers: '',
  },
  decompose: {
    task: '',
    estimate: '30',
  },
  timeCheck: {
    task: '',
    estimate: '20',
  },
  planReview: {
    plan: '',
  },
  support: {
    mode: 'anxiety',
    details: '',
  },
  bodyDouble: {
    task: '',
    durationMinutes: '30',
    checkinInterval: '10',
  },
  guardrail: {
    minutes: '60',
    reason: '',
  },
}

function formatDateTime(value) {
  if (!value) {
    return 'Unknown'
  }
  return new Date(value).toLocaleString([], {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  })
}

function formatTime(value) {
  if (!value) {
    return 'Unknown'
  }
  return new Date(value).toLocaleTimeString([], {
    hour: 'numeric',
    minute: '2-digit',
  })
}

function toDateTimeLocal(value) {
  if (!value) {
    return ''
  }
  const date = new Date(value)
  const offset = date.getTimezoneOffset() * 60000
  return new Date(date.getTime() - offset).toISOString().slice(0, 16)
}

function summarizeEvent(payload) {
  const data = payload.data || {}
  switch (payload.event_type) {
    case 'checkin_due':
      return `Check-in ${data.checkin_number || 0}/${data.total_checkins || 0} for ${data.task || 'focus block'}.`
    case 'focus_warning':
      return data.message || 'Focus warning received.'
    case 'task_completed':
      return data.task_type
        ? `Completed ${data.task_type}.`
        : 'A task completion was recorded.'
    case 'energy_updated':
      return `Energy level updated to ${data.level}/10.`
    default:
      return data.message || data.task || 'System update recorded.'
  }
}

function buildMorningPrompt(form) {
  const priorities = form.priorities
    .split('\n')
    .map((line) => line.trim())
    .filter(Boolean)
    .slice(0, 3)
  const blockers = form.blockers.trim() || 'None noted.'
  const medicationLine = form.medicationTime
    ? `Medication taken at ${new Date(form.medicationTime).toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}.`
    : 'Medication time not logged.'

  return [
    'morning activation',
    `Energy level: ${form.energy}/10.`,
    medicationLine,
    `Top priorities: ${priorities.length > 0 ? priorities.join('; ') : 'None listed yet.'}`,
    `Blockers or anxiety: ${blockers}`,
  ].join('\n')
}

function buildDecomposePrompt(form) {
  return `Break down this task into microscopic steps.\nTask: ${form.task.trim()}\nMy estimate: ${form.estimate} minutes.`
}

function buildTimeCheckPrompt(form) {
  return `How long will this task realistically take?\nTask: ${form.task.trim()}\nMy estimate: ${form.estimate} minutes.`
}

function buildPlanReviewPrompt(form) {
  return `Review my plan for blind spots and missing steps:\n${form.plan.trim()}`
}

function buildSupportPrompt(form) {
  const labels = {
    anxiety: "I'm worried about this situation:",
    rejection: 'I think someone is upset with me:',
    motivation: 'Make this boring task feel doable:',
  }
  return `${labels[form.mode]}\n${form.details.trim()}`
}

function App() {
  const [loading, setLoading] = useState(true)
  const [working, setWorking] = useState(false)
  const [error, setError] = useState(null)
  const [activeSession, setActiveSession] = useState(null)
  const [messages, setMessages] = useState([])
  const [stats, setStats] = useState(null)
  const [userState, setUserState] = useState(null)
  const [bodyDouble, setBodyDouble] = useState({ state: 'idle' })
  const [focusGuardrail, setFocusGuardrailState] = useState({ state: 'idle' })
  const [sessions, setSessions] = useState([])
  const [history, setHistory] = useState([])
  const [activity, setActivity] = useState([])
  const [providerStatus, setProviderStatus] = useState(null)
  const [composerText, setComposerText] = useState('')
  const [selectedAction, setSelectedAction] = useState('morning')
  const [forms, setForms] = useState(EMPTY_FORMS)
  const [stateEditor, setStateEditor] = useState({
    energy: '5',
    currentTask: '',
    medicationTime: '',
    moodIndicator: '',
  })
  const [toasts, setToasts] = useState([])
  const [notificationPermission, setNotificationPermission] = useState(
    typeof Notification === 'undefined' ? 'unsupported' : Notification.permission,
  )
  const transcriptEndRef = useRef(null)

  function syncDashboard(bootstrap, historyItems) {
    setActiveSession(bootstrap.active_session)
    setMessages(bootstrap.messages || [])
    setStats(bootstrap.stats)
    setUserState(bootstrap.user_state)
    setBodyDouble(bootstrap.body_double || { state: 'idle' })
    setFocusGuardrailState(bootstrap.focus_guardrail || { state: 'idle' })
    setSessions(bootstrap.recent_sessions || [])
    setProviderStatus(bootstrap.provider_status)
    setActivity(bootstrap.recent_activity || [])
    setHistory(historyItems)
    setStateEditor({
      energy: String(bootstrap.user_state?.energy_level ?? 5),
      currentTask: bootstrap.user_state?.current_task || '',
      medicationTime: toDateTimeLocal(bootstrap.user_state?.medication_time),
      moodIndicator: '',
    })
  }

  function addToast(title, message) {
    const id = `${Date.now()}-${Math.random()}`
    setToasts((current) => [...current, { id, title, message }])
    window.setTimeout(() => {
      setToasts((current) => current.filter((toast) => toast.id !== id))
    }, 5000)
  }

  function maybeNotifyBrowser(title, body) {
    if (typeof Notification === 'undefined' || notificationPermission !== 'granted') {
      return
    }
    new Notification(title, { body })
  }

  const handleLiveEvent = useEffectEvent((payload) => {
    const summary = summarizeEvent(payload)
    setActivity((current) => [...current.slice(-9), payload])
    addToast(payload.event_type.replace('_', ' '), summary)
    maybeNotifyBrowser('ADHD-OS', summary)

    if (payload.event_type === 'energy_updated' && payload.data?.level) {
      setStats((current) => current ? { ...current, current_energy: payload.data.level } : current)
      setUserState((current) => current ? { ...current, energy_level: payload.data.level } : current)
    }

    if (payload.event_type === 'checkin_due' && payload.data) {
      setBodyDouble((current) => ({
        ...current,
        state: current.state === 'idle' ? 'active' : current.state,
        checkins_completed: payload.data.checkin_number ?? current.checkins_completed,
        task: payload.data.task ?? current.task,
      }))
    }

    if (payload.event_type === 'focus_warning' && payload.data) {
      setFocusGuardrailState((current) => ({
        ...current,
        state: current.state === 'idle' ? 'active' : current.state,
        hard_stop_time: payload.data.hard_stop_time ?? current.hard_stop_time,
        reason: payload.data.reason ?? current.reason,
      }))
    }

    if (payload.event_type === 'system_notice' && payload.data) {
      if (payload.data.machine === 'body_double' && payload.data.task && payload.data.state) {
        setBodyDouble((current) => ({
          ...current,
          state: payload.data.state,
          task: payload.data.state === 'idle' ? null : payload.data.task ?? current.task,
          remaining_minutes: payload.data.state === 'idle' ? 0 : current.remaining_minutes,
        }))
      }

      if (payload.data.machine === 'focus_guardrail') {
        setFocusGuardrailState((current) => ({
          ...current,
          state: payload.data.hard_stop_time ? 'active' : payload.data.state ?? current.state,
          hard_stop_time: payload.data.state === 'idle' ? null : payload.data.hard_stop_time ?? current.hard_stop_time,
          reason: payload.data.state === 'idle' ? null : payload.data.reason ?? current.reason,
        }))
      }
    }
  })

  async function loadDashboard(sessionId) {
    setLoading(true)
    try {
      const [bootstrap, historyItems] = await Promise.all([
        getBootstrap(sessionId),
        getHistory(),
      ])
      syncDashboard(bootstrap, historyItems)
      setError(null)
    } catch (loadError) {
      setError(loadError.message || 'Unable to connect to the ADHD-OS backend.')
    } finally {
      setLoading(false)
    }
  }

  function mergeTurnResponse(response) {
    setActiveSession((current) => ({
      ...(current || {}),
      id: response.session_id,
      last_active: new Date().toISOString(),
    }))
    setMessages((current) => {
      const knownIds = new Set(current.map((message) => message.id))
      const incoming = (response.messages || []).filter((message) => !knownIds.has(message.id))
      return [...current, ...incoming]
    })
    setUserState(response.user_state)
    setBodyDouble(response.body_double)
    setFocusGuardrailState(response.focus_guardrail)
    setStats((current) => current ? {
      ...current,
      current_energy: response.user_state?.energy_level ?? current.current_energy,
      current_multiplier: response.user_state?.dynamic_multiplier ?? current.current_multiplier,
    } : current)
    setSessions((current) => {
      const existing = current.filter((session) => session.id !== response.session_id)
      const promoted = current.find((session) => session.id === response.session_id) || {
        id: response.session_id,
        created_at: new Date().toISOString(),
        last_active: new Date().toISOString(),
      }
      return [{ ...promoted, last_active: new Date().toISOString() }, ...existing]
    })
  }

  async function sendPrompt(text) {
    const response = await sendChatTurn({
      session_id: activeSession?.id,
      text,
    })
    mergeTurnResponse(response)
    setComposerText('')
  }

  useEffect(() => {
    let ignore = false

    async function loadInitialDashboard() {
      setLoading(true)
      try {
        const [bootstrap, historyItems] = await Promise.all([
          getBootstrap(),
          getHistory(),
        ])
        if (!ignore) {
          syncDashboard(bootstrap, historyItems)
          setError(null)
        }
      } catch (loadError) {
        if (!ignore) {
          setError(loadError.message || 'Unable to connect to the ADHD-OS backend.')
        }
      } finally {
        if (!ignore) {
          setLoading(false)
        }
      }
    }

    loadInitialDashboard()

    return () => {
      ignore = true
    }
  }, [])

  useEffect(() => {
    if (!transcriptEndRef.current) {
      return
    }
    if (typeof transcriptEndRef.current.scrollIntoView === 'function') {
      transcriptEndRef.current.scrollIntoView({ behavior: 'smooth', block: 'end' })
    }
  }, [messages])

  useEffect(() => {
    const stream = createLiveStream()
    const listener = (event) => {
      try {
        handleLiveEvent(JSON.parse(event.data))
      } catch {
        // Ignore malformed events and keep the stream alive.
      }
    }

    LIVE_EVENT_NAMES.forEach((eventName) => {
      stream.addEventListener(eventName, listener)
    })

    stream.onerror = () => {
      setActivity((current) => [...current.slice(-9), {
        event_type: 'system_notice',
        timestamp: new Date().toISOString(),
        data: { message: 'Live connection dropped. Retrying automatically.' },
      }])
    }

    return () => {
      LIVE_EVENT_NAMES.forEach((eventName) => {
        stream.removeEventListener(eventName, listener)
      })
      stream.close()
    }
  }, [])

  async function handleNotificationPermission() {
    if (typeof Notification === 'undefined') {
      return
    }
    const permission = await Notification.requestPermission()
    setNotificationPermission(permission)
  }

  async function handleSessionOpen(sessionId) {
    startTransition(() => {
      setSelectedAction('morning')
    })
    await loadDashboard(sessionId)
  }

  async function handleComposerSubmit(event) {
    event.preventDefault()
    if (!composerText.trim() || working) {
      return
    }
    setWorking(true)
    try {
      await sendPrompt(composerText)
      setError(null)
    } catch (submitError) {
      setError(submitError.message || 'Unable to send your message right now.')
    } finally {
      setWorking(false)
    }
  }

  async function handleStateSave(event) {
    event.preventDefault()
    setWorking(true)
    try {
      const updated = await patchUserState({
        energy_level: Number(stateEditor.energy),
        current_task: stateEditor.currentTask,
        medication_time: stateEditor.medicationTime
          ? new Date(stateEditor.medicationTime).toISOString()
          : '',
        mood_indicator: stateEditor.moodIndicator.trim() || null,
      })
      setUserState(updated)
      setStats((current) => current ? {
        ...current,
        current_energy: updated.energy_level,
        current_multiplier: updated.dynamic_multiplier,
      } : current)
      setStateEditor((current) => ({ ...current, moodIndicator: '' }))
      addToast('state updated', 'Capacity and task context saved.')
      setError(null)
    } catch (patchError) {
      setError(patchError.message || 'Unable to update your state.')
    } finally {
      setWorking(false)
    }
  }

  async function handleQuickActionSubmit(event) {
    event.preventDefault()
    if (working) {
      return
    }

    const form = forms[selectedAction]
    setWorking(true)

    try {
      if (selectedAction === 'morning') {
        await patchUserState({
          energy_level: Number(form.energy),
          medication_time: form.medicationTime
            ? new Date(form.medicationTime).toISOString()
            : '',
        })
        await sendPrompt(buildMorningPrompt(form))
      } else if (selectedAction === 'decompose') {
        await sendPrompt(buildDecomposePrompt(form))
      } else if (selectedAction === 'timeCheck') {
        await sendPrompt(buildTimeCheckPrompt(form))
      } else if (selectedAction === 'planReview') {
        await sendPrompt(buildPlanReviewPrompt(form))
      } else if (selectedAction === 'support') {
        await sendPrompt(buildSupportPrompt(form))
      } else if (selectedAction === 'bodyDouble') {
        const status = await startBodyDouble({
          task: form.task,
          duration_minutes: Number(form.durationMinutes),
          checkin_interval: Number(form.checkinInterval),
        })
        setBodyDouble(status)
        addToast('body double', `Started a body-double block for ${form.task}.`)
      } else if (selectedAction === 'guardrail') {
        const status = await setFocusGuardrail({
          minutes: Number(form.minutes),
          reason: form.reason,
        })
        setFocusGuardrailState(status)
        addToast('focus guardrail', `Hard stop set for ${form.minutes} minutes.`)
      }

      setError(null)
    } catch (actionError) {
      setError(actionError.message || 'Unable to complete that quick action.')
    } finally {
      setWorking(false)
    }
  }

  async function handleShutdown() {
    if (!activeSession?.id || working) {
      return
    }
    setWorking(true)
    try {
      const response = await shutdownSession(activeSession.id)
      mergeTurnResponse(response)
      addToast('shutdown', 'Session saved and summarized.')
      setError(null)
    } catch (shutdownError) {
      setError(shutdownError.message || 'Unable to shut down the current session.')
    } finally {
      setWorking(false)
    }
  }

  async function handleBodyDoublePause() {
    setWorking(true)
    try {
      const status = await pauseBodyDouble({ reason: 'Paused from the dashboard' })
      setBodyDouble(status)
      addToast('body double', 'Body-double session paused.')
      setError(null)
    } catch (pauseError) {
      setError(pauseError.message || 'Unable to pause the body-double session.')
    } finally {
      setWorking(false)
    }
  }

  async function handleBodyDoubleResume() {
    setWorking(true)
    try {
      const status = await resumeBodyDouble()
      setBodyDouble(status)
      addToast('body double', 'Body-double session resumed.')
      setError(null)
    } catch (resumeError) {
      setError(resumeError.message || 'Unable to resume the body-double session.')
    } finally {
      setWorking(false)
    }
  }

  async function handleBodyDoubleEnd() {
    setWorking(true)
    try {
      const status = await endBodyDouble({ completed: true })
      setBodyDouble(status)
      addToast('body double', 'Body-double session completed.')
      setError(null)
    } catch (endError) {
      setError(endError.message || 'Unable to finish the body-double session.')
    } finally {
      setWorking(false)
    }
  }

  async function handleGuardrailClear() {
    setWorking(true)
    try {
      const status = await clearFocusGuardrail()
      setFocusGuardrailState(status)
      addToast('focus guardrail', 'Hard stop cleared.')
      setError(null)
    } catch (clearError) {
      setError(clearError.message || 'Unable to clear the focus guardrail.')
    } finally {
      setWorking(false)
    }
  }

  function updateForm(section, key, value) {
    setForms((current) => ({
      ...current,
      [section]: {
        ...current[section],
        [key]: value,
      },
    }))
  }

  function renderQuickActionFields() {
    const form = forms[selectedAction]

    if (selectedAction === 'morning') {
      return (
        <>
          <label>
            Energy
            <input
              type="range"
              min="1"
              max="10"
              value={form.energy}
              onChange={(event) => updateForm('morning', 'energy', event.target.value)}
            />
            <span className="field-hint">{form.energy}/10</span>
          </label>
          <label>
            Medication Time
            <input
              type="datetime-local"
              value={form.medicationTime}
              onChange={(event) => updateForm('morning', 'medicationTime', event.target.value)}
            />
          </label>
          <label>
            Top Priorities
            <textarea
              rows="4"
              placeholder="One priority per line"
              value={form.priorities}
              onChange={(event) => updateForm('morning', 'priorities', event.target.value)}
            />
          </label>
          <label>
            Blockers
            <textarea
              rows="3"
              placeholder="Anxiety, obstacles, or friction"
              value={form.blockers}
              onChange={(event) => updateForm('morning', 'blockers', event.target.value)}
            />
          </label>
        </>
      )
    }

    if (selectedAction === 'decompose') {
      return (
        <>
          <label>
            Task
            <textarea
              rows="4"
              placeholder="What needs to be broken down?"
              value={form.task}
              onChange={(event) => updateForm('decompose', 'task', event.target.value)}
            />
          </label>
          <label>
            Your Estimate (minutes)
            <input
              type="number"
              min="1"
              value={form.estimate}
              onChange={(event) => updateForm('decompose', 'estimate', event.target.value)}
            />
          </label>
        </>
      )
    }

    if (selectedAction === 'timeCheck') {
      return (
        <>
          <label>
            Task
            <textarea
              rows="4"
              placeholder="What are you estimating?"
              value={form.task}
              onChange={(event) => updateForm('timeCheck', 'task', event.target.value)}
            />
          </label>
          <label>
            Your Estimate (minutes)
            <input
              type="number"
              min="1"
              value={form.estimate}
              onChange={(event) => updateForm('timeCheck', 'estimate', event.target.value)}
            />
          </label>
        </>
      )
    }

    if (selectedAction === 'planReview') {
      return (
        <label>
          Plan
          <textarea
            rows="8"
            placeholder="Paste the plan you want reviewed"
            value={form.plan}
            onChange={(event) => updateForm('planReview', 'plan', event.target.value)}
          />
        </label>
      )
    }

    if (selectedAction === 'support') {
      return (
        <>
          <label>
            Support Type
            <select
              value={form.mode}
              onChange={(event) => updateForm('support', 'mode', event.target.value)}
            >
              <option value="anxiety">Catastrophe Check</option>
              <option value="rejection">RSD Shield</option>
              <option value="motivation">Motivation Engineer</option>
            </select>
          </label>
          <label>
            Situation
            <textarea
              rows="6"
              placeholder="What happened, or what feels hard right now?"
              value={form.details}
              onChange={(event) => updateForm('support', 'details', event.target.value)}
            />
          </label>
        </>
      )
    }

    if (selectedAction === 'bodyDouble') {
      return (
        <>
          <label>
            Task
            <input
              type="text"
              value={form.task}
              placeholder="What are you staying with?"
              onChange={(event) => updateForm('bodyDouble', 'task', event.target.value)}
            />
          </label>
          <label>
            Duration (minutes)
            <input
              type="number"
              min="5"
              max="480"
              value={form.durationMinutes}
              onChange={(event) => updateForm('bodyDouble', 'durationMinutes', event.target.value)}
            />
          </label>
          <label>
            Check-in Interval
            <input
              type="number"
              min="1"
              max="480"
              value={form.checkinInterval}
              onChange={(event) => updateForm('bodyDouble', 'checkinInterval', event.target.value)}
            />
          </label>
        </>
      )
    }

    return (
      <>
        <label>
          Minutes Until Hard Stop
          <input
            type="number"
            min="5"
            max="480"
            value={form.minutes}
            onChange={(event) => updateForm('guardrail', 'minutes', event.target.value)}
          />
        </label>
        <label>
          Reason
          <input
            type="text"
            value={form.reason}
            placeholder="Why does this stop matter?"
            onChange={(event) => updateForm('guardrail', 'reason', event.target.value)}
          />
        </label>
      </>
    )
  }

  if (loading) {
    return (
      <div className="shell loading-shell">
        <div className="glass-card hero-card">
          <p className="eyebrow">ADHD-OS</p>
          <h1>Loading the local command center...</h1>
          <p>Bootstrapping your current session, recent activity, and machine status.</p>
        </div>
      </div>
    )
  }

  return (
    <div className="shell">
      <header className="topbar glass-card">
        <div>
          <p className="eyebrow">ADHD-OS</p>
          <h1>Executive Function Workspace</h1>
          <p className="subtle">
            Session {activeSession?.id?.slice(0, 8) || 'new'} | {providerStatus?.model_mode || 'unknown'} mode
          </p>
        </div>
        <div className="topbar-actions">
          <div className={`provider-pill ${providerStatus?.ready ? 'ready' : 'warning'}`}>
            {providerStatus?.ready ? 'Providers ready' : 'API keys missing'}
          </div>
          {notificationPermission === 'default' ? (
            <button className="secondary-button" type="button" onClick={handleNotificationPermission}>
              Enable Notifications
            </button>
          ) : null}
          <button className="danger-button" type="button" onClick={handleShutdown} disabled={working || !activeSession?.id}>
            Shutdown Session
          </button>
        </div>
      </header>

      {error ? (
        <div className="error-banner glass-card" role="alert">
          {error}
        </div>
      ) : null}

      <div className="workspace">
        <aside className="left-column">
          <section className="glass-card panel-card">
            <div className="panel-heading">
              <h2>Recent Sessions</h2>
              <span>{sessions.length}</span>
            </div>
            <div className="session-list">
              {sessions.map((session) => (
                <button
                  type="button"
                  key={session.id}
                  className={`session-tile ${activeSession?.id === session.id ? 'active' : ''}`}
                  onClick={() => handleSessionOpen(session.id)}
                >
                  <strong>{session.id.slice(0, 8)}</strong>
                  <span>{formatDateTime(session.last_active)}</span>
                </button>
              ))}
            </div>
          </section>

          <section className="glass-card panel-card">
            <div className="panel-heading">
              <h2>Quick Actions</h2>
              <span>Hybrid UI</span>
            </div>
            <div className="action-list">
              {QUICK_ACTIONS.map((action) => (
                <button
                  key={action.id}
                  type="button"
                  className={`action-chip ${selectedAction === action.id ? 'active' : ''}`}
                  onClick={() => setSelectedAction(action.id)}
                >
                  {action.label}
                </button>
              ))}
            </div>
            <form className="quick-form" onSubmit={handleQuickActionSubmit}>
              {renderQuickActionFields()}
              <button className="primary-button" type="submit" disabled={working}>
                {selectedAction === 'bodyDouble'
                  ? 'Start Session'
                  : selectedAction === 'guardrail'
                    ? 'Set Guardrail'
                    : 'Send Guided Prompt'}
              </button>
            </form>
          </section>
        </aside>

        <main className="center-column glass-card transcript-card">
          <div className="panel-heading transcript-heading">
            <div>
              <h2>Conversation</h2>
              <p className="subtle">Chat directly or use structured workflows on the left.</p>
            </div>
            <div className="stats-strip">
              <div>
                <strong>{stats?.current_energy ?? 0}/10</strong>
                <span>capacity</span>
              </div>
              <div>
                <strong>{stats?.current_multiplier ?? 1}x</strong>
                <span>multiplier</span>
              </div>
              <div>
                <strong>{stats?.tasks_completed_today ?? 0}</strong>
                <span>done today</span>
              </div>
            </div>
          </div>

          <div className="transcript" aria-live="polite">
            {messages.length === 0 ? (
              <div className="empty-state">
                <h3>No transcript yet</h3>
                <p>Start with a freeform message or one of the guided quick actions.</p>
              </div>
            ) : (
              messages.map((message) => (
                <article
                  key={message.id}
                  className={`message-bubble ${message.role} ${message.kind}`}
                >
                  <div className="message-meta">
                    <span>{message.role === 'user' ? 'You' : message.role === 'assistant' ? 'ADHD-OS' : 'System'}</span>
                    <span>{formatDateTime(message.created_at)}</span>
                  </div>
                  <p>{message.text}</p>
                </article>
              ))
            )}
            <div ref={transcriptEndRef} />
          </div>

          <form className="composer" onSubmit={handleComposerSubmit}>
            <textarea
              rows="4"
              placeholder="Talk to ADHD-OS like a coworker. Example: I'm stuck on the QBR report."
              value={composerText}
              onChange={(event) => setComposerText(event.target.value)}
              disabled={working}
            />
            <div className="composer-actions">
              <span className="subtle">Freeform chat routes through the orchestrator and persists to this session.</span>
              <button className="primary-button" type="submit" disabled={working || !composerText.trim()}>
                Send Message
              </button>
            </div>
          </form>
        </main>

        <aside className="right-column">
          <section className="glass-card panel-card">
            <div className="panel-heading">
              <h2>State Snapshot</h2>
              <span>{userState?.peak_window?.active ? 'Peak window' : 'Off peak'}</span>
            </div>
            <form className="state-form" onSubmit={handleStateSave}>
              <label>
                Energy
                <input
                  type="range"
                  min="1"
                  max="10"
                  value={stateEditor.energy}
                  onChange={(event) => setStateEditor((current) => ({ ...current, energy: event.target.value }))}
                />
                <span className="field-hint">{stateEditor.energy}/10</span>
              </label>
              <label>
                Current Task
                <input
                  type="text"
                  value={stateEditor.currentTask}
                  onChange={(event) => setStateEditor((current) => ({ ...current, currentTask: event.target.value }))}
                />
              </label>
              <label>
                Medication Time
                <input
                  type="datetime-local"
                  value={stateEditor.medicationTime}
                  onChange={(event) => setStateEditor((current) => ({ ...current, medicationTime: event.target.value }))}
                />
              </label>
              <label>
                Mood Note
                <input
                  type="text"
                  value={stateEditor.moodIndicator}
                  placeholder="Optional"
                  onChange={(event) => setStateEditor((current) => ({ ...current, moodIndicator: event.target.value }))}
                />
              </label>
              <button className="secondary-button" type="submit" disabled={working}>
                Save State
              </button>
            </form>
          </section>

          <section className="glass-card panel-card">
            <div className="panel-heading">
              <h2>Active Machines</h2>
              <span>{bodyDouble?.state === 'idle' && focusGuardrail?.state === 'idle' ? 'Quiet' : 'Running'}</span>
            </div>
            <div className="machine-card">
              <h3>Body Double</h3>
              <p>{bodyDouble?.task || 'No active session'}</p>
              <div className="machine-metrics">
                <span>{bodyDouble?.state || 'idle'}</span>
                <span>{bodyDouble?.remaining_minutes ?? 0} min left</span>
              </div>
              <div className="inline-actions">
                {bodyDouble?.state === 'paused' ? (
                  <button type="button" className="secondary-button" onClick={handleBodyDoubleResume} disabled={working}>
                    Resume
                  </button>
                ) : (
                  <button type="button" className="secondary-button" onClick={handleBodyDoublePause} disabled={working || bodyDouble?.state === 'idle'}>
                    Pause
                  </button>
                )}
                <button type="button" className="secondary-button" onClick={handleBodyDoubleEnd} disabled={working || bodyDouble?.state === 'idle'}>
                  Complete
                </button>
              </div>
            </div>
            <div className="machine-card">
              <h3>Focus Guardrail</h3>
              <p>{focusGuardrail?.reason || 'No hard stop scheduled'}</p>
              <div className="machine-metrics">
                <span>{focusGuardrail?.state || 'idle'}</span>
                <span>{focusGuardrail?.hard_stop_time ? formatTime(focusGuardrail.hard_stop_time) : '-'}</span>
              </div>
              <button type="button" className="secondary-button" onClick={handleGuardrailClear} disabled={working || focusGuardrail?.state === 'idle'}>
                Clear Guardrail
              </button>
            </div>
          </section>

          <section className="glass-card panel-card">
            <div className="panel-heading">
              <h2>Live Activity</h2>
              <span>{activity.length}</span>
            </div>
            <div className="activity-list">
              {activity.length === 0 ? (
                <p className="subtle">Live check-ins, warnings, and task events will appear here.</p>
              ) : (
                activity.map((event, index) => (
                  <div key={`${event.timestamp}-${index}`} className="activity-item">
                    <strong>{event.event_type.replace('_', ' ')}</strong>
                    <span>{summarizeEvent(event)}</span>
                    <time>{formatDateTime(event.timestamp)}</time>
                  </div>
                ))
              )}
            </div>
          </section>

          <section className="glass-card panel-card">
            <div className="panel-heading">
              <h2>Task History</h2>
              <span>{history.length}</span>
            </div>
            <div className="history-list">
              {history.slice(0, 8).length === 0 ? (
                <p className="subtle">No task completions recorded yet.</p>
              ) : (
                history.slice(0, 8).map((item) => (
                  <div key={item.id} className="history-item">
                    <strong>{item.task_type || item.type}</strong>
                    <span>{item.duration_minutes ? `${item.duration_minutes.toFixed(1)}m` : 'Logged'}</span>
                    <time>{formatDateTime(item.completed_at || item.date)}</time>
                  </div>
                ))
              )}
            </div>
          </section>
        </aside>
      </div>

      <div className="toast-stack" aria-live="polite" aria-atomic="true">
        {toasts.map((toast) => (
          <div key={toast.id} className="toast glass-card">
            <strong>{toast.title}</strong>
            <span>{toast.message}</span>
          </div>
        ))}
      </div>
    </div>
  )
}

export default App
