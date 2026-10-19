import type { Pick, Stats, Status } from './types'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(path, init)
  if (!res.ok) {
    let detail = res.statusText
    try {
      const body = await res.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // not JSON
    }
    throw new ApiError(res.status, detail)
  }
  return res.json() as Promise<T>
}

export const api = {
  status: () => request<Status>('/api/status'),
  picks: (status: 'open' | 'graded') => request<Pick[]>(`/api/picks?status=${status}`),
  stats: () => request<Stats>('/api/stats'),
  scan: () => request<{ result: string }>('/api/scan', { method: 'POST' }),
}
