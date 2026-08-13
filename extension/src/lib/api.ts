// 后端 API 客户端（Phase 2 后端 REST：/api/v1/{health,settings,jobs,tasks,conversations,...}）。
// 职责：统一 fetch 封装 + 超时 + 非 2xx 抛 ApiError，供 stores 调用，组件不直接 fetch。
// 原理：extension 页面跨源 fetch 依赖 manifest host_permissions（localhost:8000 已加）；
//       非 2xx 统一抛错，由调用方决定回退策略（文档 §51：UI 不猜测后端状态）。
const DEFAULT_API_BASE = "http://localhost:8000/api/v1"
const REQUEST_TIMEOUT_MS = 5000

/** 后端返回的领域错误（FastAPI 全局 handler 的 {"detail": ...}） */
export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.name = "ApiError"
    this.status = status
  }
}

async function request<T>(path: string, init: RequestInit = {}, base = DEFAULT_API_BASE): Promise<T> {
  const controller = new AbortController()
  const timer = setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)
  try {
    const res = await fetch(`${base}${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...(init.headers ?? {}) },
      signal: controller.signal,
    })
    if (!res.ok) {
      // 尝试解析 FastAPI detail；失败则回退 statusText
      let detail = res.statusText
      try {
        const body = (await res.json()) as { detail?: unknown }
        detail = typeof body.detail === "string" ? body.detail : JSON.stringify(body.detail ?? body)
      } catch {
        /* 非 JSON 响应体，保留 statusText */
      }
      throw new ApiError(res.status, detail)
    }
    return (await res.json()) as T
  } finally {
    clearTimeout(timer)
  }
}

export function apiGet<T>(path: string): Promise<T> {
  return request<T>(path)
}

export function apiPut<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "PUT", body: JSON.stringify(body) })
}

export function apiPost<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: "POST", body: JSON.stringify(body) })
}

export function apiDelete<T>(path: string): Promise<T> {
  return request<T>(path, { method: "DELETE" })
}
