<script setup lang="ts">
import { ref } from 'vue'
import { Upload, EyeOff } from 'lucide-vue-next'
import { useAnbiaoStore } from '../stores/anbiaoStore'

const store = useAnbiaoStore()

// --- Rule file upload (optional) ---
const ruleFile = ref<File | null>(null)
const ruleDragOver = ref(false)

function handleRuleDrop(e: DragEvent) {
  ruleDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file && (file.name.endsWith('.docx') || file.name.endsWith('.doc') || file.name.endsWith('.pdf'))) {
    ruleFile.value = file
  }
}

function handleRuleFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) ruleFile.value = input.files[0]
}

function clearRuleFile() {
  ruleFile.value = null
}

// --- Tender file upload (required) ---
const tenderFile = ref<File | null>(null)
const tenderDragOver = ref(false)

function handleTenderDrop(e: DragEvent) {
  tenderDragOver.value = false
  const file = e.dataTransfer?.files[0]
  if (file && (file.name.endsWith('.docx') || file.name.endsWith('.doc') || file.name.endsWith('.pdf'))) {
    tenderFile.value = file
  }
}

function handleTenderFileSelect(e: Event) {
  const input = e.target as HTMLInputElement
  if (input.files?.[0]) tenderFile.value = input.files[0]
}

// --- Default rules toggle ---
const useDefaultRules = ref(true)

// --- Start review ---
const submitting = ref(false)

async function startReview() {
  if (!tenderFile.value) return
  submitting.value = true
  try {
    await store.startReview(tenderFile.value, ruleFile.value, useDefaultRules.value)
  } catch { /* error shown via store */ }
  finally { submitting.value = false }
}
</script>

<template>
  <div class="max-w-2xl mx-auto py-8 space-y-6">
    <h2 class="text-xl font-semibold text-text-primary">暗标审查</h2>
    <p class="text-sm text-text-muted">上传暗标规则文档和待审查标书，系统将区分格式规则和内容规则分别审查。</p>

    <!-- Rule file upload (optional) -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">暗标规则文档（可选）</label>
      <div
        class="border-2 border-dashed rounded-lg p-6 text-center transition-colors"
        :class="ruleDragOver ? 'border-success bg-success/5' : 'border-border'"
        @dragover.prevent="ruleDragOver = true"
        @dragleave="ruleDragOver = false"
        @drop.prevent="handleRuleDrop"
      >
        <Upload class="size-6 mx-auto text-text-muted mb-2" />
        <p class="text-sm text-text-muted">拖拽规则文档到此处，或
          <label class="text-success cursor-pointer hover:underline">
            点击选择
            <input type="file" accept=".docx,.doc,.pdf" class="hidden" @change="handleRuleFileSelect" />
          </label>
        </p>
        <p v-if="ruleFile" class="mt-2 text-sm text-text-primary flex items-center justify-center gap-2">
          {{ ruleFile.name }}
          <button class="text-danger text-xs hover:underline" @click="clearRuleFile">移除</button>
        </p>
      </div>
    </div>

    <!-- Default rules toggle -->
    <div class="flex items-center gap-2">
      <input
        type="checkbox"
        v-model="useDefaultRules"
        class="rounded border-border text-success focus:ring-success"
      />
      <label class="text-sm text-text-secondary">同时使用通用暗标规则</label>
    </div>

    <!-- Tender file upload (required) -->
    <div class="space-y-2">
      <label class="text-sm text-text-secondary">待审查标书（必填）</label>
      <div
        class="border-2 border-dashed rounded-lg p-8 text-center transition-colors"
        :class="tenderDragOver ? 'border-success bg-success/5' : 'border-border'"
        @dragover.prevent="tenderDragOver = true"
        @dragleave="tenderDragOver = false"
        @drop.prevent="handleTenderDrop"
      >
        <Upload class="size-8 mx-auto text-text-muted mb-2" />
        <p class="text-sm text-text-muted">拖拽标书文件到此处，或
          <label class="text-success cursor-pointer hover:underline">
            点击选择
            <input type="file" accept=".docx,.doc,.pdf" class="hidden" @change="handleTenderFileSelect" />
          </label>
        </p>
        <p v-if="tenderFile" class="mt-2 text-sm text-text-primary">{{ tenderFile.name }}</p>
      </div>
    </div>

    <!-- Error -->
    <p v-if="store.error" class="text-sm text-danger">{{ store.error }}</p>

    <!-- Start button -->
    <button
      :disabled="!tenderFile || submitting"
      class="w-full py-3 bg-success text-white rounded-lg font-medium disabled:opacity-50 flex items-center justify-center gap-2"
      @click="startReview"
    >
      <EyeOff class="size-5" />
      {{ submitting ? '提交中...' : '开始暗标审查' }}
    </button>
  </div>
</template>