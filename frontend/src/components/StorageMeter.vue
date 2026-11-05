<template>
  <div class="storage-meter">
    <div class="flex justify-between items-center text-xs mb-1">
      <span class="font-bold flex items-center gap-1">
        <span>{{ $t('storage.title') }}</span>
        <span v-if="isWarning" class="eink-badge eink-badge-dark text-xs font-bold">!</span>
      </span>
      <span>
        {{ usedMbFormatted }} / {{ quotaMbFormatted }} {{ $t('storage.mb') }} ({{ percent }}%)
      </span>
    </div>

    <!-- Monochrome E-Ink Progress Bar -->
    <div class="eink-progress-container" :title="`${percent}% ${$t('storage.percent_used')}`">
      <div
        class="eink-progress-fill"
        :style="{ width: `${clampedPercent}%` }"
        :class="{ 'pattern-warning': isWarning }"
      ></div>
    </div>

    <!-- Alert Banner when > 90% -->
    <div
      v-if="isWarning"
      class="mt-2 p-2 border text-xs font-bold flex items-center gap-2 eink-card-muted"
    >
      <TriangleAlert :size="15" />
      <span>{{ isFull ? $t('storage.limit_reached') : $t('storage.warning_90') }}</span>
    </div>
  </div>
</template>

<script setup>
import { TriangleAlert } from 'lucide-vue-next'
import { computed } from 'vue'

const props = defineProps({
  usedBytes: {
    type: Number,
    default: 0
  },
  quotaBytes: {
    type: Number,
    default: 0
  }
})

const usedMb = computed(() => {
  return props.usedBytes / (1024 * 1024)
})

const quotaMb = computed(() => {
  return props.quotaBytes / (1024 * 1024)
})

const usedMbFormatted = computed(() => {
  return usedMb.value.toFixed(1)
})

const quotaMbFormatted = computed(() => {
  return quotaMb.value.toFixed(0)
})

const percent = computed(() => {
  if (!props.quotaBytes || props.quotaBytes <= 0) return 0
  const p = (props.usedBytes / props.quotaBytes) * 100
  return Math.min(100, Math.round(p * 10) / 10)
})

const clampedPercent = computed(() => {
  return Math.min(100, Math.max(0, percent.value))
})

const isWarning = computed(() => percent.value >= 90)
const isFull = computed(() => percent.value >= 100)
</script>

<style scoped>
.pattern-warning {
  background-image: repeating-linear-gradient(
    45deg,
    var(--color-ink-900),
    var(--color-ink-900) 4px,
    var(--color-paper) 4px,
    var(--color-paper) 8px
  );
}
</style>
