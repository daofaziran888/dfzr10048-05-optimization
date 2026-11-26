import { request } from './client'
import { moduleMeta } from '@/data/modules'
import type {
  ActionResult,
  EntryRow,
  OverviewResult,
  PageResult,
  ReleaseReview,
  SignatureResult,
} from '@/data/types'

export { moduleMeta }

export async function listEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<PageResult> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}?${query}`)
  if (!response.ok) throw new Error('业务数据读取失败')
  return await response.json()
}

export async function createEntry(
  key: string,
  values: Record<string, string>,
): Promise<ActionResult> {
  const response = await request(`/api/${key}`, {
    method: 'POST',
    body: JSON.stringify({ values }),
  })
  return await response.json()
}

export async function runAction(
  key: string,
  id: number,
  action: string,
): Promise<ActionResult> {
  const response = await request(`/api/${key}/${id}/actions`, {
    method: 'POST',
    body: JSON.stringify({ action }),
  })
  return await response.json()
}

export async function downloadEntries(
  key: string,
  filters: Record<string, string> = {},
): Promise<void> {
  const query = new URLSearchParams(filters).toString()
  const response = await request(`/api/${key}/export?${query}`)
  if (!response.ok) throw new Error('业务数据导出失败')
  const url = URL.createObjectURL(await response.blob())
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `${key}.csv`
  document.body.appendChild(anchor)
  anchor.click()
  document.body.removeChild(anchor)
  URL.revokeObjectURL(url)
}

export async function loadOverview(): Promise<OverviewResult> {
  const response = await request('/api/overview')
  if (!response.ok) throw new Error('运营概览读取失败')
  return await response.json()
}

export async function loadReleaseReview(versionRef: string): Promise<ReleaseReview> {
  const response = await request(`/api/transcript_version/${encodeURIComponent(versionRef)}/release-review`)
  if (!response.ok) throw new Error('发布复核明细读取失败')
  return await response.json()
}

export async function publishVersion(
  versionRef: string,
  actor = '制作人',
): Promise<ReleaseReview> {
  const response = await request(`/api/transcript_version/${encodeURIComponent(versionRef)}/release`, {
    method: 'POST',
    body: JSON.stringify({ actor }),
  })
  if (!response.ok) throw new Error('发布复核请求失败')
  return await response.json()
}

export async function loadReviewTodo(versionRef: string): Promise<ReleaseReview> {
  const response = await request(`/api/confidence_review/todo?version=${encodeURIComponent(versionRef)}`)
  if (!response.ok) throw new Error('复核待办读取失败')
  return await response.json()
}

export async function claimSegment(
  segmentId: string,
  versionRef: string,
  reviewer: string,
): Promise<SignatureResult & { review_id?: string }> {
  const response = await request('/api/confidence_review/claim', {
    method: 'POST',
    body: JSON.stringify({ segment_id: segmentId, version: versionRef, reviewer }),
  })
  return await response.json()
}

export async function submitSignature(
  segmentId: string,
  versionRef: string,
  reviewer: string,
): Promise<SignatureResult> {
  const response = await request('/api/confidence_review/signature', {
    method: 'POST',
    body: JSON.stringify({ segment_id: segmentId, version: versionRef, reviewer }),
  })
  return await response.json()
}
