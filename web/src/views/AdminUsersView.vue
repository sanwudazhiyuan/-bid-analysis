<script setup lang="ts">
import { ref, onMounted } from 'vue'
import DefaultLayout from '../layouts/DefaultLayout.vue'
import client from '../api/client'

const users = ref<any[]>([])
const showCreate = ref(false)
const form = ref({ username: '', password: '', display_name: '', role: 'user' })

async function loadUsers() {
  const res = await client.get('/users')
  users.value = res.data
}

async function createUser() {
  await client.post('/users', form.value)
  showCreate.value = false
  form.value = { username: '', password: '', display_name: '', role: 'user' }
  await loadUsers()
}

async function deleteUser(id: number) {
  if (!confirm('确认删除？')) return
  await client.delete(`/users/${id}`)
  await loadUsers()
}

onMounted(loadUsers)
</script>

<template>
  <DefaultLayout>
    <div class="flex items-center justify-between mb-6">
      <h1 class="text-xl font-bold">用户管理</h1>
      <button @click="showCreate = true" class="px-4 py-2 bg-blue-600 text-white rounded-md text-sm hover:bg-blue-700">创建用户</button>
    </div>

    <!-- 创建表单 -->
    <div v-if="showCreate" class="bg-white p-4 rounded-lg shadow mb-6 space-y-3">
      <input v-model="form.username" placeholder="用户名" class="w-full border rounded px-3 py-2 text-sm" />
      <input v-model="form.password" type="password" placeholder="密码" class="w-full border rounded px-3 py-2 text-sm" />
      <input v-model="form.display_name" placeholder="显示名称" class="w-full border rounded px-3 py-2 text-sm" />
      <select v-model="form.role" class="border rounded px-3 py-2 text-sm">
        <option value="user">普通用户</option>
        <option value="admin">管理员</option>
      </select>
      <div class="flex gap-2">
        <button @click="createUser" class="px-4 py-2 bg-green-600 text-white rounded text-sm">创建</button>
        <button @click="showCreate = false" class="px-4 py-2 border rounded text-sm">取消</button>
      </div>
    </div>

    <!-- 用户列表 -->
    <div class="bg-white rounded-lg shadow overflow-hidden">
      <table class="w-full text-sm">
        <thead class="bg-gray-50"><tr>
          <th class="px-4 py-3 text-left">用户名</th>
          <th class="px-4 py-3 text-left">显示名</th>
          <th class="px-4 py-3 text-left">角色</th>
          <th class="px-4 py-3 text-left">操作</th>
        </tr></thead>
        <tbody>
          <tr v-for="u in users" :key="u.id" class="border-t">
            <td class="px-4 py-3">{{ u.username }}</td>
            <td class="px-4 py-3">{{ u.display_name }}</td>
            <td class="px-4 py-3">{{ u.role }}</td>
            <td class="px-4 py-3">
              <button v-if="u.role !== 'admin'" @click="deleteUser(u.id)" class="text-red-500 hover:underline text-sm">删除</button>
            </td>
          </tr>
        </tbody>
      </table>
    </div>
  </DefaultLayout>
</template>
