<script setup lang="ts">
import { usePreviewStore } from '../stores/previewStore'
import type { Module } from '../types/preview'

const store = usePreviewStore()
const props = defineProps<{ modules: Record<string, Module | null> }>()

function selectModule(key: string) {
  store.currentModule = key
  store.currentSection = ''
}

function selectSection(moduleKey: string, sectionId: string) {
  store.currentModule = moduleKey
  store.currentSection = sectionId
}
</script>

<template>
  <nav class="w-56 bg-white border-r overflow-y-auto h-full">
    <div v-for="(mod, key) in props.modules" :key="key" class="py-1">
      <button v-if="mod"
        @click="selectModule(key as string)"
        :class="['w-full text-left px-4 py-2 text-sm hover:bg-gray-100',
          store.currentModule === key ? 'bg-blue-50 text-blue-700 font-medium' : 'text-gray-700']">
        {{ mod.title }}
      </button>
      <div v-if="mod && store.currentModule === key">
        <button v-for="sec in mod.sections" :key="sec.id"
          @click="selectSection(key as string, sec.id)"
          :class="['w-full text-left pl-8 pr-4 py-1 text-xs hover:bg-gray-50',
            store.currentSection === sec.id ? 'text-blue-600 font-medium' : 'text-gray-500']">
          {{ sec.id }} {{ sec.title }}
        </button>
      </div>
    </div>
  </nav>
</template>
