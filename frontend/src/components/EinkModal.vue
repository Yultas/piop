<template>
  <Teleport to="body">
    <Transition name="eink-modal">
      <div v-if="open" class="eink-modal-backdrop" @click.self="emit('close')">
        <div
          ref="panelRef"
          class="eink-card eink-modal"
          role="dialog"
          aria-modal="true"
          :aria-label="title || undefined"
          :style="{ maxWidth }"
        >
          <h3 v-if="title" class="eink-modal-title">{{ title }}</h3>
          <slot />
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  open: Boolean,
  title: { type: String, default: '' },
  maxWidth: { type: String, default: '28rem' }
})

const emit = defineEmits(['close'])

const panelRef = ref(null)

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      window.addEventListener('keydown', onKeydown)
      nextTick(() => {
        const panel = panelRef.value
        if (!panel) return
        if (panel.contains(document.activeElement)) return
        const first = panel.querySelector('input, textarea, select')
        if (first) first.focus()
      })
    } else {
      window.removeEventListener('keydown', onKeydown)
    }
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
})
</script>
