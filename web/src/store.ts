import { reactive } from 'vue'
import { TOKEN, api, postJSON, withToken } from './api'
import type { AppState } from './types'

interface WriteResponse {
  ok: boolean
  state: AppState
}

export interface TaskEditPayload {
  task_id: string
  name: string
  description: string
  how_to: string[]
  done_criteria: string
  priority: string
  checkin_mode: string
  checkin_goal: number
}

export interface ApplicationPayload {
  company: string
  role: string
  channel: string
  status: string
}

interface Store {
  state: AppState | null
  loading: boolean
  busy: boolean
  error: string
  sseError: string
  toast: string
  closed: boolean
}

export const store = reactive<Store>({
  state: null,
  loading: false,
  busy: false,
  error: '',
  sseError: '',
  toast: '',
  closed: false,
})

let toastTimer: number | undefined
let loadingState = false
let events: EventSource | null = null

export function showToast(message: string): void {
  store.toast = message
  if (toastTimer) window.clearTimeout(toastTimer)
  toastTimer = window.setTimeout(() => {
    store.toast = ''
  }, 2200)
}

export async function loadState(): Promise<void> {
  if (loadingState) return
  loadingState = true
  store.loading = true
  try {
    store.state = await api<AppState>('/api/state')
    store.error = ''
  } catch (error) {
    store.error = (error as Error).message
  } finally {
    store.loading = false
    loadingState = false
  }
}

export async function checkin(taskId: string, status: string, amount = 0): Promise<void> {
  if (store.busy) return
  store.busy = true
  try {
    const data = await postJSON<WriteResponse>('/api/checkin', {
      task_id: taskId,
      status,
      amount,
    })
    store.state = data.state
    store.error = ''
    showToast('已同步到档案')
  } catch (error) {
    showToast((error as Error).message)
  } finally {
    store.busy = false
  }
}

export async function saveTask(payload: TaskEditPayload): Promise<boolean> {
  try {
    const data = await postJSON<WriteResponse>('/api/task', payload)
    store.state = data.state
    store.error = ''
    showToast('任务已保存')
    return true
  } catch (error) {
    showToast((error as Error).message)
    return false
  }
}

export async function addApplication(payload: ApplicationPayload): Promise<boolean> {
  try {
    const data = await postJSON<WriteResponse>('/api/application', payload)
    store.state = data.state
    store.error = ''
    showToast('投递已登记')
    return true
  } catch (error) {
    showToast((error as Error).message)
    return false
  }
}

export function connectEvents(): void {
  if (!window.EventSource || events) return
  events = new EventSource('/api/events?token=' + encodeURIComponent(TOKEN))
  events.onopen = () => {
    store.sseError = ''
  }
  events.onmessage = () => {
    void loadState()
  }
  events.onerror = () => {
    store.sseError = '实时连接中断，正在自动重连；也可以点击「刷新」手动更新。'
  }
}

export function assetUrl(path: string | undefined): string {
  return withToken(path || '')
}

export async function shutdown(): Promise<void> {
  try {
    await postJSON('/api/shutdown', {})
  } catch {
    // 服务可能已经退出，按关闭处理
  }
  store.closed = true
  window.setTimeout(() => {
    try {
      window.close()
    } catch {
      // 浏览器不允许脚本关闭非脚本打开的页面时，保留提示页
    }
  }, 80)
}
