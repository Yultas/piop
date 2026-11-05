<template>
  <div class="login-view flex justify-center items-center">
    <div class="eink-card p-6 w-full max-w-md">
      <h1 class="text-xl font-bold mb-6">{{ $t('auth.title') }}</h1>

      <form @submit.prevent="handleLogin" class="flex flex-col gap-4">
        <!-- Error Alert -->
        <div
          v-if="errorMessage"
          class="p-3 border text-xs eink-card-muted flex items-start gap-2"
        >
          <span class="font-bold text-sm">!</span>
          <span>{{ localizedError }}</span>
        </div>

        <div>
          <label class="ui-label text-sm font-semibold block mb-1">
            {{ $t('auth.username') }}
          </label>
          <input
            v-model="username"
            type="text"
            required
            autocomplete="username"
            class="eink-input"
            :placeholder="$t('auth.username_placeholder')"
            :disabled="authStore.loading"
          />
        </div>

        <div>
          <label class="ui-label text-sm font-semibold block mb-1">
            {{ $t('auth.password') }}
          </label>
          <input
            v-model="password"
            type="password"
            required
            autocomplete="current-password"
            class="eink-input"
            :placeholder="$t('auth.password_placeholder')"
            :disabled="authStore.loading"
          />
        </div>

        <button
          type="submit"
          class="eink-btn eink-btn-primary w-full mt-2"
          :disabled="authStore.loading"
        >
          <span v-if="authStore.loading">{{ $t('auth.logging_in') }}</span>
          <span v-else>{{ $t('auth.login_btn') }}</span>
        </button>
      </form>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'

const router = useRouter()
const route = useRoute()
const { te, t } = useI18n()
const authStore = useAuthStore()
const workspaceStore = useWorkspaceStore()

const username = ref('')
const password = ref('')
const errorMessage = ref('')

const localizedError = computed(() => {
  if (!errorMessage.value) return ''
  if (te(errorMessage.value)) {
    return t(errorMessage.value)
  }
  return errorMessage.value
})

async function handleLogin() {
  errorMessage.value = ''
  try {
    await authStore.login(username.value, password.value)
    await workspaceStore.fetchWorkspaces()

    const redirectPath = route.query.redirect || '/workspaces'
    router.push(redirectPath)
  } catch (err) {
    errorMessage.value = err.detail || err.message || 'auth.invalid_credentials'
  }
}
</script>

<style scoped>
.login-view {
  min-height: calc(100vh - 140px);
  padding: 2rem 1rem;
}
.max-w-md {
  max-width: 28rem;
}
</style>
