<template>
  <div class="provider-switcher" ref="switcherRef">
    <button class="switcher-trigger" :title="tooltip" @click="toggleDropdown" :disabled="loading">
      <span class="prov-dot" :class="{ ready: activeConfigured }"></span>
      {{ activeLabel }}
      <span class="caret">{{ open ? '▲' : '▼' }}</span>
    </button>
    <ul v-if="open" class="switcher-dropdown">
      <li
        v-for="p in providers"
        :key="p.name"
        class="switcher-option"
        :class="{ active: p.name === activeName, disabled: !p.configured }"
        @click="p.configured && switchProvider(p.name)"
      >
        <span class="opt-label">{{ p.label }}</span>
        <span v-if="!p.configured" class="opt-hint">未配置</span>
      </li>
    </ul>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { getLlmProvider, setLlmProvider } from '@/api/settings'

const switcherRef = ref(null)
const open = ref(false)
const loading = ref(false)
const providers = ref([])
const activeName = ref('')
const activeLabel = ref('LLM')
const activeModel = ref('')

const activeConfigured = computed(() => {
  const a = providers.value.find(p => p.name === activeName.value)
  return a ? a.configured : false
})

const tooltip = computed(() => activeModel.value ? `Model: ${activeModel.value}` : 'LLM Provider')

const refresh = async () => {
  try {
    const res = await getLlmProvider()
    providers.value = res.available || []
    if (res.active) {
      activeName.value = res.active.name
      activeLabel.value = res.active.label
      activeModel.value = res.active.model
    }
  } catch (e) {
    console.error('Failed to load LLM providers', e)
  }
}

const toggleDropdown = () => {
  open.value = !open.value
  if (open.value) refresh()
}

const switchProvider = async (name) => {
  loading.value = true
  try {
    const res = await setLlmProvider(name)
    if (res && res.active) {
      activeName.value = res.active.name
      activeLabel.value = res.active.label
      activeModel.value = res.active.model
    }
    open.value = false
    await refresh()
  } catch (e) {
    console.error('Failed to switch LLM provider', e)
    alert('切换失败：' + (e.response?.data?.error || e.message))
  } finally {
    loading.value = false
  }
}

const onClickOutside = (e) => {
  if (switcherRef.value && !switcherRef.value.contains(e.target)) open.value = false
}

onMounted(() => {
  document.addEventListener('click', onClickOutside)
  refresh()
})

onUnmounted(() => {
  document.removeEventListener('click', onClickOutside)
})
</script>

<style scoped>
.provider-switcher {
  position: relative;
  display: inline-block;
  font-family: 'JetBrains Mono', monospace;
}

.switcher-trigger {
  background: transparent;
  color: #333;
  border: 1px solid #CCC;
  padding: 4px 12px;
  font-family: 'JetBrains Mono', monospace;
  font-size: 0.8rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
  transition: border-color 0.2s, opacity 0.2s;
}

.switcher-trigger:hover { border-color: #999; }
.switcher-trigger:disabled { opacity: 0.6; cursor: not-allowed; }

.prov-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #CCC;
  display: inline-block;
}
.prov-dot.ready { background: #2ECC71; }

.caret { font-size: 0.6rem; }

.switcher-dropdown {
  position: absolute;
  top: 100%;
  right: 0;
  margin-top: 4px;
  background: #FFFFFF;
  border: 1px solid #DDD;
  list-style: none;
  padding: 4px 0;
  min-width: 180px;
  z-index: 1000;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.switcher-option {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
  padding: 6px 12px;
  font-size: 0.8rem;
  color: #333;
  cursor: pointer;
  white-space: nowrap;
  transition: background 0.15s;
}

.switcher-option:hover:not(.disabled) { background: #F0F0F0; }
.switcher-option.active { color: var(--orange, #FF4500); }
.switcher-option.disabled { color: #999; cursor: not-allowed; }

.opt-hint {
  font-size: 0.7rem;
  color: #999;
}
</style>
