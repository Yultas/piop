<template>
  <div id="eink-app" class="min-h-screen flex flex-col">
    <Navbar />

    <!-- Main View Outlet -->
    <main class="flex-1 app-main">
      <router-view v-slot="{ Component, route }">
        <Transition name="route" mode="out-in">
          <component :is="Component" :key="route.path" />
        </Transition>
      </router-view>
    </main>

  </div>
</template>

<script setup>
import { onMounted } from 'vue'
import Navbar from './components/Navbar.vue'
import { useAuthStore } from './stores/auth'

const authStore = useAuthStore()

onMounted(async () => {
  // Check auth session on startup
  if (!authStore.initialized) {
    await authStore.checkAuth()
  }
})
</script>

<style>
#eink-app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}
.flex-1 {
  flex: 1 1 0%;
}
.app-main {
  padding: 2rem 0 3rem;
}
@media (max-width: 640px) {
  .app-main { padding: 1.25rem 0 2rem; }
}
</style>
