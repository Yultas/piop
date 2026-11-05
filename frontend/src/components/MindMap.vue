<template>
  <div class="mindmap-container flex flex-col gap-3">
    <!-- Toolbar -->
    <div class="toolbar eink-card p-3 flex flex-wrap justify-between items-center gap-2">
      <!-- Node Actions -->
      <div class="flex items-center gap-2 flex-wrap">
        <button
          class="eink-btn eink-btn-sm"
          :disabled="!selectedNode"
          @click="addChildNode"
        >
          <CornerDownRight :size="14" /> {{ $t('mindmap.add_child') }}
        </button>
        <button
          class="eink-btn eink-btn-sm"
          :disabled="!selectedNode || selectedNode.id === 'root'"
          @click="addSiblingNode"
        >
          <Plus :size="14" /> {{ $t('mindmap.add_sibling') }}
        </button>
        <button
          class="eink-btn eink-btn-sm text-muted hover:text-ink-900"
          :disabled="!selectedNode || selectedNode.id === 'root'"
          @click="deleteSelectedNode"
        >
          <Trash2 :size="14" /> {{ $t('mindmap.delete_node') }}
        </button>

        <!-- Selected Node Text Editor -->
        <div v-if="selectedNode" class="flex items-center gap-1 border-l pl-2 ml-1">
          <input
            v-model="selectedNode.text"
            type="text"
            class="eink-input text-xs font-sans py-1 px-2 w-48 font-bold"
            @keydown.enter.prevent
          />
        </div>
      </div>

      <!-- Map & File Actions -->
      <div class="flex items-center gap-2">
        <button class="eink-btn eink-btn-sm" @click="resetView">
          <LocateFixed :size="14" /> {{ $t('mindmap.reset_view') }}
        </button>
        <button class="eink-btn eink-btn-sm" @click="exportSvg">
          <Download :size="14" /> {{ $t('mindmap.export_svg') }}
        </button>
        <button
          class="eink-btn eink-btn-sm eink-btn-dark"
          :disabled="saving"
          @click="saveMindMap"
        >
          <Save :size="14" /> {{ saving ? $t('common.loading') : $t('mindmap.save_map') }}
        </button>
      </div>
    </div>

    <!-- Interactive Canvas SVG Area -->
    <div
      ref="mapContainerRef"
      class="mindmap-viewport border bg-paper eink-card flex-1 relative overflow-auto select-none"
      @click.self="selectedNodeId = null"
    >
      <div class="text-xs text-muted p-2 absolute top-2 left-2 z-10 bg-paper-card border px-2 py-1">
        <Info :size="14" /> {{ $t('mindmap.edit_hint') }}
      </div>

      <svg
        ref="svgRef"
        :width="computedSvgWidth"
        :height="computedSvgHeight"
        class="mindmap-svg"
      >
        <!-- Connection Lines -->
        <g class="mindmap-links">
          <path
            v-for="link in layoutLinks"
            :key="link.id"
            :d="link.path"
            fill="none"
            stroke="var(--color-ink-900)"
            stroke-width="1.5"
          />
        </g>

        <!-- Nodes -->
        <g class="mindmap-nodes">
          <g
            v-for="node in layoutNodes"
            :key="node.id"
            :transform="`translate(${node.x}, ${node.y})`"
            class="node-group cursor-pointer"
            @click.stop="selectNode(node)"
            @dblclick.stop="startEdit(node)"
          >
            <!-- Node Box -->
            <rect
              :width="node.width"
              :height="node.height"
              :rx="0"
              :ry="0"
              :class="getNodeRectClass(node)"
            />

            <!-- Node Text -->
            <text
              :x="node.width / 2"
              :y="node.height / 2 + 4"
              text-anchor="middle"
              :class="getNodeTextClass(node)"
              class="text-xs select-none"
            >
              {{ truncateText(node.text, 22) }}
            </text>

            <!-- Collapse/Expand Indicator Button (if has children) -->
            <g
              v-if="node.hasChildren"
              :transform="`translate(${node.width + 8}, ${node.height / 2})`"
              class="cursor-pointer"
              @click.stop="toggleCollapse(node.rawNode)"
            >
              <circle
                cx="0"
                cy="0"
                r="7"
                fill="var(--color-paper-card)"
                stroke="var(--color-ink-900)"
                stroke-width="1.5"
              />
              <text
                cx="0"
                cy="3"
                text-anchor="middle"
                font-size="9"
                font-weight="bold"
                font-family="monospace"
                fill="var(--color-ink-900)"
              >
                {{ node.rawNode.collapsed ? '+' : '-' }}
              </text>
            </g>
          </g>
        </g>
      </svg>
    </div>
  </div>
</template>

<script setup>
import { Trash2, LocateFixed, Download, Save, Info, Plus, CornerDownRight } from 'lucide-vue-next'
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api/client'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  }
})

const { t } = useI18n()

const defaultTree = {
  id: 'root',
  text: "Pi'op",
  collapsed: false,
  children: [
    {
      id: 'node-chat',
      text: 'Slack Chat & Tasks',
      collapsed: false,
      children: [
        { id: 'node-chat-1', text: 'Channels (#general)', children: [] },
        { id: 'node-chat-2', text: 'Message Threads', children: [] },
        { id: 'node-chat-3', text: 'Convert /task API', children: [] }
      ]
    },
    {
      id: 'node-docs',
      text: 'Markdown & Typst',
      collapsed: false,
      children: [
        { id: 'node-docs-1', text: 'Mermaid Diagrams', children: [] },
        { id: 'node-docs-2', text: 'Typst Vector SVG', children: [] },
        { id: 'node-docs-3', text: 'Debounced Compiler', children: [] }
      ]
    },
    {
      id: 'node-tools',
      text: 'Whiteboard & MindMap',
      collapsed: false,
      children: [
        { id: 'node-tools-1', text: 'Tree SVG Layout', children: [] },
        { id: 'node-tools-2', text: 'Monochrome HTML5 Canvas', children: [] }
      ]
    },
    {
      id: 'node-storage',
      text: 'Storage & Security',
      collapsed: false,
      children: [
        { id: 'node-sec-1', text: 'Device Fingerprint', children: [] },
        { id: 'node-sec-2', text: 'Strict MB Quotas', children: [] }
      ]
    }
  ]
}

const rootNode = ref(JSON.parse(JSON.stringify(defaultTree)))
const selectedNodeId = ref('root')
const saving = ref(false)
const docId = ref(null)
const mapContainerRef = ref(null)
const svgRef = ref(null)

const selectedNode = computed(() => {
  if (!selectedNodeId.value) return null
  return findNodeById(rootNode.value, selectedNodeId.value)
})

function findNodeById(current, id) {
  if (current.id === id) return current
  if (current.children) {
    for (const child of current.children) {
      const found = findNodeById(child, id)
      if (found) return found
    }
  }
  return null
}

function findParentNode(current, targetId) {
  if (current.children) {
    for (const child of current.children) {
      if (child.id === targetId) return current
      const found = findParentNode(child, targetId)
      if (found) return found
    }
  }
  return null
}

function selectNode(layoutNode) {
  selectedNodeId.value = layoutNode.id
}

function startEdit(layoutNode) {
  selectedNodeId.value = layoutNode.id
}

function toggleCollapse(node) {
  node.collapsed = !node.collapsed
}

function addChildNode() {
  const current = selectedNode.value
  if (!current) return
  if (!current.children) current.children = []
  current.collapsed = false
  const newId = `node-${Date.now()}`
  current.children.push({
    id: newId,
    text: t('mindmap.child_node'),
    collapsed: false,
    children: []
  })
  selectedNodeId.value = newId
}

function addSiblingNode() {
  const current = selectedNode.value
  if (!current || current.id === 'root') return
  const parent = findParentNode(rootNode.value, current.id)
  if (!parent) return
  const newId = `node-${Date.now()}`
  parent.children.push({
    id: newId,
    text: t('mindmap.sibling_node'),
    collapsed: false,
    children: []
  })
  selectedNodeId.value = newId
}

function deleteSelectedNode() {
  const current = selectedNode.value
  if (!current || current.id === 'root') return
  const parent = findParentNode(rootNode.value, current.id)
  if (!parent) return
  parent.children = parent.children.filter((c) => c.id !== current.id)
  selectedNodeId.value = parent.id
}

function truncateText(str, maxLen = 20) {
  if (!str) return ''
  return str.length > maxLen ? str.slice(0, maxLen - 1) + '…' : str
}

// Tree Layout Computation
const layoutData = computed(() => {
  const nodes = []
  const links = []
  const nodeWidth = 160
  const nodeHeight = 36
  const horizontalGap = 80
  const verticalGap = 20

  // Calculate leaf count of each node
  function computeLeafHeight(node) {
    if (node.collapsed || !node.children || node.children.length === 0) {
      return nodeHeight + verticalGap
    }
    let total = 0
    for (const child of node.children) {
      total += computeLeafHeight(child)
    }
    return total
  }

  // Layout recursive
  function layoutRecursive(node, depth, startY) {
    const subtreeHeight = computeLeafHeight(node)
    const x = 50 + depth * (nodeWidth + horizontalGap)
    const y = startY + subtreeHeight / 2 - nodeHeight / 2

    const layoutNode = {
      id: node.id,
      text: node.text,
      x,
      y,
      width: nodeWidth,
      height: nodeHeight,
      hasChildren: node.children && node.children.length > 0,
      rawNode: node
    }
    nodes.push(layoutNode)

    if (!node.collapsed && node.children && node.children.length > 0) {
      let currentY = startY
      for (const child of node.children) {
        const childSubtreeHeight = computeLeafHeight(child)
        const childLayoutNode = layoutRecursive(child, depth + 1, currentY)
        currentY += childSubtreeHeight

        // Generate curved orthogonal bezier path from parent right edge to child left edge
        const x1 = layoutNode.x + layoutNode.width + (layoutNode.hasChildren ? 16 : 0)
        const y1 = layoutNode.y + layoutNode.height / 2
        const x2 = childLayoutNode.x
        const y2 = childLayoutNode.y + childLayoutNode.height / 2
        const cx1 = x1 + (x2 - x1) / 2
        const cx2 = x1 + (x2 - x1) / 2
        const path = `M ${x1} ${y1} C ${cx1} ${y1}, ${cx2} ${y2}, ${x2} ${y2}`

        links.push({
          id: `${node.id}->${child.id}`,
          path
        })
      }
    }

    return layoutNode
  }

  layoutRecursive(rootNode.value, 0, 50)

  return { nodes, links }
})

const layoutNodes = computed(() => layoutData.value.nodes)
const layoutLinks = computed(() => layoutData.value.links)

const computedSvgWidth = computed(() => {
  let maxX = 800
  for (const n of layoutNodes.value) {
    if (n.x + n.width + 100 > maxX) maxX = n.x + n.width + 100
  }
  return maxX
})

const computedSvgHeight = computed(() => {
  let maxY = 600
  for (const n of layoutNodes.value) {
    if (n.y + n.height + 100 > maxY) maxY = n.y + n.height + 100
  }
  return maxY
})

function getNodeRectClass(node) {
  const isSelected = selectedNodeId.value === node.id
  if (isSelected) {
    return 'fill-ink-900 stroke-ink-900 stroke-2'
  }
  if (node.id === 'root') {
    return 'fill-paper-dim stroke-ink-900 stroke-2'
  }
  return 'fill-paper-card stroke-ink-900 stroke-1'
}

function getNodeTextClass(node) {
  const isSelected = selectedNodeId.value === node.id
  if (isSelected) {
    return 'fill-paper font-bold'
  }
  if (node.id === 'root') {
    return 'fill-ink-900 font-bold'
  }
  return 'fill-ink-900'
}

function resetView() {
  if (mapContainerRef.value) {
    mapContainerRef.value.scrollLeft = 0
    mapContainerRef.value.scrollTop = 0
  }
}

function exportSvg() {
  if (!svgRef.value) return
  const serializer = new XMLSerializer()
  const svgString = serializer.serializeToString(svgRef.value)
  const blob = new Blob([svgString], { type: 'image/svg+xml;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = 'mindmap.svg'
  a.click()
  URL.revokeObjectURL(url)
}

async function fetchSavedMap() {
  if (!props.workspaceId) return
  try {
    const list = await api.get(`/api/workspaces/${props.workspaceId}/documents?doc_type=mindmap`)
    if (list && list.length > 0) {
      docId.value = list[0].id
      if (list[0].content_raw) {
        rootNode.value = JSON.parse(list[0].content_raw)
      }
    }
  } catch (err) {
    console.error('Failed to load mindmap:', err)
  }
}

async function saveMindMap() {
  if (!props.workspaceId) return
  saving.value = true
  try {
    const payload = {
      title: 'Воркспейс Mind Map',
      content_raw: JSON.stringify(rootNode.value, null, 2)
    }
    if (docId.value) {
      await api.put(`/api/workspaces/${props.workspaceId}/documents/${docId.value}`, payload)
    } else {
      const created = await api.post(`/api/workspaces/${props.workspaceId}/documents`, {
        ...payload,
        doc_type: 'mindmap'
      })
      docId.value = created.id
    }
  } catch (err) {
    console.error('Failed to save mindmap:', err)
  } finally {
    saving.value = false
  }
}

watch(
  () => props.workspaceId,
  (newId) => {
    if (newId) fetchSavedMap()
  }
)

onMounted(() => {
  fetchSavedMap()
})
</script>

<style scoped>
.mindmap-container {
  height: 680px;
}

.mindmap-viewport {
  height: calc(100% - 60px);
}

.mindmap-svg {
  min-width: 100%;
  min-height: 100%;
  display: block;
}

.fill-ink-900 {
  fill: var(--color-ink-900);
}

.stroke-ink-900 {
  stroke: var(--color-ink-900);
}

.fill-paper {
  fill: var(--color-paper);
}

.fill-paper-dim {
  fill: var(--color-paper-dim);
}

.fill-paper-card {
  fill: var(--color-paper-card);
}
</style>
