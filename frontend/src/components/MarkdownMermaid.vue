<template>
  <div class="markdown-mermaid-container flex flex-col gap-3">
    <!-- Toolbar -->
    <div class="toolbar eink-card p-3 flex flex-wrap justify-between items-center gap-2">
      <!-- Left: Title & Doc Selector -->
      <div class="flex items-center gap-3">
        <input
          v-model="docTitle"
          type="text"
          class="eink-input font-bold text-sm w-56"
          :placeholder="$t('notebook.doc_name')"
        />
        <select
          v-if="documents.length > 0"
          v-model="selectedDocId"
          class="eink-input text-xs"
          @change="loadDocument"
        >
          <option :value="null">-- {{ $t('notebook.documents_list') }} --</option>
          <option v-for="d in documents" :key="d.id" :value="d.id">
            {{ d.title }}
          </option>
        </select>
      </div>

      <!-- Center: View Mode Switcher -->
      <div class="eink-segmented">
        <button
          :class="{ active: viewMode === 'split' }"
          @click="viewMode = 'split'"
        >
          {{ $t('notebook.split_view') }}
        </button>
        <button
          :class="{ active: viewMode === 'edit' }"
          @click="viewMode = 'edit'"
        >
          {{ $t('notebook.editor_only') }}
        </button>
        <button
          :class="{ active: viewMode === 'preview' }"
          @click="viewMode = 'preview'"
        >
          {{ $t('notebook.preview_only') }}
        </button>
      </div>

      <!-- Right: Action Buttons -->
      <div class="flex items-center gap-2">
        <button
          class="eink-btn eink-btn-sm"
          :title="$t('notebook.new_doc')"
          @click="resetNewDoc"
        >
          <Plus :size="14" /> {{ $t('notebook.new_doc') }}
        </button>
        <button
          class="eink-btn eink-btn-sm"
          :title="$t('notebook.export_md')"
          @click="exportMarkdown"
        >
          <Download :size="14" /> {{ $t('notebook.export_md') }}
        </button>
        <button
          class="eink-btn eink-btn-sm eink-btn-dark"
          :disabled="saving"
          @click="saveDocument"
        >
          <Save :size="14" /> {{ saving ? $t('common.loading') : $t('notebook.save_btn') }}
        </button>
      </div>
    </div>

    <!-- Main Workspace (Editor + Preview) -->
    <div
      ref="splitRef"
      class="editor-preview-container"
      :class="{ split: viewMode === 'split', dragging }"
      :style="{ '--editor-width': splitRatio + '%' }"
    >
      <!-- Editor Panel -->
      <div v-show="viewMode !== 'preview'" class="editor-panel flex flex-col border bg-paper">
        <div class="eink-panel-head eink-panel-head-sm">
          <span class="font-bold">{{ $t('notebook.editor') }}</span>
          <div class="flex items-center gap-2">
            <span class="text-muted">{{ $t('notebook.diagrams_hint') }}</span>
            <button
              v-if="viewMode === 'edit'"
              type="button"
              class="eink-icon-btn"
              :title="$t('notebook.show_preview')"
              :aria-label="$t('notebook.show_preview')"
              @click="viewMode = 'split'"
            >
              <PanelRightOpen :size="15" />
            </button>
          </div>
        </div>
        <textarea
          v-model="markdownText"
          class="markdown-textarea flex-1 p-3 font-mono text-sm leading-relaxed outline-none resize-none bg-paper text-ink-900"
          placeholder="# Type markdown here..."
        ></textarea>
      </div>

      <!-- Drag handle (split mode only) -->
      <div
        v-if="viewMode === 'split'"
        class="split-handle"
        role="separator"
        aria-orientation="vertical"
        :aria-valuenow="Math.round(splitRatio)"
        aria-valuemin="20"
        aria-valuemax="80"
        tabindex="0"
        :title="$t('notebook.resize_hint')"
        @pointerdown="startDrag"
        @dblclick="setRatio(50)"
        @keydown.left.prevent="setRatio(splitRatio - 2)"
        @keydown.right.prevent="setRatio(splitRatio + 2)"
      ></div>

      <!-- Preview Panel -->
      <div v-show="viewMode !== 'edit'" class="preview-panel flex flex-col border bg-card">
        <div class="eink-panel-head eink-panel-head-sm">
          <span class="font-bold">{{ $t('notebook.preview') }}</span>
          <div class="flex items-center gap-2">
            <span class="text-muted">Markdown + Mermaid</span>
            <button
              type="button"
              class="eink-icon-btn"
              :title="$t('notebook.hide_preview')"
              :aria-label="$t('notebook.hide_preview')"
              @click="viewMode = 'edit'"
            >
              <PanelRightClose :size="15" />
            </button>
          </div>
        </div>
        <div
          ref="previewContentRef"
          class="preview-body flex-1 p-6 overflow-y-auto doc-prose eink-rendered-content"
          v-html="renderedHtml"
        ></div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Download, Save, Plus, PanelRightClose, PanelRightOpen } from 'lucide-vue-next'
import { ref, computed, watch, onMounted, onBeforeUnmount, nextTick } from 'vue'
import { marked } from 'marked'
import DOMPurify from 'dompurify'
import mermaid from 'mermaid'
import api from '../api/client'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  }
})

const defaultMarkdown = `# 📋 Архитектурный план проекта

Добро пожаловать в блокнот **Markdown + Mermaid** для монохромных E-Ink экранов.

## 1. Контрольный список задач
- [x] Изучить архитектурный план
- [x] Проверить контракты интеграции
- [ ] Развернуть продакшен стенд

## 2. Архитектура системы (Mermaid Diagram)

\`\`\`mermaid
flowchart LR
    A[Пользователь] -->|REST API| B[FastAPI Backend]
    B -->|SQLModel| C[(SQLite / DB)]
    B -->|Typst CLI| D[Векторный SVG]
    A -->|Pinia / Fetch| E[Pi'op Frontend]
\`\`\`

## 3. Взаимодействие компонентов

\`\`\`mermaid
sequenceDiagram
    participant User as Пользователь
    participant UI as Chat Thread
    participant API as Backend Task API
    User->>UI: Клик "Превратить в задачу"
    UI->>API: POST /api/workspaces/:id/tasks/from-message
    API-->>UI: 201 Created (Task Object)
    UI-->>User: Обновление Kanban доски
\`\`\`

> *Примечание: все диаграммы процедурно рендерятся в строгом черно-белом E-Ink стиле без размытий и теней.*
`

const markdownText = ref(defaultMarkdown)
const docTitle = ref('Архитектурный план')
const currentDocId = ref(null)
const documents = ref([])
const selectedDocId = ref(null)
const viewMode = ref('split')
const saving = ref(false)
const previewContentRef = ref(null)

// Initialize Mermaid with strict E-Ink monochrome parameters
mermaid.initialize({
  startOnLoad: false,
  securityLevel: 'strict',
  theme: 'neutral',
  themeVariables: {
    darkMode: false,
    background: '#ffffff',
    primaryColor: '#ffffff',
    primaryBorderColor: '#111111',
    primaryTextColor: '#111111',
    lineColor: '#111111',
    secondaryColor: '#f7f7f5',
    tertiaryColor: '#ffffff',
    mainBkg: '#ffffff',
    nodeBorder: '#111111',
    clusterBkg: '#f7f7f5',
    clusterBorder: '#111111',
    defaultLinkColor: '#111111',
    titleColor: '#111111',
    edgeLabelBackground: '#ffffff',
    actorBorder: '#111111',
    actorBkg: '#ffffff',
    actorTextColor: '#111111',
    signalColor: '#111111',
    signalTextColor: '#111111'
  }
})

// Configure marked with custom code renderer for mermaid
const renderer = new marked.Renderer()
let mermaidCounter = 0

renderer.code = function ({ text, lang }) {
  if (lang === 'mermaid') {
    mermaidCounter++
    const id = `mermaid-node-${mermaidCounter}`
    // Escape attribute text
    const escapedCode = encodeURIComponent(text)
    return `<div class="eink-mermaid-wrapper my-4 border p-2 bg-paper-card" id="${id}" data-mermaid="${escapedCode}"><div class="text-xs font-mono text-muted p-2">Rendering diagram...</div></div>`
  }
  return `<pre class="border p-3 bg-paper-dim my-3 overflow-x-auto"><code class="font-mono text-xs">${escapeHtml(text)}</code></pre>`
}

marked.setOptions({
  renderer,
  gfm: true,
  breaks: true
})

function escapeHtml(str) {
  return str
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
}

const renderedHtml = computed(() => {
  mermaidCounter = 0
  return DOMPurify.sanitize(marked.parse(markdownText.value || ''))
})

// Resizable split between editor and preview
const splitRef = ref(null)
const dragging = ref(false)

function loadRatio() {
  try {
    const n = parseFloat(localStorage.getItem('pi-notes-split'))
    if (Number.isFinite(n)) return Math.min(80, Math.max(20, n))
  } catch {}
  return 50
}

const splitRatio = ref(loadRatio())

function setRatio(v) {
  splitRatio.value = Math.min(80, Math.max(20, v))
  try {
    localStorage.setItem('pi-notes-split', String(Math.round(splitRatio.value)))
  } catch {}
}

function startDrag(e) {
  if (e.button !== 0) return
  dragging.value = true
  try {
    e.currentTarget.setPointerCapture(e.pointerId)
  } catch {}
  window.addEventListener('pointermove', onDragMove)
  window.addEventListener('pointerup', endDrag)
  window.addEventListener('pointercancel', endDrag)
}

function onDragMove(e) {
  if (!splitRef.value) return
  const rect = splitRef.value.getBoundingClientRect()
  if (!rect.width) return
  setRatio(((e.clientX - rect.left) / rect.width) * 100)
}

function endDrag() {
  window.removeEventListener('pointermove', onDragMove)
  window.removeEventListener('pointerup', endDrag)
  window.removeEventListener('pointercancel', endDrag)
  dragging.value = false
}

onBeforeUnmount(endDrag)

// Post-render step: render mermaid SVG nodes
async function renderMermaidDiagrams() {
  await nextTick()
  if (!previewContentRef.value) return

  const nodes = previewContentRef.value.querySelectorAll('.eink-mermaid-wrapper')
  for (let i = 0; i < nodes.length; i++) {
    const el = nodes[i]
    const encoded = el.getAttribute('data-mermaid')
    if (!encoded) continue
    const code = decodeURIComponent(encoded)
    const renderId = `mermaid-render-${Date.now()}-${i}`

    try {
      const { svg } = await mermaid.render(renderId, code)
      el.innerHTML = svg
    } catch (err) {
      console.warn('Mermaid render error:', err)
      el.innerHTML = `<div class="p-2 border border-ink-900 bg-paper-dim text-xs font-mono text-ink-900"><strong>[Mermaid Syntax Error]</strong><pre class="mt-1">${escapeHtml(code)}</pre></div>`
      // Remove temporary error element mermaid might have injected
      const errEl = document.getElementById(renderId)
      if (errEl) errEl.remove()
    }
  }
}

watch(renderedHtml, () => {
  renderMermaidDiagrams()
})

async function fetchDocuments() {
  if (!props.workspaceId) return
  try {
    const list = await api.get(`/api/workspaces/${props.workspaceId}/documents?doc_type=doc`)
    documents.value = list || []
  } catch (err) {
    console.error('Failed to fetch documents:', err)
  }
}

function resetNewDoc() {
  currentDocId.value = null
  selectedDocId.value = null
  docTitle.value = 'Новый документ'
  markdownText.value = defaultMarkdown
}

function loadDocument() {
  if (!selectedDocId.value) return
  const found = documents.value.find((d) => d.id === selectedDocId.value)
  if (found) {
    currentDocId.value = found.id
    docTitle.value = found.title
    markdownText.value = found.content_raw
  }
}

async function saveDocument() {
  if (!props.workspaceId || !docTitle.value.trim()) return
  saving.value = true
  try {
    if (currentDocId.value) {
      await api.put(`/api/workspaces/${props.workspaceId}/documents/${currentDocId.value}`, {
        title: docTitle.value.trim(),
        content_raw: markdownText.value
      })
    } else {
      const created = await api.post(`/api/workspaces/${props.workspaceId}/documents`, {
        title: docTitle.value.trim(),
        doc_type: 'doc',
        content_raw: markdownText.value
      })
      currentDocId.value = created.id
      selectedDocId.value = created.id
    }
    await fetchDocuments()
  } catch (err) {
    console.error('Failed to save document:', err)
  } finally {
    saving.value = false
  }
}

function exportMarkdown() {
  const blob = new Blob([markdownText.value], { type: 'text/markdown;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = `${docTitle.value || 'document'}.md`
  a.click()
  URL.revokeObjectURL(url)
}

watch(
  () => props.workspaceId,
  (newId) => {
    if (newId) {
      fetchDocuments()
    }
  }
)

onMounted(() => {
  fetchDocuments()
  renderMermaidDiagrams()
})
</script>

<style scoped>
.markdown-mermaid-container {
  height: 680px;
}

.editor-preview-container {
  display: flex;
  gap: 0;
  height: calc(100% - 60px);
}

.markdown-textarea {
  border: none;
}

.editor-panel,
.preview-panel {
  min-width: 0;
  height: 100%;
  overflow: hidden;
  flex: 1 1 0;
  width: auto;
  border-radius: var(--radius-lg);
}

.editor-panel {
  transition: width 200ms cubic-bezier(0.2, 0.8, 0.2, 1);
}

.editor-preview-container.dragging {
  user-select: none;
}

.editor-preview-container.dragging .editor-panel {
  transition: none;
}

@media (min-width: 768px) {
  .editor-preview-container.split .editor-panel {
    flex: 0 0 auto;
    width: var(--editor-width);
  }

  .editor-preview-container.split .preview-panel {
    flex: 1 1 0;
  }
}

.split-handle {
  flex: 0 0 12px;
  cursor: col-resize;
  position: relative;
  touch-action: none;
  outline: none;
}

.split-handle::before {
  content: '';
  position: absolute;
  left: 5px;
  top: 0;
  bottom: 0;
  width: 2px;
  background: var(--color-ink-100);
  border-radius: 2px;
  transition: background-color 120ms;
}

.split-handle:hover::before,
.split-handle:focus-visible::before,
.editor-preview-container.dragging .split-handle::before {
  background: var(--color-ink-900);
}

@media (max-width: 767px) {
  .markdown-mermaid-container,
  .editor-preview-container {
    height: auto;
  }

  .editor-preview-container {
    flex-direction: column;
    gap: 0.75rem;
  }

  .editor-panel,
  .preview-panel {
    height: 420px;
    flex: 0 0 auto;
  }

  .editor-panel {
    width: auto !important;
  }

  .split-handle {
    display: none;
  }
}

:deep(.eink-mermaid-wrapper svg) {
  max-width: 100%;
  height: auto;
  display: block;
  margin: 0 auto;
}
</style>
