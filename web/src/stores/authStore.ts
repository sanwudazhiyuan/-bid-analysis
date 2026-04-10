import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { authApi } from '../api/auth'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref(localStorage.getItem('access_token') || '')
  const user = ref<{ id: number; username: string; display_name: string | null; role: string } | null>(null)

  const isAuthenticated = computed(() => !!accessToken.value)
  const isAdmin = computed(() => user.value?.role === 'admin')

  function setTokens(access: string, refresh: string) {
    accessToken.value = access
    localStorage.setItem('access_token', access)
    localStorage.setItem('refresh_token', refresh)
  }

  async function fetchUser() {
    if (!accessToken.value) return
    try {
      const res = await authApi.me()
      user.value = res.data
    } catch (err: any) {
      // 只有 401 未授权才清除 token，其他错误（网络问题等）保留登录状态
      if (err?.response?.status === 401) {
        logout()
      }
    }
  }

  function logout() {
    accessToken.value = ''
    user.value = null
    localStorage.removeItem('access_token')
    localStorage.removeItem('refresh_token')
  }

  return { accessToken, user, isAuthenticated, isAdmin, setTokens, fetchUser, logout }
})
