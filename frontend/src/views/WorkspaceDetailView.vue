<template>
  <div class="workspace-detail-view app-container">
    <div v-if="loading" class="eink-card p-8 text-center my-8">
      <p class="text-sm text-muted">{{ $t('common.loading') }}</p>
    </div>

    <div v-else-if="workspace" class="flex flex-col gap-4">
      <div class="ws-header">
        <div class="flex items-center gap-3" style="min-width: 0">
          <router-link to="/workspaces" class="eink-btn eink-btn-icon" :title="$t('common.back')" :aria-label="$t('common.back')"><ArrowLeft :size="16" /></router-link>
          <div style="min-width: 0">
            <h1 class="text-xl font-bold truncate">{{ workspace.name }}</h1>
            <p v-if="workspace.description" class="text-xs text-muted truncate">
              {{ workspace.description }}
            </p>
          </div>
        </div>
        <div class="ws-storage">
          <StorageMeter
            :used-bytes="usedStorageBytes"
            :quota-bytes="quotaStorageBytes"
          />
        </div>
      </div>

      <nav class="ws-tabs" role="tablist">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          type="button"
          role="tab"
          class="eink-tab"
          :class="{ active: currentTab === tab.id }"
          :aria-selected="currentTab === tab.id"
          @click="currentTab = tab.id"
        >
          {{ $t(`workspace.tab_${tab.id}`) }}
        </button>
      </nav>

      <!-- Tab 1: Chat and Tasks (v-show preserves live state) -->
      <div v-show="currentTab === 'chat_tasks'" class="tab-pane flex flex-col gap-4">
        <div class="eink-segmented">
          <button :class="{ active: chatTasksView === 'split' }" @click="chatTasksView = 'split'">
            {{ $t('notebook.split_view') }}
          </button>
          <button :class="{ active: chatTasksView === 'chat' }" @click="chatTasksView = 'chat'">
            {{ $t('chat.title') }}
          </button>
          <button :class="{ active: chatTasksView === 'tasks' }" @click="chatTasksView = 'tasks'">
            {{ $t('tasks.title') }}
          </button>
        </div>

        <div class="grid gap-4" :class="chatTasksGridClass">
          <div v-show="chatTasksView !== 'tasks'" class="tab-pane" style="min-width: 0">
            <ChatThread
              :workspace-id="workspace.id"
              @task-created="handleTaskCreated"
            />
          </div>
          <div v-show="chatTasksView !== 'chat'" class="tab-pane" style="min-width: 0">
            <TaskBoard
              ref="taskBoardRef"
              :workspace-id="workspace.id"
            />
          </div>
        </div>
      </div>

      <!-- Tab 2: Notebook & Typst -->
      <div v-show="currentTab === 'notebook_typst'" class="tab-pane flex flex-col gap-4">
        <div class="eink-segmented">
          <button :class="{ active: notebookTypstView === 'notebook' }" @click="notebookTypstView = 'notebook'">
            {{ $t('notebook.title') }}
          </button>
          <button :class="{ active: notebookTypstView === 'typst' }" @click="notebookTypstView = 'typst'">
            {{ $t('typst.title') }}
          </button>
        </div>

        <div v-show="notebookTypstView === 'notebook'" class="tab-pane">
          <MarkdownMermaid :workspace-id="workspace.id" />
        </div>
        <div v-show="notebookTypstView === 'typst'" class="tab-pane">
          <TypstRenderer :workspace-id="workspace.id" />
        </div>
      </div>

      <!-- Tab 3: Mind Map & Whiteboard Canvas -->
      <div v-show="currentTab === 'mindmap_canvas'" class="tab-pane flex flex-col gap-4">
        <div class="eink-segmented">
          <button :class="{ active: mindmapCanvasView === 'mindmap' }" @click="mindmapCanvasView = 'mindmap'">
            {{ $t('mindmap.title') }}
          </button>
          <button :class="{ active: mindmapCanvasView === 'canvas' }" @click="mindmapCanvasView = 'canvas'">
            {{ $t('canvas.title') }}
          </button>
        </div>

        <div v-show="mindmapCanvasView === 'mindmap'" class="tab-pane">
          <MindMap :workspace-id="workspace.id" />
        </div>
        <div v-show="mindmapCanvasView === 'canvas'" class="tab-pane">
          <CanvasWhiteboard :workspace-id="workspace.id" />
        </div>
      </div>

      <!-- Tab: AI Assistant -->
      <div v-show="currentTab === 'assistant'" class="tab-pane">
        <AssistantPanel :workspace-id="workspace.id" @changed="handleAssistantChanged" />
      </div>

      <!-- Tab 4: Quizzes -->
      <div v-show="currentTab === 'quizzes'" class="tab-pane">
        <QuizPlayer :workspace-id="workspace.id" />
      </div>

      <!-- Tab 5: File Storage -->
      <div v-show="currentTab === 'files'" class="tab-pane">
        <FileManager
          :workspace-id="workspace.id"
          @storage-updated="handleStorageUpdated"
        />
      </div>

      <!-- Floating chat drawer -->
      <button
        v-show="!chatDrawerOpen"
        type="button"
        class="eink-fab"
        :title="$t('chat.open_drawer')"
        :aria-label="$t('chat.open_drawer')"
        @click="openChatDrawer"
      >
        <MessageSquare :size="20" />
      </button>

      <EinkDrawer
        :open="chatDrawerOpen"
        :title="$t('chat.title')"
        @close="chatDrawerOpen = false"
      >
        <ChatThread
          v-if="chatDrawerMounted"
          fill
          :workspace-id="workspace.id"
          @task-created="handleTaskCreated"
        />
      </EinkDrawer>
    </div>
  </div>
</template>

<script setup>
import { ArrowLeft, MessageSquare } from 'lucide-vue-next'
import { ref, computed, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { useWorkspaceStore } from '../stores/workspace'

// E-Ink Feature Components
import StorageMeter from '../components/StorageMeter.vue'
import ChatThread from '../components/ChatThread.vue'
import TaskBoard from '../components/TaskBoard.vue'
import MarkdownMermaid from '../components/MarkdownMermaid.vue'
import TypstRenderer from '../components/TypstRenderer.vue'
import MindMap from '../components/MindMap.vue'
import CanvasWhiteboard from '../components/CanvasWhiteboard.vue'
import QuizPlayer from '../components/QuizPlayer.vue'
import FileManager from '../components/FileManager.vue'
import AssistantPanel from '../components/AssistantPanel.vue'
import EinkDrawer from '../components/EinkDrawer.vue'

const route = useRoute()
const workspaceStore = useWorkspaceStore()

const workspace = ref(null)
const loading = ref(true)

// Active tab state
const tabs = [
  { id: 'chat_tasks' },
  { id: 'notebook_typst' },
  { id: 'mindmap_canvas' },
  { id: 'assistant' },
  { id: 'quizzes' },
  { id: 'files' }
]
const currentTab = ref('chat_tasks')

// Submodule layout states
const chatTasksView = ref('split')
const notebookTypstView = ref('notebook')
const mindmapCanvasView = ref('mindmap')

// Live storage tracking
const liveUsedBytes = ref(null)
const liveQuotaBytes = ref(null)

const taskBoardRef = ref(null)

// Floating chat drawer: mounted on first open, then kept alive to preserve chat state
const chatDrawerOpen = ref(false)
const chatDrawerMounted = ref(false)

function openChatDrawer() {
  chatDrawerMounted.value = true
  chatDrawerOpen.value = true
}

const usedStorageBytes = computed(() => {
  if (liveUsedBytes.value !== null) return liveUsedBytes.value
  return workspace.value?.used_storage_bytes || 0
})

const quotaStorageBytes = computed(() => {
  if (liveQuotaBytes.value !== null) return liveQuotaBytes.value
  return workspace.value?.storage_quota_bytes || 0
})

const chatTasksGridClass = computed(() => {
  if (chatTasksView.value === 'split') return 'grid-cols-1 lg:grid-cols-2'
  return 'grid-cols-1'
})

function handleTaskCreated() {
  if (taskBoardRef.value && typeof taskBoardRef.value.refreshTasks === 'function') {
    taskBoardRef.value.refreshTasks()
  }
}

function handleAssistantChanged() {
  handleTaskCreated()
}

function handleStorageUpdated({ usedBytes, quotaBytes }) {
  liveUsedBytes.value = usedBytes
  liveQuotaBytes.value = quotaBytes
  if (workspace.value) {
    workspace.value.used_storage_bytes = usedBytes
    workspace.value.storage_quota_bytes = quotaBytes
  }
}

onMounted(async () => {
  const wsId = route.params.id
  if (wsId) {
    try {
      workspace.value = await workspaceStore.fetchWorkspace(wsId)
      liveUsedBytes.value = workspace.value.used_storage_bytes
      liveQuotaBytes.value = workspace.value.storage_quota_bytes
    } catch (e) {
      console.error('Failed to load workspace:', e)
    } finally {
      loading.value = false
    }
  }
})
</script>

<style scoped>
.workspace-detail-view {
  padding-bottom: calc(3.25rem + 2.5rem + env(safe-area-inset-bottom));
}

.ws-header {
  display: flex;
  flex-wrap: wrap;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  padding-bottom: 1rem;
  border-bottom: var(--border-crisp);
}

.ws-storage {
  width: 260px;
}

.ws-tabs {
  display: flex;
  gap: 0.25rem;
  overflow-x: auto;
  border-bottom: var(--border-faint);
  scrollbar-width: none;
}

.ws-tabs .eink-tab {
  white-space: nowrap;
  flex-shrink: 0;
}

.tab-pane {
  animation: eink-rise-in var(--dur) var(--ease-out);
}

@media (max-width: 640px) {
  .ws-storage { width: 100%; }
}
</style>
