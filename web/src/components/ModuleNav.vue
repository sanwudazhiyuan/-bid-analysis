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
  <nav class="w-56 bg-surface border-r overflow-y-auto h-full">
    <div v-for="(mod, key) in props.modules" :key="key" class="py-1">
      <button v-if="mod"
        @click="selectModule(key as string)"
        :class="['w-full text-left px-4 py-2 text-sm hover:bg-background',
          store.currentModule === key ? 'bg-primary-light text-primary font-medium' : 'text-text-secondary']">
        {{ mod.title }}
      </button>
      <div v-if="mod && store.currentModule === key">
        <button v-for="sec in mod.sections" :key="sec.id"
          @click="selectSection(key as string, sec.id)"
          :class="['w-full text-left pl-8 pr-4 py-1 text-xs hover:bg-background',
            store.currentSection === sec.id ? 'text-primary font-medium' : 'text-text-muted']">
          {{ sec.id }} {{ sec.title }}
        </button>
      </div>
    </div>
  </nav>
</template>
