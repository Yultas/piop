<template>
  <div class="whiteboard" :class="{ 'layers-open': showLayers }">
    <!-- Top bar: boards, history, view, export -->
    <div class="wb-topbar eink-card">
      <div class="wb-group wb-boards">
        <select class="eink-select wb-board-select" :value="boardId ?? ''" :aria-label="$t('canvas.boards')" @change="switchBoard($event.target.value)">
          <option v-if="boardId === null" value="">{{ boardTitle }}</option>
          <option v-for="b in boards" :key="b.id" :value="b.id">{{ b.title }}</option>
        </select>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.new_board')" @click="newBoard"><Plus :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.rename_board')" @click="renameBoard"><Pencil :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.delete_board')" :disabled="boardId === null" @click="deleteBoard"><Trash2 :size="14" /></button>
        <span class="wb-save-state text-xs text-muted">{{ saveLabel }}</span>
        <span v-if="peerNames" class="wb-save-state text-xs text-muted">{{ $t('canvas.peers', { names: peerNames }) }}</span>
      </div>

      <div class="wb-group">
        <button type="button" class="eink-btn eink-btn-sm" :title="`${$t('canvas.undo')} (Ctrl+Z)`" :disabled="!canUndo" @click="undo"><Undo2 :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm" :title="`${$t('canvas.redo')} (Ctrl+Shift+Z)`" :disabled="!canRedo" @click="redo"><Redo2 :size="14" /></button>
        <span class="wb-sep"></span>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.zoom_out')" @click="zoomBy(1 / 1.25)"><ZoomOut :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm wb-zoom" :title="$t('canvas.zoom_reset')" @click="resetZoom">{{ zoomPct }}%</button>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.zoom_in')" @click="zoomBy(1.25)"><ZoomIn :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm" :title="`${$t('canvas.fit')} (Shift+1)`" @click="fitToContent"><Maximize :size="14" /></button>
        <span class="wb-sep"></span>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.background')" @click="cycleBackground"><Grid3x3 :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm" :class="{ 'eink-btn-primary': showLayers }" :title="$t('canvas.layers')" @click="showLayers = !showLayers"><Layers :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.export_png')" @click="downloadPng">PNG</button>
        <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.export_svg')" @click="downloadSvg">SVG</button>
      </div>
    </div>

    <div class="wb-body">
      <!-- Tools -->
      <div class="wb-tools eink-card" role="toolbar" :aria-label="$t('canvas.tools')">
        <button
          v-for="t in toolList"
          :key="t.id"
          type="button"
          class="wb-tool"
          :class="{ active: tool === t.id }"
          :title="`${$t(`canvas.tool_${t.id}`)} (${t.key})`"
          :aria-pressed="tool === t.id"
          @click="setTool(t.id)"
        >
          <component :is="t.icon" :size="18" />
        </button>
      </div>

      <!-- Canvas -->
      <div ref="stageRef" class="wb-stage">
        <canvas ref="staticRef" class="wb-canvas"></canvas>
        <canvas
          ref="liveRef"
          class="wb-canvas wb-live"
          :style="{ cursor: cursorStyle }"
          @pointerdown="onPointerDown"
          @pointermove="onPointerMove"
          @pointerup="onPointerUp"
          @pointercancel="onPointerCancel"
          @pointerleave="onPointerLeave"
          @wheel.prevent="onWheel"
          @dblclick="onDoubleClick"
          @contextmenu.prevent
        ></canvas>

        <textarea
          v-if="textEditor"
          ref="textRef"
          v-model="textEditor.text"
          class="wb-text-editor"
          :style="textEditorStyle"
          @keydown.esc.prevent="commitText"
          @keydown.enter.exact.prevent="commitText"
          @blur="commitText"
        ></textarea>

        <!-- Contextual properties -->
        <div class="wb-props eink-card">
          <template v-if="tool !== 'select' && tool !== 'hand'">
            <div v-if="tool !== 'eraser'" class="wb-colors">
              <button
                v-for="c in palette"
                :key="c"
                type="button"
                class="wb-swatch"
                :class="{ active: color === c }"
                :style="{ background: c }"
                :title="c"
                @click="color = c"
              ></button>
              <label class="wb-swatch wb-swatch-custom" :title="$t('canvas.custom_color')">
                <input v-model="color" type="color" />
              </label>
            </div>
            <label class="wb-slider">
              <span class="text-xs">{{ $t('canvas.size') }}</span>
              <input v-model.number="currentSize" type="range" :min="sizeRange[0]" :max="sizeRange[1]" step="1" />
              <span class="text-xs wb-value">{{ currentSize }}</span>
            </label>
            <label v-if="tool !== 'eraser' && tool !== 'text'" class="wb-slider">
              <span class="text-xs">{{ $t('canvas.opacity') }}</span>
              <input v-model.number="opacity" type="range" min="10" max="100" step="5" />
              <span class="text-xs wb-value">{{ opacity }}%</span>
            </label>
            <div v-if="tool === 'eraser'" class="eink-segmented">
              <button type="button" :class="{ active: eraserMode === 'precise' }" @click="eraserMode = 'precise'">{{ $t('canvas.eraser_precise') }}</button>
              <button type="button" :class="{ active: eraserMode === 'object' }" @click="eraserMode = 'object'">{{ $t('canvas.eraser_object') }}</button>
            </div>
          </template>
          <template v-else-if="selectionCount">
            <span class="text-xs font-semibold">{{ $t('canvas.selected', { count: selectionCount }) }}</span>
            <button type="button" class="eink-btn eink-btn-sm" :title="`${$t('canvas.duplicate')} (Ctrl+D)`" @click="duplicateSelection"><Copy :size="14" /></button>
            <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.bring_front')" @click="reorderSelection(true)"><BringToFront :size="14" /></button>
            <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.send_back')" @click="reorderSelection(false)"><SendToBack :size="14" /></button>
            <button type="button" class="eink-btn eink-btn-sm" :title="`${$t('common.delete')} (Del)`" @click="deleteSelection"><Trash2 :size="14" /></button>
          </template>
          <span v-else class="text-xs text-muted">{{ tool === 'hand' ? $t('canvas.hint_hand') : $t('canvas.hint_select') }}</span>
        </div>

        <div v-if="notice" class="wb-notice text-sm">{{ notice }}</div>
      </div>

      <!-- Layers -->
      <aside v-if="showLayers" class="wb-layers eink-card">
        <div class="wb-layers-head">
          <span class="text-sm font-semibold">{{ $t('canvas.layers') }}</span>
          <div class="flex gap-1">
            <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.layer_add')" @click="addLayer"><Plus :size="14" /></button>
            <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.layer_up')" @click="moveLayer(1)"><ArrowUp :size="14" /></button>
            <button type="button" class="eink-btn eink-btn-sm" :title="$t('canvas.layer_down')" @click="moveLayer(-1)"><ArrowDown :size="14" /></button>
          </div>
        </div>
        <div class="wb-layer-list">
          <div
            v-for="layer in layersView"
            :key="layer.id"
            class="wb-layer"
            :class="{ active: layer.id === activeLayerId }"
            @click="setActiveLayer(layer.id)"
            @dblclick="renameLayer(layer.id)"
          >
            <button type="button" class="wb-icon" :title="$t('canvas.layer_visible')" @click.stop="toggleLayer(layer.id, 'visible')">
              <Eye v-if="layer.visible" :size="14" /><EyeOff v-else :size="14" />
            </button>
            <button type="button" class="wb-icon" :title="$t('canvas.layer_lock')" @click.stop="toggleLayer(layer.id, 'locked')">
              <Lock v-if="layer.locked" :size="14" /><Unlock v-else :size="14" />
            </button>
            <span class="truncate flex-1 text-sm">{{ layer.name }}</span>
            <span class="text-xs wb-layer-count">{{ layer.count }}</span>
            <button type="button" class="wb-icon" :title="$t('canvas.layer_delete')" :disabled="layersView.length < 2" @click.stop="deleteLayer(layer.id)">
              <Trash2 :size="13" />
            </button>
          </div>
        </div>
      </aside>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onBeforeUnmount, markRaw } from 'vue'
import { useI18n } from 'vue-i18n'
import {
  Lasso, Hand, PenTool, Pencil, Highlighter, Eraser, Minus, Square, Circle, Type,
  Plus, Trash2, Undo2, Redo2, ZoomIn, ZoomOut, Maximize, Grid3x3, Layers, Copy,
  BringToFront, SendToBack, ArrowUp, ArrowDown, Eye, EyeOff, Lock, Unlock
} from 'lucide-vue-next'
import api from '../api/client'
import {
  MIN_ZOOM, MAX_ZOOM, uid, createLayer, createDocument, parseDocument, serializeDocument,
  roundPoint, elementBounds, unionBounds, boundsIntersect, hitTest, eraseFromStroke, insideLasso,
  transformElement, drawElement, drawBackground, createBudget, visibleWorldBounds, contentBounds,
  resolveImageSize, exportPng, exportSvg
} from '../whiteboard/engine'
import { diffState, applyOps } from '../whiteboard/sync'
import { connectBoard } from '../whiteboard/live'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  },
  selectedBoardId: {
    type: Number,
    default: null
  }
})
const emit = defineEmits(['update:selectedBoardId'])

const { t } = useI18n()

const toolList = [
  { id: 'select', key: 'V', icon: markRaw(Lasso) },
  { id: 'hand', key: 'H', icon: markRaw(Hand) },
  { id: 'pen', key: 'P', icon: markRaw(PenTool) },
  { id: 'pencil', key: 'B', icon: markRaw(Pencil) },
  { id: 'marker', key: 'M', icon: markRaw(Highlighter) },
  { id: 'eraser', key: 'E', icon: markRaw(Eraser) },
  { id: 'line', key: 'L', icon: markRaw(Minus) },
  { id: 'rect', key: 'R', icon: markRaw(Square) },
  { id: 'ellipse', key: 'O', icon: markRaw(Circle) },
  { id: 'text', key: 'T', icon: markRaw(Type) }
]
const TOOL_KEYS = Object.fromEntries(toolList.map((x) => [x.key.toLowerCase(), x.id]))
const BRUSH_TOOLS = ['pen', 'pencil', 'marker']
const SHAPE_TOOLS = ['line', 'rect', 'ellipse']
const BACKGROUNDS = ['dots', 'grid', 'none']

const palette = ['#111111', '#555555', '#9a9a9a', '#d6d6d6', '#ffffff', '#1f4e8c', '#b23a2e', '#2f7a3b', '#c98a1c']

// ---------- UI state (reactive) ----------
const tool = ref('pen')
const color = ref('#111111')
const opacity = ref(100)
const sizes = ref({ brush: 4, shape: 3, text: 24, eraser: 16 })
const eraserMode = ref('precise')
const showLayers = ref(false)
const notice = ref('')
const textEditor = ref(null)
const textRef = ref(null)

const boards = ref([])
const boardId = ref(null)
const boardTitle = ref('')
const saveState = ref('saved')
const liveStatus = ref('off') // off | connecting | live | offline | denied
const peers = ref([])

// Bumped whenever the non-reactive document changes, to refresh derived UI
const revision = ref(0)
const zoomPct = ref(100)
const selectionCount = ref(0)
const cursorStyle = ref('crosshair')

const stageRef = ref(null)
const staticRef = ref(null)
const liveRef = ref(null)

// ---------- document state (plain JS, not reactive) ----------
let doc = createDocument(t('canvas.layer_default', { n: 1 }))
let past = []
let future = []
let selection = new Set()
const view = { x: 0, y: 0, zoom: 1 }

// Live sync: `shadow` is what the server has plus what we sent, `acked` only what it confirmed
let live = null
let shadow = null
let acked = null
let pending = new Map() // cid -> ops sent, not yet acked
let liveEver = false
let myConnId = ''

let width = 0
let height = 0
let dpr = 1
let staticDirty = true
let liveDirty = true
let frame = 0
let resizeObserver = null
let saveTimer = null
let noticeTimer = null
// The board may load while its tab is hidden (zero size); place the view once it is shown
let pendingInitialView = false

// Interaction state
const pointers = new Map()
let penSeen = false
let spaceDown = false
let gesture = null // current pointer gesture
let hover = null // last pointer position over the canvas (screen)

const sizeKey = computed(() => {
  if (BRUSH_TOOLS.includes(tool.value)) return 'brush'
  if (SHAPE_TOOLS.includes(tool.value)) return 'shape'
  return tool.value === 'text' ? 'text' : 'eraser'
})
const sizeRange = computed(() => ({ brush: [1, 48], shape: [1, 24], text: [10, 120], eraser: [4, 120] }[sizeKey.value]))
const currentSize = computed({
  get: () => sizes.value[sizeKey.value],
  set: (v) => { sizes.value = { ...sizes.value, [sizeKey.value]: v } }
})

const activeLayerId = computed(() => (revision.value, doc.activeLayerId))
const layersView = computed(() => {
  revision.value
  return [...doc.layers].reverse().map((l) => ({
    id: l.id, name: l.name, visible: l.visible, locked: l.locked, count: l.elements.length
  }))
})
const canUndo = computed(() => (revision.value, past.length > 0))
const canRedo = computed(() => (revision.value, future.length > 0))
const saveLabel = computed(() => liveStatus.value === 'offline' ? t('canvas.reconnecting') : ({
  saved: t('canvas.saved'), dirty: t('canvas.unsaved'), saving: t('canvas.saving'), error: t('canvas.save_error')
}[saveState.value]))
const peerNames = computed(() => [...new Set(peers.value.filter((p) => p.id !== myConnId).map((p) => p.user))].join(', '))

const textEditorStyle = computed(() => {
  if (!textEditor.value) return {}
  const { x, y, size, color: c } = textEditor.value
  return {
    left: `${x * view.zoom + view.x}px`,
    top: `${y * view.zoom + view.y}px`,
    fontSize: `${size * view.zoom}px`,
    lineHeight: 1.3,
    color: c
  }
})

// ---------- helpers ----------

function showNotice(text) {
  notice.value = text
  clearTimeout(noticeTimer)
  noticeTimer = setTimeout(() => { notice.value = '' }, 2200)
}

function toWorld(sx, sy) {
  return { x: (sx - view.x) / view.zoom, y: (sy - view.y) / view.zoom }
}

function screenPoint(e) {
  const rect = liveRef.value.getBoundingClientRect()
  return { x: e.clientX - rect.left, y: e.clientY - rect.top }
}

function activeLayer() {
  return doc.layers.find((l) => l.id === doc.activeLayerId) || doc.layers[doc.layers.length - 1]
}

function editableLayers() {
  return doc.layers.filter((l) => l.visible && !l.locked)
}

function requestRender(staticToo = true) {
  if (staticToo) staticDirty = true
  liveDirty = true
  if (!frame) frame = requestAnimationFrame(renderFrame)
}

function touched() {
  revision.value += 1
  markDirty()
}

/** Record the current layers for undo, then replace them. */
function commit(newLayers) {
  past.push(doc.layers)
  if (past.length > 300) past.shift()
  future = []
  doc.layers = newLayers
  touched()
  requestRender()
}

function mapLayer(layerId, fn) {
  return doc.layers.map((l) => (l.id === layerId ? fn(l) : l))
}

function selectedElements() {
  const out = []
  for (const l of editableLayers()) for (const el of l.elements) if (selection.has(el.id)) out.push(el)
  return out
}

function setSelection(ids) {
  selection = new Set(ids)
  selectionCount.value = selection.size
  requestRender()
}

// ---------- rendering ----------

function renderFrame() {
  frame = 0
  const doStatic = staticDirty
  const doLive = liveDirty
  staticDirty = false
  liveDirty = false
  if (doStatic) renderStatic()
  if (doLive) renderLive()
}

function hiddenWhileTransforming() {
  return gesture && (gesture.kind === 'move' || gesture.kind === 'scale') ? selection : null
}

function renderStatic() {
  const canvas = staticRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.fillStyle = '#ffffff'
  ctx.fillRect(0, 0, width, height)
  drawBackground(ctx, doc.background, view, width, height)

  ctx.setTransform(dpr * view.zoom, 0, 0, dpr * view.zoom, dpr * view.x, dpr * view.y)
  const visible = visibleWorldBounds(view, width, height)
  const hidden = hiddenWhileTransforming()
  const budget = createBudget()
  for (const layer of doc.layers) {
    if (!layer.visible) continue
    for (const el of layer.elements) {
      if (hidden && hidden.has(el.id)) continue
      if (!boundsIntersect(elementBounds(el), visible)) continue
      drawElement(ctx, el, { onImageLoad: onImageLoaded, budget })
    }
  }
  // Some strokes were drawn as quick previews: refine them on the next frame
  if (budget.deferred) requestRender()
}

function renderLive() {
  const canvas = liveRef.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.clearRect(0, 0, width, height)
  ctx.setTransform(dpr * view.zoom, 0, 0, dpr * view.zoom, dpr * view.x, dpr * view.y)

  if (gesture?.kind === 'draw' && gesture.element) drawElement(ctx, gesture.element, { live: true })
  if (gesture?.kind === 'shape' && gesture.element) drawElement(ctx, gesture.element)

  const sel = selectedElements()
  if (sel.length) {
    let tr = null
    if (gesture?.kind === 'move') tr = { dx: gesture.dx, dy: gesture.dy }
    if (gesture?.kind === 'scale') tr = gesture.transform
    if (tr) {
      // Transformed preview uses cached paths under a canvas transform: no re-tessellation
      ctx.save()
      if (tr.sx) {
        ctx.translate(tr.ax + tr.dx, tr.ay + tr.dy)
        ctx.scale(tr.sx, tr.sy)
        ctx.translate(-tr.ax, -tr.ay)
      } else {
        ctx.translate(tr.dx, tr.dy)
      }
      for (const el of sel) drawElement(ctx, el)
      ctx.restore()
    }
    drawSelectionBox(ctx, sel, tr)
  }

  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  if (gesture?.kind === 'lasso' && gesture.points.length > 2) {
    ctx.save()
    ctx.setLineDash([5, 4])
    ctx.strokeStyle = '#111111'
    ctx.lineWidth = 1
    ctx.fillStyle = 'rgba(17,17,17,0.05)'
    ctx.beginPath()
    ctx.moveTo(gesture.points[0], gesture.points[1])
    for (let i = 2; i < gesture.points.length; i += 2) ctx.lineTo(gesture.points[i], gesture.points[i + 1])
    ctx.closePath()
    ctx.fill()
    ctx.stroke()
    ctx.restore()
  }
  if (tool.value === 'eraser' && hover) {
    ctx.beginPath()
    ctx.arc(hover.x, hover.y, sizes.value.eraser / 2, 0, Math.PI * 2)
    ctx.strokeStyle = '#111111'
    ctx.lineWidth = 1
    ctx.stroke()
  }
}

function selectionFrame(sel, tr) {
  const b = unionBounds(sel)
  if (!b) return null
  let { minX, minY, maxX, maxY } = b
  if (tr) {
    const tx = (x) => (tr.sx ? tr.ax + (x - tr.ax) * tr.sx : x) + tr.dx
    const ty = (y) => (tr.sy ? tr.ay + (y - tr.ay) * tr.sy : y) + tr.dy
    ;[minX, maxX] = [tx(minX), tx(maxX)].sort((a, c) => a - c)
    ;[minY, maxY] = [ty(minY), ty(maxY)].sort((a, c) => a - c)
  }
  // Screen space for crisp outlines and fixed-size handles
  return {
    x1: minX * view.zoom + view.x, y1: minY * view.zoom + view.y,
    x2: maxX * view.zoom + view.x, y2: maxY * view.zoom + view.y
  }
}

function drawSelectionBox(ctx, sel, tr) {
  const f = selectionFrame(sel, tr)
  if (!f) return
  ctx.save()
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  ctx.strokeStyle = '#111111'
  ctx.lineWidth = 1
  ctx.setLineDash([4, 3])
  ctx.strokeRect(Math.round(f.x1) + 0.5, Math.round(f.y1) + 0.5, Math.round(f.x2 - f.x1), Math.round(f.y2 - f.y1))
  ctx.setLineDash([])
  ctx.fillStyle = '#ffffff'
  for (const [hx, hy] of handlePoints(f)) {
    ctx.fillRect(hx - 5, hy - 5, 10, 10)
    ctx.strokeRect(hx - 4.5, hy - 4.5, 9, 9)
  }
  ctx.restore()
}

function handlePoints(f) {
  return [[f.x1, f.y1], [f.x2, f.y1], [f.x2, f.y2], [f.x1, f.y2]]
}

function onImageLoaded() {
  // Legacy boards stored a raster image without a size: fill it in once known
  let changed = false
  doc.layers = doc.layers.map((l) => {
    const elements = l.elements.map((el) => {
      const resolved = resolveImageSize(el)
      if (resolved) changed = true
      return resolved || el
    })
    return changed ? { ...l, elements } : l
  })
  if (changed) revision.value += 1
  requestRender()
}

// ---------- sizing ----------

function resize() {
  const stage = stageRef.value
  if (!stage) return
  const rect = stage.getBoundingClientRect()
  // Hidden tab: keep the last real size instead of collapsing to zero
  if (!rect.width || !rect.height) return
  width = rect.width
  height = rect.height
  dpr = window.devicePixelRatio || 1
  for (const c of [staticRef.value, liveRef.value]) {
    c.width = Math.round(width * dpr)
    c.height = Math.round(height * dpr)
    c.style.width = `${width}px`
    c.style.height = `${height}px`
  }
  if (pendingInitialView) applyInitialView()
  requestRender()
}

function applyInitialView() {
  pendingInitialView = false
  if (contentBounds(doc)) {
    fitToContent()
  } else {
    view.x = width / 2
    view.y = height / 2
    setZoom(1)
  }
}

// ---------- view ----------

function setZoom(z, sx = width / 2, sy = height / 2) {
  const nz = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, z))
  view.x = sx - (sx - view.x) * (nz / view.zoom)
  view.y = sy - (sy - view.y) * (nz / view.zoom)
  view.zoom = nz
  zoomPct.value = Math.round(nz * 100)
  requestRender()
}

function zoomBy(f) {
  setZoom(view.zoom * f)
}

function resetZoom() {
  setZoom(1)
}

function fitToContent() {
  const b = contentBounds(doc)
  if (!b || !width) {
    view.x = width / 2
    view.y = height / 2
    setZoom(1)
    return
  }
  const pad = 48
  const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, Math.min(
    (width - pad * 2) / Math.max(1, b.maxX - b.minX), (height - pad * 2) / Math.max(1, b.maxY - b.minY), 2
  )))
  view.zoom = z
  view.x = width / 2 - ((b.minX + b.maxX) / 2) * z
  view.y = height / 2 - ((b.minY + b.maxY) / 2) * z
  zoomPct.value = Math.round(z * 100)
  requestRender()
}

function onWheel(e) {
  const p = screenPoint(e)
  // Pinch on trackpads arrives as ctrl+wheel; a mouse wheel has large integer steps
  const isMouseWheel = e.deltaMode === 1 || (Math.abs(e.deltaY) >= 50 && e.deltaX === 0 && Number.isInteger(e.deltaY))
  if (e.ctrlKey || e.metaKey || isMouseWheel) {
    const factor = Math.exp(-e.deltaY * (e.deltaMode === 1 ? 0.05 : e.ctrlKey ? 0.01 : 0.0015))
    setZoom(view.zoom * factor, p.x, p.y)
  } else {
    view.x -= e.deltaX
    view.y -= e.deltaY
    requestRender()
  }
}

function cycleBackground() {
  doc.background = BACKGROUNDS[(BACKGROUNDS.indexOf(doc.background) + 1) % BACKGROUNDS.length]
  markDirty()
  requestRender()
}

// ---------- tools ----------

function setTool(id) {
  if (textEditor.value) commitText()
  tool.value = id
  if (id !== 'select') setSelection([])
  updateCursor()
  requestRender(false)
}

function updateCursor() {
  if (gesture?.kind === 'pan') cursorStyle.value = 'grabbing'
  else if (spaceDown || tool.value === 'hand') cursorStyle.value = 'grab'
  else if (tool.value === 'eraser') cursorStyle.value = 'none'
  else if (tool.value === 'text') cursorStyle.value = 'text'
  else if (tool.value === 'select') cursorStyle.value = 'default'
  else cursorStyle.value = 'crosshair'
}

function canDrawOnActive() {
  const layer = activeLayer()
  if (!layer.visible) {
    showNotice(t('canvas.layer_hidden_hint'))
    return false
  }
  if (layer.locked) {
    showNotice(t('canvas.layer_locked_hint'))
    return false
  }
  return true
}

function pressureOf(e) {
  // Mouse reports 0.5 while pressed; pens report real pressure (0 can happen on touch-down)
  if (e.pointerType === 'pen') return roundPoint(e.pressure || 0.5, 2)
  return 0.5
}

// ---------- pointer handling ----------

function onPointerDown(e) {
  if (textEditor.value) {
    commitText()
    return
  }
  if (e.pointerType === 'pen') penSeen = true
  // The resize observer may not have run yet right after the tab became visible
  const rect = stageRef.value.getBoundingClientRect()
  if (Math.abs(rect.width - width) > 0.5 || Math.abs(rect.height - height) > 0.5) resize()
  try {
    liveRef.value.setPointerCapture(e.pointerId)
  } catch {
    // Capture is a nicety (strokes continue outside the canvas); drawing works without it
  }
  const p = screenPoint(e)
  pointers.set(e.pointerId, p)

  // Two fingers: pinch-zoom and pan; abandon whatever one finger started
  if (pointers.size === 2 && e.pointerType === 'touch') {
    gesture = startPinch()
    requestRender()
    return
  }
  if (gesture) return

  // With a pen around, fingers only navigate (palm rejection)
  const navigate = e.button === 1 || spaceDown || tool.value === 'hand' || (e.pointerType === 'touch' && penSeen)
  if (navigate) {
    gesture = { kind: 'pan', last: p }
    updateCursor()
    return
  }
  if (e.button !== 0) return

  const w = toWorld(p.x, p.y)
  if (BRUSH_TOOLS.includes(tool.value)) startStroke(w, e)
  else if (SHAPE_TOOLS.includes(tool.value)) startShape(w)
  else if (tool.value === 'eraser') startErase(p)
  else if (tool.value === 'text') {
    // Otherwise the compatibility mousedown that follows moves focus off the new editor, which commits it empty
    e.preventDefault()
    startText(w)
  }
  else if (tool.value === 'select') startSelect(p, w, e)
}

function onPointerMove(e) {
  const p = screenPoint(e)
  hover = p
  if (pointers.has(e.pointerId)) pointers.set(e.pointerId, p)

  if (!gesture) {
    if (tool.value === 'eraser') requestRender(false)
    return
  }
  if (gesture.kind === 'pinch') return updatePinch()
  if (gesture.pointerId !== undefined && gesture.pointerId !== e.pointerId) return

  if (gesture.kind === 'pan') {
    view.x += p.x - gesture.last.x
    view.y += p.y - gesture.last.y
    gesture.last = p
    requestRender()
  } else if (gesture.kind === 'draw') {
    // Coalesced events keep every sample a fast pen produces between frames
    const events = e.getCoalescedEvents ? e.getCoalescedEvents() : [e]
    for (const ce of events.length ? events : [e]) {
      const cp = screenPoint(ce)
      addStrokePoint(toWorld(cp.x, cp.y), pressureOf(ce))
    }
    requestRender(false)
  } else if (gesture.kind === 'shape') {
    updateShape(toWorld(p.x, p.y), e.shiftKey)
  } else if (gesture.kind === 'erase') {
    eraseAlong(p)
  } else if (gesture.kind === 'lasso') {
    gesture.points.push(p.x, p.y)
    requestRender(false)
  } else if (gesture.kind === 'move') {
    const w = toWorld(p.x, p.y)
    gesture.dx = w.x - gesture.start.x
    gesture.dy = w.y - gesture.start.y
    requestRender(false)
  } else if (gesture.kind === 'scale') {
    updateScale(toWorld(p.x, p.y), e.shiftKey)
  }
}

function onPointerUp(e) {
  pointers.delete(e.pointerId)
  if (!gesture) return
  if (gesture.kind === 'pinch') {
    if (pointers.size < 2) gesture = null
    return
  }
  if (gesture.pointerId !== undefined && gesture.pointerId !== e.pointerId) return
  finishGesture(e)
}

function onPointerCancel(e) {
  pointers.delete(e.pointerId)
  if (gesture?.kind === 'erase') {
    // Keep what was erased so far as one undo step
    finishGesture(e)
    return
  }
  gesture = null
  requestRender()
}

function onPointerLeave() {
  hover = null
  if (tool.value === 'eraser') requestRender(false)
}

function finishGesture(e) {
  const g = gesture
  gesture = null
  if (g.kind === 'draw') finishStroke(g)
  else if (g.kind === 'shape') finishShape(g)
  else if (g.kind === 'erase') finishErase(g)
  else if (g.kind === 'lasso') finishLasso(g, e.shiftKey)
  else if (g.kind === 'move') finishMove(g)
  else if (g.kind === 'scale') finishScale(g)
  updateCursor()
  requestRender()
}

// Pinch

function startPinch() {
  const [a, b] = [...pointers.values()]
  return {
    kind: 'pinch',
    dist: Math.hypot(a.x - b.x, a.y - b.y) || 1,
    mid: { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 },
    zoom: view.zoom,
    vx: view.x,
    vy: view.y
  }
}

function updatePinch() {
  const [a, b] = [...pointers.values()]
  if (!a || !b) return
  const g = gesture
  const dist = Math.hypot(a.x - b.x, a.y - b.y)
  const mid = { x: (a.x + b.x) / 2, y: (a.y + b.y) / 2 }
  const z = Math.min(MAX_ZOOM, Math.max(MIN_ZOOM, g.zoom * (dist / g.dist)))
  // Keep the world point under the initial midpoint under the current midpoint
  const wx = (g.mid.x - g.vx) / g.zoom
  const wy = (g.mid.y - g.vy) / g.zoom
  view.zoom = z
  view.x = mid.x - wx * z
  view.y = mid.y - wy * z
  zoomPct.value = Math.round(z * 100)
  requestRender()
}

// Freehand strokes

function startStroke(w, e) {
  if (!canDrawOnActive()) return
  gesture = {
    kind: 'draw',
    pointerId: e.pointerId,
    element: {
      id: uid(), type: 'stroke', tool: tool.value, color: color.value,
      size: sizes.value.brush, opacity: opacity.value / 100, points: []
    }
  }
  addStrokePoint(w, pressureOf(e))
  requestRender(false)
}

function addStrokePoint(w, pressure) {
  const pts = gesture.element.points
  const n = pts.length
  // Skip sub-pixel jitter; it only adds weight to the saved board
  if (n && Math.hypot(pts[n - 3] - w.x, pts[n - 2] - w.y) < 0.6 / view.zoom) return
  pts.push(roundPoint(w.x), roundPoint(w.y), pressure)
}

function finishStroke(g) {
  const el = g.element
  if (!el.points.length) return
  const layer = activeLayer()
  commit(mapLayer(layer.id, (l) => ({ ...l, elements: [...l.elements, el] })))
}

// Shapes

function startShape(w) {
  if (!canDrawOnActive()) return
  gesture = {
    kind: 'shape',
    start: w,
    element: null
  }
}

function updateShape(w, constrain) {
  const g = gesture
  let { x, y } = w
  if (constrain) {
    const dx = x - g.start.x
    const dy = y - g.start.y
    if (tool.value === 'line') {
      // Snap to 45° steps
      const angle = Math.round(Math.atan2(dy, dx) / (Math.PI / 4)) * (Math.PI / 4)
      const len = Math.hypot(dx, dy)
      x = g.start.x + Math.cos(angle) * len
      y = g.start.y + Math.sin(angle) * len
    } else {
      const side = Math.max(Math.abs(dx), Math.abs(dy))
      x = g.start.x + Math.sign(dx || 1) * side
      y = g.start.y + Math.sign(dy || 1) * side
    }
  }
  g.element = {
    id: uid(), type: tool.value, color: color.value, size: sizes.value.shape, opacity: opacity.value / 100,
    x1: roundPoint(g.start.x), y1: roundPoint(g.start.y), x2: roundPoint(x), y2: roundPoint(y)
  }
  requestRender(false)
}

function finishShape(g) {
  const el = g.element
  if (!el || Math.hypot(el.x2 - el.x1, el.y2 - el.y1) * view.zoom < 3) return
  const layer = activeLayer()
  commit(mapLayer(layer.id, (l) => ({ ...l, elements: [...l.elements, el] })))
}

// Eraser

function startErase(p) {
  gesture = { kind: 'erase', before: doc.layers, last: null, changed: false }
  eraseAlong(p)
}

function eraseAlong(p) {
  const g = gesture
  const r = sizes.value.eraser / 2 / view.zoom
  const w = toWorld(p.x, p.y)
  // Fill the gap since the last event so quick swipes erase continuously
  const stops = []
  if (g.last) {
    const dist = Math.hypot(w.x - g.last.x, w.y - g.last.y)
    const steps = Math.max(1, Math.ceil(dist / (r / 2)))
    for (let i = 1; i <= steps; i++) {
      stops.push({ x: g.last.x + ((w.x - g.last.x) * i) / steps, y: g.last.y + ((w.y - g.last.y) * i) / steps })
    }
  } else {
    stops.push(w)
  }
  g.last = w

  let layers = doc.layers
  for (const s of stops) {
    layers = layers.map((l) => {
      if (!l.visible || l.locked) return l
      let changed = false
      const out = []
      for (const el of l.elements) {
        if (!hitTest(el, s.x, s.y, r)) {
          out.push(el)
          continue
        }
        if (eraserMode.value === 'precise' && el.type === 'stroke') {
          const pieces = eraseFromStroke(el, s.x, s.y, r)
          if (pieces === null) {
            out.push(el)
            continue
          }
          out.push(...pieces)
        }
        changed = true
      }
      return changed ? { ...l, elements: out } : l
    })
  }
  if (layers !== doc.layers && layers.some((l, i) => l !== doc.layers[i])) {
    doc.layers = layers
    g.changed = true
    requestRender()
  } else {
    requestRender(false)
  }
}

function finishErase(g) {
  if (!g.changed) return
  past.push(g.before)
  if (past.length > 300) past.shift()
  future = []
  touched()
}

// Text

function startText(w, existing = null) {
  if (!existing && !canDrawOnActive()) return
  textEditor.value = existing
    ? { x: existing.x, y: existing.y, text: existing.text, size: existing.size, color: existing.color, editId: existing.id }
    : { x: w.x, y: w.y, text: '', size: sizes.value.text, color: color.value, editId: null }
  nextTick(() => textRef.value?.focus())
}

function commitText() {
  const ed = textEditor.value
  if (!ed) return
  textEditor.value = null
  const text = ed.text.replace(/\s+$/, '')
  if (ed.editId) {
    const layer = doc.layers.find((l) => l.elements.some((el) => el.id === ed.editId))
    if (!layer) return
    commit(mapLayer(layer.id, (l) => ({
      ...l,
      elements: text
        ? l.elements.map((el) => (el.id === ed.editId ? { ...el, text } : el))
        : l.elements.filter((el) => el.id !== ed.editId)
    })))
    return
  }
  if (!text) return
  const el = { id: uid(), type: 'text', x: roundPoint(ed.x), y: roundPoint(ed.y), text, size: ed.size, color: ed.color, opacity: 1 }
  commit(mapLayer(activeLayer().id, (l) => ({ ...l, elements: [...l.elements, el] })))
}

function onDoubleClick(e) {
  if (tool.value !== 'select') return
  const p = screenPoint(e)
  const w = toWorld(p.x, p.y)
  const el = topElementAt(w, 4 / view.zoom)
  if (el && el.type === 'text') {
    setSelection([])
    startText(w, el)
  }
}

// Selection

function topElementAt(w, r) {
  const layers = editableLayers()
  for (let i = layers.length - 1; i >= 0; i--) {
    const els = layers[i].elements
    for (let j = els.length - 1; j >= 0; j--) if (hitTest(els[j], w.x, w.y, r)) return els[j]
  }
  return null
}

function startSelect(p, w, e) {
  const sel = selectedElements()
  const f = sel.length ? selectionFrame(sel) : null
  if (f) {
    const corners = handlePoints(f)
    const idx = corners.findIndex(([hx, hy]) => Math.abs(hx - p.x) <= 8 && Math.abs(hy - p.y) <= 8)
    if (idx >= 0) {
      const b = unionBounds(sel)
      const anchorCorner = [[b.maxX, b.maxY], [b.minX, b.maxY], [b.minX, b.minY], [b.maxX, b.minY]][idx]
      const dragCorner = [[b.minX, b.minY], [b.maxX, b.minY], [b.maxX, b.maxY], [b.minX, b.maxY]][idx]
      gesture = {
        kind: 'scale', pointerId: e.pointerId,
        ax: anchorCorner[0], ay: anchorCorner[1], cx: dragCorner[0], cy: dragCorner[1],
        transform: { dx: 0, dy: 0, sx: 1, sy: 1, ax: anchorCorner[0], ay: anchorCorner[1] }
      }
      return
    }
    if (p.x >= f.x1 && p.x <= f.x2 && p.y >= f.y1 && p.y <= f.y2) {
      gesture = { kind: 'move', pointerId: e.pointerId, start: w, dx: 0, dy: 0 }
      requestRender()
      return
    }
  }
  gesture = { kind: 'lasso', pointerId: e.pointerId, points: [p.x, p.y], start: w }
}

function finishLasso(g, additive) {
  const pts = g.points
  let span = 0
  for (let i = 2; i < pts.length; i += 2) span = Math.max(span, Math.hypot(pts[i] - pts[0], pts[i + 1] - pts[1]))

  if (span < 6) {
    // A click: pick the topmost element under the pointer
    const el = topElementAt(g.start, 6 / view.zoom)
    if (!el) {
      if (!additive) setSelection([])
      return
    }
    const ids = new Set(additive ? selection : [])
    if (ids.has(el.id)) ids.delete(el.id)
    else ids.add(el.id)
    setSelection([...ids])
    return
  }

  const poly = []
  for (let i = 0; i < pts.length; i += 2) {
    const w = toWorld(pts[i], pts[i + 1])
    poly.push(w.x, w.y)
  }
  const ids = new Set(additive ? selection : [])
  for (const l of editableLayers()) for (const el of l.elements) if (insideLasso(el, poly)) ids.add(el.id)
  setSelection([...ids])
}

function finishMove(g) {
  if (Math.abs(g.dx) < 0.01 && Math.abs(g.dy) < 0.01) return
  applyToSelection((el) => transformElement(el, { dx: g.dx, dy: g.dy }))
}

function updateScale(w, free) {
  const g = gesture
  const bw = g.cx - g.ax || 1
  const bh = g.cy - g.ay || 1
  let sx = (w.x - g.ax) / bw
  let sy = (w.y - g.ay) / bh
  if (!free) {
    // Uniform by default; Shift scales each axis freely
    const s = Math.abs(sx) > Math.abs(sy) ? sx : sy
    sx = s
    sy = s
  }
  const clamp = (v) => (Math.abs(v) < 0.02 ? 0.02 * Math.sign(v || 1) : v)
  g.transform = { dx: 0, dy: 0, sx: clamp(sx), sy: clamp(sy), ax: g.ax, ay: g.ay }
  requestRender(false)
}

function finishScale(g) {
  const tr = g.transform
  if (tr.sx === 1 && tr.sy === 1) return
  applyToSelection((el) => transformElement(el, tr))
}

function applyToSelection(fn) {
  commit(doc.layers.map((l) => {
    if (!l.visible || l.locked || !l.elements.some((el) => selection.has(el.id))) return l
    return { ...l, elements: l.elements.map((el) => (selection.has(el.id) ? fn(el) : el)) }
  }))
}

function duplicateSelection() {
  const ids = []
  const offset = 16 / view.zoom
  commit(doc.layers.map((l) => {
    if (!l.visible || l.locked) return l
    const copies = l.elements
      .filter((el) => selection.has(el.id))
      .map((el) => {
        const copy = { ...transformElement(el, { dx: offset, dy: offset }), id: uid() }
        ids.push(copy.id)
        return copy
      })
    return copies.length ? { ...l, elements: [...l.elements, ...copies] } : l
  }))
  setSelection(ids)
}

function deleteSelection() {
  if (!selection.size) return
  commit(doc.layers.map((l) => (
    l.visible && !l.locked && l.elements.some((el) => selection.has(el.id))
      ? { ...l, elements: l.elements.filter((el) => !selection.has(el.id)) }
      : l
  )))
  setSelection([])
}

function reorderSelection(toFront) {
  commit(doc.layers.map((l) => {
    if (!l.visible || l.locked) return l
    const chosen = l.elements.filter((el) => selection.has(el.id))
    if (!chosen.length) return l
    const rest = l.elements.filter((el) => !selection.has(el.id))
    return { ...l, elements: toFront ? [...rest, ...chosen] : [...chosen, ...rest] }
  }))
}

// ---------- history ----------

function undo() {
  if (!past.length) return
  future.push(doc.layers)
  doc.layers = past.pop()
  afterHistoryJump()
}

function redo() {
  if (!future.length) return
  past.push(doc.layers)
  doc.layers = future.pop()
  afterHistoryJump()
}

function afterHistoryJump() {
  if (!doc.layers.some((l) => l.id === doc.activeLayerId)) doc.activeLayerId = doc.layers[doc.layers.length - 1].id
  setSelection([])
  touched()
  requestRender()
}

// ---------- layers ----------

function setActiveLayer(id) {
  doc.activeLayerId = id
  revision.value += 1
}

function addLayer() {
  const layer = createLayer(t('canvas.layer_default', { n: doc.layers.length + 1 }))
  const idx = doc.layers.findIndex((l) => l.id === doc.activeLayerId)
  const layers = [...doc.layers]
  layers.splice(idx + 1, 0, layer)
  doc.activeLayerId = layer.id
  commit(layers)
}

function deleteLayer(id) {
  if (doc.layers.length < 2) return
  const layer = doc.layers.find((l) => l.id === id)
  if (layer.elements.length && !confirm(t('canvas.layer_delete_confirm', { name: layer.name }))) return
  const layers = doc.layers.filter((l) => l.id !== id)
  if (doc.activeLayerId === id) doc.activeLayerId = layers[layers.length - 1].id
  commit(layers)
}

function toggleLayer(id, field) {
  commit(mapLayer(id, (l) => ({ ...l, [field]: !l[field] })))
  setSelection([])
}

function moveLayer(dir) {
  const idx = doc.layers.findIndex((l) => l.id === doc.activeLayerId)
  const target = idx + dir
  if (idx < 0 || target < 0 || target >= doc.layers.length) return
  const layers = [...doc.layers]
  ;[layers[idx], layers[target]] = [layers[target], layers[idx]]
  commit(layers)
}

function renameLayer(id) {
  const layer = doc.layers.find((l) => l.id === id)
  const name = prompt(t('canvas.layer_rename'), layer.name)
  if (name && name.trim()) commit(mapLayer(id, (l) => ({ ...l, name: name.trim().slice(0, 60) })))
}

// ---------- boards & saving ----------

const base = computed(() => `/api/workspaces/${props.workspaceId}/documents`)

function markDirty() {
  saveState.value = 'dirty'
  if (liveEver && boardId.value) return syncNow()
  clearTimeout(saveTimer)
  saveTimer = setTimeout(save, 1200)
}

// ---------- live sync ----------

function state() {
  return { layers: doc.layers, background: doc.background }
}

function refreshSaveState() {
  if (liveStatus.value === 'live') saveState.value = pending.size ? 'saving' : 'saved'
}

// Send everything that changed since the last send; unsent changes wait for the next connect
function syncNow() {
  if (liveStatus.value !== 'live') return
  const ops = diffState(shadow, state())
  if (boardTitle.value !== shadow.title) ops.push({ op: 'title', title: boardTitle.value })
  const cid = ops.length ? live.send(ops) : null
  if (cid !== null) {
    pending.set(cid, ops)
    shadow = { ...state(), title: boardTitle.value }
  }
  refreshSaveState()
}

function setDocState({ layers, background }) {
  doc.layers = layers
  doc.background = background
  if (!layers.some((l) => l.id === doc.activeLayerId)) doc.activeLayerId = layers[layers.length - 1].id
  const ids = new Set(layers.flatMap((l) => l.elements.map((el) => el.id)))
  setSelection([...selection].filter((id) => ids.has(id)))
  revision.value += 1
  requestRender()
}

function setTitle(title) {
  boardTitle.value = title
  boards.value = boards.value.map((b) => (b.id === boardId.value ? { ...b, title } : b))
}

function startLive() {
  stopLive()
  if (!boardId.value) return
  shadow = { ...state(), title: boardTitle.value }
  acked = state()
  pending = new Map()
  liveEver = false
  live = connectBoard({
    workspaceId: props.workspaceId,
    boardId: boardId.value,
    onInit: onLiveInit,
    onOps: onLiveOps,
    onAck: onLiveAck,
    onReset: onLiveReset,
    onPeers: (list) => { peers.value = list },
    onStatus: onLiveStatus
  })
}

function stopLive() {
  syncNow()
  live?.close()
  live = null
  liveStatus.value = 'off'
  peers.value = []
}

function onLiveStatus(s) {
  liveStatus.value = s
  // Denied means the socket is gone for good: the HTTP save path takes over
  if (s === 'denied' && liveEver) {
    liveEver = false
    markDirty()
  }
}

function onLiveInit(msg) {
  const keepTitle = hasPendingTitle() || boardTitle.value !== shadow.title
  const local = [...pending.values()].flat().concat(diffState(shadow, state()))
  const server = { layers: msg.doc.layers, background: msg.doc.background }
  setDocState(applyOps(server, local))
  acked = server
  pending = new Map()
  shadow = { ...server, title: msg.title }
  if (!keepTitle) setTitle(msg.title)
  liveEver = true
  myConnId = msg.you
  peers.value = msg.peers
  syncNow()
}

function onLiveOps(msg) {
  syncNow()
  acked = applyOps(acked, msg.ops)
  setDocState(applyOps(acked, [...pending.values()].flat()))
  shadow = { ...state(), title: shadow.title }
  // Rebase undo history so undo keeps others' changes and reverts only ours
  const rebase = (layers) => applyOps({ layers, background: doc.background }, msg.ops).layers
  past = past.map(rebase)
  future = future.map(rebase)
  if (gesture?.kind === 'erase') gesture.before = rebase(gesture.before)
  // Our own unsent title wins: the server applies it after this remote one
  const title = msg.ops.filter((o) => o.op === 'title').pop()
  if (title && !hasPendingTitle()) {
    setTitle(title.title)
    shadow.title = title.title
  }
  refreshSaveState()
}

function hasPendingTitle() {
  return [...pending.values()].some((ops) => ops.some((o) => o.op === 'title'))
}

function onLiveAck(cid) {
  const ops = pending.get(cid)
  if (ops) acked = applyOps(acked, ops)
  pending.delete(cid)
  refreshSaveState()
}

function onLiveReset(msg) {
  acked = { layers: msg.doc.layers, background: msg.doc.background }
  pending = new Map()
  past = []
  future = []
  setDocState(acked)
  shadow = { ...acked, title: msg.title }
  setTitle(msg.title)
  refreshSaveState()
}

async function save() {
  clearTimeout(saveTimer)
  saveTimer = null
  if (liveEver && boardId.value) return syncNow()
  if (saveState.value !== 'dirty' || !props.workspaceId) return
  saveState.value = 'saving'
  const workspaceId = props.workspaceId
  doc.view = { x: view.x, y: view.y, zoom: view.zoom }
  const payload = { title: boardTitle.value, content_raw: serializeDocument(doc) }
  try {
    if (boardId.value) {
      await api.put(`/api/workspaces/${workspaceId}/documents/${boardId.value}`, payload)
    } else {
      const created = await api.post(`/api/workspaces/${workspaceId}/documents`, { ...payload, doc_type: 'canvas' })
      boardId.value = created.id
      boards.value = [...boards.value, { id: created.id, title: created.title }]
      startLive()
    }
    // Changes made while the request was in flight are saved by the next timer
    if (saveState.value === 'saving') saveState.value = 'saved'
  } catch (err) {
    saveState.value = 'error'
    console.error('Failed to save board:', err)
  }
}

function loadBoard(record) {
  stopLive()
  doc = record ? parseDocument(record.content_raw || '', t('canvas.layer_default', { n: 1 })) : createDocument(t('canvas.layer_default', { n: 1 }))
  boardId.value = record ? record.id : null
  boardTitle.value = record ? record.title : t('canvas.board_default', { n: boards.value.length + 1 })
  past = []
  future = []
  setSelection([])
  saveState.value = 'saved'
  revision.value += 1
  if (doc.view && doc.view.zoom && record && !record.content_raw?.startsWith('data:image')) {
    Object.assign(view, doc.view)
    zoomPct.value = Math.round(view.zoom * 100)
    requestRender()
  } else if (width) {
    applyInitialView()
  } else {
    pendingInitialView = true
  }
  if (record) startLive()
}

async function fetchBoards(selectId = null) {
  if (!props.workspaceId) return
  try {
    const list = await api.get(`${base.value}?doc_type=canvas`)
    boards.value = list.map((d) => ({ id: d.id, title: d.title }))
    const record = list.find((d) => d.id === selectId) || list[0] || null
    loadBoard(record)
  } catch (err) {
    console.error('Failed to load boards:', err)
  }
}

async function switchBoard(value) {
  const id = Number(value)
  if (!id || id === boardId.value) return
  await save()
  try {
    loadBoard(await api.get(`${base.value}/${id}`))
  } catch (err) {
    showNotice(t('common.error'))
  }
}

async function newBoard() {
  await save()
  loadBoard(null)
}

async function renameBoard() {
  const name = prompt(t('canvas.rename_board'), boardTitle.value)
  if (!name || !name.trim()) return
  boardTitle.value = name.trim().slice(0, 120)
  boards.value = boards.value.map((b) => (b.id === boardId.value ? { ...b, title: boardTitle.value } : b))
  markDirty()
}

async function deleteBoard() {
  if (!boardId.value || !confirm(t('canvas.delete_board_confirm', { name: boardTitle.value }))) return
  clearTimeout(saveTimer)
  stopLive()
  try {
    await api.delete(`${base.value}/${boardId.value}`)
    boards.value = boards.value.filter((b) => b.id !== boardId.value)
    saveState.value = 'saved'
    const next = boards.value[0]
    loadBoard(next ? await api.get(`${base.value}/${next.id}`) : null)
  } catch (err) {
    showNotice(t('common.error'))
  }
}

// ---------- export ----------

function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  setTimeout(() => URL.revokeObjectURL(url), 1000)
}

async function downloadPng() {
  const blob = await exportPng(doc)
  if (!blob) return showNotice(t('canvas.empty_board'))
  downloadBlob(blob, `${boardTitle.value || 'board'}.png`)
}

function downloadSvg() {
  const svg = exportSvg(doc)
  if (!svg) return showNotice(t('canvas.empty_board'))
  downloadBlob(new Blob([svg], { type: 'image/svg+xml' }), `${boardTitle.value || 'board'}.svg`)
}

// ---------- keyboard ----------

function isVisible() {
  return stageRef.value && stageRef.value.offsetParent !== null
}

function onKeyDown(e) {
  if (!isVisible()) return
  const tag = e.target?.tagName
  if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT' || e.target?.isContentEditable) return
  const mod = e.ctrlKey || e.metaKey
  const key = e.key.toLowerCase()

  if (mod && key === 'z') {
    e.preventDefault()
    if (e.shiftKey) redo()
    else undo()
  } else if (mod && key === 'y') {
    e.preventDefault()
    redo()
  } else if (mod && key === 'd') {
    e.preventDefault()
    duplicateSelection()
  } else if (mod && key === 'a' && tool.value === 'select') {
    e.preventDefault()
    setSelection(editableLayers().flatMap((l) => l.elements.map((el) => el.id)))
  } else if ((key === 'delete' || key === 'backspace') && selection.size) {
    e.preventDefault()
    deleteSelection()
  } else if (key === 'escape') {
    setSelection([])
  } else if (key === ' ' && !spaceDown) {
    e.preventDefault()
    spaceDown = true
    updateCursor()
  } else if (e.shiftKey && e.code === 'Digit1') {
    fitToContent()
  } else if (mod && key === '0') {
    e.preventDefault()
    resetZoom()
  } else if (!mod && (key === '=' || key === '+')) {
    zoomBy(1.25)
  } else if (!mod && key === '-') {
    zoomBy(1 / 1.25)
  } else if (!mod && !e.altKey && TOOL_KEYS[key]) {
    setTool(TOOL_KEYS[key])
  } else if (!mod && key === '[') {
    currentSize.value = Math.max(sizeRange.value[0], currentSize.value - 1)
  } else if (!mod && key === ']') {
    currentSize.value = Math.min(sizeRange.value[1], currentSize.value + 1)
  }
}

function onKeyUp(e) {
  if (e.key === ' ') {
    spaceDown = false
    updateCursor()
  }
}

function onBeforeUnload(e) {
  if (saveState.value === 'dirty' || saveState.value === 'saving') {
    save()
    e.preventDefault()
  }
}

watch(() => props.workspaceId, async (id) => {
  if (!id) return
  await save()
  fetchBoards()
})

watch(tool, updateCursor)
watch(boardId, (id) => emit('update:selectedBoardId', id))

onMounted(() => {
  resizeObserver = new ResizeObserver(resize)
  resizeObserver.observe(stageRef.value)
  window.addEventListener('keydown', onKeyDown)
  window.addEventListener('keyup', onKeyUp)
  window.addEventListener('beforeunload', onBeforeUnload)
  resize()
  fetchBoards(props.selectedBoardId)
})

onBeforeUnmount(() => {
  save()
  stopLive()
  resizeObserver?.disconnect()
  cancelAnimationFrame(frame)
  window.removeEventListener('keydown', onKeyDown)
  window.removeEventListener('keyup', onKeyUp)
  window.removeEventListener('beforeunload', onBeforeUnload)
})
</script>

<style scoped>
.whiteboard {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  height: max(520px, calc(100vh - 230px));
}

.wb-topbar {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding: 0.5rem;
}

.wb-group {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
}

.wb-board-select {
  width: auto;
  max-width: 14rem;
  padding: 0.25rem 0.5rem;
  font-size: 0.8125rem;
}

.wb-save-state {
  margin-left: 0.25rem;
  white-space: nowrap;
}

.wb-sep {
  width: 1px;
  height: 1.25rem;
  margin: 0 0.25rem;
  background-color: var(--color-ink-100);
}

.wb-zoom {
  min-width: 3.5rem;
  font-variant-numeric: tabular-nums;
}

.wb-body {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 0.5rem;
}

.wb-tools {
  display: flex;
  flex-direction: column;
  gap: 0.25rem;
  padding: 0.35rem;
  align-self: flex-start;
}

.wb-tool {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2.25rem;
  height: 2.25rem;
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--color-ink-700);
  cursor: pointer;
  transition: background-color 120ms, color 120ms, border-color 120ms;
}

.wb-tool:hover {
  border-color: var(--color-ink-300);
}

.wb-tool.active {
  background-color: var(--color-ink-900);
  color: var(--color-paper);
}

.wb-stage {
  position: relative;
  flex: 1;
  min-width: 0;
  overflow: hidden;
  border: var(--border-crisp);
  border-radius: var(--radius-lg);
  background-color: #ffffff;
}

.wb-canvas {
  position: absolute;
  inset: 0;
  display: block;
}

.wb-live {
  touch-action: none;
}

.wb-text-editor {
  position: absolute;
  z-index: 5;
  min-width: 4rem;
  min-height: 1.5em;
  padding: 0;
  margin: 0;
  border: 1px dashed var(--color-ink-500);
  border-radius: var(--radius-sm);
  background: rgba(255, 255, 255, 0.85);
  font-family: Inter, system-ui, sans-serif;
  resize: both;
  outline: none;
  field-sizing: content;
}

.wb-props {
  position: absolute;
  left: 50%;
  bottom: 0.75rem;
  transform: translateX(-50%);
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  justify-content: center;
  gap: 0.75rem;
  max-width: calc(100% - 1.5rem);
  padding: 0.4rem 0.75rem;
  z-index: 4;
}

.wb-colors {
  display: flex;
  align-items: center;
  gap: 0.25rem;
}

.wb-swatch {
  width: 1.25rem;
  height: 1.25rem;
  border: 1px solid var(--color-ink-300);
  border-radius: 50%;
  cursor: pointer;
  padding: 0;
}

.wb-swatch.active {
  outline: 2px solid var(--color-ink-900);
  outline-offset: 1px;
}

.wb-swatch-custom {
  position: relative;
  overflow: hidden;
  background: conic-gradient(#b23a2e, #c98a1c, #2f7a3b, #1f4e8c, #6b3fa0, #b23a2e);
}

.wb-swatch-custom input {
  position: absolute;
  inset: 0;
  opacity: 0;
  cursor: pointer;
}

.wb-slider {
  display: flex;
  align-items: center;
  gap: 0.4rem;
}

.wb-slider input {
  width: 6.5rem;
  accent-color: var(--color-ink-900);
}

.wb-value {
  min-width: 2.25rem;
  font-variant-numeric: tabular-nums;
}

.wb-notice {
  position: absolute;
  top: 0.75rem;
  left: 50%;
  transform: translateX(-50%);
  padding: 0.4rem 0.8rem;
  border-radius: var(--radius);
  background-color: var(--color-ink-900);
  color: var(--color-paper);
  z-index: 6;
}

.wb-layers {
  width: 15rem;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  padding: 0.5rem;
  gap: 0.5rem;
}

.wb-layers-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
}

.wb-layer-list {
  overflow-y: auto;
}

.wb-layer {
  display: flex;
  align-items: center;
  gap: 0.25rem;
  padding: 0.35rem 0.25rem;
  border-bottom: var(--border-faint);
  border-radius: var(--radius-sm);
  cursor: pointer;
}

.wb-layer.active {
  background-color: var(--color-ink-900);
  color: var(--color-paper);
}

.wb-layer-count {
  opacity: 0.6;
}

.wb-icon {
  display: inline-flex;
  padding: 0.2rem;
  background: none;
  border: none;
  color: inherit;
  cursor: pointer;
}

.wb-icon:disabled {
  opacity: 0.3;
  cursor: default;
}

@media (max-width: 767px) {
  .whiteboard {
    height: calc(100vh - 160px);
    min-height: 480px;
  }

  .wb-body {
    flex-direction: column;
  }

  .wb-tools {
    flex-direction: row;
    overflow-x: auto;
    align-self: stretch;
    order: 2;
  }

  .wb-stage {
    order: 1;
  }

  .wb-layers {
    position: absolute;
    right: 0.5rem;
    top: 4rem;
    z-index: 8;
    max-height: 60%;
  }

  .whiteboard {
    position: relative;
  }

  .wb-props {
    gap: 0.5rem;
    padding: 0.35rem 0.5rem;
  }

  .wb-slider input {
    width: 5rem;
  }
}
</style>
