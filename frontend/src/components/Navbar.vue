<template>
  <header class="navbar">
    <div class="app-container navbar-inner">
      <div class="nav-left">
        <router-link to="/workspaces" class="brand-link" :title="$t('nav.workspaces')">
          <span class="brand-box"><PenTool :size="15" /></span>
          <span class="brand-name">{{ $t('nav.brand') }}</span>
        </router-link>

        <select
          v-if="authStore.isAuthenticated && workspaceStore.workspaces.length > 1"
          class="eink-select ws-select"
          :value="workspaceStore.currentWorkspace?.id || ''"
          :aria-label="$t('nav.select_workspace')"
          @change="onWorkspaceChange"
        >
          <option value="" disabled>{{ $t('nav.select_workspace') }}</option>
          <option
            v-for="ws in workspaceStore.workspaces"
            :key="ws.id"
            :value="ws.id"
          >
            {{ ws.name }}
          </option>
        </select>
      </div>

      <div class="nav-right">
        <router-link
          v-if="authStore.isAdmin"
          to="/admin"
          class="eink-btn eink-btn-sm"
          active-class="eink-btn-primary"
          :title="$t('nav.admin')"
        >
          <Settings :size="14" />
          <span class="hide-sm">{{ $t('nav.admin') }}</span>
        </router-link>

        <button
          type="button"
          class="eink-btn eink-btn-sm lang-btn"
          :title="currentLang === 'ru' ? 'English' : 'Русский'"
          @click="switchLang(currentLang === 'ru' ? 'en' : 'ru')"
        >
          {{ currentLang === 'ru' ? $t('nav.lang_en') : $t('nav.lang_ru') }}
        </button>

        <template v-if="authStore.isAuthenticated">
          <span class="username hide-sm text-xs">{{ authStore.username }}</span>
          <button
            type="button"
            class="eink-btn eink-btn-sm"
            :title="$t('nav.logout')"
            @click="handleLogout"
          >
            <LogOut :size="14" />
            <span class="hide-sm">{{ $t('nav.logout') }}</span>
          </button>
        </template>

        <router-link v-else-if="$route.name !== 'login'" to="/login" class="eink-btn eink-btn-sm eink-btn-primary">
          {{ $t('nav.login') }}
        </router-link>
      </div>
    </div>
  </header>
</template>

<script setup>
import { computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { Settings, LogOut, PenTool } from 'lucide-vue-next'
import { useAuthStore } from '../stores/auth'
import { useWorkspaceStore } from '../stores/workspace'
import { setLocale } from '../i18n'

const router = useRouter()
const { locale } = useI18n()
const authStore = useAuthStore()
const workspaceStore = useWorkspaceStore()

const currentLang = computed(() => locale.value)

function switchLang(lang) {
  setLocale(lang)
}

function onWorkspaceChange(event) {
  const wsId = Number(event.target.value)
  const targetWs = workspaceStore.workspaces.find((w) => w.id === wsId)
  if (targetWs) {
    workspaceStore.setCurrentWorkspace(targetWs)
    router.push(`/workspaces/${wsId}`)
  }
}

async function handleLogout() {
  await authStore.logout()
  workspaceStore.setCurrentWorkspace(null)
  router.push('/login')
}
</script>

<style scoped>
.navbar {
  background-color: var(--color-paper-card);
  border-bottom: var(--border-crisp);
  position: sticky;
  top: 0;
  z-index: 20;
}

.navbar-inner {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 1rem;
  height: 52px;
}

.nav-left,
.nav-right {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  min-width: 0;
}

.nav-right {
  gap: 0.5rem;
  flex-shrink: 0;
}

.brand-link {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  text-decoration: none;
  color: var(--color-ink-900);
  font-weight: 700;
  letter-spacing: 0.05em;
  flex-shrink: 0;
}

.brand-box {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  background-color: var(--color-ink-900);
  color: var(--color-paper);
}

.ws-select {
  width: auto;
  max-width: 220px;
  padding: 0.3rem 0.5rem;
  font-size: 0.8125rem;
}

.lang-btn {
  font-family: var(--font-mono);
  min-width: 2.25rem;
}

.username {
  color: var(--color-ink-500);
  padding: 0 0.25rem;
}

@media (max-width: 640px) {
  .hide-sm,
  .brand-name { display: none; }
  .ws-select { max-width: 150px; }
}
</style>
