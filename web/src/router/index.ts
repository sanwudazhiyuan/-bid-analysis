import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/login', name: 'login', component: () => import('../views/LoginView.vue') },
  { path: '/', name: 'dashboard', component: () => import('../views/DashboardView.vue'), meta: { requiresAuth: true } },
  { path: '/tasks/:id', name: 'task-detail', component: () => import('../views/TaskDetailView.vue'), meta: { requiresAuth: true } },
  { path: '/tasks/:id/preview', name: 'preview', component: () => import('../views/PreviewView.vue'), meta: { requiresAuth: true } },
  { path: '/admin/users', name: 'admin-users', component: () => import('../views/AdminUsersView.vue'), meta: { requiresAuth: true, requiresAdmin: true } },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.meta.requiresAuth && !token) return { name: 'login' }
})

export default router
