/** 纯前端数据层的公共类型：与全栈版后端返回的结构保持一致，换回后端时页面不用改。 */

export type EntryRow = {
  id: number
  status: string
  pending: boolean
  abnormal: boolean
  [field: string]: string | number | boolean
}

export type ModuleMeta = {
  key: string
  name: string
  entity: string
  desc: string
  fields: string[]
  statuses: string[]
  actions: string[]
  actionTargets: Record<string, string>
  metrics: string[]
}

export type PageResult = {
  items: EntryRow[]
  total: number
  page: number
  size: number
}

export type ActionResult = {
  ok: boolean
  message: string
  entry?: EntryRow
}

export type SignatureView = {
  review_id: string
  segment_id: string
  reviewer: string
  threshold_text: string
  conclusion: string
  signed_at: string
  valid?: boolean
  invalid_reason?: string
}

export type SegmentCoverage = {
  segment_id: string
  confidence: number
  confidence_text: string
  threshold: number
  required: boolean
  exempt: boolean
  signature_valid: boolean
  status: string
  valid_signature: SignatureView | null
  stale_signatures: SignatureView[]
  open_claim: { review_id: string; claimant: string; claimed_at: string; threshold_text: string } | null
  needs_review_by: string
  note: string
}

export type ReleaseReview = {
  ok: boolean
  message: string
  version_id?: string
  version_no?: string
  version_status?: string
  task_id?: string
  delivered?: boolean
  threshold: number
  previous_threshold?: number
  threshold_changed?: boolean
  required_count: number
  signed_count: number
  exempt_count: number
  coverage_complete: boolean
  segments: SegmentCoverage[]
  signatures: SignatureView[]
  missing_segments: string[]
  reviews_needed: { segment_id: string; reviewer: string; reason: string }[]
  items?: SegmentCoverage[]
  pending_count?: number
}

export type SignatureResult = {
  ok: boolean
  message: string
  counted: boolean
  signature_valid: boolean
  signed_count?: number
  required_count?: number
  review_id?: string
}

export type OverviewResult = {
  cards: { label: string; value: number }[]
  modules: { name: string; created: number; pending: number; abnormal: number }[]
}
