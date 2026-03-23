import axios from 'axios'
import { useAuthStore } from '../stores/authStore'

const client = axios.create({ baseURL: '/api' })

client.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

client.interceptors.response.use(
  (res) => res,
  async (error) => {
    if (error.response?.status === 401) {
      const refresh = localStorage.getItem('refresh_token')
      if (refresh && !error.config._retry) {
        error.config._retry = true
        try {
          const res = await axios.post('/api/auth/refresh', { refresh_token: refresh })
          const store = useAuthStore()
          store.setTokens(res.data.access_token, res.data.refresh_token)
          error.config.headers.Authorization = `Bearer ${res.data.access_token}`
          return client(error.config)
        } catch {
          const store = useAuthStore()
          store.logout()
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(error)
  }
)

export default client
