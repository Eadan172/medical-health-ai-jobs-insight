import { useCallback, useEffect, useState } from 'react'

import {
  AutomationApiError,
  fetchInsights,
  fetchStatus,
  triggerRun,
  updateSchedule,
  type AutomationInsights,
  type AutomationStatus,
  type RunReport,
  type ScheduleUpdate,
} from '@/lib/automation'

export interface UseAutomation {
  /** 每日洞察与调度信息，来自静态产出文件。 */
  insights: AutomationInsights | null
  /** 控制接口在线时的实时状态。 */
  status: AutomationStatus | null
  /** 控制接口是否可用（决定是否显示运行/改时间按钮）。 */
  online: boolean
  running: boolean
  error: string | null
  lastRun: RunReport | null
  runNow: () => Promise<RunReport | null>
  changeSchedule: (updates: ScheduleUpdate) => Promise<boolean>
  refresh: () => Promise<void>
}

/**
 * 汇总自动化状态。控制接口不可用时静默降级：`online` 为 false，
 * 页面只展示静态洞察，不弹错误。
 */
export function useAutomation(pollIntervalMs = 60_000): UseAutomation {
  const [insights, setInsights] = useState<AutomationInsights | null>(null)
  const [status, setStatus] = useState<AutomationStatus | null>(null)
  const [online, setOnline] = useState(false)
  const [running, setRunning] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [lastRun, setLastRun] = useState<RunReport | null>(null)

  const refresh = useCallback(async () => {
    setInsights(await fetchInsights())
    try {
      const next = await fetchStatus()
      setStatus(next)
      setOnline(true)
      setRunning(next.running)
      if (next.last_run) setLastRun(next.last_run)
    } catch {
      setOnline(false)
      setStatus(null)
    }
  }, [])

  useEffect(() => {
    void refresh()
    if (pollIntervalMs <= 0) return
    const timer = window.setInterval(() => void refresh(), pollIntervalMs)
    return () => window.clearInterval(timer)
  }, [refresh, pollIntervalMs])

  const runNow = useCallback(async () => {
    setRunning(true)
    setError(null)
    try {
      const report = await triggerRun({ trigger: 'web' })
      setLastRun(report)
      await refresh()
      return report
    } catch (cause) {
      setError(cause instanceof AutomationApiError ? cause.message : '无法连接自动化接口')
      return null
    } finally {
      setRunning(false)
    }
  }, [refresh])

  const changeSchedule = useCallback(
    async (updates: ScheduleUpdate) => {
      setError(null)
      try {
        const schedule = await updateSchedule(updates)
        setStatus((current) => (current ? { ...current, schedule } : current))
        return true
      } catch (cause) {
        setError(cause instanceof AutomationApiError ? cause.message : '修改运行时间失败')
        return false
      }
    },
    [],
  )

  return { insights, status, online, running, error, lastRun, runNow, changeSchedule, refresh }
}
