<template>
  <div class="file-manager-container flex flex-col gap-3">
    <!-- Toolbar -->
    <div class="toolbar eink-card p-3 flex flex-wrap justify-between items-center gap-2">
      <nav class="breadcrumbs" :aria-label="$t('files.title')">
        <button type="button" class="crumb" :class="{ current: !folderId }" @click="openFolder(null)">
          {{ $t('files.root') }}
        </button>
        <template v-for="crumb in breadcrumbs" :key="crumb.id">
          <span class="crumb-sep">/</span>
          <button type="button" class="crumb" :class="{ current: crumb.id === folderId }" @click="openFolder(crumb.id)">
            {{ crumb.name }}
          </button>
        </template>
      </nav>

      <div class="flex flex-wrap items-center gap-2">
        <span class="text-xs text-muted">{{ usedMb }} / {{ quotaMb }} {{ $t('storage.mb') }}</span>
        <button type="button" class="eink-btn eink-btn-sm eink-btn-icon" :title="$t('common.refresh')" @click="fetchFiles"><RefreshCw :size="14" /></button>
        <button type="button" class="eink-btn eink-btn-sm" @click="openFolderDialog()">
          <FolderPlus :size="14" /> {{ $t('files.new_folder') }}
        </button>
        <input ref="fileInputRef" type="file" multiple class="hidden" @change="handleFileInputChange" />
        <button type="button" class="eink-btn eink-btn-sm eink-btn-primary" :disabled="uploading" @click="openFilePicker">
          <Upload :size="14" /> {{ uploading ? $t('files.uploading') : $t('files.upload_btn') }}
        </button>
      </div>
    </div>

    <!-- Selection actions -->
    <div v-if="selectedCount" class="selection-bar eink-card p-2 flex flex-wrap items-center gap-2">
      <span class="text-sm font-semibold px-1">{{ $t('files.selected', { count: selectedCount }) }}</span>
      <button type="button" class="eink-btn eink-btn-sm eink-btn-primary" :disabled="downloading" @click="downloadSelection">
        <Download :size="14" />
        {{ isSingleFileSelected ? $t('files.download') : $t('files.download_zip') }}
      </button>
      <button type="button" class="eink-btn eink-btn-sm" @click="openMoveDialog">
        <FolderInput :size="14" /> {{ $t('files.move') }}
      </button>
      <button type="button" class="eink-btn eink-btn-sm eink-btn-danger" @click="deleteSelection">
        <Trash2 :size="14" /> {{ $t('files.delete') }}
      </button>
      <button type="button" class="eink-btn eink-btn-sm" @click="clearSelection">{{ $t('common.cancel') }}</button>
    </div>

    <div v-if="errorMessage" class="error-banner eink-card p-3 flex items-center justify-between gap-2 text-sm">
      <strong>{{ errorMessage }}</strong>
      <button type="button" class="eink-btn eink-btn-sm eink-btn-icon" :aria-label="$t('common.close')" @click="errorMessage = ''"><X :size="14" /></button>
    </div>

    <!-- Listing / drop zone -->
    <div
      class="dropzone-area eink-card flex flex-col min-h-[450px]"
      :class="{ 'dropzone-active': isDraggingOver }"
      @dragover.prevent="isDraggingOver = true"
      @dragleave.prevent="isDraggingOver = false"
      @drop.prevent="handleDrop"
    >
      <div v-if="isDraggingOver" class="drop-overlay p-6 text-center text-sm font-semibold bg-paper-dim border-b">
        {{ $t('files.drop_hint') }}
      </div>

      <div class="overflow-x-auto flex-1">
        <table class="file-table">
          <thead>
            <tr>
              <th class="col-check">
                <input
                  type="checkbox"
                  :checked="allSelected"
                  :indeterminate.prop="selectedCount > 0 && !allSelected"
                  :disabled="!folders.length && !files.length"
                  :aria-label="$t('files.select_all')"
                  @change="toggleAll"
                />
              </th>
              <th>{{ $t('files.file_name') }}</th>
              <th class="col-size">{{ $t('files.file_size') }}</th>
              <th class="col-date">{{ $t('files.uploaded_at') }}</th>
              <th class="col-actions"></th>
            </tr>
          </thead>
          <tbody>
            <tr v-if="loading">
              <td colspan="5" class="p-6 text-center text-muted">{{ $t('common.loading') }}</td>
            </tr>
            <tr v-else-if="!folders.length && !files.length">
              <td colspan="5" class="p-8 text-center text-muted">
                {{ folderId ? $t('files.empty_folder') : $t('files.no_files') }}
              </td>
            </tr>

            <template v-else>
              <tr
                v-for="folder in folders"
                :key="`d${folder.id}`"
                class="row"
                :class="{ selected: selectedFolders.has(folder.id) }"
              >
                <td class="col-check">
                  <input type="checkbox" :checked="selectedFolders.has(folder.id)" @change="toggle(selectedFolders, folder.id)" />
                </td>
                <td>
                  <button type="button" class="name-link" @click="openFolder(folder.id)">
                    <Folder :size="16" class="shrink-0" />
                    <span class="truncate">{{ folder.name }}</span>
                  </button>
                </td>
                <td class="col-size text-muted">
                  {{ folder.size_formatted }}
                  <span class="items-count">· {{ $t('files.items', { count: folder.items_count }) }}</span>
                </td>
                <td class="col-date text-muted">{{ formatDate(folder.created_at) }}</td>
                <td class="col-actions">
                  <div class="row-actions">
                    <button type="button" class="icon-btn" :title="$t('files.download_zip')" @click="downloadArchive([], [folder.id])">
                      <Download :size="14" />
                    </button>
                    <button type="button" class="icon-btn" :title="$t('files.rename')" @click="openFolderDialog(folder)">
                      <Pencil :size="14" />
                    </button>
                    <button type="button" class="icon-btn" :title="$t('files.delete')" @click="deleteItems([], [folder])">
                      <Trash2 :size="14" />
                    </button>
                  </div>
                </td>
              </tr>

              <tr
                v-for="file in files"
                :key="`f${file.id}`"
                class="row"
                :class="{ selected: selectedFiles.has(file.id) }"
              >
                <td class="col-check">
                  <input type="checkbox" :checked="selectedFiles.has(file.id)" @change="toggle(selectedFiles, file.id)" />
                </td>
                <td>
                  <span class="name-cell">
                    <component :is="fileIcon(file.mime_type)" :size="16" class="shrink-0" />
                    <span class="truncate">{{ file.file_name }}</span>
                  </span>
                </td>
                <td class="col-size text-muted">{{ file.file_size_formatted }}</td>
                <td class="col-date text-muted">{{ formatDate(file.created_at) }}</td>
                <td class="col-actions">
                  <div class="row-actions">
                    <button type="button" class="icon-btn" :title="$t('files.download')" @click="downloadFile(file)">
                      <Download :size="14" />
                    </button>
                    <button type="button" class="icon-btn" :title="$t('files.delete')" @click="deleteItems([file], [])">
                      <Trash2 :size="14" />
                    </button>
                  </div>
                </td>
              </tr>
            </template>
          </tbody>
        </table>
      </div>
    </div>

    <!-- New / rename folder -->
    <EinkModal
      :open="!!folderDialog"
      :title="folderDialog?.folder ? $t('files.rename_folder') : $t('files.new_folder')"
      @close="folderDialog = null"
    >
      <template v-if="folderDialog">
        <form @submit.prevent="submitFolderDialog">
          <input
            ref="folderNameRef"
            v-model="folderDialog.name"
            type="text"
            required
            maxlength="120"
            class="eink-input mb-4"
            :placeholder="$t('files.folder_name')"
          />
          <div class="eink-modal-actions">
            <button type="button" class="eink-btn" @click="folderDialog = null">{{ $t('common.cancel') }}</button>
            <button type="submit" class="eink-btn eink-btn-primary" :disabled="!folderDialog.name.trim()">
              {{ folderDialog.folder ? $t('common.save') : $t('files.create') }}
            </button>
          </div>
        </form>
      </template>
    </EinkModal>

    <!-- Move -->
    <EinkModal
      :open="!!moveDialog"
      :title="moveDialog ? $t('files.move_to', { count: selectedCount }) : ''"
      @close="moveDialog = null"
    >
      <template v-if="moveDialog">
        <form @submit.prevent="submitMove">
          <select v-model="moveDialog.target" class="eink-select mb-4">
            <option :value="null">/ {{ $t('files.root') }}</option>
            <option v-for="f in moveTargets" :key="f.id" :value="f.id">/ {{ f.path }}</option>
          </select>
          <div class="eink-modal-actions">
            <button type="button" class="eink-btn" @click="moveDialog = null">{{ $t('common.cancel') }}</button>
            <button type="submit" class="eink-btn eink-btn-primary">{{ $t('files.move') }}</button>
          </div>
        </form>
      </template>
    </EinkModal>
  </div>
</template>

<script setup>
import { ref, reactive, computed, watch, nextTick, onMounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { Folder, FolderPlus, FolderInput, Upload, Download, Trash2, Pencil, File as FileIcon, FileText, FileImage, FileArchive, RefreshCw, X } from 'lucide-vue-next'
import api, { csrfHeaders } from '../api/client'
import EinkModal from './EinkModal.vue'

const props = defineProps({
  workspaceId: {
    type: [Number, String],
    required: true
  }
})

const emit = defineEmits(['storage-updated'])

const { t, te } = useI18n()

const folderId = ref(null)
const breadcrumbs = ref([])
const folders = ref([])
const files = ref([])
const loading = ref(false)
const uploading = ref(false)
const downloading = ref(false)
const errorMessage = ref('')
const isDraggingOver = ref(false)
const fileInputRef = ref(null)
const folderNameRef = ref(null)

const selectedFiles = reactive(new Set())
const selectedFolders = reactive(new Set())

const folderDialog = ref(null)
const moveDialog = ref(null)
const allFolders = ref([])

const usedBytes = ref(0)
const quotaBytes = ref(0)

const base = computed(() => `/api/workspaces/${props.workspaceId}/files`)

const usedMb = computed(() => (usedBytes.value / (1024 * 1024)).toFixed(1))
const quotaMb = computed(() => (quotaBytes.value / (1024 * 1024)).toFixed(0))

const selectedCount = computed(() => selectedFiles.size + selectedFolders.size)
const allSelected = computed(() =>
  selectedCount.value > 0 && selectedCount.value === folders.value.length + files.value.length
)
const isSingleFileSelected = computed(() => selectedFiles.size === 1 && selectedFolders.size === 0)

// A folder cannot be moved into itself or anything nested inside it
const moveTargets = computed(() => {
  const blocked = allFolders.value
    .filter((f) => selectedFolders.has(f.id))
    .map((f) => f.path)
  return allFolders.value.filter((f) => !blocked.some((p) => f.path === p || f.path.startsWith(p + '/')))
})

function describeError(err) {
  const detail = err.detail || err.message || ''
  if (err.status === 413) return t('files.quota_exceeded')
  return te(detail) ? t(detail) : detail || t('common.error')
}

function formatDate(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  return d.toLocaleDateString() + ' ' + d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
}

function fileIcon(mime) {
  if (!mime) return FileIcon
  if (mime.includes('image')) return FileImage
  if (mime.includes('zip') || mime.includes('compressed') || mime.includes('archive')) return FileArchive
  if (mime.includes('text') || mime.includes('json') || mime.includes('pdf')) return FileText
  return FileIcon
}

function toggle(set, id) {
  if (set.has(id)) set.delete(id)
  else set.add(id)
}

function clearSelection() {
  selectedFiles.clear()
  selectedFolders.clear()
}

function toggleAll() {
  if (allSelected.value) {
    clearSelection()
    return
  }
  folders.value.forEach((f) => selectedFolders.add(f.id))
  files.value.forEach((f) => selectedFiles.add(f.id))
}

async function fetchFiles() {
  if (!props.workspaceId) return
  loading.value = true
  try {
    const params = folderId.value ? `?folder_id=${folderId.value}` : ''
    const data = await api.get(`${base.value}${params}`)
    folders.value = data.folders || []
    files.value = data.files || []
    breadcrumbs.value = data.breadcrumbs || []
    usedBytes.value = data.used_storage_bytes || 0
    quotaBytes.value = data.storage_quota_bytes || 0
    emit('storage-updated', { usedBytes: usedBytes.value, quotaBytes: quotaBytes.value })
  } catch (err) {
    // The open folder may have been deleted elsewhere: fall back to the root
    if (err.status === 404 && folderId.value) {
      folderId.value = null
      return fetchFiles()
    }
    errorMessage.value = describeError(err)
  } finally {
    loading.value = false
  }
}

function openFolder(id) {
  folderId.value = id
  clearSelection()
  fetchFiles()
}

function openFilePicker() {
  fileInputRef.value?.click()
}

function handleFileInputChange(e) {
  uploadFiles([...(e.target.files || [])])
  e.target.value = ''
}

function handleDrop(e) {
  isDraggingOver.value = false
  uploadFiles([...(e.dataTransfer?.files || [])])
}

async function uploadFiles(list) {
  if (!list.length) return
  const total = list.reduce((sum, f) => sum + f.size, 0)
  if (usedBytes.value + total > quotaBytes.value) {
    errorMessage.value = t('files.quota_exceeded')
    return
  }

  uploading.value = true
  errorMessage.value = ''
  try {
    for (const file of list) {
      const formData = new FormData()
      formData.append('file', file)
      if (folderId.value) formData.append('folder_id', folderId.value)
      await api.post(base.value, formData)
    }
  } catch (err) {
    errorMessage.value = describeError(err)
  } finally {
    uploading.value = false
    fetchFiles()
  }
}

async function saveBlob(response, fallbackName) {
  // Prefer the server's (possibly non-ASCII) filename from Content-Disposition
  const disposition = response.headers.get('Content-Disposition') || ''
  const encoded = disposition.match(/filename\*=utf-8''([^;]+)/i)
  const plain = disposition.match(/filename="?([^";]+)"?/i)
  const name = encoded ? decodeURIComponent(encoded[1]) : plain ? plain[1] : fallbackName

  const url = URL.createObjectURL(await response.blob())
  const a = document.createElement('a')
  a.href = url
  a.download = name
  a.click()
  URL.revokeObjectURL(url)
}

function authHeaders() {
  return { ...csrfHeaders }
}

async function downloadFile(file) {
  try {
    const response = await fetch(`${base.value}/${file.id}/download`, {
      headers: authHeaders(),
      credentials: 'same-origin'
    })
    if (!response.ok) throw new Error(response.statusText)
    await saveBlob(response, file.file_name)
  } catch (err) {
    errorMessage.value = describeError(err)
  }
}

async function downloadArchive(fileIds, folderIds) {
  downloading.value = true
  try {
    const response = await fetch(`${base.value}/archive`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', ...authHeaders() },
      credentials: 'same-origin',
      body: JSON.stringify({ file_ids: fileIds, folder_ids: folderIds })
    })
    if (!response.ok) throw new Error(response.statusText)
    await saveBlob(response, 'files.zip')
  } catch (err) {
    errorMessage.value = describeError(err)
  } finally {
    downloading.value = false
  }
}

function downloadSelection() {
  if (isSingleFileSelected.value) {
    const id = [...selectedFiles][0]
    downloadFile(files.value.find((f) => f.id === id))
  } else {
    downloadArchive([...selectedFiles], [...selectedFolders])
  }
}

async function deleteItems(fileList, folderList) {
  const names = [...folderList.map((f) => f.name + '/'), ...fileList.map((f) => f.file_name)]
  const message = folderList.length
    ? t('files.confirm_delete_folders', { names: names.join(', ') })
    : `${t('files.confirm_delete')}: ${names.join(', ')}`
  if (!confirm(message)) return

  try {
    for (const folder of folderList) await api.delete(`${base.value}/folders/${folder.id}`)
    for (const file of fileList) await api.delete(`${base.value}/${file.id}`)
  } catch (err) {
    errorMessage.value = describeError(err)
  }
  clearSelection()
  fetchFiles()
}

function deleteSelection() {
  deleteItems(
    files.value.filter((f) => selectedFiles.has(f.id)),
    folders.value.filter((f) => selectedFolders.has(f.id))
  )
}

async function openFolderDialog(folder = null) {
  folderDialog.value = { folder, name: folder ? folder.name : '' }
  await nextTick()
  folderNameRef.value?.focus()
}

async function submitFolderDialog() {
  const { folder, name } = folderDialog.value
  try {
    if (folder) {
      await api.patch(`${base.value}/folders/${folder.id}`, { name })
    } else {
      await api.post(`${base.value}/folders`, { name, parent_id: folderId.value })
    }
    folderDialog.value = null
    fetchFiles()
  } catch (err) {
    errorMessage.value = describeError(err)
    folderDialog.value = null
  }
}

async function openMoveDialog() {
  try {
    allFolders.value = await api.get(`${base.value}/folders`)
    moveDialog.value = { target: null }
  } catch (err) {
    errorMessage.value = describeError(err)
  }
}

async function submitMove() {
  try {
    await api.post(`${base.value}/move`, {
      file_ids: [...selectedFiles],
      folder_ids: [...selectedFolders],
      target_folder_id: moveDialog.value.target
    })
    clearSelection()
  } catch (err) {
    errorMessage.value = describeError(err)
  }
  moveDialog.value = null
  fetchFiles()
}

watch(
  () => props.workspaceId,
  (newId) => {
    if (!newId) return
    folderId.value = null
    clearSelection()
    fetchFiles()
  }
)

onMounted(() => {
  fetchFiles()
})
</script>

<style scoped>
.file-manager-container {
  min-height: 600px;
}

.hidden {
  display: none;
}

.breadcrumbs {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 0.25rem;
  min-width: 0;
}

.crumb {
  background: none;
  border: none;
  padding: 0.2rem 0.35rem;
  font-size: 0.95rem;
  font-weight: 600;
  color: var(--color-ink-500);
  cursor: pointer;
}

.crumb:hover {
  color: var(--color-ink-900);
  text-decoration: underline;
}

.crumb.current {
  color: var(--color-ink-900);
  cursor: default;
  text-decoration: none;
}

.crumb-sep {
  color: var(--color-ink-300);
}

.selection-bar {
  background-color: var(--color-paper-dim);
}

.error-banner {
  border-width: 2px;
}

.dropzone-active {
  border: 2px dashed var(--color-ink-900) !important;
  background-color: var(--color-paper-dim);
}

.file-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 0.875rem;
}

.file-table th {
  text-align: left;
  font-size: 0.75rem;
  font-weight: 600;
  color: var(--color-ink-500);
  padding: 0.6rem 0.75rem;
  border-bottom: var(--border-crisp);
  background-color: var(--color-paper-dim);
  white-space: nowrap;
}

.file-table td {
  padding: 0.55rem 0.75rem;
  border-bottom: var(--border-faint);
  vertical-align: middle;
}

.row:hover {
  background-color: var(--color-paper);
}

.row.selected {
  background-color: var(--color-paper-dim);
}

.col-check {
  width: 2.5rem;
}

.col-size {
  width: 12rem;
  white-space: nowrap;
}

.col-date {
  width: 10rem;
  white-space: nowrap;
}

.col-actions {
  width: 7rem;
}

.items-count {
  font-size: 0.75rem;
}

.name-link,
.name-cell {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  min-width: 0;
  max-width: 100%;
}

.name-link {
  background: none;
  border: none;
  padding: 0;
  font: inherit;
  font-weight: 600;
  color: var(--color-ink-900);
  cursor: pointer;
  text-align: left;
}

.name-link:hover span {
  text-decoration: underline;
}

.row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 0.25rem;
}

.icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 1.9rem;
  height: 1.9rem;
  background: none;
  border: 1px solid transparent;
  border-radius: var(--radius-sm);
  color: var(--color-ink-700);
  cursor: pointer;
  transition: color 120ms, border-color 120ms;
}

.dropzone-area {
  overflow: hidden;
}

.icon-btn:hover {
  border-color: var(--color-ink-900);
  color: var(--color-ink-900);
}

@media (max-width: 767px) {
  .col-date,
  .items-count {
    display: none;
  }

  .col-size {
    width: auto;
  }

  .file-table td,
  .file-table th {
    padding: 0.5rem;
  }
}
</style>
