<template>
  <div class="assistant-panel">
    <div v-if="status && !status.configured" class="eink-card p-6 text-center">
      <p class="text-sm mb-2 font-semibold">{{ $t('ai.not_configured') }}</p>
      <p class="text-sm text-muted">{{ $t('ai.not_configured_hint') }}</p>
    </div>

    <div v-else class="assistant-layout eink-card">
      <!-- Conversations -->
      <aside class="conv-sidebar">
        <div class="conv-header">
          <button type="button" class="eink-btn eink-btn-sm eink-btn-primary flex-1" @click="newConversation">
            <Plus :size="14" /> {{ $t('ai.new_chat') }}
          </button>
          <button
            v-if="status?.can_manage"
            type="button"
            class="eink-btn eink-btn-sm"
            :title="$t('ai.permissions')"
            @click="openPermissions"
          >
            <Settings :size="14" />
          </button>
        </div>
        <div class="conv-list">
          <div
            v-for="c in conversations"
            :key="c.id"
            class="conv-item"
            :class="{ active: c.id === activeId }"
            @click="selectConversation(c.id)"
          >
            <span class="truncate">{{ c.title || $t('ai.untitled') }}</span>
            <button
              type="button"
              class="conv-delete"
              :title="$t('common.delete')"
              @click.stop="deleteConversation(c.id)"
            >
              <Trash2 :size="12" />
            </button>
          </div>
        </div>
      </aside>

      <!-- Chat -->
      <section class="chat-area">
        <div ref="feedRef" class="feed scroll-blocks">
          <div v-if="!messages.length && !loading" class="empty text-sm text-muted">
            <p class="mb-2">{{ $t('ai.empty_title') }}</p>
            <p>{{ $t('ai.empty_examples') }}</p>
          </div>

          <template v-for="m in messages" :key="m.id">
            <div v-if="m.role === 'user'" class="bubble user">{{ m.content }}</div>

            <div v-else-if="m.role === 'assistant'" class="bubble assistant eink-rendered-content" v-html="renderMarkdown(m.content)"></div>

            <div v-else-if="m.status === 'pending'" class="action-card">
              <div class="text-sm font-semibold mb-2">
                {{ $t('ai.confirm_title') }}: {{ actionLabel(m.tool_name) }}
              </div>
              <dl class="action-args">
                <template v-for="(value, key) in m.tool_args" :key="key">
                  <dt>{{ key }}</dt>
                  <dd>{{ formatValue(value) }}</dd>
                </template>
              </dl>
              <div class="flex gap-2 mt-3">
                <button type="button" class="eink-btn eink-btn-sm eink-btn-primary" :disabled="loading" @click="resolve(m.id, true)">
                  <Check :size="14" /> {{ $t('ai.approve') }}
                </button>
                <button type="button" class="eink-btn eink-btn-sm" :disabled="loading" @click="resolve(m.id, false)">
                  <X :size="14" /> {{ $t('ai.reject') }}
                </button>
              </div>
            </div>

            <details v-else class="tool-line" :class="m.status">
              <summary>
                <span class="tool-status"><component :is="statusIcon(m.status)" :size="13" /></span>
                <span>{{ actionLabel(m.tool_name) }}</span>
                <span v-if="argsSummary(m)" class="text-muted truncate">{{ argsSummary(m) }}</span>
              </summary>
              <pre class="tool-result">{{ prettyResult(m.content) }}</pre>
            </details>
          </template>

          <div v-if="loading" class="thinking text-sm text-muted">{{ $t('ai.thinking') }}</div>
          <div v-if="error" class="error-line text-sm">{{ error }}</div>
        </div>

        <form class="input-bar" @submit.prevent="send">
          <textarea
            v-model="draft"
            class="eink-textarea"
            rows="2"
            :placeholder="pending ? $t('ai.waiting_decision') : $t('ai.placeholder')"
            :disabled="loading || pending"
            @keydown.enter.exact.prevent="send"
          ></textarea>
          <button type="submit" class="eink-btn eink-btn-primary" :disabled="loading || pending || !draft.trim()">
            {{ $t('chat.send') }}
          </button>
        </form>
      </section>
    </div>

    <!-- Permissions -->
    <EinkModal :open="showPermissions" :title="$t('ai.permissions')" max-width="30rem" @close="showPermissions = false">
      <p class="text-sm text-muted mb-4">{{ $t('ai.permissions_hint') }}</p>
      <div v-for="group in permissionGroups" :key="group.kind" class="mb-4">
        <div class="text-xs font-semibold text-muted mb-2">{{ $t(`ai.kind_${group.kind}`) }}</div>
        <div v-for="p in group.items" :key="p.action" class="perm-row">
          <span class="text-sm">{{ actionLabel(p.action) }}</span>
          <select v-model="permissionDraft[p.action]" class="eink-select perm-select">
            <option value="off">{{ $t('ai.mode_off') }}</option>
            <option value="confirm">{{ $t('ai.mode_confirm') }}</option>
            <option value="auto">{{ $t('ai.mode_auto') }}</option>
          </select>
        </div>
      </div>
      <div class="eink-modal-actions">
        <button type="button" class="eink-btn" @click="showPermissions = false">{{ $t('common.cancel') }}</button>
        <button type="button" class="eink-btn eink-btn-primary" @click="savePermissions">{{ $t('common.save') }}</button>
      </div>
    </EinkModal>
  </div>
</template>

<script setup>
import { ref, computed, nextTick, onMounted, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { Marked } from 'marked'
import DOMPurify from 'dompurify'
import { Plus, Settings, Trash2, Check, X, Minus, Dot } from 'lucide-vue-next'
import api from '../api/client'
import EinkModal from './EinkModal.vue'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  }
})

const emit = defineEmits(['changed'])
const { t, te } = useI18n()

const status = ref(null)
const conversations = ref([])
const activeId = ref(null)
const messages = ref([])
const pending = ref(false)
const draft = ref('')
const loading = ref(false)
const error = ref('')
const feedRef = ref(null)

const showPermissions = ref(false)
const permissions = ref([])
const permissionDraft = ref({})

const base = computed(() => `/api/workspaces/${props.workspaceId}/ai`)

// Model output is untrusted: escape raw HTML and allow only safe link schemes
function escapeHtml(text) {
  return String(text).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]))
}
const safeMarked = new Marked({
  gfm: true,
  breaks: true,
  renderer: {
    html({ text }) {
      return escapeHtml(text)
    },
    link({ href, text }) {
      if (!/^(https?:|mailto:)/i.test(href || '')) return escapeHtml(text)
      return `<a href="${escapeHtml(href)}" target="_blank" rel="noopener noreferrer">${escapeHtml(text)}</a>`
    },
    image({ text }) {
      return escapeHtml(text)
    }
  }
})

function renderMarkdown(text) {
  return DOMPurify.sanitize(safeMarked.parse(text || ''), { ADD_ATTR: ['target'] })
}

function actionLabel(name) {
  const key = `ai.action_${name}`
  return te(key) ? t(key) : name
}

function statusIcon(s) {
  return { done: Check, error: X, rejected: Minus }[s] || Dot
}

function formatValue(value) {
  if (typeof value === 'string') return value.length > 400 ? value.slice(0, 400) + '…' : value
  return JSON.stringify(value)
}

function argsSummary(m) {
  const args = m.tool_args || {}
  const main = args.query ?? args.title ?? args.document_id ?? args.task_id ?? args.channel_id
  if (main === undefined) return ''
  return typeof main === 'string' ? `«${main}»` : `#${main}`
}

function prettyResult(content) {
  try {
    return JSON.stringify(JSON.parse(content), null, 2)
  } catch {
    return content || ''
  }
}

function describeError(err) {
  const detail = err.detail || err.message || ''
  return te(detail) ? t(detail) : detail
}

async function scrollToEnd() {
  await nextTick()
  if (feedRef.value) feedRef.value.scrollTop = feedRef.value.scrollHeight
}

function applyPayload(payload) {
  messages.value = payload.messages
  pending.value = payload.pending
  scrollToEnd()
}

async function loadStatus() {
  status.value = await api.get(`${base.value}/status`)
}

async function loadConversations() {
  conversations.value = await api.get(`${base.value}/conversations`)
}

async function selectConversation(id) {
  activeId.value = id
  error.value = ''
  applyPayload(await api.get(`${base.value}/conversations/${id}/messages`))
}

async function newConversation() {
  activeId.value = null
  messages.value = []
  pending.value = false
  error.value = ''
}

async function deleteConversation(id) {
  await api.delete(`${base.value}/conversations/${id}`)
  if (activeId.value === id) newConversation()
  await loadConversations()
}

async function send() {
  const content = draft.value.trim()
  if (!content || loading.value || pending.value) return
  loading.value = true
  error.value = ''
  try {
    if (!activeId.value) {
      const conv = await api.post(`${base.value}/conversations`, {})
      activeId.value = conv.id
    }
    messages.value = [...messages.value, { id: `local-${Date.now()}`, role: 'user', content }]
    draft.value = ''
    scrollToEnd()
    applyPayload(await api.post(`${base.value}/conversations/${activeId.value}/messages`, { content }))
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
    if (activeId.value) applyPayload(await api.get(`${base.value}/conversations/${activeId.value}/messages`))
  } finally {
    loading.value = false
    loadConversations()
  }
}

async function resolve(messageId, approve) {
  loading.value = true
  error.value = ''
  try {
    const action = approve ? 'approve' : 'reject'
    applyPayload(await api.post(`${base.value}/conversations/${activeId.value}/actions/${messageId}/${action}`))
    emit('changed')
  } catch (err) {
    error.value = describeError(err)
    applyPayload(await api.get(`${base.value}/conversations/${activeId.value}/messages`))
  } finally {
    loading.value = false
  }
}

const permissionGroups = computed(() => ['read', 'write', 'delete'].map((kind) => ({
  kind,
  items: permissions.value.filter((p) => p.kind === kind)
})))

async function openPermissions() {
  permissions.value = await api.get(`${base.value}/permissions`)
  permissionDraft.value = Object.fromEntries(permissions.value.map((p) => [p.action, p.mode]))
  showPermissions.value = true
}

async function savePermissions() {
  try {
    permissions.value = await api.put(`${base.value}/permissions`, { modes: permissionDraft.value })
    showPermissions.value = false
  } catch (err) {
    error.value = describeError(err)
  }
}

async function init() {
  error.value = ''
  try {
    await loadStatus()
    if (status.value.configured) await loadConversations()
  } catch (err) {
    error.value = describeError(err)
  }
}

watch(() => props.workspaceId, () => {
  newConversation()
  init()
})

onMounted(init)
</script>

<style scoped>
.assistant-layout {
  display: flex;
  height: 650px;
  overflow: hidden;
}

.conv-sidebar {
  width: 240px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  border-right: var(--border-crisp);
  background-color: var(--color-paper);
}

.conv-header {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem;
  border-bottom: var(--border-crisp);
}

.conv-list {
  flex: 1;
  overflow-y: auto;
}

.conv-item {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.6rem 0.75rem;
  font-size: 0.875rem;
  border-bottom: var(--border-faint);
  cursor: pointer;
}

.conv-item:hover {
  background-color: var(--color-paper-dim);
}

.conv-item.active {
  background-color: var(--color-ink-900);
  color: var(--color-paper);
}

.conv-delete {
  background: none;
  border: none;
  color: inherit;
  opacity: 0.5;
  cursor: pointer;
  padding: 0.125rem;
}

.conv-delete:hover {
  opacity: 1;
}

.chat-area {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.feed {
  flex: 1;
  overflow-y: auto;
  padding: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.empty {
  margin: auto;
  max-width: 28rem;
  text-align: center;
}

.bubble {
  max-width: 85%;
  padding: 0.6rem 0.85rem;
  font-size: 0.9rem;
  line-height: 1.5;
  overflow-wrap: anywhere;
  border-radius: var(--radius);
}

.bubble.user {
  align-self: flex-end;
  background-color: var(--color-ink-900);
  color: var(--color-paper);
  white-space: pre-wrap;
}

.bubble.assistant {
  align-self: flex-start;
  border: var(--border-crisp);
  background-color: var(--color-paper-card);
}

.bubble.assistant {
  min-width: 0;
}

.bubble.assistant :deep(> :first-child) {
  margin-top: 0;
}

.bubble.assistant :deep(> :last-child) {
  margin-bottom: 0;
}

.bubble.assistant :deep(p:last-child) {
  margin-bottom: 0;
}

.bubble.assistant :deep(p) {
  margin: 0.5rem 0;
}

/* Model replies use headings as section labels, not document titles */
.bubble.assistant :deep(h1),
.bubble.assistant :deep(h2),
.bubble.assistant :deep(h3),
.bubble.assistant :deep(h4) {
  font-size: 1rem;
  font-weight: 700;
  margin: 0.75rem 0 0.35rem;
  padding-bottom: 0;
  border-bottom: none;
}

.bubble.assistant :deep(table) {
  margin: 0.6rem 0;
  font-size: 0.85rem;
}

.bubble.assistant :deep(th),
.bubble.assistant :deep(td) {
  padding: 0.35rem 0.6rem;
  border-color: var(--color-ink-300);
}

.bubble.assistant :deep(ul),
.bubble.assistant :deep(ol) {
  padding-left: 1.25rem;
  margin: 0.4rem 0;
}

.bubble.assistant :deep(pre) {
  overflow-x: auto;
  padding: 0.5rem;
  background-color: var(--color-paper-dim);
}

.tool-line {
  align-self: flex-start;
  max-width: 85%;
  font-size: 0.8rem;
  font-family: var(--font-mono);
  color: var(--color-ink-700);
}

.tool-line summary {
  display: flex;
  gap: 0.5rem;
  cursor: pointer;
  list-style: none;
  padding: 0.2rem 0;
}

.tool-line summary::-webkit-details-marker {
  display: none;
}

.tool-line.error,
.tool-line.rejected {
  color: var(--color-ink-500);
}

.tool-status {
  display: inline-flex;
  align-items: center;
  width: 1rem;
}

.tool-result {
  max-height: 240px;
  overflow: auto;
  margin-top: 0.25rem;
  padding: 0.5rem;
  border: var(--border-faint);
  border-radius: var(--radius-sm);
  background-color: var(--color-paper);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.action-card {
  align-self: flex-start;
  width: min(100%, 32rem);
  padding: 0.85rem;
  border: 2px solid var(--color-ink-900);
  border-radius: var(--radius);
  background-color: var(--color-paper-card);
}

.action-args {
  display: grid;
  grid-template-columns: auto 1fr;
  gap: 0.25rem 0.75rem;
  font-size: 0.8rem;
}

.action-args dt {
  font-family: var(--font-mono);
  color: var(--color-ink-500);
}

.action-args dd {
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.error-line {
  padding: 0.5rem 0.75rem;
  border: 1px dashed var(--color-ink-900);
}

.input-bar {
  display: flex;
  gap: 0.5rem;
  padding: 0.75rem;
  border-top: var(--border-crisp);
}

.input-bar .eink-textarea {
  resize: none;
}

.perm-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  padding: 0.35rem 0;
  border-bottom: var(--border-faint);
}

.perm-select {
  width: auto;
  min-width: 11rem;
  padding: 0.3rem 0.5rem;
}

@media (max-width: 767px) {
  .assistant-layout {
    flex-direction: column;
    height: auto;
  }

  .conv-sidebar {
    width: 100%;
    max-height: 180px;
    border-right: none;
    border-bottom: var(--border-crisp);
  }

  .feed {
    min-height: 420px;
    max-height: 70vh;
  }

  .bubble,
  .tool-line {
    max-width: 100%;
  }

  .perm-row {
    flex-direction: column;
    align-items: stretch;
    gap: 0.25rem;
  }

  .perm-select {
    width: 100%;
  }
}
</style>
