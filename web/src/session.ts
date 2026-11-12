import { TOKEN, postJSON } from './api'

const SESSION_ID =
  typeof crypto !== 'undefined' && 'randomUUID' in crypto
    ? crypto.randomUUID()
    : `ck-${Date.now()}-${Math.random().toString(36).slice(2)}`

const HEARTBEAT_MS = 20_000

let started = false

function openSession(): void {
  void postJSON('/api/session/open', { id: SESSION_ID }).catch(() => {})
}

function closeSession(): void {
  const url =
    '/api/session/close?id=' +
    encodeURIComponent(SESSION_ID) +
    '&token=' +
    encodeURIComponent(TOKEN)
  if (navigator.sendBeacon) {
    navigator.sendBeacon(url)
    return
  }
  void postJSON('/api/session/close', { id: SESSION_ID }).catch(() => {})
}

export function startSession(): void {
  if (started) return
  started = true
  openSession()
  window.setInterval(openSession, HEARTBEAT_MS)
  window.addEventListener('pagehide', closeSession)
  window.addEventListener('beforeunload', closeSession)
  window.addEventListener('pageshow', openSession)
  window.addEventListener('online', openSession)
}

window.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible') openSession()
})
