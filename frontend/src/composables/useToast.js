import { ref } from 'vue'

const toasts = ref([])
let nextId = 1

export function useToast() {
  function showToast(message, type = 'info', duration = 5000) {
    const id = nextId++
    toasts.value.push({ id, message, type })
    if (duration > 0) {
      setTimeout(() => dismissToast(id), duration)
    }
  }

  function dismissToast(id) {
    const index = toasts.value.findIndex(t => t.id === id)
    if (index !== -1) toasts.value.splice(index, 1)
  }

  return { toasts, showToast, dismissToast }
}
