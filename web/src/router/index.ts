import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/login',
    name: 'login',
    component: () => import('../views/LoginView.vue'),
  },
  {
    path: '/',
    component: () => import('../layouts/SidebarLayout.vue'),
    meta: { requiresAuth: true },
    children: [
      {
        path: '',
        name: 'bid-analysis',
        component: () => import('../views/BidAnalysisView.vue'),
      },
      {
        path: 'files/:fileType',
        name: 'file-manager',
        component: () => import('../views/FileManagerView.vue'),
        props: true,
      },
      {
        path: 'files/:fileType/:id/preview',
        name: 'file-preview',
        component: () => import('../views/FilePreviewView.vue'),
        props: true,
      },
      {
        path: 'admin/users',
        name: 'admin-users',
        component: () => import('../views/AdminUsersView.vue'),
        meta: { requiresAdmin: true },
      },
    ],
  },
]

const router = createRouter({ history: createWebHistory(), routes })

router.beforeEach((to) => {
  const token = localStorage.getItem('access_token')
  if (to.matched.some(r => r.meta.requiresAuth) && !token) return { name: 'login' }
})

export default router
