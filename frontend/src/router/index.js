import { createRouter, createWebHistory } from 'vue-router'
import { useAuthStore } from '../stores/auth'

const routes = [
  {
    path: '/',
    redirect: '/workspaces'
  },
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
    meta: { guestOnly: true }
  },
  {
    path: '/invite/:token',
    name: 'invite',
    component: () => import('../views/InviteView.vue'),
    meta: { public: true }
  },
  {
    path: '/workspaces',
    name: 'workspaces',
    component: () => import('../views/WorkspacesView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/workspaces/:id',
    name: 'workspace-detail',
    component: () => import('../views/WorkspaceDetailView.vue'),
    meta: { requiresAuth: true }
  },
  {
    path: '/admin',
    name: 'admin',
    component: () => import('../views/AdminView.vue'),
    meta: { requiresAuth: true, requiresAdmin: true }
  },
  {
    path: '/:pathMatch(.*)*',
    redirect: '/workspaces'
  }
]

export const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach(async (to, from, next) => {
  const authStore = useAuthStore()

  // Ensure auth state is resolved
  if (!authStore.initialized) {
    await authStore.checkAuth()
  }

  const isAuth = authStore.isAuthenticated
  const isAdmin = authStore.isAdmin

  if (to.meta.guestOnly && isAuth) {
    return next('/workspaces')
  }

  if (to.meta.requiresAuth && !isAuth) {
    return next({ path: '/login', query: { redirect: to.fullPath } })
  }

  if (to.meta.requiresAdmin && !isAdmin) {
    return next('/workspaces')
  }

  next()
})

export default router
