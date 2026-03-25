<script setup lang="ts">
import { useRoute } from 'vue-router'
import UserMenu from './UserMenu.vue'

const route = useRoute()

const navItems = [
  { path: '/', label: '招标解读', icon: '📝', group: 'main' },
  { path: '/files/bid-documents', label: '招标文件', icon: '📁', group: 'files' },
  { path: '/files/reports', label: '解析报告', icon: '📊', group: 'files' },
  { path: '/files/formats', label: '文件格式', icon: '📐', group: 'files' },
  { path: '/files/checklists', label: '资料清单', icon: '📋', group: 'files' },
]

function isActive(path: string) {
  return route.path === path
}
</script>

<template>
  <aside class="w-[200px] min-w-[200px] bg-white border-r border-gray-200 flex flex-col h-screen">
    <div class="px-4 py-4 font-bold text-gray-800 text-base">
      招标分析系统
    </div>

    <nav class="flex-1 flex flex-col">
      <router-link
        v-for="item in navItems.filter(n => n.group === 'main')"
        :key="item.path"
        :to="item.path"
        data-testid="nav-item"
        :class="[
          'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors',
          isActive(item.path)
            ? 'active bg-purple-50 text-purple-700 font-medium border-l-[3px] border-purple-600'
            : 'text-gray-600 hover:bg-gray-50 border-l-[3px] border-transparent'
        ]"
      >
        <span>{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>

      <div class="h-px bg-gray-200 mx-4 my-3"></div>
      <div class="px-4 pb-1 text-xs text-gray-400">文档管理</div>

      <router-link
        v-for="item in navItems.filter(n => n.group === 'files')"
        :key="item.path"
        :to="item.path"
        data-testid="nav-item"
        :class="[
          'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors',
          isActive(item.path)
            ? 'active bg-purple-50 text-purple-700 font-medium border-l-[3px] border-purple-600'
            : 'text-gray-600 hover:bg-gray-50 border-l-[3px] border-transparent'
        ]"
      >
        <span>{{ item.icon }}</span>
        <span>{{ item.label }}</span>
      </router-link>
    </nav>

    <div class="border-t border-gray-200 p-3">
      <UserMenu />
    </div>
  </aside>
</template>
