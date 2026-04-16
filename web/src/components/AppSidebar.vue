<script setup lang="ts">
import { useRoute } from 'vue-router'
import { PenLine, FolderOpen, BarChart3, Ruler, ClipboardList, ShieldCheck, FileCheck, Users, Settings } from 'lucide-vue-next'
import { useAuthStore } from '../stores/authStore'
import UserMenu from './UserMenu.vue'

const route = useRoute()
const authStore = useAuthStore()

const navItems = [
  { path: '/', label: '招标解读', icon: PenLine, group: 'main' },
  { path: '/bid-review', label: '标书审查', icon: ShieldCheck, group: 'main' },
  { path: '/files/bid-documents', label: '招标文件', icon: FolderOpen, group: 'files' },
  { path: '/files/reports', label: '解析报告', icon: BarChart3, group: 'files' },
  { path: '/files/formats', label: '文件格式', icon: Ruler, group: 'files' },
  { path: '/files/checklists', label: '资料清单', icon: ClipboardList, group: 'files' },
  { path: '/review-results', label: '审查结果', icon: FileCheck, group: 'files' },
]

const adminItems = [
  { path: '/admin/users', label: '用户管理', icon: Users },
  { path: '/admin/config', label: '模型配置', icon: Settings },
]

function isActive(path: string) {
  return route.path === path
}
</script>

<template>
  <aside class="w-[200px] min-w-[200px] bg-surface border-r border-border flex flex-col h-screen">
    <div class="px-4 py-4 font-bold text-text-primary text-base">
      智能招投标文档分析系统
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
            ? 'active bg-primary-light text-primary font-medium border-l-[3px] border-primary'
            : 'text-text-secondary hover:bg-background border-l-[3px] border-transparent'
        ]"
      >
        <component :is="item.icon" class="size-4" />
        <span>{{ item.label }}</span>
      </router-link>

      <div class="h-px bg-border mx-4 my-3"></div>
      <div class="px-4 pb-1 text-xs text-text-muted">文档管理</div>

      <router-link
        v-for="item in navItems.filter(n => n.group === 'files')"
        :key="item.path"
        :to="item.path"
        data-testid="nav-item"
        :class="[
          'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors',
          isActive(item.path)
            ? 'active bg-primary-light text-primary font-medium border-l-[3px] border-primary'
            : 'text-text-secondary hover:bg-background border-l-[3px] border-transparent'
        ]"
      >
        <component :is="item.icon" class="size-4" />
        <span>{{ item.label }}</span>
      </router-link>

      <!-- Admin section (only visible to admin users) -->
      <template v-if="authStore.isAdmin">
        <div class="h-px bg-border mx-4 my-3"></div>
        <div class="px-4 pb-1 text-xs text-text-muted">管理</div>

        <router-link
          v-for="item in adminItems"
          :key="item.path"
          :to="item.path"
          :class="[
            'flex items-center gap-2 px-4 py-2.5 text-sm transition-colors',
            isActive(item.path)
              ? 'active bg-primary-light text-primary font-medium border-l-[3px] border-primary'
              : 'text-text-secondary hover:bg-background border-l-[3px] border-transparent'
          ]"
        >
          <component :is="item.icon" class="size-4" />
          <span>{{ item.label }}</span>
        </router-link>
      </template>
    </nav>

    <div class="border-t border-border p-3">
      <UserMenu />
    </div>
  </aside>
</template>
