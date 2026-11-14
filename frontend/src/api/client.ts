// 统一的 HTTP 客户端：所有后端调用都走 /api（开发时 Vite 代理到 8000，演示时同源）。
export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, url: string, body?: unknown, isForm = false): Promise<T> {
  const init: RequestInit = { method, headers: {} }
  if (body !== undefined) {
    if (isForm) init.body = body as FormData
    else {
      ;(init.headers as Record<string, string>)['Content-Type'] = 'application/json'
      init.body = JSON.stringify(body)
    }
  }
  const resp = await fetch('/api' + url, init)
  if (!resp.ok) {
    let msg = resp.statusText
    try {
      const j = await resp.json()
      msg = typeof j.detail === 'string' ? j.detail : JSON.stringify(j.detail ?? j)
    } catch {
      /* ignore */
    }
    throw new ApiError(resp.status, msg)
  }
  const ct = resp.headers.get('content-type') || ''
  return (ct.includes('application/json') ? resp.json() : resp.text()) as Promise<T>
}

export const api = {
  get: <T = any>(url: string) => request<T>('GET', url),
  post: <T = any>(url: string, body?: unknown) => request<T>('POST', url, body ?? {}),
  put: <T = any>(url: string, body?: unknown) => request<T>('PUT', url, body ?? {}),
  upload: <T = any>(url: string, form: FormData) => request<T>('POST', url, form, true),
}
