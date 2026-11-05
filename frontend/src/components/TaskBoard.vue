<template>
  <div class="task-board flex flex-col gap-4">
    <div class="eink-card eink-panel-head">
      <h2 class="eink-panel-title">{{ $t('tasks.title') }}</h2>
      <div class="flex items-center gap-2">
        <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('common.refresh')" @click="fetchTasks">
          <RefreshCw :size="14" />
        </button>
        <button class="eink-btn eink-btn-sm eink-btn-primary" @click="showCreateModal = true">
          <Plus :size="14" /> {{ $t('tasks.add_task') }}
        </button>
      </div>
    </div>

    <div class="kanban-grid">
      <section v-for="col in columns" :key="col.status" class="kanban-column eink-card">
        <div class="eink-panel-head">
          <span class="eink-panel-title text-sm">{{ $t(col.label) }}</span>
          <span class="eink-badge">{{ col.tasks.length }}</span>
        </div>

        <div class="column-body scroll-blocks">
          <div v-if="loading" class="eink-empty">{{ $t('common.loading') }}</div>
          <div v-else-if="!col.tasks.length" class="eink-empty">{{ $t('tasks.no_tasks') }}</div>

          <article v-for="task in col.tasks" :key="task.id" v-reveal class="task-card" :class="{ done: task.status === 'done' }">
            <div class="flex justify-between items-start gap-2">
              <span class="task-title">{{ task.title }}</span>
              <span class="eink-badge shrink-0" :class="getPriorityClass(task.priority)">
                {{ formatPriority(task.priority) }}
              </span>
            </div>

            <p v-if="task.description" class="task-desc">{{ task.description }}</p>

            <div class="task-footer">
              <div class="task-meta">
                <span v-if="task.due_date" class="inline-flex items-center gap-1">
                  <CalendarDays :size="12" /> {{ formatDate(task.due_date) }}
                </span>
                <span v-if="task.assignee_username" class="inline-flex items-center gap-1">
                  <User :size="12" /> {{ task.assignee_username }}
                </span>
              </div>
              <div class="flex items-center gap-1">
                <button
                  v-for="move in col.moves"
                  :key="move.to"
                  type="button"
                  class="eink-icon-btn"
                  :title="$t(move.label)"
                  @click="updateStatus(task.id, move.to)"
                >
                  <component :is="move.icon" :size="15" />
                </button>
                <button type="button" class="eink-icon-btn" :title="$t('tasks.delete_task')" @click="deleteTask(task.id)">
                  <Trash2 :size="14" />
                </button>
              </div>
            </div>
          </article>
        </div>
      </section>
    </div>

    <!-- Create task -->
    <EinkModal :open="showCreateModal" :title="$t('tasks.create_task_modal')" @close="showCreateModal = false">
      <form @submit.prevent="createTask">
        <div class="flex flex-col gap-3">
          <div>
            <label class="eink-label">{{ $t('tasks.task_title') }}</label>
            <input v-model="newTask.title" type="text" class="eink-input" required />
          </div>
          <div>
            <label class="eink-label">{{ $t('tasks.task_desc') }}</label>
            <textarea v-model="newTask.description" class="eink-textarea h-20 resize-none"></textarea>
          </div>
          <div class="grid grid-cols-2 gap-3">
            <div>
              <label class="eink-label">{{ $t('tasks.priority') }}</label>
              <select v-model="newTask.priority" class="eink-select">
                <option value="low">{{ $t('tasks.priority_low') }}</option>
                <option value="medium">{{ $t('tasks.priority_medium') }}</option>
                <option value="high">{{ $t('tasks.priority_high') }}</option>
              </select>
            </div>
            <div>
              <label class="eink-label">{{ $t('tasks.due_date') }}</label>
              <input v-model="newTask.dueDate" type="date" class="eink-input" />
            </div>
          </div>
        </div>
        <div class="eink-modal-actions">
          <button type="button" class="eink-btn" @click="showCreateModal = false">{{ $t('common.cancel') }}</button>
          <button type="submit" class="eink-btn eink-btn-primary" :disabled="!newTask.title.trim() || creating">
            {{ creating ? $t('common.loading') : $t('common.create') }}
          </button>
        </div>
      </form>
    </EinkModal>
  </div>
</template>

<script setup>
import { markRaw } from 'vue'
import { Plus, RefreshCw, CalendarDays, User, ArrowRight, ArrowLeft, Check, Undo2, Trash2 } from 'lucide-vue-next'
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api/client'
import EinkModal from './EinkModal.vue'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  }
})

const { t } = useI18n()

const tasks = ref([])
const loading = ref(false)
const showCreateModal = ref(false)
const creating = ref(false)

const newTask = ref({
  title: '',
  description: '',
  priority: 'medium',
  dueDate: ''
})

const todoTasks = computed(() => tasks.value.filter((t) => t.status === 'todo'))
const inProgressTasks = computed(() => tasks.value.filter((t) => t.status === 'in_progress'))
const doneTasks = computed(() => tasks.value.filter((t) => t.status === 'done'))

const columns = computed(() => [
  {
    status: 'todo', label: 'tasks.status_todo', tasks: todoTasks.value,
    moves: [{ to: 'in_progress', label: 'tasks.status_in_progress', icon: markRaw(ArrowRight) }]
  },
  {
    status: 'in_progress', label: 'tasks.status_in_progress', tasks: inProgressTasks.value,
    moves: [
      { to: 'todo', label: 'tasks.status_todo', icon: markRaw(ArrowLeft) },
      { to: 'done', label: 'tasks.status_done', icon: markRaw(Check) }
    ]
  },
  {
    status: 'done', label: 'tasks.status_done', tasks: doneTasks.value,
    moves: [{ to: 'in_progress', label: 'tasks.status_in_progress', icon: markRaw(Undo2) }]
  }
])

function formatDate(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  return d.toLocaleDateString()
}

function formatPriority(p) {
  if (p === 'high') return t('tasks.priority_high')
  if (p === 'low') return t('tasks.priority_low')
  return t('tasks.priority_medium')
}

function getPriorityClass(p) {
  if (p === 'high') return 'eink-badge-dark'
  if (p === 'low') return 'eink-badge-muted'
  return ''
}

async function fetchTasks() {
  if (!props.workspaceId) return
  loading.value = true
  try {
    const data = await api.get(`/api/workspaces/${props.workspaceId}/tasks`)
    tasks.value = data || []
  } catch (err) {
    console.error('Failed to fetch tasks:', err)
  } finally {
    loading.value = false
  }
}

async function updateStatus(taskId, newStatus) {
  try {
    await api.patch(`/api/workspaces/${props.workspaceId}/tasks/${taskId}/status`, {
      status: newStatus
    })
    const found = tasks.value.find((t) => t.id === taskId)
    if (found) {
      found.status = newStatus
    }
  } catch (err) {
    console.error('Failed to update task status:', err)
  }
}

async function deleteTask(taskId) {
  if (!confirm(t('common.delete') + '?')) return
  try {
    await api.delete(`/api/workspaces/${props.workspaceId}/tasks/${taskId}`)
    tasks.value = tasks.value.filter((t) => t.id !== taskId)
  } catch (err) {
    console.error('Failed to delete task:', err)
  }
}

async function createTask() {
  if (!newTask.value.title.trim() || !props.workspaceId) return
  creating.value = true
  try {
    const payload = {
      title: newTask.value.title.trim(),
      description: newTask.value.description.trim(),
      priority: newTask.value.priority,
      status: 'todo',
      due_date: newTask.value.dueDate ? new Date(newTask.value.dueDate).toISOString() : null
    }
    const created = await api.post(`/api/workspaces/${props.workspaceId}/tasks`, payload)
    tasks.value.unshift(created)
    showCreateModal.value = false
    newTask.value = {
      title: '',
      description: '',
      priority: 'medium',
      dueDate: ''
    }
  } catch (err) {
    console.error('Failed to create task:', err)
  } finally {
    creating.value = false
  }
}

// Expose refreshTasks so parent or sister components can trigger it
defineExpose({
  refreshTasks: fetchTasks
})

watch(
  () => props.workspaceId,
  (newId) => {
    if (newId) fetchTasks()
  }
)

onMounted(() => {
  fetchTasks()
})
</script>

<style scoped>
.task-board {
  container-type: inline-size;
}

.kanban-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 1rem;
}

.kanban-column {
  display: flex;
  flex-direction: column;
  min-height: 480px;
  background-color: var(--color-paper);
}

.column-body {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 0.6rem;
  padding: 0.75rem;
  overflow-y: auto;
}

.task-card {
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
  padding: 0.75rem;
  background-color: var(--color-paper-card);
  border: var(--border-crisp);
  border-radius: var(--radius);
}

.task-card.done .task-title {
  text-decoration: line-through;
  color: var(--color-ink-500);
}

.task-title {
  font-size: 0.9rem;
  font-weight: 600;
  line-height: 1.35;
  overflow-wrap: anywhere;
}

.task-desc {
  font-size: 0.8125rem;
  color: var(--color-ink-500);
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
  white-space: pre-wrap;
}

.task-footer {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  padding-top: 0.5rem;
  border-top: var(--border-faint);
}

.task-meta {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem 0.75rem;
  font-size: 0.75rem;
  color: var(--color-ink-500);
  min-width: 0;
}

/* Follows the board's own width, so the split view stacks columns too */
@container (max-width: 820px) {
  .kanban-grid {
    grid-template-columns: minmax(0, 1fr);
  }

  .kanban-column {
    min-height: 0;
  }
}
</style>
