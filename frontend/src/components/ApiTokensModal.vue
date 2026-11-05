<template>
  <EinkModal :open="open" :title="$t('tokens.title')" maxWidth="40rem" @close="emit('close')">
    <p class="text-sm mb-4">{{ $t('tokens.intro') }}</p>

    <div class="mb-4">
      <label class="ui-label text-sm font-semibold block mb-1">{{ $t('tokens.mcp_url') }}</label>
      <div class="flex gap-2">
        <input ref="mcpFieldRef" :value="mcpUrl" readonly class="eink-input text-xs" />
        <button
          type="button"
          class="eink-btn eink-btn-sm whitespace-nowrap"
          @click="copyText(mcpUrl, mcpFieldRef, 'mcp')"
        >
          {{ copiedKey === 'mcp' ? $t('common.copied') : $t('common.copy') }}
        </button>
      </div>
    </div>

    <form @submit.prevent="createToken" class="flex gap-2 items-end mb-6">
      <div class="flex-1">
        <label class="ui-label text-sm font-semibold block mb-1">{{ $t('tokens.name_label') }}</label>
        <input
          v-model="newName"
          type="text"
          maxlength="100"
          class="eink-input"
          :placeholder="$t('tokens.name_placeholder')"
        />
      </div>
      <button
        type="submit"
        class="eink-btn eink-btn-primary whitespace-nowrap"
        :disabled="!newName.trim() || creating"
      >
        {{ $t('tokens.create_btn') }}
      </button>
    </form>

    <div v-if="createdToken" class="mb-6 p-4 border">
      <h3 class="text-sm font-bold mb-1">{{ $t('tokens.created_heading') }}</h3>
      <p class="text-sm mb-3">{{ $t('tokens.created_warning') }}</p>

      <label class="ui-label text-sm font-semibold block mb-1">{{ $t('tokens.token_label') }}</label>
      <div class="flex gap-2 mb-3">
        <input ref="tokenFieldRef" :value="createdToken.token" readonly class="eink-input text-xs" />
        <button
          type="button"
          class="eink-btn eink-btn-sm whitespace-nowrap"
          @click="copyText(createdToken.token, tokenFieldRef, 'token')"
        >
          {{ copiedKey === 'token' ? $t('common.copied') : $t('common.copy') }}
        </button>
      </div>

      <label class="ui-label text-sm font-semibold block mb-1">{{ $t('tokens.command_label') }}</label>
      <div class="flex gap-2">
        <input ref="commandFieldRef" :value="claudeCommand" readonly class="eink-input text-xs" />
        <button
          type="button"
          class="eink-btn eink-btn-sm whitespace-nowrap"
          @click="copyText(claudeCommand, commandFieldRef, 'command')"
        >
          {{ copiedKey === 'command' ? $t('common.copied') : $t('common.copy') }}
        </button>
      </div>
    </div>

    <h3 class="text-sm font-bold mb-2">{{ $t('tokens.list_heading') }}</h3>

    <div v-if="loading" class="text-center text-sm py-4">{{ $t('common.loading') }}</div>
    <p v-else-if="!tokens.length" class="text-sm text-muted">{{ $t('tokens.empty') }}</p>

    <div v-else class="overflow-x-auto">
      <table class="admin-table">
        <thead>
          <tr>
            <th>{{ $t('tokens.col_name') }}</th>
            <th>{{ $t('tokens.col_prefix') }}</th>
            <th>{{ $t('tokens.col_created') }}</th>
            <th>{{ $t('tokens.col_last_used') }}</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="tok in tokens" :key="tok.id">
            <td class="font-bold text-sm">{{ tok.name }}</td>
            <td class="text-muted text-xs">{{ tok.prefix }}…</td>
            <td class="text-muted">{{ formatDate(tok.created_at) }}</td>
            <td class="text-muted">{{ tok.last_used_at ? formatDate(tok.last_used_at) : $t('tokens.never') }}</td>
            <td class="text-right">
              <template v-if="revokeId === tok.id">
                <button
                  type="button"
                  class="eink-btn eink-btn-sm eink-btn-danger"
                  :disabled="revoking"
                  @click="revokeToken(tok.id)"
                >
                  {{ $t('tokens.revoke_confirm') }}
                </button>
                <button type="button" class="eink-btn eink-btn-sm" @click="revokeId = null">
                  {{ $t('common.cancel') }}
                </button>
              </template>
              <button
                v-else
                type="button"
                class="eink-btn eink-btn-sm eink-btn-danger"
                @click="revokeId = tok.id"
              >
                {{ $t('tokens.revoke') }}
              </button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>

    <p v-if="notice" class="text-sm mt-4">{{ notice }}</p>
    <p v-if="error" class="text-sm mt-4 font-bold">{{ error }}</p>
  </EinkModal>
</template>

<script setup>
import { ref, computed, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import EinkModal from './EinkModal.vue'
import api from '../api/client'

const props = defineProps({
  open: Boolean
})

const emit = defineEmits(['close'])

const { t, te } = useI18n()

const tokens = ref([])
const loading = ref(false)
const creating = ref(false)
const revoking = ref(false)
const newName = ref('')
const createdToken = ref(null)
const revokeId = ref(null)
const copiedKey = ref('')
const notice = ref('')
const error = ref('')

const mcpFieldRef = ref(null)
const tokenFieldRef = ref(null)
const commandFieldRef = ref(null)

const mcpUrl = computed(() => `${window.location.origin}/api/mcp`)

const claudeCommand = computed(() =>
  createdToken.value
    ? `claude mcp add --transport http piop ${mcpUrl.value} --header "Authorization: Bearer ${createdToken.value.token}"`
    : ''
)

function errorText(err) {
  const detail = err?.detail ?? err?.message
  if (typeof detail === 'string' && te(detail)) return t(detail)
  return typeof detail === 'string' && detail ? detail : t('common.error')
}

function formatDate(iso) {
  return iso ? new Date(iso).toLocaleString() : ''
}

async function loadTokens() {
  loading.value = true
  error.value = ''
  try {
    tokens.value = await api.get('/api/auth/tokens')
  } catch (err) {
    error.value = errorText(err)
  } finally {
    loading.value = false
  }
}

async function createToken() {
  const name = newName.value.trim()
  if (!name) return
  creating.value = true
  error.value = ''
  notice.value = ''
  try {
    createdToken.value = await api.post('/api/auth/tokens', { name })
    newName.value = ''
    notice.value = t('tokens.created')
    await loadTokens()
  } catch (err) {
    error.value = errorText(err)
  } finally {
    creating.value = false
  }
}

async function revokeToken(id) {
  revoking.value = true
  error.value = ''
  notice.value = ''
  try {
    await api.delete(`/api/auth/tokens/${id}`)
    if (createdToken.value?.id === id) createdToken.value = null
    revokeId.value = null
    notice.value = t('tokens.revoked')
    await loadTokens()
  } catch (err) {
    error.value = errorText(err)
  } finally {
    revoking.value = false
  }
}

// Copy via the clipboard API; if it is unavailable or refused, select the field so the user can copy manually
async function copyText(text, field, key) {
  try {
    await navigator.clipboard.writeText(text)
    copiedKey.value = key
    setTimeout(() => {
      if (copiedKey.value === key) copiedKey.value = ''
    }, 2000)
  } catch (err) {
    field?.focus()
    field?.select()
  }
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      loadTokens()
    } else {
      createdToken.value = null
      newName.value = ''
      revokeId.value = null
      notice.value = ''
      error.value = ''
      copiedKey.value = ''
    }
  }
)
</script>
