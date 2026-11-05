import { defineStore } from 'pinia'
import api from '../api/client'

// Legacy cleanup: the JWT used to live in localStorage. Sessions are now HttpOnly cookies,
// so drop the stale key once on load.
try {
  localStorage.removeItem('eink_token')
} catch (err) {
  // localStorage unavailable (e.g. blocked storage); there is nothing to clean up
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    user: null,
    loading: false,
    initialized: false
  }),

  getters: {
    isAuthenticated: (state) => Boolean(state.user),
    isAdmin: (state) => Boolean(state.user?.is_global_admin),
    username: (state) => state.user?.username || ''
  },

  actions: {
    setUser(user) {
      this.user = user
    },

    async login(username, password) {
      this.loading = true
      try {
        const data = await api.post('/api/auth/login', { username, password })
        this.setUser(data.user)
        return data
      } finally {
        this.loading = false
      }
    },

    async checkAuth() {
      this.loading = true
      try {
        const user = await api.get('/api/auth/me')
        this.user = user
        this.initialized = true
        return true
      } catch (err) {
        this.clearSession()
        this.initialized = true
        return false
      } finally {
        this.loading = false
      }
    },

    // Local-only: forget the user without calling the server (used on 401 to avoid loops)
    clearSession() {
      this.user = null
    },

    // Best-effort server logout clears the session cookie, then the local user
    async logout() {
      try {
        await api.post('/api/auth/logout')
      } catch (err) {
        // Ignore: the local session is cleared either way
      }
      this.clearSession()
    }
  }
})

// Global event listener for session expiration
if (typeof window !== 'undefined') {
  window.addEventListener('eink:unauthorized', () => {
    const authStore = useAuthStore()
    authStore.clearSession()
  })
}

export default useAuthStore
