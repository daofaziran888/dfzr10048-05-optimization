<template>
  <section class="page" :data-module="meta.key">
    <header class="page-head">
      <div>
        <h2>{{ meta.name }}</h2>
        <p class="page-desc">{{ meta.desc }}</p>
      </div>
      <div class="page-actions">
        <button class="btn primary" data-testid="open-create" type="button" @click="openCreate">
          登记{{ meta.entity }}
        </button>
        <button class="btn" data-testid="export" type="button" @click="exportRows">
          导出{{ meta.name }}清单
        </button>
      </div>
    </header>

    <div class="stat-row">
      <article v-for="item in stats" :key="item.label" class="stat-card">
        <span class="stat-label">{{ item.label }}</span>
        <strong class="stat-value">{{ item.value }}</strong>
      </article>
    </div>

    <p class="status-legend">
      <span v-for="item in statusSummary" :key="item.status" class="legend-item">
        {{ item.status }}：{{ item.count }}
      </span>
    </p>

    <section v-if="isReleaseView" class="review-panel" data-testid="release-panel">
      <header class="review-head">
        <div>
          <h3>发布复核明细</h3>
          <p class="page-desc">
            按所选版本自己的生效阈值核对低置信段与签名；每段只认对该段和该版本的有效签名。
          </p>
        </div>
        <div class="review-controls">
          <label>
            <span>版本</span>
            <select v-model="releaseVersion" data-testid="release-version" @change="loadRelease">
              <option v-for="row in rows" :key="String(row.id)" :value="String(row['版本号'])">
                {{ row['版本号'] }}（{{ row['版本编号'] }}）
              </option>
            </select>
          </label>
          <button
            class="btn primary"
            data-testid="publish"
            type="button"
            :disabled="releasing || !releaseVersion || Boolean(releaseReview?.delivered)"
            @click="publishSelected"
          >
            {{ releaseReview?.delivered ? '已交付' : releasing ? '发布中…' : '发布版本' }}
          </button>
        </div>
      </header>

      <p v-if="releaseReview" class="review-summary" data-testid="release-summary">
        <strong>{{ releaseReview.delivered ? '已交付' : releaseReview.coverage_complete ? '可发布' : '不可发布' }}</strong>
        ·
        {{ thresholdNote(releaseReview) }}
        ·
        已审 {{ releaseReview.signed_count }}/{{ releaseReview.required_count }} 个低置信段
        <span v-if="!releaseReview.coverage_complete" class="warn-text">
          （{{ publishBlockReason(releaseReview) }}）
        </span>
        <span v-else-if="releaseReview.delivered" class="muted-text">
          （该版本已按自己的阈值交付，后续版本调整不影响这里的记录）
        </span>
      </p>
      <p v-if="reviewMessage" class="review-message" data-testid="review-message">{{ reviewMessage }}</p>

      <table v-if="releaseReview" class="data-table review-table">
        <thead>
          <tr>
            <th>分段</th><th>段置信度</th><th>生效阈值</th><th>签名判定</th>
            <th>有效签名</th><th>失效签名</th><th>领取</th><th>需谁重审</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in releaseReview.segments"
            :key="item.segment_id"
            :data-testid="`release-segment-${item.segment_id}`"
            :data-state="item.status"
          >
            <td>{{ item.segment_id }}</td>
            <td>{{ item.confidence_text }}</td>
            <td>{{ item.threshold.toFixed(2) }}</td>
            <td :class="`tone-${coverageTone(item)}`">{{ coverageLabel(item) }}</td>
            <td>
              <span v-if="item.valid_signature">
                {{ item.valid_signature.reviewer }} 按 {{ item.valid_signature.threshold_text }} 签署
              </span>
              <span v-else class="muted-text">—</span>
            </td>
            <td>
              <span v-for="sig in item.stale_signatures" :key="sig.review_id" class="stale-tag">
                {{ sig.reviewer }} 按 {{ sig.threshold_text }} 签署（已失效）
              </span>
              <span v-if="!item.stale_signatures.length" class="muted-text">—</span>
            </td>
            <td>
              <span v-if="item.open_claim">{{ item.open_claim.claimant }}（{{ item.open_claim.threshold_text }}）</span>
              <span v-else class="muted-text">—</span>
            </td>
            <td>{{ item.exempt ? '—' : item.needs_review_by || '—' }}</td>
          </tr>
        </tbody>
      </table>
    </section>

    <section v-if="isTodoView" class="review-panel" data-testid="todo-panel">
      <header class="review-head">
        <div>
          <h3>复核待办</h3>
          <p class="page-desc">
            待办只列仍缺有效签名的段；从待办领取后按领取时阈值签名，旧阈值领取的签名会被判定失效。
          </p>
        </div>
        <div class="review-controls">
          <label>
            <span>版本</span>
            <select v-model="todoVersion" data-testid="todo-version" @change="loadTodo">
              <option v-for="version in versionOptions" :key="version" :value="version">{{ version }}</option>
            </select>
          </label>
          <label>
            <span>复核员</span>
            <input v-model="reviewer" data-testid="todo-reviewer" />
          </label>
        </div>
      </header>

      <p v-if="todo" class="review-summary" data-testid="todo-summary">
        <strong>{{ todo.pending_count ? `待处理 ${todo.pending_count} 段` : '待办已清零' }}</strong>
        ·
        生效阈值 {{ todo.threshold.toFixed(2) }}
        ·
        已审 {{ todo.signed_count }}/{{ todo.required_count }}
      </p>
      <p v-if="reviewMessage" class="review-message" data-testid="review-message">{{ reviewMessage }}</p>

      <table v-if="todo" class="data-table review-table">
        <thead>
          <tr>
            <th>分段</th><th>段置信度</th><th>签名判定</th><th>有效签名</th>
            <th>失效签名</th><th>领取人</th><th>需谁重审</th><th>操作</th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="item in todo.items"
            :key="item.segment_id"
            :data-testid="`todo-segment-${item.segment_id}`"
            :data-state="item.status"
          >
            <td>{{ item.segment_id }}</td>
            <td>{{ item.confidence_text }}</td>
            <td :class="`tone-${coverageTone(item)}`">{{ coverageLabel(item) }}</td>
            <td>
              <span v-if="item.valid_signature">
                {{ item.valid_signature.reviewer }} 按 {{ item.valid_signature.threshold_text }} 签署
              </span>
              <span v-else class="muted-text">—</span>
            </td>
            <td>
              <span v-for="sig in item.stale_signatures" :key="sig.review_id" class="stale-tag">
                {{ sig.reviewer }} 按 {{ sig.threshold_text }} 签署（已失效）
              </span>
              <span v-if="!item.stale_signatures.length" class="muted-text">—</span>
            </td>
            <td>{{ item.open_claim?.claimant || '—' }}</td>
            <td>{{ item.needs_review_by || '—' }}</td>
            <td class="row-actions">
              <button
                v-if="canClaim(item, reviewer)"
                class="link"
                type="button"
                :data-testid="`claim-${item.segment_id}`"
                @click="claimItem(item)"
              >
                {{ claimLabel(item, reviewer) }}
              </button>
              <button
                v-if="canSign(item, reviewer)"
                class="link"
                type="button"
                :data-testid="`sign-${item.segment_id}`"
                @click="signItem(item)"
              >
                提交签名
              </button>
              <span
                v-if="item.open_claim && !item.signature_valid && item.open_claim.claimant !== reviewer"
                class="muted-text"
              >
                等待 {{ item.open_claim.claimant }} 签名
              </span>
            </td>
          </tr>
          <tr v-if="!todo.items?.length">
            <td colspan="8" class="empty-state">该版本没有需签名的低置信段</td>
          </tr>
        </tbody>
      </table>
    </section>

    <form class="filter-bar" @submit.prevent="reload">
      <label v-for="field in filterFields" :key="field" class="filter-item">
        <span>{{ field }}</span>
        <input v-model="filters[field]" :data-testid="`filter-${field}`" :placeholder="`按${field}检索`" />
      </label>
      <button class="btn" data-testid="query" type="submit">查询</button>
      <button class="btn ghost" data-testid="reset" type="button" @click="resetFilters">重置条件</button>
    </form>

    <table class="data-table">
      <thead>
        <tr>
          <th v-for="column in meta.fields" :key="column">{{ column }}</th>
          <th>当前状态</th>
          <th>可执行动作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="row in rows" :key="String(row.id)" :data-testid="`row-${row.id}`" :data-status="String(row.status)">
          <td v-for="column in meta.fields" :key="column">{{ row[column] ?? '—' }}</td>
          <td>{{ row.status }}</td>
          <td class="row-actions">
            <button
              v-for="action in meta.actions"
              :key="action"
              class="link"
              type="button"
              :data-testid="`action-${row.id}-${action}`"
              @click="runAction(action, row)"
            >
              {{ action }}
            </button>
          </td>
        </tr>
        <tr v-if="!rows.length">
          <td :colspan="meta.fields.length + 2" class="empty-state">
            暂无{{ meta.name }}数据，可先登记{{ meta.entity }}
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="showCreate" class="modal-backdrop" data-testid="create-modal">
      <form class="modal" @submit.prevent="submitCreate">
        <h3>登记{{ meta.entity }}</h3>
        <label v-for="field in meta.fields" :key="field" class="create-field">
          <span>{{ field }}</span>
          <input v-model="createValues[field]" :data-testid="`create-${field}`" required />
        </label>
        <div class="page-actions">
          <button class="btn" type="button" @click="showCreate = false">取消</button>
          <button class="btn primary" data-testid="submit-create" type="submit" :disabled="creating">
            {{ creating ? '提交中…' : '确认登记' }}
          </button>
        </div>
      </form>
    </div>

    <footer class="page-foot">
      <span>共 {{ total }} 条{{ meta.name }}记录</span>
      <span v-if="errorMessage" class="error-text">{{ errorMessage }}</span>
    </footer>
  </section>
</template>

<script setup lang="ts">
import { computed, onMounted, ref, watch } from 'vue'

import {
  claimSegment,
  createEntry,
  downloadEntries,
  listEntries,
  loadReleaseReview,
  loadReviewTodo,
  moduleMeta,
  publishVersion,
  runAction as applyAction,
  submitSignature,
} from '@/api/backend-service'
import type { EntryRow, ReleaseReview, SegmentCoverage } from '@/data/types'
import {
  canClaim,
  canSign,
  claimLabel,
  coverageLabel,
  coverageTone,
  defaultReviewVersion,
  publishBlockReason,
  supportsRelease,
  supportsTodo,
  thresholdNote,
} from '@/domain/release_review'

const props = defineProps<{ moduleKey: string }>()
// 路由参数变化时 Vue 会复用同一个组件实例，模块元数据必须跟着 props 走。
const meta = computed(() => moduleMeta(props.moduleKey))
const rows = ref<EntryRow[]>([])
const total = ref(0)
const errorMessage = ref('')
const filters = ref<Record<string, string>>({})
const filterFields = computed(() => meta.value.fields.slice(0, 3))
const showCreate = ref(false)
const creating = ref(false)
const createValues = ref<Record<string, string>>({})

const isReleaseView = computed(() => supportsRelease(props.moduleKey))
const isTodoView = computed(() => supportsTodo(props.moduleKey))
const releaseVersion = ref('')
const todoVersion = ref('')
const allVersions = ref<EntryRow[]>([])
const reviewer = ref('reviewer_01')
const releaseReview = ref<ReleaseReview | null>(null)
const todo = ref<ReleaseReview | null>(null)
const releasing = ref(false)
const reviewMessage = ref('')

const versionOptions = computed(() => {
  const source = isReleaseView.value ? rows.value : allVersions.value
  return Array.from(
    new Set(source.map((row) => String(row['版本号'] ?? '')).filter(Boolean)),
  )
})

const stats = computed(() => [
  { label: meta.value.metrics[0], value: total.value },
  {
    label: meta.value.metrics[1],
    value: rows.value.filter((row) => row.status === meta.value.statuses[1]).length,
  },
  {
    label: meta.value.metrics[2],
    value: rows.value.filter(
      (row) => row.status === meta.value.statuses[meta.value.statuses.length - 1],
    ).length,
  },
])
const statusSummary = computed(() =>
  meta.value.statuses.map((status) => ({
    status,
    count: rows.value.filter((row) => String(row.status) === status).length,
  })),
)

function resetFilters() {
  filters.value = {}
  void reload()
}

async function exportRows() {
  errorMessage.value = ''
  try {
    await downloadEntries(meta.value.key, filters.value)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '导出失败'
  }
}

function openCreate() {
  createValues.value = Object.fromEntries(meta.value.fields.map((field) => [field, '']))
  errorMessage.value = ''
  showCreate.value = true
}

async function submitCreate() {
  creating.value = true
  errorMessage.value = ''
  try {
    const result = await createEntry(meta.value.key, createValues.value)
    if (!result.ok) throw new Error(result.message)
    showCreate.value = false
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '登记失败'
  } finally {
    creating.value = false
  }
}

async function runAction(action: string, row: EntryRow) {
  errorMessage.value = ''
  try {
    const result = await applyAction(meta.value.key, Number(row.id), action)
    if (!result.ok) throw new Error(result.message)
    await reload()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '操作失败'
  }
}

async function reload() {
  errorMessage.value = ''
  try {
    const payload = await listEntries(meta.value.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
    await ensureReviewSelection()
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '业务列表读取失败'
  }
}

async function ensureReviewSelection() {
  if (isReleaseView.value) {
    if (!releaseVersion.value || !rows.value.some((row) => String(row['版本号']) === releaseVersion.value)) {
      releaseVersion.value = defaultReviewVersion(rows.value)
    }
    if (releaseVersion.value) await loadRelease()
    return
  }
  if (isTodoView.value) {
    // 待办按版本核对，需要先拿到转写版本清单里的版本号。
    if (!allVersions.value.length) {
      try {
        const payload = await listEntries('transcript_version', {})
        allVersions.value = payload.items
      } catch {
        allVersions.value = []
      }
    }
    if (!todoVersion.value || !versionOptions.value.includes(todoVersion.value)) {
      todoVersion.value = versionOptions.value[0] ?? ''
    }
    if (todoVersion.value) await loadTodo()
  }
}

async function loadRelease() {
  if (!releaseVersion.value) {
    releaseReview.value = null
    return
  }
  reviewMessage.value = ''
  try {
    releaseReview.value = await loadReleaseReview(releaseVersion.value)
  } catch (error) {
    releaseReview.value = null
    errorMessage.value = error instanceof Error ? error.message : '发布复核明细读取失败'
  }
}

async function loadTodo() {
  if (!todoVersion.value) {
    todo.value = null
    return
  }
  reviewMessage.value = ''
  try {
    todo.value = await loadReviewTodo(todoVersion.value)
  } catch (error) {
    todo.value = null
    errorMessage.value = error instanceof Error ? error.message : '复核待办读取失败'
  }
}

async function publishSelected() {
  if (!releaseVersion.value) return
  releasing.value = true
  reviewMessage.value = ''
  try {
    const result = await publishVersion(releaseVersion.value)
    releaseReview.value = result
    reviewMessage.value = result.message
    // 发布放行后状态回写，列表与待办都要按新口径刷新。
    const payload = await listEntries(meta.value.key, filters.value)
    rows.value = payload.items
    total.value = payload.total
  } catch (error) {
    reviewMessage.value = error instanceof Error ? error.message : '发布失败'
  } finally {
    releasing.value = false
  }
}

async function claimItem(item: SegmentCoverage) {
  reviewMessage.value = ''
  try {
    const result = await claimSegment(item.segment_id, todoVersion.value, reviewer.value)
    reviewMessage.value = result.message
    await loadTodo()
  } catch (error) {
    reviewMessage.value = error instanceof Error ? error.message : '领取失败'
  }
}

async function signItem(item: SegmentCoverage) {
  reviewMessage.value = ''
  try {
    const result = await submitSignature(item.segment_id, todoVersion.value, reviewer.value)
    reviewMessage.value = result.message
    await loadTodo()
  } catch (error) {
    reviewMessage.value = error instanceof Error ? error.message : '签名提交失败'
  }
}

watch(
  () => props.moduleKey,
  () => {
    releaseReview.value = null
    todo.value = null
    reviewMessage.value = ''
    releaseVersion.value = ''
    todoVersion.value = ''
    showCreate.value = false
    rows.value = []
    total.value = 0
    void reload()
  },
)

onMounted(reload)
</script>
