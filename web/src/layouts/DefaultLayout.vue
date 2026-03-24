<script setup lang="ts">
import { useAuthStore } from '../stores/authStore'
import { useRouter } from 'vue-router'

const auth = useAuthStore()
const router = useRouter()

function logout() {
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="min-h-screen bg-gray-50">
    <header class="bg-white shadow-sm border-b">
      <div class="max-w-7xl mx-auto px-4 py-3 flex items-center justify-between">
        <router-link to="/" class="text-lg font-bold text-gray-800">招标文件分析系统</router-link>
        <div class="flex items-center gap-4">
          <span class="text-sm text-gray-600">{{ auth.user?.display_name || auth.user?.username }}</span>
          <button @click="logout" class="text-sm text-gray-500 hover:text-red-500">退出</button>
        </div>
      </div>
    </header>
    <main class="max-w-7xl mx-auto px-4 py-6">
      <slot />
    </main>
  </div>
</template>
