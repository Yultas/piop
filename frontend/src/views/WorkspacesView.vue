<template>
  <div class="workspaces-view app-container">
    <div class="page-header">
      <h1 class="text-2xl font-bold">{{ $t('workspace.title') }}</h1>
      <button
        type="button"
        class="eink-btn eink-btn-sm eink-btn-icon"
        :disabled="loading"
        :title="$t('common.refresh')"
        @click="loadWorkspaces"
      >
        <RefreshCw :size="14" />
      </button>
    </div>

    <!-- Loading State -->
    <div v-if="loading" class="eink-card p-6 text-center">
      <p class="text-sm">{{ $t('common.loading') }}</p>
    </div>

    <!-- Error State -->
    <div v-else-if="error" class="eink-card p-6 border mb-4">
      <div class="text-xs text-muted mb-1">{{ $t('common.error') }}</div>
      <p class="text-sm">{{ error }}</p>
      <button class="eink-btn eink-btn-sm mt-3" @click="loadWorkspaces">
        {{ $t('common.refresh') }}
      </button>
    </div>

    <!-- Empty State -->
    <div
      v-else-if="workspaces.length === 0"
      class="eink-card p-8 text-center eink-card-muted"
    >
      <p class="text-sm text-muted mb-4">{{ $t('workspace.no_workspaces') }}</p>
      <router-link
        v-if="authStore.isAdmin"
        to="/admin"
        class="eink-btn eink-btn-primary"
      >
        <Plus :size="14" /> {{ $t('admin.create_ws_heading') }}
      </router-link>
    </div>

    <!-- Workspaces Cards Grid -->
    <div v-else class="ws-grid">
      <div
        v-for="ws in workspaces"
        :key="ws.id"
        v-reveal
        class="eink-card ws-card"
      >
        <div>
          <div class="flex justify-between items-start gap-2 mb-2">
            <h2 class="text-lg font-bold break-words">{{ ws.name }}</h2>
            <span v-if="ws.role === 'admin'" class="eink-badge eink-badge-dark shrink-0">
              {{ ws.role }}
            </span>
          </div>
          <p v-if="ws.description" class="text-sm text-muted mb-4 line-clamp-2">
            {{ ws.description }}
          </p>
        </div>

        <div>
          <!-- Storage Meter component -->
          <div class="mt-4 mb-4">
            <StorageMeter
              :used-bytes="ws.used_storage_bytes || 0"
              :quota-bytes="ws.storage_quota_bytes || 0"
            />
          </div>

          <button
            type="button"
            class="eink-btn eink-btn-primary w-full"
            @click="enterWorkspace(ws)"
          >
            {{ $t('workspace.enter') }} <ArrowRight :size="14" />
          </button>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { RefreshCw, ArrowRight, Plus } from 'lucide-vue-next'
import { ref, computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'
import StorageMeter from '../components/StorageMeter.vue'

const router = useRouter()
const authStore = useAuthStore()
const workspaceStore = useWorkspaceStore()

const loading = ref(false)
const error = ref('')

const workspaces = computed(() => workspaceStore.workspaces)

async function loadWorkspaces() {
  loading.value = true
  error.value = ''
  try {
    await workspaceStore.fetchWorkspaces()
  } catch (err) {
    error.value = err.detail || err.message || 'common.error'
  } finally {
    loading.value = false
  }
}

function enterWorkspace(ws) {
  workspaceStore.setCurrentWorkspace(ws)
  router.push(`/workspaces/${ws.id}`)
}

onMounted(() => {
  loadWorkspaces()
})
</script>

<style scoped>
.line-clamp-2 {
  display: -webkit-box;
  -webkit-line-clamp: 2;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 1rem;
  margin-bottom: 1.5rem;
}
.ws-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
  gap: 1.25rem;
}
.ws-card {
  display: flex;
  flex-direction: column;
  justify-content: space-between;
  padding: 1.25rem;
}
</style>
