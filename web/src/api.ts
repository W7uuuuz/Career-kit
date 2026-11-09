export const TOKEN = new URLSearchParams(window.location.search).get('token') || ''

export function withToken(url: string): string {
  if (!url) return ''
  if (!TOKEN) return url
  return url + (url.includes('?') ? '&' : '?') + 'token=' + encodeURIComponent(TOKEN)
}

const ERROR_MESSAGES: Record<string, string> = {
  'invalid token': '访问令牌无效，请从桌面快捷方式重新打开控制台',
  'asset not found': '资产文件不存在',
  'asset outside root': '资产路径不在允许范围内',
  'not found': '接口不存在',
  'task_id required': '缺少任务 ID',
  'invalid json': '请求数据格式错误',
}

function readError(data: unknown): string {
  if (data && typeof data === 'object') {
    const record = data as Record<string, unknown>
    const message = record.message ?? record.error
    if (typeof message === 'string' && message.trim()) {
      const text = message.trim()
      return ERROR_MESSAGES[text] || text
    }
  }
  return '请求失败'
}

export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers = new Headers(init.headers)
  headers.set('X-CK-Token', TOKEN)
  const response = await fetch(path, { ...init, headers })
  let data: unknown = null
  try {
    data = await response.json()
  } catch {
    data = null
  }
  if (!response.ok) {
    throw new Error(readError(data) || `请求失败（${response.status}）`)
  }
  return data as T
}

export function postJSON<T>(path: string, body: unknown): Promise<T> {
  return api<T>(path, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body ?? {}),
  })
}
