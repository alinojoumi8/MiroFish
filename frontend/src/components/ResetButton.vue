<template>
  <div class="reset-wrapper">
    <!-- Trigger button -->
    <button
      class="reset-btn"
      :class="{ busy: state === 'confirming' || state === 'resetting', dark: dark }"
      :title="$t('reset.tooltip')"
      @click="handleClick"
    >
      <span class="reset-icon">{{ state === 'resetting' ? '⟳' : '⏹' }}</span>
      <span class="reset-label">{{ label }}</span>
    </button>

    <!-- Inline confirm popover -->
    <Transition name="popover">
      <div v-if="state === 'confirming'" class="confirm-popover" @click.stop>
        <p class="confirm-msg">{{ $t('reset.confirmMsg') }}</p>
        <div class="confirm-actions">
          <button class="btn-yes" @click="doReset">{{ $t('reset.confirmYes') }}</button>
          <button class="btn-no" @click="cancel">{{ $t('reset.confirmNo') }}</button>
        </div>
      </div>
    </Transition>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'
import { useRouter } from 'vue-router'
import { useI18n } from 'vue-i18n'
import { resetAllSimulations } from '../api/simulation'
import { useToast } from '../composables/useToast'

const router = useRouter()
const { t } = useI18n()
const { showToast } = useToast()

const props = defineProps({
  dark: { type: Boolean, default: false }
})

// 'idle' | 'confirming' | 'resetting'
const state = ref('idle')

const label = computed(() => {
  if (state.value === 'resetting') return t('reset.resetting')
  if (state.value === 'confirming') return t('reset.confirm')
  return t('reset.label')
})

function handleClick() {
  if (state.value === 'idle') {
    state.value = 'confirming'
    // Auto-dismiss confirm after 5s if user ignores it
    setTimeout(() => {
      if (state.value === 'confirming') state.value = 'idle'
    }, 5000)
  }
}

function cancel() {
  state.value = 'idle'
}

async function doReset() {
  state.value = 'resetting'
  try {
    await resetAllSimulations()
    showToast(t('reset.success'), 'success')
    // Navigate home so user starts fresh
    setTimeout(() => router.push('/'), 800)
  } catch (err) {
    showToast(t('reset.failed', { error: err.message }), 'error')
    state.value = 'idle'
  }
}
</script>

<style scoped>
.reset-wrapper {
  position: relative;
  display: flex;
  align-items: center;
}

.reset-btn {
  display: flex;
  align-items: center;
  gap: 5px;
  padding: 4px 10px;
  font-size: 11px;
  font-family: inherit;
  font-weight: 600;
  letter-spacing: 0.05em;
  text-transform: uppercase;
  border: 1.5px solid #000;
  background: #fff;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
  white-space: nowrap;
}

.reset-btn:hover,
.reset-btn.busy {
  background: #000;
  color: #fff;
}

/* Dark navbar variant */
.reset-btn.dark {
  border-color: rgba(255, 255, 255, 0.75);
  background: rgba(255, 255, 255, 0.08);
  color: #fff;
}

.reset-btn.dark:hover,
.reset-btn.dark.busy {
  background: #fff;
  border-color: #fff;
  color: #000;
}

.reset-icon {
  font-size: 12px;
  line-height: 1;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.reset-btn.busy .reset-icon {
  display: inline-block;
  animation: spin 0.8s linear infinite;
}

/* Confirm popover */
.confirm-popover {
  position: absolute;
  top: calc(100% + 8px);
  right: 0;
  z-index: 500;
  background: #fff;
  border: 1.5px solid #000;
  box-shadow: 4px 4px 0 #000;
  padding: 12px 14px;
  min-width: 220px;
}

.confirm-msg {
  font-size: 12px;
  margin-bottom: 10px;
  line-height: 1.4;
}

.confirm-actions {
  display: flex;
  gap: 8px;
}

.btn-yes, .btn-no {
  flex: 1;
  padding: 5px 0;
  font-size: 11px;
  font-family: inherit;
  font-weight: 700;
  letter-spacing: 0.04em;
  text-transform: uppercase;
  border: 1.5px solid #000;
  cursor: pointer;
  transition: background 0.1s, color 0.1s;
}

.btn-yes {
  background: #000;
  color: #fff;
}
.btn-yes:hover {
  background: #cc0000;
  border-color: #cc0000;
}

.btn-no {
  background: #fff;
  color: #000;
}
.btn-no:hover {
  background: #eee;
}

/* Transition */
.popover-enter-active, .popover-leave-active {
  transition: opacity 0.15s, transform 0.15s;
}
.popover-enter-from, .popover-leave-to {
  opacity: 0;
  transform: translateY(-4px);
}
</style>
