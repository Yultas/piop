<template>
  <div class="admin-view app-container">
    <!-- Header -->
    <h1 class="text-2xl font-bold mb-4">{{ $t('admin.title') }}</h1>

    <!-- Alert / Toast Message -->
    <div
      v-if="notification"
      class="p-3 border text-xs mb-4 flex justify-between items-center"
      :class="notification.type === 'error' ? 'eink-card-muted font-bold' : 'bg-white'"
    >
      <span>{{ notification.text }}</span>
      <button class="eink-btn eink-btn-sm eink-btn-icon" :aria-label="$t('common.close')" @click="notification = null"><X :size="14" /></button>
    </div>

    <!-- Tabs Navigation -->
    <div class="admin-tabs mb-6">
      <button
        type="button"
        class="eink-tab"
        :class="{ active: currentTab === 'workspaces' }"
        @click="currentTab = 'workspaces'"
      >
        {{ $t('admin.tab_workspaces') }}
      </button>
      <button
        type="button"
        class="eink-tab"
        :class="{ active: currentTab === 'users' }"
        @click="currentTab = 'users'"
      >
        {{ $t('admin.tab_users') }}
      </button>
      <button
        type="button"
        class="eink-tab"
        :class="{ active: currentTab === 'invites' }"
        @click="currentTab = 'invites'"
      >
        {{ $t('admin.tab_invites') }}
      </button>
      <button
        type="button"
        class="eink-tab"
        :class="{ active: currentTab === 'ai' }"
        @click="currentTab = 'ai'"
      >
        {{ $t('admin.tab_ai') }}
      </button>
    </div>

    <!-- TAB 1: WORKSPACES & QUOTAS -->
    <div v-if="currentTab === 'workspaces'" class="flex flex-col gap-6">
      <!-- Create Workspace Card -->
      <div class="eink-card p-5">
        <h2 class="text-base font-bold mb-4">
          {{ $t('admin.create_ws_heading') }}
        </h2>
        <form @submit.prevent="handleCreateWorkspace" class="grid grid-cols-3 gap-4 items-end">
          <div>
            <label class="ui-label text-sm font-semibold block mb-1">
              {{ $t('admin.ws_name') }}
            </label>
            <input
              v-model="newWsName"
              type="text"
              required
              class="eink-input"
            />
          </div>

          <div>
            <label class="ui-label text-sm font-semibold block mb-1">
              {{ $t('admin.ws_desc') }}
            </label>
            <input
              v-model="newWsDesc"
              type="text"
              class="eink-input"
            />
          </div>

          <div>
            <label class="ui-label text-sm font-semibold block mb-1">
              {{ $t('admin.ws_quota_mb') }}
            </label>
            <div class="flex gap-2">
              <input
                v-model.number="newWsQuota"
                type="number"
                min="1"
                required
                class="eink-input"
                placeholder="500"
              />
              <button
                type="submit"
                class="eink-btn eink-btn-primary whitespace-nowrap"
                :disabled="creatingWs"
              >
                <Plus :size="14" /> {{ $t('admin.create_ws_btn') }}
              </button>
            </div>
          </div>
        </form>
      </div>

      <!-- Workspaces List & Quota Management Table -->
      <div class="eink-card p-5">
        <div class="flex justify-between items-center mb-4">
          <h2 class="text-base font-bold">{{ $t('admin.workspaces_list') }}</h2>
          <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('common.refresh')" @click="fetchAdminWorkspaces"><RefreshCw :size="14" /></button>
        </div>

        <div v-if="loadingWs" class="text-center text-sm py-4">
          {{ $t('common.loading') }}
        </div>

        <div v-else class="overflow-x-auto">
          <table class="admin-table">
            <thead>
              <tr>
                <th>{{ $t('workspace.name') }}</th>
                <th>{{ $t('storage.title') }}</th>
                <th>{{ $t('workspace.members_count') }}</th>
                <th>{{ $t('admin.quota_edit') }}</th>
                <th></th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="ws in adminWorkspaces" :key="ws.id">
                <td>
                  <div class="font-bold font-sans text-sm">{{ ws.name }}</div>
                  <div class="text-xs text-muted font-sans">{{ ws.description }}</div>
                </td>
                <td>
                  <div class="meter-cell">
                    <StorageMeter
                      :used-bytes="ws.used_storage_bytes"
                      :quota-bytes="ws.storage_quota_bytes"
                    />
                  </div>
                </td>
                <td class="text-center font-bold">
                  {{ ws.members_count }}
                </td>
                <td>
                  <div class="flex items-center gap-2">
                    <input
                      v-model.number="quotaEdits[ws.id]"
                      type="number"
                      min="1"
                      class="eink-input w-24 py-1 px-2"
                    />
                    <button
                      type="button"
                      class="eink-btn eink-btn-sm"
                      @click="saveQuota(ws.id)"
                    >
                      {{ $t('admin.save_quota') }}
                    </button>
                  </div>
                </td>
                <td class="text-right">
                  <button
                    type="button"
                    class="eink-btn eink-btn-sm eink-btn-danger"
                    :title="$t('admin.delete_ws')"
                    @click="openDelete('workspace', ws.id, ws.name)"
                  >
                    <Trash2 :size="14" />
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </div>
    </div>

    <!-- TAB 2: USERS & PERMISSIONS -->
    <div v-if="currentTab === 'users'" class="eink-card p-5">
      <div class="flex justify-between items-center mb-4">
        <h2 class="text-base font-bold">{{ $t('admin.users_list') }}</h2>
        <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('common.refresh')" @click="fetchAdminUsers"><RefreshCw :size="14" /></button>
      </div>

      <div v-if="loadingUsers" class="text-center text-sm py-4">
        {{ $t('common.loading') }}
      </div>

      <div v-else class="overflow-x-auto">
        <table class="admin-table">
          <thead>
            <tr>
              <th>{{ $t('admin.user_col_name') }}</th>
              <th>{{ $t('admin.user_col_admin') }}</th>
              <th>{{ $t('admin.user_col_created') }}</th>
              <th>{{ $t('admin.user_col_actions') }}</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            <tr v-for="user in adminUsers" :key="user.id">
              <td class="font-bold text-sm">{{ user.username }}</td>
              <td>
                <span
                  class="eink-badge"
                  :class="user.is_global_admin ? 'eink-badge-dark' : ''"
                >
                  {{ user.is_global_admin ? 'admin' : 'user' }}
                </span>
              </td>
              <td class="text-muted">
                {{ formatDate(user.created_at) }}
              </td>
              <td>
                <button
                  type="button"
                  class="eink-btn eink-btn-sm"
                  :class="{ 'eink-btn-danger': user.is_global_admin }"
                  @click="toggleUserAdmin(user)"
                >
                  {{ user.is_global_admin ? $t('admin.revoke_admin') : $t('admin.grant_admin') }}
                </button>
              </td>
              <td class="text-right">
                <button
                  v-if="user.id !== authStore.user?.id"
                  type="button"
                  class="eink-btn eink-btn-sm eink-btn-danger"
                  :title="$t('admin.delete_user')"
                  @click="openDelete('user', user.id, user.username)"
                >
                  <Trash2 :size="14" />
                </button>
              </td>
            </tr>
          </tbody>
        </table>
      </div>
    </div>

    <!-- TAB 4: AI PROVIDER -->
    <div v-if="currentTab === 'ai'" class="eink-card p-5 ai-settings">
      <h2 class="text-base font-bold mb-1">{{ $t('ai.provider_heading') }}</h2>
      <p class="text-sm text-muted mb-4">{{ $t('ai.provider_hint') }}</p>

      <form class="flex flex-col gap-4" @submit.prevent="saveAiSettings">
        <label class="flex items-center gap-2 text-sm font-semibold cursor-pointer">
          <input v-model="aiForm.enabled" type="checkbox" />
          {{ $t('ai.enabled') }}
        </label>

        <div>
          <label class="ui-label text-sm font-semibold block mb-1">{{ $t('ai.base_url') }}</label>
          <input v-model="aiForm.base_url" type="url" required class="eink-input" placeholder="https://api.openai.com/v1" />
        </div>

        <div>
          <label class="ui-label text-sm font-semibold block mb-1">{{ $t('ai.api_key') }}</label>
          <input
            v-model="aiForm.api_key"
            type="password"
            autocomplete="off"
            class="eink-input"
            :placeholder="aiSettings?.has_api_key ? $t('ai.api_key_saved', { hint: aiSettings.api_key_hint }) : $t('ai.api_key_empty')"
          />
        </div>

        <div>
          <label class="ui-label text-sm font-semibold block mb-1">{{ $t('ai.model') }}</label>
          <div class="flex flex-wrap gap-2">
            <input v-model="aiForm.model" list="ai-models" required class="eink-input flex-1" placeholder="gpt-4o-mini" />
            <datalist id="ai-models">
              <option v-for="m in aiModels" :key="m" :value="m" />
            </datalist>
            <button type="button" class="eink-btn" :disabled="checkingAi" @click="checkAiConnection">
              {{ checkingAi ? $t('common.loading') : $t('ai.check_connection') }}
            </button>
          </div>
          <p v-if="aiModels.length" class="text-xs text-muted mt-1">
            {{ $t('ai.models_found', { count: aiModels.length }) }}
          </p>
        </div>

        <div>
          <button type="submit" class="eink-btn eink-btn-primary" :disabled="savingAi">
            {{ $t('common.save') }}
          </button>
        </div>
      </form>
    </div>

    <!-- TAB 3: INVITES GENERATOR -->
    <div v-if="currentTab === 'invites'" class="flex flex-col gap-6">
      <div class="eink-card p-5">
        <h2 class="text-base font-bold mb-4">
          {{ $t('admin.generate_invite_heading') }}
        </h2>

        <form @submit.prevent="handleGenerateInvite" class="grid grid-cols-3 gap-4 items-end">
          <div>
            <label class="ui-label text-sm font-semibold block mb-1">
              {{ $t('admin.select_workspace') }}
            </label>
            <select
              v-model="inviteWorkspaceId"
              required
              class="eink-select"
            >
              <option value="" disabled>{{ $t('admin.select_workspace') }}</option>
              <option
                v-for="ws in adminWorkspaces"
                :key="ws.id"
                :value="ws.id"
              >
                {{ ws.name }}
              </option>
            </select>
          </div>

          <div>
            <label class="ui-label text-sm font-semibold block mb-1">
              {{ $t('admin.target_role') }}
            </label>
            <select
              v-model="inviteTargetRole"
              class="eink-select"
            >
              <option value="member">{{ $t('workspace.role_member') }}</option>
              <option value="admin">{{ $t('workspace.role_admin') }}</option>
            </select>
          </div>

          <div>
            <label class="ui-label text-sm font-semibold block mb-1">
              {{ $t('admin.expires_days') }} <span class="text-muted font-normal">{{ $t('admin.expires_days_help') }}</span>
            </label>
            <div class="flex gap-2">
              <input
                v-model.number="inviteExpiresDays"
                type="number"
                min="0"
                max="365"
                required
                class="eink-input"
              />
              <button
                type="submit"
                class="eink-btn eink-btn-primary whitespace-nowrap"
                :disabled="generatingInvite"
              >
                {{ $t('admin.generate_btn') }}
              </button>
            </div>
          </div>
        </form>

        <!-- Generated Link Result -->
        <div v-if="generatedInviteUrl" class="mt-6 p-4 border bg-stone-50">
          <div class="flex justify-between items-center mb-2">
            <span class="text-xs font-bold">
              {{ $t('admin.generated_link') }}
            </span>
            <span v-if="generatedInviteData && !generatedInviteData.expires_at" class="eink-badge text-xs">{{ $t('admin.perpetual') }}</span>
                      </div>

          <div class="flex flex-wrap gap-2 items-center">
            <input
              type="text"
              readonly
              :value="generatedInviteUrl"
              class="eink-input text-xs bg-white"
            />
            <button
              type="button"
              class="eink-btn eink-btn-primary whitespace-nowrap"
              @click="copyInviteUrl"
            >
              {{ copied ? $t('common.copied') : $t('common.copy') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- Delete Confirmation (workspace or user) -->
    <EinkModal
      :open="!!deleteTarget"
      :title="deleteTarget ? $t(`admin.delete_${deleteTarget.kind}_title`) : ''"
      @close="closeDelete"
    >
      <template v-if="deleteTarget">
        <form @submit.prevent="confirmDelete">
          <p class="text-sm mb-4">
            {{ $t(`admin.delete_${deleteTarget.kind}_warning`, { name: deleteTarget.name }) }}
          </p>
          <label class="ui-label text-sm font-semibold block mb-1">
            {{ $t(`admin.delete_${deleteTarget.kind}_type_name`) }}
          </label>
          <input
            v-model="deleteConfirmName"
            type="text"
            class="eink-input mb-4"
            :placeholder="deleteTarget.name"
            autofocus
          />
          <div class="eink-modal-actions">
            <button type="button" class="eink-btn" @click="closeDelete">
              {{ $t('common.cancel') }}
            </button>
            <button
              type="submit"
              class="eink-btn eink-btn-primary"
              :disabled="deleteConfirmName !== deleteTarget.name || deleting"
            >
              {{ $t('common.delete') }}
            </button>
          </div>
        </form>
      </template>
    </EinkModal>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Trash2, X, RefreshCw, Plus } from 'lucide-vue-next'
import api from '../api/client'
import StorageMeter from '../components/StorageMeter.vue'
import EinkModal from '../components/EinkModal.vue'
import { useWorkspaceStore } from '../stores/workspace'
import { useAuthStore } from '../stores/auth'

const { t, te } = useI18n()

const currentTab = ref('workspaces')
const notification = ref(null)

// Workspaces data
const adminWorkspaces = ref([])
const loadingWs = ref(false)
const newWsName = ref('')
const newWsDesc = ref('')
const newWsQuota = ref(500)
const creatingWs = ref(false)
const quotaEdits = reactive({})
const aiSettings = ref(null)
const aiForm = reactive({ enabled: false, base_url: '', model: '', api_key: '' })
const aiModels = ref([])
const checkingAi = ref(false)
const savingAi = ref(false)
const deleteTarget = ref(null)
const deleteConfirmName = ref('')
const deleting = ref(false)

const workspaceStore = useWorkspaceStore()
const authStore = useAuthStore()

// Users data
const adminUsers = ref([])
const loadingUsers = ref(false)

// Invites data
const inviteWorkspaceId = ref('')
const inviteTargetRole = ref('member')
const inviteExpiresDays = ref(7)
const generatingInvite = ref(false)
const generatedInviteUrl = ref('')
const generatedInviteData = ref(null)
const copied = ref(false)

function notify(text, type = 'info') {
  const message = te(text) ? t(text) : text
  notification.value = { text: message, type }
  setTimeout(() => {
    if (notification.value?.text === message) {
      notification.value = null
    }
  }, 5000)
}

function formatDate(isoStr) {
  if (!isoStr) return ''
  try {
    return new Date(isoStr).toLocaleDateString()
  } catch {
    return isoStr
  }
}

async function fetchAdminWorkspaces() {
  loadingWs.value = true
  try {
    const list = await api.get('/api/admin/workspaces')
    adminWorkspaces.value = list
    list.forEach((ws) => {
      quotaEdits[ws.id] = ws.storage_quota_mb || Math.round(ws.storage_quota_bytes / 1048576)
    })
    if (!inviteWorkspaceId.value && list.length > 0) {
      inviteWorkspaceId.value = list[0].id
    }
  } catch (err) {
    notify(err.detail || err.message, 'error')
  } finally {
    loadingWs.value = false
  }
}

async function handleCreateWorkspace() {
  creatingWs.value = true
  try {
    await api.post('/api/workspaces', {
      name: newWsName.value,
      description: newWsDesc.value,
      storage_quota_mb: Number(newWsQuota.value)
    })
    newWsName.value = ''
    newWsDesc.value = ''
    newWsQuota.value = 500
    notify('admin.workspace_created', 'success')
    await fetchAdminWorkspaces()
  } catch (err) {
    notify(err.detail || err.message, 'error')
  } finally {
    creatingWs.value = false
  }
}

function openDelete(kind, id, name) {
  deleteTarget.value = { kind, id, name }
  deleteConfirmName.value = ''
}

function closeDelete() {
  deleteTarget.value = null
}

async function confirmDelete() {
  const target = deleteTarget.value
  if (!target || deleteConfirmName.value !== target.name) return

  deleting.value = true
  try {
    if (target.kind === 'workspace') {
      await api.delete(`/api/admin/workspaces/${target.id}`)
      if (workspaceStore.currentWorkspace?.id === target.id) {
        workspaceStore.setCurrentWorkspace(null)
      }
      deleteTarget.value = null
      notify('admin.workspace_deleted', 'success')
      await Promise.all([fetchAdminWorkspaces(), workspaceStore.fetchWorkspaces()])
    } else {
      await api.delete(`/api/admin/users/${target.id}`)
      deleteTarget.value = null
      notify('admin.user_deleted', 'success')
      await Promise.all([fetchAdminUsers(), fetchAdminWorkspaces()])
    }
  } catch (err) {
    notify(err.detail || err.message, 'error')
  } finally {
    deleting.value = false
  }
}

async function saveQuota(workspaceId) {
  const quotaMb = quotaEdits[workspaceId]
  if (!quotaMb || quotaMb < 1) return

  try {
    await api.put(`/api/admin/workspaces/${workspaceId}/quota`, {
      storage_quota_mb: Number(quotaMb)
    })
    notify('admin.quota_updated', 'success')
    await fetchAdminWorkspaces()
  } catch (err) {
    notify(err.detail || err.message, 'error')
  }
}

async function fetchAdminUsers() {
  loadingUsers.value = true
  try {
    adminUsers.value = await api.get('/api/admin/users')
  } catch (err) {
    notify(err.detail || err.message, 'error')
  } finally {
    loadingUsers.value = false
  }
}

async function toggleUserAdmin(user) {
  const newRole = !user.is_global_admin
  try {
    await api.put(`/api/admin/users/${user.id}/role`, {
      is_global_admin: newRole
    })
    notify('admin.role_updated', 'success')
    await fetchAdminUsers()
  } catch (err) {
    notify(err.detail || err.message, 'error')
  }
}

async function handleGenerateInvite() {
  if (!inviteWorkspaceId.value) return
  generatingInvite.value = true
  copied.value = false
  try {
    const res = await api.post('/api/invites', {
      workspace_id: Number(inviteWorkspaceId.value),
      target_role: inviteTargetRole.value,
      expires_in_days: Number(inviteExpiresDays.value)
    })

    const origin = window.location.origin
    generatedInviteData.value = res
    generatedInviteUrl.value = `${origin}/invite/${res.token}`
  } catch (err) {
    notify(err.detail || err.message, 'error')
  } finally {
    generatingInvite.value = false
  }
}

function copyInviteUrl() {
  if (!generatedInviteUrl.value) return
  navigator.clipboard.writeText(generatedInviteUrl.value)
  copied.value = true
  setTimeout(() => {
    copied.value = false
  }, 3000)
}

function fillAiForm(data) {
  aiSettings.value = data
  Object.assign(aiForm, { enabled: data.enabled, base_url: data.base_url, model: data.model, api_key: '' })
}

function aiPayload() {
  // An empty key field keeps the stored key
  return { ...aiForm, api_key: aiForm.api_key ? aiForm.api_key : null }
}

async function fetchAiSettings() {
  try {
    fillAiForm(await api.get('/api/admin/ai-settings'))
  } catch (err) {
    notify(err.detail || err.message, 'error')
  }
}

async function checkAiConnection() {
  checkingAi.value = true
  try {
    const res = await api.post('/api/admin/ai-settings/models', aiPayload())
    aiModels.value = res.models
    notify(t('ai.connection_ok', { count: res.models.length }), 'success')
  } catch (err) {
    aiModels.value = []
    notify(err.detail || err.message, 'error')
  } finally {
    checkingAi.value = false
  }
}

async function saveAiSettings() {
  savingAi.value = true
  try {
    fillAiForm(await api.put('/api/admin/ai-settings', aiPayload()))
    notify('ai.settings_saved', 'success')
  } catch (err) {
    notify(err.detail || err.message, 'error')
  } finally {
    savingAi.value = false
  }
}

onMounted(() => {
  fetchAdminWorkspaces()
  fetchAdminUsers()
  fetchAiSettings()
})
</script>

<style scoped>
.admin-tabs {
  display: flex;
  gap: 0.25rem;
  overflow-x: auto;
  border-bottom: var(--border-faint);
}

.admin-tabs .eink-tab {
  white-space: nowrap;
  flex-shrink: 0;
}

.admin-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.admin-table th {
  text-align: left;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-ink-500);
  padding: 0.5rem 0.75rem;
  border-bottom: var(--border-crisp);
  white-space: nowrap;
}

.admin-table td {
  padding: 0.75rem;
  border-bottom: var(--border-faint);
  vertical-align: middle;
}

.ai-settings {
  max-width: 40rem;
}

.meter-cell {
  min-width: 180px;
}

@media (max-width: 767px) {
  .admin-table th,
  .admin-table td {
    padding: 0.5rem;
  }
}
</style>
