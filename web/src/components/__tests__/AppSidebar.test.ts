import { describe, it, expect, beforeEach } from 'vitest'
import { mount } from '@vue/test-utils'
import { createPinia, setActivePinia } from 'pinia'
import { createRouter, createMemoryHistory } from 'vue-router'
import AppSidebar from '../AppSidebar.vue'
import { useAuthStore } from '../../stores/authStore'

const router = createRouter({
  history: createMemoryHistory(),
  routes: [
    { path: '/', component: { template: '<div />' } },
    { path: '/files/bid-documents', component: { template: '<div />' } },
    { path: '/files/reports', component: { template: '<div />' } },
    { path: '/files/formats', component: { template: '<div />' } },
    { path: '/files/checklists', component: { template: '<div />' } },
    { path: '/admin/users', component: { template: '<div />' } },
    { path: '/login', component: { template: '<div />' } },
  ],
})

function mountSidebar(userOverride = {}) {
  const pinia = createPinia()
  setActivePinia(pinia)

  const auth = useAuthStore()
  auth.user = { id: 1, username: 'testuser', display_name: 'Test', role: 'user', ...userOverride }
  auth.accessToken = 'fake-token'

  return mount(AppSidebar, {
    global: { plugins: [pinia, router] },
  })
}

describe('AppSidebar', () => {
  beforeEach(async () => {
    await router.push('/')
    await router.isReady()
  })

  it('renders 5 navigation items', () => {
    const wrapper = mountSidebar()
    const navItems = wrapper.findAll('[data-testid="nav-item"]')
    expect(navItems.length).toBe(5)
  })

  it('highlights active route', async () => {
    await router.push('/files/reports')
    const wrapper = mountSidebar()
    const active = wrapper.find('[data-testid="nav-item"].active')
    expect(active.exists()).toBe(true)
    expect(active.text()).toContain('解析报告')
  })

  it('shows user info at bottom', () => {
    const wrapper = mountSidebar({ username: 'admin', display_name: 'Admin' })
    expect(wrapper.text()).toContain('admin')
  })

  it('shows admin menu item for admin users', async () => {
    const wrapper = mountSidebar({ role: 'admin' })
    await wrapper.find('[data-testid="user-avatar"]').trigger('click')
    expect(wrapper.text()).toContain('用户管理')
  })

  it('hides admin menu item for regular users', async () => {
    const wrapper = mountSidebar({ role: 'user' })
    await wrapper.find('[data-testid="user-avatar"]').trigger('click')
    expect(wrapper.text()).not.toContain('用户管理')
  })
})
