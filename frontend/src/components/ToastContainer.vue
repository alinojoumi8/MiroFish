<template>
  <Teleport to="body">
    <div class="toast-container">
      <TransitionGroup name="toast">
        <div
          v-for="toast in toasts"
          :key="toast.id"
          class="toast"
          :class="toast.type"
          @click="dismissToast(toast.id)"
        >
          <span class="toast-icon">
            <template v-if="toast.type === 'error'">✕</template>
            <template v-else-if="toast.type === 'success'">✓</template>
            <template v-else>ℹ</template>
          </span>
          <span class="toast-message">{{ toast.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToast } from '../composables/useToast'
const { toasts, dismissToast } = useToast()
</script>

<style scoped>
.toast-container {
  position: fixed;
  top: 16px;
  right: 16px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 380px;
}

.toast {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 16px;
  border: 1px solid #000;
  background: #fff;
  cursor: pointer;
  font-size: 13px;
  line-height: 1.4;
  box-shadow: 3px 3px 0 #000;
  transition: box-shadow 0.1s;
}

.toast:hover {
  box-shadow: 1px 1px 0 #000;
}

.toast.error {
  background: #fff0f0;
  border-color: #cc0000;
  box-shadow: 3px 3px 0 #cc0000;
}

.toast.error:hover {
  box-shadow: 1px 1px 0 #cc0000;
}

.toast.success {
  background: #f0fff0;
  border-color: #006600;
  box-shadow: 3px 3px 0 #006600;
}

.toast.success:hover {
  box-shadow: 1px 1px 0 #006600;
}

.toast-icon {
  font-weight: 700;
  flex-shrink: 0;
  line-height: 1.4;
}

.toast-message {
  flex: 1;
  word-break: break-word;
}

.toast-enter-active,
.toast-leave-active {
  transition: all 0.2s ease;
}

.toast-enter-from {
  opacity: 0;
  transform: translateX(20px);
}

.toast-leave-to {
  opacity: 0;
  transform: translateX(20px);
}
</style>
