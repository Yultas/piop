<template>
  <div class="typst-renderer-container flex flex-col gap-3">
    <!-- Toolbar -->
    <div class="toolbar eink-card p-3 flex flex-wrap justify-between items-center gap-2">
      <!-- Quick Templates -->
      <div class="flex items-center gap-2">
        <span class="text-xs font-bold">{{ $t('notebook.templates') }}:</span>
        <button class="eink-btn eink-btn-sm" @click="insertTemplate('math')">
          {{ $t('typst.template_math') }}
        </button>
        <button class="eink-btn eink-btn-sm" @click="insertTemplate('matrix')">
          {{ $t('typst.template_matrix') }}
        </button>
        <button class="eink-btn eink-btn-sm" @click="insertTemplate('paper')">
          {{ $t('typst.template_paper') }}
        </button>
      </div>

      <!-- Auto-compile toggle & Controls -->
      <div class="flex items-center gap-3">
        <label class="flex items-center gap-1 text-xs cursor-pointer select-none">
          <input v-model="autoCompile" type="checkbox" />
          <span>{{ $t('typst.auto_compile') }}</span>
        </label>

        <button
          class="eink-btn eink-btn-sm eink-btn-dark"
          :disabled="compiling"
          @click="compileCode"
        >
          <Play :size="14" /> {{ compiling ? $t('typst.compiling') : $t('typst.compile_btn') }}
        </button>

        <button
          class="eink-btn eink-btn-sm"
          :title="$t('typst.download_pdf')"
          :disabled="downloadingPdf"
          @click="downloadPdf"
        >
          <Download :size="14" /> {{ downloadingPdf ? '…' : $t('typst.download_pdf') }}
        </button>
      </div>
    </div>

    <!-- Error Banner -->
    <div
      v-if="errorMessage"
      class="eink-card p-3 border-ink-900 bg-paper-dim flex items-start gap-2 text-xs text-ink-900"
    >
      <TriangleAlert :size="16" />
      <div class="flex-1 overflow-x-auto whitespace-pre-wrap">
        <strong>{{ $t('typst.compile_error') }}:</strong>
        <p class="mt-1">{{ errorMessage }}</p>
      </div>
      <button class="eink-btn eink-btn-sm eink-btn-icon" :aria-label="$t('common.close')" @click="errorMessage = ''"><X :size="14" /></button>
    </div>

    <!-- Main Workspace (Editor + SVG Preview) -->
    <div class="grid grid-cols-2 gap-3 flex-1 min-h-[550px]">
      <!-- Code Editor Panel -->
      <div class="editor-panel flex flex-col border bg-paper">
        <div class="eink-panel-head eink-panel-head-sm">
          <span class="font-bold">{{ $t('typst.source_code') }}</span>
          <span class="text-muted">Typst v0.12+</span>
        </div>
        <textarea
          ref="editorTextarea"
          v-model="typstCode"
          class="typst-textarea flex-1 p-3 font-mono text-sm leading-relaxed outline-none resize-none bg-paper text-ink-900"
          placeholder="// Enter Typst code..."
          @keydown="handleKeydown"
        ></textarea>
      </div>

      <!-- Compiled SVG Preview Panel -->
      <div class="preview-panel flex flex-col border bg-card">
        <div class="eink-panel-head eink-panel-head-sm">
          <span class="font-bold">{{ $t('typst.compiled_view') }}</span>
          <div class="flex items-center gap-1">
            <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('canvas.zoom_out')" @click="zoomOut"><ZoomOut :size="14" /></button>
            <span class="text-xs px-1 zoom-value">{{ Math.round(zoomLevel * 100) }}%</span>
            <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('canvas.zoom_in')" @click="zoomIn"><ZoomIn :size="14" /></button>
            <button class="eink-btn eink-btn-sm" @click="resetZoom">100%</button>
          </div>
        </div>

        <div class="svg-viewport flex-1 overflow-auto p-4 flex justify-center items-start bg-paper">
          <div v-if="compiling && !compiledSvg" class="p-8 text-center text-xs text-muted">
            {{ $t('typst.compiling') }}
          </div>
          <div
            v-else-if="compiledSvg"
            class="svg-document-wrapper eink-card p-4 bg-white"
            :style="{ transform: `scale(${zoomLevel})`, transformOrigin: 'top center' }"
            v-html="compiledSvg"
          ></div>
          <div v-else class="p-8 text-center text-xs text-muted">
            {{ $t('typst.compiled_view') }}
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { Play, Download, TriangleAlert, X, ZoomIn, ZoomOut } from 'lucide-vue-next'
import { ref, watch, onMounted } from 'vue'
import DOMPurify from 'dompurify'
import api, { csrfHeaders } from '../api/client'

// Typst glyphs are <use href="#id">; allow only in-document references
DOMPurify.addHook('uponSanitizeAttribute', (node, data) => {
  if (node.nodeName.toLowerCase() === 'use' && (data.attrName === 'href' || data.attrName === 'xlink:href') && !data.attrValue.startsWith('#')) {
    data.keepAttr = false
  }
})

const templates = {
  math: `= Теорема энергии и импульса

В специальной теории относительности полная энергия частицы связана с её импульсом $p$ и массой покоя $m$ выражением:

$ E^2 = (p c)^2 + (m c^2)^2 $

Для покоящейся частицы ($p = 0$) формула принимает фундаментальный вид:

$ E = m c^2 $

Интеграл квантовой волновой функции:

$ psi(x, t) = 1 / sqrt(2 pi) integral_(-infinity)^(+infinity) phi(k) e^(i (k x - omega t)) dif k $
`,
  matrix: `= Линейная алгебра и Матрицы

Матричное уравнение для системы линейных уравнений:

$ mat(
  a_11, a_12, ..., a_(1n);
  a_21, a_22, ..., a_(2n);
  dots.v, dots.v, dots.down, dots.v;
  a_(m 1), a_(m 2), ..., a_(m n)
) mat(x_1; x_2; dots.v; x_n) = mat(b_1; b_2; dots.v; b_m) $

Определитель матрицы второго порядка:

$ det(mat(a, b; c, d)) = a d - b c $
`,
  paper: `#set page(paper: "a4", margin: (x: 2cm, y: 2.5cm))
#set text(font: "Newsreader", size: 11pt, lang: "ru")

#align(center)[
  #text(16pt, weight: "bold")[Архитектура монохромных E-Ink систем]
  
  #v(0.5em)
  #text(11pt, style: "italic")[Инженерная лаборатория Pi'op]
]

#v(1em)

== Введение
Современные экраны на электронных чернилах (E-Ink) требуют строгого соблюдения контрастности и отказа от градиентных теней. Данный документ сгенерирован компилятором *Typst* в векторный формат SVG.

== Ключевые требования:
- Высокий контраст черного и белого
- Монохромная типографика (Serif для текста, Mono для формул)
- Отсутствие анимаций и размытий

#align(center)[
  #table(
    columns: (1fr, 1fr),
    align: (left, center),
    [Параметр], [Значение],
    [Разрешение], [300 DPI],
    [Цветовая палитра], [1-bit / Monochrome],
    [Время отклика], [~150 ms]
  )
]
`
}

const typstCode = ref(templates.paper)
const compiledSvg = ref('')
const compiling = ref(false)
const autoCompile = ref(true)
const errorMessage = ref('')
const downloadingPdf = ref(false)
const zoomLevel = ref(1)

let debounceTimer = null

function handleKeydown(e) {
  // Ctrl + Enter to compile
  if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
    e.preventDefault()
    compileCode()
  }
}

function insertTemplate(type) {
  if (templates[type]) {
    typstCode.value = templates[type]
    compileCode()
  }
}

function zoomIn() {
  zoomLevel.value = Math.min(2, Math.round((zoomLevel.value + 0.1) * 10) / 10)
}

function zoomOut() {
  zoomLevel.value = Math.max(0.5, Math.round((zoomLevel.value - 0.1) * 10) / 10)
}

function resetZoom() {
  zoomLevel.value = 1
}

async function compileCode() {
  if (!typstCode.value.trim()) {
    compiledSvg.value = ''
    errorMessage.value = ''
    return
  }

  compiling.value = true
  errorMessage.value = ''

  try {
    const res = await api.post('/api/typst/compile', {
      code: typstCode.value,
      format: 'svg'
    })
    compiledSvg.value = DOMPurify.sanitize(res.result || '', { USE_PROFILES: { svg: true, svgFilters: true }, ADD_TAGS: ['use'] })
  } catch (err) {
    errorMessage.value = err.detail || err.message || 'Typst compilation failed'
  } finally {
    compiling.value = false
  }
}

async function downloadPdf() {
  if (!typstCode.value.trim()) return
  downloadingPdf.value = true
  try {
    const response = await fetch('/api/typst/compile', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...csrfHeaders
      },
      credentials: 'same-origin',
      body: JSON.stringify({
        code: typstCode.value,
        format: 'pdf'
      })
    })

    if (!response.ok) {
      throw new Error(`PDF compile error: ${response.statusText}`)
    }

    const blob = await response.blob()
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = 'typst_document.pdf'
    a.click()
    URL.revokeObjectURL(url)
  } catch (err) {
    errorMessage.value = err.message
  } finally {
    downloadingPdf.value = false
  }
}

watch(typstCode, () => {
  if (autoCompile.value) {
    if (debounceTimer) clearTimeout(debounceTimer)
    debounceTimer = setTimeout(() => {
      compileCode()
    }, 600)
  }
})

onMounted(() => {
  compileCode()
})
</script>

<style scoped>
.typst-renderer-container {
  height: 680px;
}

.typst-textarea {
  border: none;
}

.editor-panel,
.preview-panel {
  height: 100%;
  overflow: hidden;
  border-radius: var(--radius-lg);
}

.svg-viewport {
  overflow: auto;
}

.svg-document-wrapper {
  max-width: 100%;
  box-shadow: 2px 2px 0 var(--color-ink-900);
  transition: transform 0.15s ease-out;
}

:deep(.svg-document-wrapper svg) {
  display: block;
  max-width: 100%;
  height: auto;
}
</style>
