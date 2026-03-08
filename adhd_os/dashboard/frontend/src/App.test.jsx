import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  clearFocusGuardrail: vi.fn(),
  createLiveStream: vi.fn(),
  createTask: vi.fn(),
  decomposeTask: vi.fn(),
  endBodyDouble: vi.fn(),
  getBootstrap: vi.fn(),
  getHistory: vi.fn(),
  patchProviderSettings: vi.fn(),
  patchUserState: vi.fn(),
  pauseBodyDouble: vi.fn(),
  resumeBodyDouble: vi.fn(),
  sendChatTurn: vi.fn(),
  setFocusGuardrail: vi.fn(),
  shutdownSession: vi.fn(),
  startBodyDouble: vi.fn(),
  updateTask: vi.fn(),
  updateTaskStep: vi.fn(),
}))

import App from './App'
import * as api from './api'

class MockEventSource {
  constructor() {
    this.listeners = new Map()
    this.onerror = null
  }

  addEventListener(name, listener) {
    this.listeners.set(name, listener)
  }

  removeEventListener(name) {
    this.listeners.delete(name)
  }

  emit(name, payload) {
    const listener = this.listeners.get(name)
    if (listener) {
      listener({ data: JSON.stringify(payload) })
    }
  }

  close() {}
}

function buildTask(overrides = {}) {
  return {
    id: 201,
    title: 'Quarterly report',
    description: 'Calibrated estimate: 45 minutes. Activation phrase: I am just going to open the report doc.',
    status: 'today',
    source: 'decomposition',
    session_id: 'sess-001-a',
    estimated_minutes: 45,
    activation_phrase: 'I am just going to open the report doc.',
    created_at: '2026-03-08T12:00:00',
    updated_at: '2026-03-08T12:00:00',
    completed_at: null,
    steps: [
      {
        id: 301,
        task_id: 201,
        step_number: 1,
        text: 'Open the report doc and outline the first section.',
        duration_minutes: 5,
        is_checkpoint: false,
        completed: false,
        created_at: '2026-03-08T12:00:00',
        completed_at: null,
      },
      {
        id: 302,
        task_id: 201,
        step_number: 2,
        text: 'Draft the intro section.',
        duration_minutes: 10,
        is_checkpoint: false,
        completed: false,
        created_at: '2026-03-08T12:00:00',
        completed_at: null,
      },
    ],
    ...overrides,
  }
}

function buildBootstrap(overrides = {}) {
  return {
    active_session: {
      id: 'sess-001-a',
      last_active: '2026-03-08T12:00:00',
    },
    messages: [
      {
        id: 1,
        session_id: 'sess-001-a',
        role: 'assistant',
        kind: 'chat',
        text: 'How can I help?',
        created_at: '2026-03-08T12:00:00',
      },
    ],
    stats: {
      current_energy: 6,
      current_multiplier: 1.7,
      tasks_completed_today: 2,
    },
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
      current_task: 'Inbox cleanup',
      medication_time: '2026-03-08T10:00:00',
      peak_window: { active: true },
    },
    body_double: { state: 'idle' },
    focus_guardrail: { state: 'idle' },
    tasks: [buildTask()],
    recent_sessions: [
      { id: 'sess-001-a', last_active: '2026-03-08T12:00:00' },
      { id: 'sess-002-b', last_active: '2026-03-07T20:00:00' },
    ],
    provider_status: {
      google_api_key_present: true,
      anthropic_api_key_present: true,
      ready: true,
      model_mode: 'production',
      effective_model_mode: 'production',
      model_mode_restart_required: false,
    },
    recent_activity: [],
    ...overrides,
  }
}

beforeEach(() => {
  vi.resetAllMocks()
  api.getBootstrap.mockResolvedValue(buildBootstrap())
  api.getHistory.mockResolvedValue([
    {
      id: 'history-11',
      task_type: 'Email triage',
      completed_at: '2026-03-08T11:00:00',
      duration_minutes: 12,
    },
  ])
  api.patchUserState.mockResolvedValue({
    energy_level: 7,
    dynamic_multiplier: 1.6,
    current_task: 'Inbox cleanup',
    peak_window: { active: true },
  })
  api.patchProviderSettings.mockResolvedValue({
    google_api_key_present: true,
    anthropic_api_key_present: true,
    ready: true,
    model_mode: 'quality',
    effective_model_mode: 'production',
    model_mode_restart_required: true,
  })
  api.sendChatTurn.mockResolvedValue({
    session_id: 'sess-001-a',
    messages: [
      {
        id: 2,
        session_id: 'sess-001-a',
        role: 'user',
        kind: 'chat',
        text: 'Help me start',
        created_at: '2026-03-08T12:01:00',
      },
      {
        id: 3,
        session_id: 'sess-001-a',
        role: 'assistant',
        kind: 'chat',
        text: 'Open the document and write the title.',
        created_at: '2026-03-08T12:01:05',
      },
    ],
    tasks: [buildTask()],
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
      current_task: 'Inbox cleanup',
    },
    body_double: { state: 'idle' },
    focus_guardrail: { state: 'idle' },
  })
  api.createTask.mockResolvedValue({
    task: buildTask({
      id: 202,
      title: 'Pay internet bill',
      status: 'inbox',
      estimated_minutes: null,
      activation_phrase: null,
      description: null,
      steps: [],
    }),
    tasks: [
      buildTask({
        id: 202,
        title: 'Pay internet bill',
        status: 'inbox',
        estimated_minutes: null,
        activation_phrase: null,
        description: null,
        steps: [],
      }),
      buildTask(),
    ],
    stats: {
      current_energy: 6,
      current_multiplier: 1.7,
      tasks_completed_today: 2,
    },
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
      current_task: 'Inbox cleanup',
    },
  })
  api.decomposeTask.mockResolvedValue({
    task: buildTask({
      id: 203,
      title: 'Draft launch email',
      description: 'Calibrated estimate: 50 minutes. Activation phrase: I am just going to open the email draft.',
      status: 'today',
      estimated_minutes: 50,
      activation_phrase: 'I am just going to open the email draft.',
      steps: [
        {
          id: 401,
          task_id: 203,
          step_number: 1,
          text: 'Open the email draft and write the subject line.',
          duration_minutes: 5,
          is_checkpoint: false,
          completed: false,
          created_at: '2026-03-08T12:05:00',
          completed_at: null,
        },
      ],
    }),
    tasks: [
      buildTask({
        id: 203,
        title: 'Draft launch email',
        description: 'Calibrated estimate: 50 minutes. Activation phrase: I am just going to open the email draft.',
        status: 'today',
        estimated_minutes: 50,
        activation_phrase: 'I am just going to open the email draft.',
        steps: [
          {
            id: 401,
            task_id: 203,
            step_number: 1,
            text: 'Open the email draft and write the subject line.',
            duration_minutes: 5,
            is_checkpoint: false,
            completed: false,
            created_at: '2026-03-08T12:05:00',
            completed_at: null,
          },
        ],
      }),
      buildTask(),
    ],
    stats: {
      current_energy: 6,
      current_multiplier: 1.7,
      tasks_completed_today: 2,
    },
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
      current_task: 'Inbox cleanup',
    },
    plan: {},
    used_cache: false,
  })
  api.updateTask.mockResolvedValue({
    task: buildTask({
      status: 'doing',
    }),
    tasks: [
      buildTask({
        status: 'doing',
      }),
    ],
    stats: {
      current_energy: 6,
      current_multiplier: 1.7,
      tasks_completed_today: 2,
    },
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
      current_task: 'Quarterly report',
    },
  })
  api.updateTaskStep.mockResolvedValue({
    task: buildTask({
      steps: [
        {
          id: 301,
          task_id: 201,
          step_number: 1,
          text: 'Open the report doc and outline the first section.',
          duration_minutes: 5,
          is_checkpoint: false,
          completed: true,
          created_at: '2026-03-08T12:00:00',
          completed_at: '2026-03-08T12:07:00',
        },
        {
          id: 302,
          task_id: 201,
          step_number: 2,
          text: 'Draft the intro section.',
          duration_minutes: 10,
          is_checkpoint: false,
          completed: false,
          created_at: '2026-03-08T12:00:00',
          completed_at: null,
        },
      ],
    }),
    tasks: [
      buildTask({
        steps: [
          {
            id: 301,
            task_id: 201,
            step_number: 1,
            text: 'Open the report doc and outline the first section.',
            duration_minutes: 5,
            is_checkpoint: false,
            completed: true,
            created_at: '2026-03-08T12:00:00',
            completed_at: '2026-03-08T12:07:00',
          },
          {
            id: 302,
            task_id: 201,
            step_number: 2,
            text: 'Draft the intro section.',
            duration_minutes: 10,
            is_checkpoint: false,
            completed: false,
            created_at: '2026-03-08T12:00:00',
            completed_at: null,
          },
        ],
      }),
    ],
    stats: {
      current_energy: 6,
      current_multiplier: 1.7,
      tasks_completed_today: 2,
    },
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
      current_task: 'Inbox cleanup',
    },
  })
  api.startBodyDouble.mockResolvedValue({
    state: 'active',
    task: 'Deep work',
    remaining_minutes: 30,
  })
  api.setFocusGuardrail.mockResolvedValue({
    state: 'active',
    reason: 'School pickup',
    hard_stop_time: '2026-03-08T15:00:00',
  })
  api.pauseBodyDouble.mockResolvedValue({ state: 'paused', task: 'Deep work' })
  api.resumeBodyDouble.mockResolvedValue({ state: 'active', task: 'Deep work', remaining_minutes: 25 })
  api.endBodyDouble.mockResolvedValue({ state: 'idle' })
  api.clearFocusGuardrail.mockResolvedValue({ state: 'idle' })
  api.shutdownSession.mockResolvedValue({
    session_id: 'sess-001-a',
    messages: [
      {
        id: 99,
        session_id: 'sess-001-a',
        role: 'system',
        kind: 'system',
        text: 'Session saved. Work mode complete!',
        created_at: '2026-03-08T12:30:00',
      },
    ],
    tasks: [buildTask()],
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
      current_task: 'Inbox cleanup',
    },
    body_double: { state: 'idle' },
    focus_guardrail: { state: 'idle' },
  })
  globalThis.Notification = class NotificationMock {
    static permission = 'denied'
    static requestPermission = vi.fn().mockResolvedValue('denied')

    constructor() {}
  }
})

describe('App', () => {
  it('renders bootstrap data', async () => {
    const stream = new MockEventSource()
    api.createLiveStream.mockReturnValue(stream)

    render(<App />)

    expect(await screen.findByText('Executive Function Workspace')).toBeInTheDocument()
    expect(screen.getByText('How can I help?')).toBeInTheDocument()
    expect(screen.getByText('Quarterly report')).toBeInTheDocument()
    expect(screen.getByText('Email triage')).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Morning Activation' })).toBeInTheDocument()
  })

  it('submits a freeform chat turn', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.type(
      screen.getByPlaceholderText(/Talk to ADHD-OS like a coworker/i),
      'Help me start',
    )
    await user.click(screen.getByRole('button', { name: 'Send Message' }))

    await waitFor(() => {
      expect(api.sendChatTurn).toHaveBeenCalledWith({
        session_id: 'sess-001-a',
        text: 'Help me start',
      })
    })
    expect(await screen.findByText('Open the document and write the title.')).toBeInTheDocument()
  })

  it('switches sessions from the left rail', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())
    api.getBootstrap.mockImplementation(async (sessionId) => {
      if (sessionId === 'sess-002-b') {
        return buildBootstrap({
          active_session: { id: 'sess-002-b', last_active: '2026-03-07T20:00:00' },
          messages: [
            {
              id: 4,
              session_id: 'sess-002-b',
              role: 'assistant',
              kind: 'chat',
              text: 'Resumed the older session.',
              created_at: '2026-03-07T20:00:00',
            },
          ],
        })
      }
      return buildBootstrap()
    })

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.click(screen.getByRole('button', { name: /sess-002/i }))

    expect(await screen.findByText('Resumed the older session.')).toBeInTheDocument()
  })

  it('runs the morning activation quick action', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.type(screen.getByPlaceholderText('One priority per line'), 'Invoices')
    await user.click(screen.getByRole('button', { name: 'Send Guided Prompt' }))

    await waitFor(() => {
      expect(api.patchUserState).toHaveBeenCalled()
      expect(api.sendChatTurn).toHaveBeenCalled()
    })
  })

  it('captures a task into the board', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.type(screen.getByLabelText('Task to Capture'), 'Pay internet bill')
    await user.click(screen.getByRole('button', { name: 'Capture Task' }))

    await waitFor(() => {
      expect(api.createTask).toHaveBeenCalledWith({
        title: 'Pay internet bill',
        status: 'inbox',
        session_id: 'sess-001-a',
      })
    })
    expect(await screen.findByText('Pay internet bill')).toBeInTheDocument()
  })

  it('creates a checklist from the decompose quick action', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.click(screen.getByRole('button', { name: 'Decompose Task' }))
    await user.type(screen.getByPlaceholderText('What needs to be broken down?'), 'Draft launch email')
    await user.clear(screen.getByLabelText('Your Estimate (minutes)'))
    await user.type(screen.getByLabelText('Your Estimate (minutes)'), '50')
    await user.click(screen.getByRole('button', { name: 'Create Checklist' }))

    await waitFor(() => {
      expect(api.decomposeTask).toHaveBeenCalledWith({
        task: 'Draft launch email',
        estimated_minutes: 50,
        status: 'today',
        session_id: 'sess-001-a',
      })
    })
    expect(await screen.findByText('Draft launch email')).toBeInTheDocument()
    expect(screen.getByText(/Open the email draft and write the subject line/i)).toBeInTheDocument()
  })

  it('moves a task into doing and syncs the current-task field', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.selectOptions(screen.getByLabelText('Move Quarterly report to'), 'doing')

    await waitFor(() => {
      expect(api.updateTask).toHaveBeenCalledWith(201, { status: 'doing' })
    })
    expect(screen.getByLabelText('Current Task')).toHaveValue('Quarterly report')
  })

  it('toggles a checklist step', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.click(screen.getByLabelText('Toggle Quarterly report step 1'))

    await waitFor(() => {
      expect(api.updateTaskStep).toHaveBeenCalledWith(201, 301, { completed: true })
    })
  })

  it('saves provider settings from the dashboard', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.type(screen.getByLabelText('Google API Key'), 'google-test-key')
    await user.type(screen.getByLabelText('Anthropic API Key'), 'anthropic-test-key')
    await user.selectOptions(screen.getByLabelText('Model Mode'), 'quality')
    await user.click(screen.getByRole('button', { name: 'Save Settings' }))

    await waitFor(() => {
      expect(api.patchProviderSettings).toHaveBeenCalledWith({
        google_api_key: 'google-test-key',
        anthropic_api_key: 'anthropic-test-key',
        model_mode: 'quality',
        clear_google_api_key: false,
        clear_anthropic_api_key: false,
      })
    })
  })

  it('resumes a paused body-double session', async () => {
    const user = userEvent.setup()
    api.createLiveStream.mockReturnValue(new MockEventSource())
    api.getBootstrap.mockResolvedValue(buildBootstrap({
      body_double: {
        state: 'paused',
        task: 'Deep work',
        remaining_minutes: 25,
      },
    }))

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    await user.click(screen.getByRole('button', { name: 'Resume' }))

    await waitFor(() => {
      expect(api.resumeBodyDouble).toHaveBeenCalled()
    })
  })

  it('renders a live toast from the SSE stream', async () => {
    const stream = new MockEventSource()
    api.createLiveStream.mockReturnValue(stream)

    render(<App />)
    await screen.findByText('Executive Function Workspace')

    stream.emit('checkin_due', {
      event_type: 'checkin_due',
      timestamp: '2026-03-08T12:15:00',
      data: {
        task: 'Deep work',
        checkin_number: 1,
        total_checkins: 3,
      },
    })

    const matches = await screen.findAllByText(/Check-in 1\/3 for Deep work/i)
    expect(matches.length).toBeGreaterThan(0)
  })
})
