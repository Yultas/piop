<template>
  <div class="invite-view">
    <!-- Checking the invite and this device -->
    <div v-if="loadingInvite" class="eink-card invite-card text-center">
      <p class="text-sm text-muted">{{ $t('fingerprint.status_analyzing') }}</p>
    </div>

    <!-- Invite not found, expired or revoked -->
    <div v-else-if="fatalError" class="eink-card invite-card">
      <h1 class="text-xl font-bold mb-2">{{ $t('invite.unavailable') }}</h1>
      <p class="text-sm text-muted mb-6">{{ localizedFatalError }}</p>
      <router-link to="/login" class="eink-btn w-full">
        <ArrowLeft :size="14" /> {{ $t('nav.login') }}
      </router-link>
    </div>

    <!-- Invite already bound to another device -->
    <div v-else-if="isDeviceLocked" class="eink-card invite-card">
      <div class="flex items-center gap-2 mb-2">
        <ShieldAlert :size="20" />
        <h1 class="text-xl font-bold">{{ $t('invite.locked_title') }}</h1>
      </div>
      <p class="text-sm leading-relaxed mb-6">{{ $t('fingerprint.device_locked_desc') }}</p>
      <router-link to="/login" class="eink-btn w-full">{{ $t('nav.login') }}</router-link>
    </div>

    <!-- Claim the invite or sign in again from the bound device -->
    <div v-else class="eink-card invite-card">
      <p class="text-sm text-muted mb-1">{{ $t('invite.workspace_invitation') }}</p>
      <h1 class="text-xl font-bold mb-2">{{ inviteData?.workspace_name }}</h1>
      <p class="text-sm text-muted mb-6">
        {{ isAlreadyClaimed ? $t('invite.claimed_hint') : $t('invite.new_hint') }}
        <template v-if="inviteData?.expires_at">
          {{ $t('invite.valid_until', { date: formatDate(inviteData.expires_at) }) }}
        </template>
      </p>

      <div v-if="submitError" class="error-box text-sm mb-4">{{ localizedSubmitError }}</div>

      <form class="flex flex-col gap-4" @submit.prevent="handleClaim">
        <div>
          <label class="eink-label">{{ $t('auth.username') }}</label>
          <input
            v-model="formUsername"
            type="text"
            required
            autocomplete="username"
            class="eink-input"
            :placeholder="$t('auth.username_placeholder')"
            :disabled="submitting"
          />
        </div>
        <div>
          <label class="eink-label">{{ $t('auth.password') }}</label>
          <input
            v-model="formPassword"
            type="password"
            required
            :autocomplete="isAlreadyClaimed ? 'current-password' : 'new-password'"
            class="eink-input"
            :placeholder="$t('auth.password_placeholder')"
            :disabled="submitting"
          />
        </div>

        <button type="submit" class="eink-btn eink-btn-primary w-full mt-2" :disabled="submitting">
          <span v-if="submitting">{{ $t('invite.processing') }}</span>
          <span v-else-if="isAlreadyClaimed">{{ $t('invite.reconnect_btn') }}</span>
          <span v-else>{{ $t('invite.claim_btn') }}</span>
        </button>
      </form>

      <p class="device-note text-xs text-muted" :title="`SHA-256: ${fingerprintHash}`">
        <Fingerprint :size="13" class="shrink-0" />
        {{ isAlreadyClaimed ? $t('invite.device_bound_note') : $t('invite.device_note') }}
      </p>
    </div>
  </div>
</template>

<script setup>
import { ArrowLeft, ShieldAlert, Fingerprint } from 'lucide-vue-next'
import { ref, computed, onMounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import api from '../api/client'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'
import { getDeviceFingerprintEntropy, getFingerprintPreview } from '../api/fingerprint'

const route = useRoute()
const router = useRouter()
const { te, t } = useI18n()
const authStore = useAuthStore()
const workspaceStore = useWorkspaceStore()

const token = computed(() => route.params.token)

function formatDate(isoStr) {
  if (!isoStr) return ''
  try {
    return new Date(isoStr).toLocaleDateString()
  } catch {
    return isoStr
  }
}

const loadingInvite = ref(true)
const submitting = ref(false)
const inviteData = ref(null)
const fatalError = ref('')
const submitError = ref('')
const isDeviceLocked = ref(false)

const rawEntropy = ref('')
const fingerprintHash = ref('')

const formUsername = ref('')
const formPassword = ref('')

const isAlreadyClaimed = computed(() => inviteData.value?.is_claimed || inviteData.value?.status === 'CLAIMED')

const localizedFatalError = computed(() => {
  if (!fatalError.value) return ''
  if (te(fatalError.value)) return t(fatalError.value)
  return fatalError.value
})

const localizedSubmitError = computed(() => {
  if (!submitError.value) return ''
  if (te(submitError.value)) return t(submitError.value)
  return submitError.value
})

onMounted(async () => {
  try {
    // 1. Gather device entropy
    rawEntropy.value = await getDeviceFingerprintEntropy()
    fingerprintHash.value = await getFingerprintPreview(rawEntropy.value)

    // 2. Fetch invite status from backend
    const data = await api.get(`/api/invites/${token.value}`)
    inviteData.value = data
  } catch (err) {
    fatalError.value = err.detail || err.message || 'auth.invite.not_found'
  } finally {
    loadingInvite.value = false
  }
})

async function handleClaim() {
  submitError.value = ''
  submitting.value = true

  try {
    const res = await api.post(`/api/invites/${token.value}/claim`, {
      username: formUsername.value,
      password: formPassword.value,
      raw_fingerprint: rawEntropy.value
    })

    // The claim response already set the session cookie; refresh user session
    await authStore.checkAuth()
    await workspaceStore.fetchWorkspaces()

    // Redirect directly into claimed workspace
    const wsId = res.workspace_id || inviteData.value?.workspace_id
    if (wsId) {
      router.push(`/workspaces/${wsId}`)
    } else {
      router.push('/workspaces')
    }
  } catch (err) {
    if (err.status === 403 && err.detail === 'auth.invite.device_locked') {
      isDeviceLocked.value = true
    } else {
      // A 422 detail is a list of validation errors, not a message key
      submitError.value = typeof err.detail === 'string' ? err.detail : 'common.error'
    }
  } finally {
    submitting.value = false
  }
}
</script>

<style scoped>
.invite-view {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: calc(100vh - 140px);
  padding: 2rem 1rem;
}

.invite-card {
  width: 100%;
  max-width: 28rem;
  padding: 1.5rem;
}

.error-box {
  padding: 0.6rem 0.75rem;
  border: 1px dashed var(--color-ink-900);
}

.device-note {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  margin-top: 1rem;
}
</style>
