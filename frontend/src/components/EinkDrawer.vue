<template>
  <Teleport to="body">
    <Transition name="eink-drawer">
      <div v-if="open" class="eink-drawer-backdrop" @click.self="emit('close')">
        <aside
          ref="panelRef"
          class="eink-drawer"
          role="dialog"
          aria-modal="true"
          :aria-label="title || undefined"
          :style="{ width: `min(${width}, 100vw)` }"
        >
          <header class="eink-drawer-head">
            <h2 class="eink-drawer-title">{{ title }}</h2>
            <button
              type="button"
              class="eink-btn eink-btn-sm eink-btn-icon"
              :title="$t('common.close')"
              :aria-label="$t('common.close')"
              @click="emit('close')"
            >
              <X :size="16" />
            </button>
          </header>
          <div class="eink-drawer-body">
            <slot />
          </div>
        </aside>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { X } from 'lucide-vue-next'
import { ref, watch, nextTick, onBeforeUnmount } from 'vue'

const props = defineProps({
  open: Boolean,
  title: { type: String, default: '' },
  width: { type: String, default: '30rem' }
})

const emit = defineEmits(['close'])

const panelRef = ref(null)
let savedBodyOverflow = null

function onKeydown(e) {
  if (e.key === 'Escape') emit('close')
}

function lockBodyScroll() {
  if (savedBodyOverflow !== null) return
  savedBodyOverflow = document.body.style.overflow
  document.body.style.overflow = 'hidden'
}

function unlockBodyScroll() {
  if (savedBodyOverflow === null) return
  document.body.style.overflow = savedBodyOverflow
  savedBodyOverflow = null
}

watch(
  () => props.open,
  (isOpen) => {
    if (isOpen) {
      window.addEventListener('keydown', onKeydown)
      lockBodyScroll()
      nextTick(() => {
        const panel = panelRef.value
        if (!panel) return
        if (panel.contains(document.activeElement)) return
        const first = panel.querySelector('input, textarea, select')
        if (first) first.focus()
      })
    } else {
      window.removeEventListener('keydown', onKeydown)
      unlockBodyScroll()
    }
  },
  { immediate: true }
)

onBeforeUnmount(() => {
  window.removeEventListener('keydown', onKeydown)
  unlockBodyScroll()
})
</script>
