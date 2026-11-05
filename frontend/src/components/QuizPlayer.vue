<template>
  <div class="quiz-player-container flex flex-col gap-3">
    <div class="quiz-layout">
      <!-- Quiz list -->
      <aside class="quiz-list eink-card p-3 flex flex-col gap-2">
        <h2 class="eink-panel-title text-sm">{{ $t('quiz.list_title') }}</h2>

        <button class="eink-btn eink-btn-sm eink-btn-dark w-full" @click="requestNew">
          <Plus :size="14" /> {{ $t('quiz.new_quiz_button') }}
        </button>

        <ul v-if="quizzes.length > 0" class="flex flex-col gap-1">
          <li
            v-for="quiz in quizzes"
            :key="quiz.id"
            class="quiz-row flex items-center gap-1"
            :class="{ active: sameId(quiz.id, selectedId) }"
          >
            <button class="quiz-row-main flex-1 min-w-0 text-left" @click="selectQuiz(quiz)">
              <span class="block text-sm font-bold truncate">{{ quiz.title || $t('quiz.untitled') }}</span>
              <span class="block text-xs text-muted">
                {{ $t('quiz.questions_count', { count: countQuestions(quiz.content_raw) }) }}
                <template v-if="formatDate(quiz.updated_at)">
                  · {{ $t('quiz.updated', { date: formatDate(quiz.updated_at) }) }}
                </template>
              </span>
            </button>
            <button
              class="eink-btn eink-btn-sm eink-btn-icon shrink-0"
              :title="$t('quiz.delete')"
              :aria-label="$t('quiz.delete')"
              @click="askDelete(quiz)"
            >
              <Trash2 :size="14" />
            </button>
          </li>
        </ul>
      </aside>

      <!-- Player / editor -->
      <div class="quiz-main flex flex-col gap-3">
        <template v-if="selectedId">
          <!-- Top Bar -->
          <div class="toolbar eink-card p-3 flex flex-wrap justify-between items-center gap-2">
            <div class="flex items-center gap-3 min-w-0">
              <input
                v-if="mode === 'edit'"
                v-model="quizTitle"
                type="text"
                class="eink-input text-sm font-sans"
                :placeholder="$t('quiz.untitled')"
              />
              <h2 v-else class="eink-panel-title truncate">{{ quizTitle || $t('quiz.untitled') }}</h2>
              <span class="text-sm text-muted">{{ $t('quiz.questions_count', { count: questions.length }) }}</span>
            </div>

            <div class="flex flex-wrap items-center gap-2">
              <div class="eink-segmented">
                <button :class="{ active: mode === 'play' }" @click="setMode('play')">
                  <Play :size="13" /> {{ $t('quiz.mode_play') }}
                </button>
                <button :class="{ active: mode === 'edit' }" @click="setMode('edit')">
                  <Pencil :size="13" /> {{ $t('quiz.mode_edit') }}
                </button>
              </div>

              <button
                v-if="mode === 'play' && submitted"
                class="eink-btn eink-btn-sm"
                @click="restartQuiz"
              >
                <RotateCcw :size="14" /> {{ $t('quiz.restart') }}
              </button>

              <button
                class="eink-btn eink-btn-sm eink-btn-dark"
                :disabled="saving"
                @click="saveQuiz"
              >
                <Save :size="14" /> {{ saving ? $t('common.loading') : $t('quiz.save_quiz') }}
              </button>
            </div>
          </div>

          <!-- PLAY MODE -->
          <div v-if="mode === 'play'" class="play-mode-area flex flex-col gap-4">
            <!-- Score summary banner (when submitted) -->
            <div
              v-if="submitted"
              class="eink-card p-4 border-2 flex justify-between items-center"
              :class="isPassScore ? 'bg-paper-dim' : 'bg-paper'"
            >
              <div>
                <h3 class="text-base font-bold">
                  <CircleCheck v-if="isPassScore" :size="18" /><CircleX v-else :size="18" />
                  {{ isPassScore ? $t('quiz.passed') : $t('quiz.failed') }}
                </h3>
                <p class="text-xs text-muted mt-1">
                  {{ $t('quiz.score') }}: {{ calculatedScore }} / {{ questions.length }} ({{ scorePercent }}%)
                </p>
              </div>
              <button class="eink-btn eink-btn-sm eink-btn-dark" @click="restartQuiz">
                {{ $t('quiz.restart') }}
              </button>
            </div>

            <!-- Questions List -->
            <div class="questions-list flex flex-col gap-4">
              <div
                v-for="(q, qIndex) in questions"
                :key="q.id"
                v-reveal
                class="snap-block eink-card p-4 flex flex-col gap-3"
              >
                <!-- Question Header -->
                <div class="flex justify-between items-start gap-2 border-b pb-2">
                  <span class="font-bold text-sm font-sans">
                    {{ qIndex + 1 }}. {{ q.text }}
                  </span>
                  <span class="eink-badge text-xs shrink-0">
                    {{ q.multiple ? $t('quiz.multiple_choice') : $t('quiz.single_choice') }}
                  </span>
                </div>

                <!-- Options -->
                <div class="options-group flex flex-col gap-2">
                  <label
                    v-for="(opt, optIndex) in q.options"
                    :key="optIndex"
                    class="option-item p-2 border flex items-center justify-between text-xs cursor-pointer transition-all"
                    :class="getOptionClass(q, optIndex)"
                  >
                    <div class="flex items-center gap-2">
                      <input
                        v-if="q.multiple"
                        type="checkbox"
                        :value="optIndex"
                        :checked="userAnswers[q.id]?.includes(optIndex)"
                        :disabled="submitted"
                        @change="toggleAnswer(q.id, optIndex)"
                      />
                      <input
                        v-else
                        type="radio"
                        :name="`q-${q.id}`"
                        :value="optIndex"
                        :checked="userAnswers[q.id] === optIndex"
                        :disabled="submitted"
                        @change="setSingleAnswer(q.id, optIndex)"
                      />
                      <span class="font-sans text-sm">{{ opt.text }}</span>
                    </div>

                    <!-- Icon after submission -->
                    <span v-if="submitted && opt.isCorrect" class="font-bold text-xs">
                      <Check :size="13" /> {{ $t('quiz.correct_label') }}
                    </span>
                  </label>
                </div>

                <!-- Explanation box after submit -->
                <div
                  v-if="submitted && q.explanation"
                  class="explanation-box p-3 border border-faint bg-paper-dim text-xs text-ink-700 mt-1"
                >
                  <strong class="inline-flex items-center gap-1"><Info :size="13" /> {{ $t('quiz.explanation_label') }}:</strong>
                  <p class="mt-1 font-sans text-xs">{{ q.explanation }}</p>
                </div>
              </div>
            </div>

            <!-- Submit Quiz Button -->
            <div v-if="!submitted && questions.length > 0" class="flex justify-end p-2">
              <button
                class="eink-btn eink-btn-dark text-sm px-6"
                @click="submitQuiz"
              >
                <Check :size="14" /> {{ $t('quiz.submit_answers') }}
              </button>
            </div>
          </div>

          <!-- EDIT / ADD QUESTION MODE -->
          <div v-else class="edit-mode-area flex flex-col gap-4">
            <div class="eink-card p-4 max-w-2xl bg-paper">
              <h3 class="font-bold text-sm border-b pb-2 mb-3">
                {{ $t('quiz.add_question') }}
              </h3>

              <form class="flex flex-col gap-3" @submit.prevent="addQuestionToQuiz">
                <!-- Question text -->
                <div>
                  <label class="block text-xs mb-1">{{ $t('quiz.question_text') }} *</label>
                  <textarea
                    v-model="newQuestion.text"
                    class="eink-input w-full text-sm font-sans h-20 resize-none"
                    required
                  ></textarea>
                </div>

                <!-- Single / Multiple choice -->
                <div class="flex items-center gap-4">
                  <label class="flex items-center gap-2 text-xs cursor-pointer">
                    <input v-model="newQuestion.multiple" type="radio" :value="false" />
                    <span>{{ $t('quiz.single_choice') }}</span>
                  </label>
                  <label class="flex items-center gap-2 text-xs cursor-pointer">
                    <input v-model="newQuestion.multiple" type="radio" :value="true" />
                    <span>{{ $t('quiz.multiple_choice') }}</span>
                  </label>
                </div>

                <!-- Options Builder -->
                <div class="flex flex-col gap-2 pt-2 border-t">
                  <div class="flex justify-between items-center">
                    <span class="text-xs font-bold">{{ $t('quiz.options') }} *</span>
                    <button
                      type="button"
                      class="eink-btn eink-btn-sm"
                      @click="addOptionSlot"
                    >
                      <Plus :size="14" /> {{ $t('quiz.add_option') }}
                    </button>
                  </div>

                  <div
                    v-for="(opt, oIdx) in newQuestion.options"
                    :key="oIdx"
                    class="flex items-center gap-2"
                  >
                    <input
                      v-if="newQuestion.multiple"
                      v-model="opt.isCorrect"
                      type="checkbox"
                      :title="$t('quiz.select_correct')"
                    />
                    <input
                      v-else
                      type="radio"
                      name="correct-option-group"
                      :checked="opt.isCorrect"
                      :title="$t('quiz.select_correct')"
                      @change="setCorrectSingleOption(oIdx)"
                    />
                    <input
                      v-model="opt.text"
                      type="text"
                      class="eink-input flex-1 text-xs font-sans"
                      :placeholder="`${$t('quiz.option_text')} ${oIdx + 1}`"
                      required
                    />
                    <button
                      v-if="newQuestion.options.length > 2"
                      type="button"
                      class="eink-icon-btn"
                      :title="$t('common.delete')"
                      @click="removeOptionSlot(oIdx)"
                    >
                      <X :size="14" />
                    </button>
                  </div>
                </div>

                <!-- Explanation -->
                <div class="pt-2 border-t">
                  <label class="block text-xs mb-1">{{ $t('quiz.explanation') }}</label>
                  <input
                    v-model="newQuestion.explanation"
                    type="text"
                    class="eink-input w-full text-xs font-sans"
                    placeholder="Пояснение..."
                  />
                </div>

                <!-- Form Submit -->
                <div class="flex justify-end gap-2 pt-3 border-t mt-2">
                  <button
                    type="button"
                    class="eink-btn eink-btn-sm"
                    @click="setMode('play')"
                  >
                    {{ $t('common.cancel') }}
                  </button>
                  <button
                    type="submit"
                    class="eink-btn eink-btn-sm eink-btn-dark"
                  >
                    <Plus :size="14" /> {{ $t('quiz.add_question') }}
                  </button>
                </div>
              </form>
            </div>
          </div>
        </template>

        <!-- Empty state -->
        <div v-else-if="loaded" class="eink-card p-6 flex flex-col items-center gap-3 text-center">
          <p class="text-sm">{{ $t('quiz.empty') }}</p>
          <div class="flex flex-wrap justify-center gap-2">
            <button class="eink-btn eink-btn-sm eink-btn-dark" @click="requestNew">
              <Plus :size="14" /> {{ $t('quiz.new_quiz_button') }}
            </button>
            <button class="eink-btn eink-btn-sm" @click="requestExample">
              {{ $t('quiz.create_example') }}
            </button>
          </div>
        </div>
      </div>
    </div>

    <!-- New quiz modal -->
    <EinkModal :open="newOpen" :title="$t('quiz.new_quiz_title_prompt')" @close="closeNew">
      <form class="flex flex-col gap-3" @submit.prevent="confirmNew">
        <input
          v-model="newTitle"
          type="text"
          class="eink-input w-full text-sm font-sans"
          :placeholder="$t('quiz.new_quiz_title_prompt')"
        />
        <div class="eink-modal-actions flex justify-end gap-2">
          <button type="button" class="eink-btn eink-btn-sm" @click="closeNew">
            {{ $t('common.cancel') }}
          </button>
          <button
            type="submit"
            class="eink-btn eink-btn-sm eink-btn-dark"
            :disabled="!newTitle.trim() || saving"
          >
            {{ $t('quiz.new_quiz_button') }}
          </button>
        </div>
      </form>
    </EinkModal>

    <!-- Delete confirm modal -->
    <EinkModal
      :open="!!deleteTarget"
      :title="$t('quiz.delete_confirm_title')"
      @close="deleteTarget = null"
    >
      <p class="text-sm font-sans">
        {{ $t('quiz.delete_confirm_text', { title: deleteTarget?.title || $t('quiz.untitled') }) }}
      </p>
      <div class="eink-modal-actions flex justify-end gap-2 mt-3">
        <button class="eink-btn eink-btn-sm" @click="deleteTarget = null">
          {{ $t('common.cancel') }}
        </button>
        <button class="eink-btn eink-btn-sm eink-btn-dark" :disabled="deleting" @click="confirmDelete">
          {{ $t('common.delete') }}
        </button>
      </div>
    </EinkModal>

    <!-- Unsaved changes modal -->
    <EinkModal :open="unsavedOpen" :title="$t('quiz.unsaved_title')" @close="cancelUnsaved">
      <p class="text-sm font-sans">{{ $t('quiz.unsaved_text') }}</p>
      <div class="eink-modal-actions flex justify-end gap-2 mt-3">
        <button class="eink-btn eink-btn-sm" @click="cancelUnsaved">
          {{ $t('common.cancel') }}
        </button>
        <button class="eink-btn eink-btn-sm eink-btn-dark" @click="discardAndContinue">
          {{ $t('quiz.discard') }}
        </button>
      </div>
    </EinkModal>
  </div>
</template>

<script setup>
import { RotateCcw, Save, CircleCheck, CircleX, Check, Info, X, Plus, Play, Pencil, Trash2 } from 'lucide-vue-next'
import { ref, computed, watch, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import api from '../api/client'
import EinkModal from './EinkModal.vue'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  }
})

const { t, locale } = useI18n()

const defaultQuestions = [
  {
    id: 'q1',
    text: 'Каковы ключевые визуальные требования к интерфейсу в стиле E-Ink?',
    multiple: true,
    options: [
      { text: 'Высокая контрастность, строгие 1px границы, отсутствие размытых теней', isCorrect: true },
      { text: 'Градиенты ярких цветов и полупрозрачные стеклянные панели', isCorrect: false },
      { text: 'Монохромная палитра и точечные паттерны дизеринга для выделения', isCorrect: true },
      { text: 'Непрерывная плавная 60 FPS CSS-анимация', isCorrect: false }
    ],
    explanation: 'Экраны на электронных чернилах обладают монохромной матрицей и низкой частотой обновления, поэтому требуют высокого контраста, четких 1px границ и отсутствия градиентов.'
  },
  {
    id: 'q2',
    text: 'Как работает механизм защиты Device Fingerprint для инвайт-ссылок?',
    multiple: false,
    options: [
      { text: 'Инвайт-ссылка при первом входе жестко привязывается к отпечатку устройства и блокирует вход с других машин', isCorrect: true },
      { text: 'Ссылка отправляет SMS-код на номер телефона', isCorrect: false },
      { text: 'Отпечаток генерируется заново каждый раз и не сверяется', isCorrect: false }
    ],
    explanation: 'В целях безопасности одноразовая ссылка при активации фиксирует аппаратный хеш (Canvas, WebAudio, Screen) и при несовпадении блокирует доступ.'
  },
  {
    id: 'q3',
    text: 'Что происходит при исчерпании дисковой квоты воркспейса при загрузке файла?',
    multiple: false,
    options: [
      { text: 'Файл молча удаляет старые документы', isCorrect: false },
      { text: 'Сервер возвращает ошибку 413 Payload Too Large и загрузка блокируется', isCorrect: true },
      { text: 'Файл загружается без ограничений', isCorrect: false }
    ],
    explanation: 'В соответствии со спецификацией, при превышении квоты сервер прерывает операцию кодом 413 и выдает сообщение об исчерпании лимита.'
  }
]

// Quiz list (documents with doc_type=quiz)
const quizzes = ref([])
const loaded = ref(false)
const selectedId = ref(null)

// Open quiz state
const questions = ref([])
const quizTitle = ref('')
const userAnswers = ref({})
const submitted = ref(false)
const mode = ref('play')
const saving = ref(false)
const deleting = ref(false)

// Snapshot of the open quiz as last loaded or saved; dirty = differs from it
const savedSnapshot = ref('')
const isDirty = computed(() => snapshotOf(quizTitle.value, questions.value) !== savedSnapshot.value)

// Modals
const newOpen = ref(false)
const newTitle = ref('')
const deleteTarget = ref(null)
const unsavedOpen = ref(false)
const pendingAction = ref(null)

const newQuestion = ref({
  text: '',
  multiple: false,
  options: [
    { text: '', isCorrect: true },
    { text: '', isCorrect: false }
  ],
  explanation: ''
})

function sameId(a, b) {
  return a != null && b != null && String(a) === String(b)
}

function snapshotOf(title, qs) {
  return JSON.stringify({ title, qs })
}

function parseQuestions(raw) {
  try {
    const parsed = JSON.parse(raw)
    return Array.isArray(parsed) ? parsed : []
  } catch {
    return []
  }
}

function countQuestions(raw) {
  return parseQuestions(raw).length
}

function formatDate(value) {
  if (!value) return ''
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return ''
  return date.toLocaleDateString(locale.value, { day: '2-digit', month: '2-digit', year: 'numeric' })
}

function storageKey() {
  return `piop-quiz-${props.workspaceId}`
}

function readLastOpened() {
  try {
    return localStorage.getItem(storageKey())
  } catch {
    return null
  }
}

function writeLastOpened(id) {
  try {
    localStorage.setItem(storageKey(), String(id))
  } catch {
    // storage unavailable: selection just won't be remembered
  }
}

function setMode(m) {
  mode.value = m
}

function setSingleAnswer(qId, optIndex) {
  userAnswers.value[qId] = optIndex
}

function toggleAnswer(qId, optIndex) {
  if (!userAnswers.value[qId]) {
    userAnswers.value[qId] = []
  }
  const current = userAnswers.value[qId]
  const idx = current.indexOf(optIndex)
  if (idx >= 0) {
    current.splice(idx, 1)
  } else {
    current.push(optIndex)
  }
}

function getOptionClass(q, optIndex) {
  if (!submitted.value) {
    const isSelected = q.multiple
      ? userAnswers.value[q.id]?.includes(optIndex)
      : userAnswers.value[q.id] === optIndex
    return isSelected ? 'bg-paper-dim border-ink-900 font-bold' : 'bg-paper-card'
  }

  const isCorrect = q.options[optIndex].isCorrect
  const isSelected = q.multiple
    ? userAnswers.value[q.id]?.includes(optIndex)
    : userAnswers.value[q.id] === optIndex

  if (isCorrect && isSelected) {
    return 'bg-paper-dim border-ink-900 font-bold'
  }
  if (!isCorrect && isSelected) {
    return 'bg-paper line-through border-ink-500 text-muted'
  }
  if (isCorrect && !isSelected) {
    return 'border-dashed border-ink-900'
  }
  return 'bg-paper opacity-60'
}

const calculatedScore = computed(() => {
  let score = 0
  for (const q of questions.value) {
    const ans = userAnswers.value[q.id]
    if (ans === undefined) continue

    if (q.multiple) {
      const correctIndices = q.options
        .map((o, idx) => (o.isCorrect ? idx : null))
        .filter((idx) => idx !== null)
      const userList = Array.isArray(ans) ? ans : []
      const match =
        correctIndices.length === userList.length &&
        correctIndices.every((idx) => userList.includes(idx))
      if (match) score++
    } else {
      if (q.options[ans]?.isCorrect) {
        score++
      }
    }
  }
  return score
})

const scorePercent = computed(() => {
  if (questions.value.length === 0) return 0
  return Math.round((calculatedScore.value / questions.value.length) * 100)
})

const isPassScore = computed(() => scorePercent.value >= 70)

function submitQuiz() {
  submitted.value = true
}

function restartQuiz() {
  userAnswers.value = {}
  submitted.value = false
}

function addOptionSlot() {
  newQuestion.value.options.push({ text: '', isCorrect: false })
}

function removeOptionSlot(idx) {
  newQuestion.value.options.splice(idx, 1)
}

function setCorrectSingleOption(targetIdx) {
  newQuestion.value.options.forEach((opt, idx) => {
    opt.isCorrect = idx === targetIdx
  })
}

function addQuestionToQuiz() {
  if (!newQuestion.value.text.trim()) return

  questions.value.push({
    id: `q-${Date.now()}`,
    text: newQuestion.value.text.trim(),
    multiple: newQuestion.value.multiple,
    options: newQuestion.value.options.map((o) => ({
      text: o.text.trim(),
      isCorrect: !!o.isCorrect
    })),
    explanation: newQuestion.value.explanation.trim()
  })

  newQuestion.value = {
    text: '',
    multiple: false,
    options: [
      { text: '', isCorrect: true },
      { text: '', isCorrect: false }
    ],
    explanation: ''
  }
  mode.value = 'play'
}

// Load a quiz's content into the player (no storage side effects)
function applyQuiz(quiz) {
  questions.value = parseQuestions(quiz.content_raw)
  quizTitle.value = quiz.title || ''
  savedSnapshot.value = snapshotOf(quizTitle.value, questions.value)
  userAnswers.value = {}
  submitted.value = false
}

function openQuiz(quiz) {
  applyQuiz(quiz)
  selectedId.value = quiz.id
  writeLastOpened(quiz.id)
}

function clearSelection() {
  selectedId.value = null
  questions.value = []
  quizTitle.value = ''
  savedSnapshot.value = snapshotOf('', [])
  userAnswers.value = {}
  submitted.value = false
}

// Keep the open quiz if it still exists; otherwise the remembered one, else the first
function ensureSelection() {
  if (quizzes.value.some((q) => sameId(q.id, selectedId.value))) return
  const storedId = readLastOpened()
  const next = quizzes.value.find((q) => sameId(q.id, storedId)) || quizzes.value[0]
  if (next) {
    openQuiz(next)
  } else {
    clearSelection()
  }
}

// Run action now, or after the user confirms discarding unsaved edits
function guardUnsaved(action) {
  if (!isDirty.value) {
    action()
    return
  }
  pendingAction.value = action
  unsavedOpen.value = true
}

function cancelUnsaved() {
  unsavedOpen.value = false
  pendingAction.value = null
}

function discardAndContinue() {
  const action = pendingAction.value
  unsavedOpen.value = false
  pendingAction.value = null
  const current = quizzes.value.find((q) => sameId(q.id, selectedId.value))
  if (current) applyQuiz(current)
  if (action) action()
}

function selectQuiz(quiz) {
  if (sameId(quiz.id, selectedId.value)) return
  guardUnsaved(() => openQuiz(quiz))
}

async function fetchQuizzes() {
  if (!props.workspaceId) return
  try {
    const list = await api.get(`/api/workspaces/${props.workspaceId}/documents?doc_type=quiz`)
    quizzes.value = Array.isArray(list) ? list : []
    ensureSelection()
  } catch (err) {
    console.error('Failed to load quizzes:', err)
  } finally {
    loaded.value = true
  }
}

async function createQuiz(title, qs) {
  try {
    const created = await api.post(`/api/workspaces/${props.workspaceId}/documents`, {
      title,
      content_raw: JSON.stringify(qs, null, 2),
      doc_type: 'quiz'
    })
    await fetchQuizzes()
    const quiz = quizzes.value.find((q) => sameId(q.id, created.id)) || created
    openQuiz(quiz)
    return true
  } catch (err) {
    console.error('Failed to create quiz:', err)
    return false
  }
}

function requestNew() {
  newTitle.value = ''
  newOpen.value = true
}

function closeNew() {
  newOpen.value = false
}

function confirmNew() {
  const title = newTitle.value.trim()
  if (!title) return
  newOpen.value = false
  guardUnsaved(async () => {
    if (await createQuiz(title, [])) mode.value = 'edit'
  })
}

function requestExample() {
  guardUnsaved(() => createQuiz(t('quiz.example_title'), defaultQuestions))
}

function askDelete(quiz) {
  if (sameId(quiz.id, selectedId.value)) {
    deleteTarget.value = quiz
    return
  }
  guardUnsaved(() => {
    deleteTarget.value = quiz
  })
}

async function confirmDelete() {
  const quiz = deleteTarget.value
  if (!quiz) return
  deleting.value = true
  try {
    await api.delete(`/api/workspaces/${props.workspaceId}/documents/${quiz.id}`)
    deleteTarget.value = null
    await fetchQuizzes()
  } catch (err) {
    console.error('Failed to delete quiz:', err)
  } finally {
    deleting.value = false
  }
}

async function saveQuiz() {
  if (!props.workspaceId || !selectedId.value) return
  saving.value = true
  try {
    const title = quizTitle.value.trim() || t('quiz.untitled')
    await api.put(`/api/workspaces/${props.workspaceId}/documents/${selectedId.value}`, {
      title,
      content_raw: JSON.stringify(questions.value, null, 2)
    })
    quizTitle.value = title
    savedSnapshot.value = snapshotOf(quizTitle.value, questions.value)
    await fetchQuizzes()
  } catch (err) {
    console.error('Failed to save quiz:', err)
  } finally {
    saving.value = false
  }
}

watch(
  () => props.workspaceId,
  (newId) => {
    if (!newId) return
    quizzes.value = []
    loaded.value = false
    clearSelection()
    fetchQuizzes()
  }
)

onMounted(() => {
  fetchQuizzes()
})
</script>

<style scoped>
.quiz-player-container {
  min-height: 600px;
}

.quiz-layout {
  display: flex;
  align-items: flex-start;
  gap: 0.75rem;
}

.quiz-list {
  width: 16rem;
  flex-shrink: 0;
}

.quiz-main {
  flex: 1;
  min-width: 0;
}

@media (max-width: 899px) {
  .quiz-layout {
    flex-direction: column;
  }

  .quiz-list {
    width: 100%;
  }
}

.quiz-row {
  border: 1px solid var(--color-ink-900);
  border-radius: var(--radius);
  padding: 0.25rem;
}

.quiz-row.active {
  background: var(--color-ink-900);
  color: var(--color-paper);
  border-width: 2px;
}

.quiz-row.active .text-muted {
  color: inherit;
  opacity: 0.8;
}

.quiz-row.active .eink-btn-icon {
  background: transparent;
  color: inherit;
  border-color: currentColor;
}

.quiz-row-main {
  background: transparent;
  border: 0;
  color: inherit;
  cursor: pointer;
  padding: 0.25rem 0.375rem;
}

.option-item {
  border-radius: var(--radius);
  transition: background-color 120ms, border-color 120ms;
}

.option-item:hover {
  border-color: var(--color-ink-900);
}
</style>
