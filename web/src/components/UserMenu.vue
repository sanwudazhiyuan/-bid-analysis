<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '../stores/authStore'

const auth = useAuthStore()
const router = useRouter()
const showMenu = ref(false)

function toggleMenu() {
  showMenu.value = !showMenu.value
}

function goToUserManagement() {
  showMenu.value = false
  router.push('/admin/users')
}

function logout() {
  showMenu.value = false
  auth.logout()
  router.push('/login')
}
</script>

<template>
  <div class="relative">
    <div
      data-testid="user-avatar"
      class="flex items-center gap-2 cursor-pointer hover:bg-gray-100 rounded-lg p-2 transition-colors"
      @click="toggleMenu"
    >
      <div class="w-8 h-8 bg-purple-600 rounded-full flex items-center justify-center text-white text-sm font-medium">
        {{ (auth.user?.display_name || auth.user?.username || '?')[0].toUpperCase() }}
      </div>
      <div class="flex-1 min-w-0">
        <div class="text-sm font-medium text-gray-800 truncate">{{ auth.user?.display_name || auth.user?.username }}</div>
        <div class="text-xs text-gray-400 truncate">{{ auth.user?.username }}</div>
      </div>
      <span class="text-gray-400 text-xs">{{ showMenu ? '▴' : '▾' }}</span>
    </div>

    <div
      v-if="showMenu"
      class="absolute bottom-full left-0 right-0 mb-1 bg-white border border-gray-200 rounded-lg shadow-lg py-1 z-50"
    >
      <button
        v-if="auth.isAdmin"
        class="w-full text-left px-3 py-2 text-sm text-gray-600 hover:bg-gray-50 transition-colors"
        @click="goToUserManagement"
      >
        用户管理
      </button>
      <button
        class="w-full text-left px-3 py-2 text-sm text-red-500 hover:bg-gray-50 transition-colors"
        @click="logout"
      >
        退出登录
      </button>
    </div>
  </div>
</template>
