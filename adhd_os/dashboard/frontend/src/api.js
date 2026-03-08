const API_BASE = import.meta.env.VITE_API_URL || 'http://localhost:8000/api'

async function requestJson(path, options = {}) {
  const response = await fetch(`${API_BASE}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers || {}),
    },
    ...options,
  })

  if (!response.ok) {
    let detail = response.statusText
    try {
      const payload = await response.json()
      detail = payload.detail || detail
    } catch {
      // Ignore JSON parse failures and use the status text fallback.
    }
    throw new Error(detail)
  }

  if (response.status === 204) {
    return null
  }

  return response.json()
}

export function getBootstrap(sessionId) {
  const query = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : ''
  return requestJson(`/bootstrap${query}`)
}

export function getHistory() {
  return requestJson('/history')
}

export function sendChatTurn(payload) {
  return requestJson('/chat/turn', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function patchUserState(payload) {
  return requestJson('/user-state', {
    method: 'PATCH',
    body: JSON.stringify(payload),
  })
}

export function shutdownSession(sessionId) {
  return requestJson(`/sessions/${encodeURIComponent(sessionId)}/shutdown`, {
    method: 'POST',
  })
}

export function startBodyDouble(payload) {
  return requestJson('/body-double/start', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function pauseBodyDouble(payload) {
  return requestJson('/body-double/pause', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function endBodyDouble(payload = { completed: true }) {
  return requestJson('/body-double/end', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function setFocusGuardrail(payload) {
  return requestJson('/focus-guardrail', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function clearFocusGuardrail() {
  return requestJson('/focus-guardrail', {
    method: 'DELETE',
  })
}

export function createLiveStream() {
  return new EventSource(`${API_BASE}/live`)
}

export { API_BASE }
