<template>
  <div class="chat-thread-container flex h-full border" :class="{ 'is-fill': fill }">
    <div class="chat-thread-body">
      <!-- Channels Sidebar -->
      <div class="channels-sidebar flex flex-col border-r w-64 bg-paper">
        <div class="eink-panel-head">
          <span class="eink-panel-title text-sm">{{ $t('chat.channels') }}</span>
          <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('chat.new_channel')" @click="showNewChannelModal = true">
            <Plus :size="14" />
          </button>
        </div>

        <!-- Channel List -->
        <div class="channels-list flex-1 overflow-y-auto">
          <div v-if="loadingChannels" class="eink-empty">{{ $t('common.loading') }}</div>
          <div
            v-for="ch in channels"
            :key="ch.id"
            class="channel-item"
            :class="{ 'channel-active': activeChannel?.id === ch.id }"
            @click="selectChannel(ch)"
          >
            <Hash :size="14" class="shrink-0" />
            <span class="truncate flex-1">{{ ch.name }}</span>
            <Lock v-if="ch.is_private" :size="12" class="text-muted" />
          </div>
        </div>
      </div>

      <!-- Main Message Area -->
      <div class="message-area flex-1 flex flex-col bg-card">
        <!-- Active Channel Header -->
        <div class="eink-panel-head">
          <span class="eink-panel-title">
            <Hash :size="16" />
            <span class="truncate">{{ activeChannel?.name || $t('chat.title') }}</span>
          </span>
          <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('common.refresh')" @click="fetchMessages">
            <RefreshCw :size="14" />
          </button>
        </div>

        <!-- Messages Feed -->
        <div ref="messagesScrollContainer" class="messages-feed scroll-blocks flex-1 overflow-y-auto">
          <div v-if="loadingMessages" class="eink-empty">{{ $t('common.loading') }}</div>
          <div v-else-if="messages.length === 0" class="eink-empty">{{ $t('chat.no_messages') }}</div>
          <div
            v-for="msg in messages"
            :key="msg.id"
            class="message-row"
            :class="{ 'thread-parent-highlight': activeThreadParent?.id === msg.id }"
          >
            <span class="avatar">{{ msg.sender_username?.charAt(0).toUpperCase() || '?' }}</span>
            <div class="message-main">
              <div class="message-meta">
                <span class="font-semibold text-sm">{{ msg.sender_username || 'User' }}</span>
                <span class="text-xs text-muted">{{ formatTime(msg.created_at) }}</span>
              </div>
              <div class="message-content">{{ msg.content }}</div>
              <div class="message-actions">
                <button
                  type="button"
                  class="msg-action"
                  :class="{ active: activeThreadParent?.id === msg.id }"
                  :title="$t('chat.reply_in_thread')"
                  @click="openThread(msg)"
                >
                  <MessageSquare :size="13" />
                  <span>{{ msg.reply_count ? $t('chat.replies_count', { count: msg.reply_count }) : $t('chat.reply_in_thread') }}</span>
                </button>
                <button
                  type="button"
                  class="msg-action"
                  :disabled="convertingTaskId === msg.id"
                  :title="$t('chat.convert_to_task')"
                  @click="convertToTask(msg)"
                >
                  <ListPlus :size="13" />
                  <span>{{ convertingTaskId === msg.id ? $t('common.loading') : $t('chat.convert_to_task') }}</span>
                </button>
              </div>
            </div>
          </div>
        </div>

        <!-- Message Input Form -->
        <div class="message-input-bar">
          <form class="flex gap-2" @submit.prevent="sendMessage">
            <input
              v-model="newMessageText"
              type="text"
              class="eink-input flex-1"
              :placeholder="$t('chat.type_message')"
              :disabled="sendingMessage || !activeChannel"
            />
            <button
              type="submit"
              class="eink-btn eink-btn-primary"
              :disabled="!newMessageText.trim() || sendingMessage || !activeChannel"
            >
              <SendHorizontal :size="15" />
              <span class="hide-narrow">{{ $t('chat.send') }}</span>
            </button>
          </form>
        </div>
      </div>

      <!-- Thread Drawer (Side Panel) -->
      <div v-if="activeThreadParent" class="thread-drawer w-80 border-l flex flex-col bg-card">
        <div class="eink-panel-head">
          <span class="eink-panel-title text-sm">
            <MessagesSquare :size="15" /> {{ $t('chat.thread_title') }}
          </span>
          <button class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('chat.close_thread')" @click="closeThread">
            <X :size="14" />
          </button>
        </div>

        <!-- Root Message in Thread -->
        <div class="thread-root">
          <div class="message-meta">
            <span class="font-semibold text-sm">{{ activeThreadParent.sender_username }}</span>
            <span class="text-xs text-muted">{{ formatTime(activeThreadParent.created_at) }}</span>
          </div>
          <div class="message-content">
            {{ activeThreadParent.content }}
          </div>
        </div>

        <!-- Thread Replies List -->
        <div ref="threadScrollContainer" class="thread-feed scroll-blocks flex-1 overflow-y-auto">
          <div v-if="loadingThread" class="eink-empty">{{ $t('common.loading') }}</div>
          <div v-else-if="threadReplies.length === 0" class="eink-empty">{{ $t('chat.no_messages') }}</div>
          <div v-for="rep in threadReplies" :key="rep.id" class="message-row">
            <span class="avatar">{{ rep.sender_username?.charAt(0).toUpperCase() || '?' }}</span>
            <div class="message-main">
              <div class="message-meta">
                <span class="font-semibold text-sm">{{ rep.sender_username }}</span>
                <span class="text-xs text-muted">{{ formatTime(rep.created_at) }}</span>
              </div>
              <div class="message-content">{{ rep.content }}</div>
            </div>
          </div>
        </div>

        <!-- Thread Reply Input Form -->
        <div class="message-input-bar">
          <form class="flex gap-2" @submit.prevent="sendThreadReply">
            <input
              v-model="newThreadReplyText"
              type="text"
              class="eink-input flex-1"
              :placeholder="$t('chat.reply_placeholder')"
              :disabled="sendingThreadReply"
            />
            <button
              type="submit"
              class="eink-btn eink-btn-primary eink-btn-icon"
              :title="$t('chat.send')"
              :disabled="!newThreadReplyText.trim() || sendingThreadReply"
            >
              <SendHorizontal :size="15" />
            </button>
          </form>
        </div>
      </div>
    </div>

    <!-- Modal: Create New Channel -->
    <EinkModal :open="showNewChannelModal" :title="$t('chat.create_channel')" @close="showNewChannelModal = false">
      <form @submit.prevent="createChannel">
        <label class="eink-label">{{ $t('chat.channel_name') }}</label>
        <input v-model="newChannelName" type="text" class="eink-input" placeholder="team-discussion" required />
        <div class="eink-modal-actions">
          <button type="button" class="eink-btn" @click="showNewChannelModal = false">{{ $t('common.cancel') }}</button>
          <button type="submit" class="eink-btn eink-btn-primary" :disabled="!newChannelName.trim() || creatingChannel">
            {{ creatingChannel ? $t('common.loading') : $t('common.create') }}
          </button>
        </div>
      </form>
    </EinkModal>
  </div>
</template>

<script setup>
import { Lock, Hash, Plus, MessageSquare, ListPlus, MessagesSquare, X, RefreshCw, SendHorizontal } from 'lucide-vue-next'
import { ref, watch, onMounted, nextTick } from 'vue'
import api from '../api/client'
import EinkModal from './EinkModal.vue'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  },
  fill: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['task-created'])

// Channels state
const channels = ref([])
const activeChannel = ref(null)
const loadingChannels = ref(false)
const showNewChannelModal = ref(false)
const newChannelName = ref('')
const creatingChannel = ref(false)

// Messages state
const messages = ref([])
const loadingMessages = ref(false)
const newMessageText = ref('')
const sendingMessage = ref(false)
const convertingTaskId = ref(null)
const messagesScrollContainer = ref(null)

// Thread state
const activeThreadParent = ref(null)
const threadReplies = ref([])
const loadingThread = ref(false)
const newThreadReplyText = ref('')
const sendingThreadReply = ref(false)
const threadScrollContainer = ref(null)

// Format ISO date
function formatTime(isoString) {
  if (!isoString) return ''
  const d = new Date(isoString)
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

// Fetch Channels
async function fetchChannels() {
  if (!props.workspaceId) return
  loadingChannels.value = true
  try {
    const data = await api.get(`/api/workspaces/${props.workspaceId}/channels`)
    channels.value = data || []
    if (channels.value.length > 0 && !activeChannel.value) {
      selectChannel(channels.value[0])
    }
  } catch (err) {
    console.error('Failed to fetch channels:', err)
  } finally {
    loadingChannels.value = false
  }
}

// Select Active Channel
function selectChannel(channel) {
  activeChannel.value = channel
  activeThreadParent.value = null
  fetchMessages()
}

// Create Channel
async function createChannel() {
  if (!newChannelName.value.trim() || !props.workspaceId) return
  creatingChannel.value = true
  try {
    const created = await api.post(`/api/workspaces/${props.workspaceId}/channels`, {
      name: newChannelName.value.trim(),
      is_private: false
    })
    channels.value.push(created)
    activeChannel.value = created
    newChannelName.value = ''
    showNewChannelModal.value = false
    fetchMessages()
  } catch (err) {
    console.error('Failed to create channel:', err)
  } finally {
    creatingChannel.value = false
  }
}

// Fetch Messages in Active Channel
async function fetchMessages() {
  if (!props.workspaceId || !activeChannel.value) return
  loadingMessages.value = true
  try {
    const data = await api.get(`/api/workspaces/${props.workspaceId}/channels/${activeChannel.value.id}/messages`)
    messages.value = data || []
    await nextTick()
    scrollToBottom(messagesScrollContainer.value)
  } catch (err) {
    console.error('Failed to fetch messages:', err)
  } finally {
    loadingMessages.value = false
  }
}

// Send Message (Supports /task command)
async function sendMessage() {
  const content = newMessageText.value.trim()
  if (!content || !props.workspaceId || !activeChannel.value) return

  sendingMessage.value = true
  try {
    // Check for /task slash command
    if (content.startsWith('/task ')) {
      const taskTitle = content.replace('/task ', '').trim()
      // Post notice message to chat
      const msg = await api.post(`/api/workspaces/${props.workspaceId}/channels/${activeChannel.value.id}/messages`, {
        content: `📋 [TASK CREATED] ${taskTitle}`
      })
      messages.value.push(msg)

      // Create Task
      await api.post(`/api/workspaces/${props.workspaceId}/tasks`, {
        title: taskTitle,
        description: `Originated via /task command in #${activeChannel.value.name}`,
        status: 'todo',
        priority: 'medium'
      })
      emit('task-created')
    } else {
      const msg = await api.post(`/api/workspaces/${props.workspaceId}/channels/${activeChannel.value.id}/messages`, {
        content
      })
      messages.value.push(msg)
    }

    newMessageText.value = ''
    await nextTick()
    scrollToBottom(messagesScrollContainer.value)
  } catch (err) {
    console.error('Failed to send message:', err)
  } finally {
    sendingMessage.value = false
  }
}

// Convert message to task
async function convertToTask(msg) {
  if (!props.workspaceId || !msg?.id) return
  convertingTaskId.value = msg.id
  try {
    await api.post(`/api/workspaces/${props.workspaceId}/tasks/from-message`, {
      message_id: msg.id,
      priority: 'medium'
    })
    emit('task-created')
  } catch (err) {
    console.error('Failed to convert message to task:', err)
  } finally {
    convertingTaskId.value = null
  }
}

// Open Thread
async function openThread(msg) {
  activeThreadParent.value = msg
  await fetchThreadReplies()
}

// Close Thread
function closeThread() {
  activeThreadParent.value = null
  threadReplies.value = []
}

// Fetch Thread Replies
async function fetchThreadReplies() {
  if (!props.workspaceId || !activeChannel.value || !activeThreadParent.value) return
  loadingThread.value = true
  try {
    const data = await api.get(
      `/api/workspaces/${props.workspaceId}/channels/${activeChannel.value.id}/messages?parent_id=${activeThreadParent.value.id}`
    )
    threadReplies.value = data || []
    await nextTick()
    scrollToBottom(threadScrollContainer.value)
  } catch (err) {
    console.error('Failed to fetch thread replies:', err)
  } finally {
    loadingThread.value = false
  }
}

// Send Thread Reply
async function sendThreadReply() {
  const content = newThreadReplyText.value.trim()
  if (!content || !props.workspaceId || !activeChannel.value || !activeThreadParent.value) return

  sendingThreadReply.value = true
  try {
    const reply = await api.post(`/api/workspaces/${props.workspaceId}/channels/${activeChannel.value.id}/messages`, {
      content,
      thread_parent_id: activeThreadParent.value.id
    })
    threadReplies.value.push(reply)
    if (activeThreadParent.value) {
      activeThreadParent.value.reply_count = (activeThreadParent.value.reply_count || 0) + 1
    }
    // Update count in main feed as well
    const found = messages.value.find((m) => m.id === activeThreadParent.value.id)
    if (found) {
      found.reply_count = (found.reply_count || 0) + 1
    }

    newThreadReplyText.value = ''
    await nextTick()
    scrollToBottom(threadScrollContainer.value)
  } catch (err) {
    console.error('Failed to send thread reply:', err)
  } finally {
    sendingThreadReply.value = false
  }
}

function scrollToBottom(container) {
  if (container) {
    container.scrollTop = container.scrollHeight
  }
}

watch(
  () => props.workspaceId,
  (newId) => {
    if (newId) {
      channels.value = []
      activeChannel.value = null
      messages.value = []
      activeThreadParent.value = null
      fetchChannels()
    }
  }
)

onMounted(() => {
  fetchChannels()
})
</script>

<style scoped>
.chat-thread-container {
  height: 650px;
  background-color: var(--color-paper-card);
  container-type: inline-size;
  container-name: chat-thread;
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.chat-thread-container.is-fill {
  height: 100%;
}

.chat-thread-body {
  display: flex;
  flex: 1;
  min-width: 0;
  min-height: 0;
  height: 100%;
}

.channel-item {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  padding: 0.55rem 0.75rem;
  font-size: 0.875rem;
  border-bottom: var(--border-faint);
  cursor: pointer;
}

.channel-item:hover {
  background-color: var(--color-paper-dim);
}

.channel-active,
.channel-active:hover {
  background-color: var(--color-ink-900);
  color: var(--color-paper);
  font-weight: 600;
}

.message-row {
  display: flex;
  gap: 0.75rem;
  padding: 0.75rem 1rem;
  border-bottom: var(--border-faint);
}

.message-row:hover {
  background-color: var(--color-paper);
}

.thread-parent-highlight {
  box-shadow: inset 3px 0 0 var(--color-ink-900);
  background-color: var(--color-paper);
}

.avatar {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 2rem;
  height: 2rem;
  font-size: 0.875rem;
  font-weight: 700;
  border: var(--border-crisp);
  border-radius: var(--radius-sm);
  background-color: var(--color-paper-dim);
}

.message-main {
  flex: 1;
  min-width: 0;
}

.message-meta {
  display: flex;
  align-items: baseline;
  gap: 0.5rem;
}

.message-content {
  margin-top: 0.15rem;
  font-size: 0.9rem;
  line-height: 1.5;
  white-space: pre-wrap;
  overflow-wrap: anywhere;
}

.message-actions {
  display: flex;
  flex-wrap: wrap;
  gap: 0.25rem;
  margin-top: 0.35rem;
}

.msg-action {
  display: inline-flex;
  align-items: center;
  gap: 0.3rem;
  height: 1.6rem;
  padding: 0 0.45rem;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-ink-500);
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  cursor: pointer;
  transition: color 120ms, border-color 120ms;
}

.msg-action:hover,
.msg-action.active {
  color: var(--color-ink-900);
  border-color: var(--color-ink-900);
}

.msg-action:disabled {
  opacity: 0.4;
  cursor: default;
}

.thread-root {
  padding: 0.75rem 1rem;
  border-bottom: var(--border-crisp);
  background-color: var(--color-paper);
}

.message-input-bar {
  display: flex;
  padding: 0.75rem;
  border-top: var(--border-crisp);
  background-color: var(--color-paper);
}

.message-input-bar form {
  flex: 1;
}

@container (max-width: 520px) {
  .hide-narrow {
    display: none;
  }
}

@container chat-thread (max-width: 560px) {
  .chat-thread-body {
    flex-direction: column;
  }

  .channels-sidebar {
    width: 100%;
    max-height: 150px;
    border-right: none;
    border-bottom: var(--border-crisp);
  }

  .chat-thread-container.is-fill .channels-sidebar {
    max-height: 7rem;
  }

  .message-area {
    min-height: 420px;
  }

  .chat-thread-container.is-fill .message-area {
    min-height: 0;
  }

  .thread-drawer {
    border-left: none;
    border-top: var(--border-crisp);
  }
}

@media (max-width: 767px) {
  .chat-thread-container {
    flex-direction: column;
    height: auto;
  }

  .chat-thread-body {
    flex-direction: column;
  }

  .channels-sidebar {
    width: 100%;
    max-height: 150px;
    border-right: none;
    border-bottom: var(--border-crisp);
  }

  .message-area {
    min-height: 420px;
  }

  .thread-drawer {
    border-left: none;
    border-top: var(--border-crisp);
  }
}
</style>
