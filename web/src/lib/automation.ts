/**
 * 自动化后端（automation/ 里的 jobsinsight）的前端客户端。
 *
 * 数据文件（insights.json）是静态产出，任何部署方式下都能读到；
 * /api/* 只有在跑了 `python -m jobsinsight serve` 时才存在，
 * 所以这里把两者分开：读不到接口时页面依然完整，只是不显示控制按钮。
 *
 * 接口地址默认同源，可用 VITE_AUTOMATION_API 指向别处，
 * 写操作的令牌用 VITE_AUTOMATION_TOKEN 提供（对应 server.auth_token）。
 */

export type ScheduleMode = 'daily' | 'cron' | 'interval' | 'manual'

export interface RunDiff {
  new_jobs: number
  updated_jobs: number
  deleted_jobs: number
  unchanged_jobs: number
}

export interface AutomationInsights {
  generated_at: string
  provider: string
  model: string
  schedule: {
    mode: ScheduleMode
    description: string
    timezone: string
    next_run: string
  }
  run: { total_jobs: number } & Partial<RunDiff>
  /** llm = 模型撰写；rules = 由统计规则生成（未配置 LLM 或调用失败时） */
  source?: 'llm' | 'rules'
  headline?: string
  summary?: string
  highlights?: string[]
  hot_skills?: string[]
  advice?: string[]
}

export interface ScheduleInfo {
  enabled: boolean
  mode: ScheduleMode
  timezone: string
  daily_times: string[]
  cron: string
  interval_minutes: number
  description: string
  cron_equivalent: string
  next_runs: string[]
}

export interface RunReport {
  run_id: string
  trigger: string
  started_at: string
  finished_at: string
  duration_seconds: number
  status: 'success' | 'partial' | 'failed' | 'skipped'
  collected: number
  kept: number
  dropped_low_relevance: number
  diff: Partial<RunDiff>
  insights_generated: boolean
  dry_run: boolean
  errors: string[]
}

export interface AutomationStatus {
  now: string
  running: boolean
  scheduler_active: boolean
  schedule: ScheduleInfo
  llm: {
    enabled: boolean
    provider: string
    model: string
    api_key_configured: boolean
    enrich_jobs: boolean
    generate_insights: boolean
  }
  sources: Array<{ name: string; type: string; enabled: boolean }>
  last_run: RunReport | null
}

export type ScheduleUpdate = Partial<
  Pick<ScheduleInfo, 'enabled' | 'mode' | 'timezone' | 'daily_times' | 'cron' | 'interval_minutes'>
>

const API_BASE = (import.meta.env.VITE_AUTOMATION_API ?? '').replace(/\/$/, '')
const API_TOKEN = import.meta.env.VITE_AUTOMATION_TOKEN ?? ''

export class AutomationApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body) headers.set('Content-Type', 'application/json')
  if (API_TOKEN) headers.set('Authorization', `Bearer ${API_TOKEN}`)

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const text = await response.text()
  const payload = text ? JSON.parse(text) : null

  if (!response.ok) {
    throw new AutomationApiError(payload?.error ?? `请求失败（HTTP ${response.status}）`)
  }
  return payload as T
}

/** 静态产出文件，不需要后端进程。 */
export async function fetchInsights(): Promise<AutomationInsights | null> {
  try {
    const response = await fetch('/data/insights.json', { cache: 'no-store' })
    return response.ok ? ((await response.json()) as AutomationInsights) : null
  } catch {
    return null
  }
}

export const fetchStatus = () => request<AutomationStatus>('/api/status')

export const triggerRun = (options: { trigger?: string; limit?: number } = {}) =>
  request<RunReport>('/api/runs', {
    method: 'POST',
    body: JSON.stringify({ trigger: 'web', ...options }),
  })

export const updateSchedule = (updates: ScheduleUpdate) =>
  request<ScheduleInfo>('/api/schedule', { method: 'PUT', body: JSON.stringify(updates) })

export const askLLM = (question: string) =>
  request<{ question: string; answer: string }>('/api/llm/ask', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })

/** 把 ISO 时间显示成本地可读格式；拿不到就原样返回。 */
export function formatMoment(value: string | undefined | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}
