import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { beforeEach, describe, expect, it, vi } from 'vitest'

vi.mock('./api', () => ({
  clearFocusGuardrail: vi.fn(),
  createLiveStream: vi.fn(),
  endBodyDouble: vi.fn(),
  getBootstrap: vi.fn(),
  getHistory: vi.fn(),
  patchUserState: vi.fn(),
  pauseBodyDouble: vi.fn(),
  resumeBodyDouble: vi.fn(),
  sendChatTurn: vi.fn(),
  setFocusGuardrail: vi.fn(),
  shutdownSession: vi.fn(),
  startBodyDouble: vi.fn(),
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
    recent_sessions: [
      { id: 'sess-001-a', last_active: '2026-03-08T12:00:00' },
      { id: 'sess-002-b', last_active: '2026-03-07T20:00:00' },
    ],
    provider_status: {
      ready: true,
      model_mode: 'production',
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
      id: 11,
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
    user_state: {
      energy_level: 6,
      dynamic_multiplier: 1.7,
    },
    body_double: { state: 'idle' },
    focus_guardrail: { state: 'idle' },
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
    user_state: { energy_level: 6, dynamic_multiplier: 1.7 },
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
