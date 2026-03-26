<script setup lang="ts">
import AppSidebar from '../components/AppSidebar.vue'
</script>

<template>
  <div class="flex h-screen overflow-hidden">
    <AppSidebar />
    <main class="flex-1 overflow-auto bg-background">
      <router-view />
    </main>
  </div>
</template>
