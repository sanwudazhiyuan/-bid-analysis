<script setup lang="ts">
import DefaultLayout from '../layouts/DefaultLayout.vue'
import FileUpload from '../components/FileUpload.vue'
import TaskList from '../components/TaskList.vue'
</script>

<template>
  <DefaultLayout>
    <FileUpload class="mb-8" />
    <TaskList />
  </DefaultLayout>
</template>
