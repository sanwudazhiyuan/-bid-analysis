<script setup lang="ts">
defineProps<{ count: number }>()
</script>

<template>
  <span v-if="count > 0" class="inline-flex items-center px-1.5 py-0.5 rounded-full text-xs bg-highlight text-highlight-foreground">
    {{ count }}
  </span>
</template>
