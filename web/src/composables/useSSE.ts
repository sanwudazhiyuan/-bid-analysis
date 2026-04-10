import { ref, onUnmounted } from 'vue'
import type { ProgressEvent } from '../types/task'

export function useSSE(taskId: string, customUrl?: string) {
  const progress = ref<ProgressEvent | null>(null)
  const connected = ref(false)
  const done = ref(false)
  let reader: ReadableStreamDefaultReader<Uint8Array> | null = null
  let abortController: AbortController | null = null

  async function connect() {
    const token = localStorage.getItem('access_token')
    abortController = new AbortController()

    try {
      const url = customUrl || `/api/tasks/${taskId}/progress`
      const response = await fetch(url, {
        headers: { Authorization: `Bearer ${token}` },
        signal: abortController.signal,
      })

      if (!response.ok || !response.body) {
        connected.value = false
        return
      }

      connected.value = true
      reader = response.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { value, done: streamDone } = await reader.read()
        if (streamDone) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (line.startsWith('data: ')) {
            try {
              const data = JSON.parse(line.slice(6)) as ProgressEvent
              progress.value = data
              if (data.step === 'completed' || data.step === 'failed') {
                done.value = true
                disconnect()
                return
              }
            } catch {}
          }
        }
      }
    } catch (e: unknown) {
      if (e instanceof Error && e.name !== 'AbortError') {
        connected.value = false
      }
    }
  }

  function disconnect() {
    abortController?.abort()
    connected.value = false
  }

  onUnmounted(disconnect)

  return { progress, connected, done, connect, disconnect }
}
