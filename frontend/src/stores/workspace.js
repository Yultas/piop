import { defineStore } from 'pinia'
import api from '../api/client'

export const useWorkspaceStore = defineStore('workspace', {
  state: () => ({
    workspaces: [],
    currentWorkspace: null,
    loading: false,
    error: null
  }),

  getters: {
    currentQuotaMB: (state) => {
      if (!state.currentWorkspace?.storage_quota_bytes) return 0
      return Math.round((state.currentWorkspace.storage_quota_bytes / (1024 * 1024)) * 10) / 10
    },
    currentUsedMB: (state) => {
      if (!state.currentWorkspace?.used_storage_bytes) return 0
      return Math.round((state.currentWorkspace.used_storage_bytes / (1024 * 1024)) * 10) / 10
    },
    isCurrentAdmin: (state) => {
      return state.currentWorkspace?.role === 'admin'
    }
  },

  actions: {
    async fetchWorkspaces() {
      this.loading = true
      this.error = null
      try {
        const data = await api.get('/api/workspaces')
        this.workspaces = data || []
        
        // Restore current workspace if available
        const savedId = localStorage.getItem('eink_current_ws')
        if (savedId) {
          const match = this.workspaces.find((w) => String(w.id) === String(savedId))
          if (match) {
            this.currentWorkspace = match
          }
        }
        return this.workspaces
      } catch (err) {
        this.error = err.detail || err.message
        throw err
      } finally {
        this.loading = false
      }
    },

    async fetchWorkspace(id) {
      this.loading = true
      try {
        const ws = await api.get(`/api/workspaces/${id}`)
        this.currentWorkspace = ws
        localStorage.setItem('eink_current_ws', String(ws.id))
        return ws
      } catch (err) {
        this.error = err.detail || err.message
        throw err
      } finally {
        this.loading = false
      }
    },

    setCurrentWorkspace(workspace) {
      this.currentWorkspace = workspace
      if (workspace?.id) {
        localStorage.setItem('eink_current_ws', String(workspace.id))
      } else {
        localStorage.removeItem('eink_current_ws')
      }
    },

    async createWorkspace(name, description, storageQuotaMb = 500) {
      this.loading = true
      try {
        const ws = await api.post('/api/workspaces', {
          name,
          description,
          storage_quota_mb: Number(storageQuotaMb)
        })
        await this.fetchWorkspaces()
        return ws
      } finally {
        this.loading = false
      }
    },

    async updateQuota(workspaceId, storageQuotaMb) {
      const res = await api.put(`/api/workspaces/${workspaceId}/quota`, {
        storage_quota_mb: Number(storageQuotaMb)
      })
      if (this.currentWorkspace && this.currentWorkspace.id === workspaceId) {
        this.currentWorkspace.storage_quota_bytes = res.storage_quota_bytes
      }
      const match = this.workspaces.find((w) => w.id === workspaceId)
      if (match) {
        match.storage_quota_bytes = res.storage_quota_bytes
      }
      return res
    }
  }
})

export default useWorkspaceStore
