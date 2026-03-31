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
        path: 'bid-review',
        name: 'bid-review',
        component: () => import('../views/BidReviewView.vue'),
      },
      {
        path: 'review-results',
        name: 'review-results',
        component: () => import('../views/ReviewResultsView.vue'),
      },
      {
        path: 'review-results/:id',
        name: 'review-detail',
        component: () => import('../views/ReviewDetailView.vue'),
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

router.beforeEach(async (to) => {
  const token = localStorage.getItem('access_token')
  if (to.matched.some(r => r.meta.requiresAuth) && !token) return { name: 'login' }

  if (token) {
    const { useAuthStore } = await import('../stores/authStore')
    const auth = useAuthStore()
    if (!auth.user) {
      await auth.fetchUser()
    }
  }
})

export default router
