/** 发布复核的纯前端呈现口径：后端给判定，前端只负责把结论翻译成人能读的提示。 */
import type { ReleaseReview, SegmentCoverage } from '@/data/types'

export const RELEASE_CAPABLE_MODULES = ['transcript_version'] as const
export const TODO_CAPABLE_MODULES = ['confidence_review'] as const

export function supportsRelease(moduleKey: string): boolean {
  return (RELEASE_CAPABLE_MODULES as readonly string[]).includes(moduleKey)
}

export function supportsTodo(moduleKey: string): boolean {
  return (TODO_CAPABLE_MODULES as readonly string[]).includes(moduleKey)
}

/** 版本行里的发布入口只在有版本号时可用。 */
export function versionRefOf(row: Record<string, unknown>): string {
  return String(row['版本号'] ?? '')
}

/** 默认选中还在流转中的版本：制作人先看过渡中/草稿，再看已交付。 */
export function defaultReviewVersion(rows: Record<string, unknown>[]): string {
  const preferred = rows.find((row) => row.status === '过渡中')
    ?? rows.find((row) => row.status === '草稿')
    ?? rows[0]
  return preferred ? versionRefOf(preferred) : ''
}

export function coverageTone(item: SegmentCoverage): string {
  if (item.exempt) return 'muted'
  if (item.signature_valid) return 'ok'
  if (item.status === '需重审') return 'danger'
  return 'warn'
}

export function coverageLabel(item: SegmentCoverage): string {
  if (item.exempt) return '免签'
  if (item.signature_valid) return '签名有效'
  if (item.status === '需重审') return '签名无效·需重审'
  if (item.status === '已领取') return '已领取待签'
  return '待领取'
}

/** 阈值变化提示：旧版本展示自己的阈值，不被新版本覆盖。 */
export function thresholdNote(review: ReleaseReview): string {
  const base = `生效阈值 ${review.threshold.toFixed(2)}`
  if (review.threshold_changed && review.previous_threshold != null) {
    return `${base}（由 ${review.previous_threshold.toFixed(2)} 上调）`
  }
  return base
}

/** 发布按钮的可点状态与原因。 */
export function publishBlockReason(review: ReleaseReview | null): string {
  if (!review) return '请先加载发布复核明细'
  if (review.coverage_complete) return ''
  const missing = review.missing_segments.length
    ? `仍缺 ${review.missing_segments.join('、')} 的有效签名`
    : '覆盖校验未通过'
  return missing
}

/** 领取按钮：该段已在别人手里时不放开领取，避免替别人签。 */
export function claimLabel(item: SegmentCoverage, reviewer: string): string {
  if (item.signature_valid) return ''
  if (!item.open_claim) return '领取'
  return item.open_claim.claimant === reviewer ? '继续签名' : '已被领取'
}

export function canClaim(item: SegmentCoverage, reviewer: string): boolean {
  if (item.signature_valid) return false
  return !item.open_claim || item.open_claim.claimant === reviewer
}

export function canSign(item: SegmentCoverage, reviewer: string): boolean {
  if (item.signature_valid) return false
  return !item.open_claim || item.open_claim.claimant === reviewer
}
