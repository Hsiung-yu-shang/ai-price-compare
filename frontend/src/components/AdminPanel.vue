<script setup>
import { ref, watch, onUnmounted } from 'vue'
import { LockKeyhole, RefreshCw, X } from 'lucide-vue-next'
import { adminLogin, adminLogout, adminRefresh, adminStatus } from '../api'

const props = defineProps({ show: { type: Boolean, default: false } })
const emit = defineEmits(['close', 'refreshData'])

const password = ref('')
const token = ref('')
const status = ref(null)
const error = ref('')
const notice = ref('')
const busy = ref(false)
const statusBusy = ref(false)
const pendingManual = ref(false)
let previousFinishedAt = null
let pollTimer = null

const securePage = window.location.protocol === 'https:' ||
  ['localhost', '127.0.0.1'].includes(window.location.hostname)

function clearPoll() {
  if (pollTimer) clearInterval(pollTimer)
  pollTimer = null
}

async function loadStatus() {
  if (!token.value || statusBusy.value) return
  statusBusy.value = true
  try {
    const latest = await adminStatus(token.value)
    status.value = latest
    if (pendingManual.value && latest.finished_at &&
        latest.finished_at !== previousFinishedAt && latest.state !== 'running') {
      pendingManual.value = false
      previousFinishedAt = latest.finished_at
      notice.value = latest.state === 'success' ? '價格同步完成，頁面資料已重新載入。' : '同步已結束，部分平台可能失敗；請查看狀態。'
      emit('refreshData')
    }
  } catch (err) {
    if (err.status === 401) {
      token.value = ''
      status.value = null
      clearPoll()
    }
    error.value = err.message
  } finally {
    statusBusy.value = false
  }
}

watch([() => props.show, token], ([visible, currentToken]) => {
  clearPoll()
  if (visible && currentToken) {
    loadStatus()
    pollTimer = setInterval(loadStatus, 5000)
  }
})
onUnmounted(clearPoll)

async function login() {
  if (!securePage || !password.value || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  try {
    const result = await adminLogin(password.value)
    token.value = result.token
    password.value = ''
    notice.value = '已登入；授權約 15 分鐘後到期，關閉分頁即失效。'
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

async function refresh() {
  if (!token.value || busy.value) return
  busy.value = true
  error.value = ''
  notice.value = ''
  previousFinishedAt = status.value?.finished_at ?? null
  try {
    await adminRefresh(token.value)
    pendingManual.value = true
    notice.value = '已送出同步請求；爬蟲會在背景執行，狀態每 5 秒更新。'
    await loadStatus()
  } catch (err) {
    error.value = err.message
  } finally {
    busy.value = false
  }
}

async function logout() {
  if (token.value) {
    try { await adminLogout(token.value) } catch { /* 本機授權仍會清除 */ }
  }
  token.value = ''
  password.value = ''
  status.value = null
  pendingManual.value = false
  notice.value = '已登出。'
  clearPoll()
}

function close() {
  password.value = ''
  error.value = ''
  emit('close')
}

function formatDate(value) {
  return value ? new Date(value).toLocaleString('zh-TW') : '尚無紀錄'
}

const stateText = {
  unknown: '尚無同步紀錄',
  running: '同步中',
  success: '同步成功',
  partial: '部分成功',
  failed: '同步失敗',
  interrupted: '上次同步中斷'
}
</script>

<template>
  <div v-if="show" class="fixed inset-0 z-50 flex items-center justify-center bg-slate-950/80 p-4" @click.self="close">
    <section role="dialog" aria-modal="true" aria-label="管理員同步價格"
      class="w-full max-w-md max-h-[90vh] overflow-y-auto rounded-2xl border border-slate-700 bg-slate-900 p-6 text-slate-100 shadow-2xl space-y-5">
      <div class="flex items-center justify-between gap-4">
        <h2 class="flex items-center gap-2 text-lg font-bold"><LockKeyhole class="h-5 w-5 text-blue-400" />管理員同步價格</h2>
        <button type="button" class="rounded-lg p-1 text-slate-400 hover:text-white" aria-label="關閉管理員視窗" @click="close"><X class="h-5 w-5" /></button>
      </div>

      <p v-if="!securePage" class="text-sm text-rose-300">請使用 HTTPS 正式網域開啟網站後再登入，避免密碼透過未加密連線傳輸。</p>

      <div v-if="!token" class="space-y-3">
        <label for="admin-password" class="block text-sm text-slate-300">管理員密碼</label>
        <input id="admin-password" v-model="password" type="password" autocomplete="current-password"
          class="w-full rounded-xl border border-slate-700 bg-slate-950 px-3 py-2.5 text-sm outline-none focus:border-blue-500"
          maxlength="256" :disabled="!securePage || busy" @keyup.enter="login" />
        <button type="button" class="w-full rounded-xl bg-blue-600 px-4 py-2.5 text-sm font-semibold hover:bg-blue-500 disabled:opacity-50"
          :disabled="!securePage || !password || busy" @click="login">{{ busy ? '登入中…' : '登入' }}</button>
      </div>

      <div v-else class="space-y-4">
        <div class="rounded-xl border border-slate-700 bg-slate-950/70 p-4 text-sm space-y-1">
          <p>狀態：{{ status?.queued ? '等待啟動' : (stateText[status?.state] || '查詢中') }}</p>
          <p class="text-slate-400">上次開始：{{ formatDate(status?.started_at) }}</p>
          <p class="text-slate-400">上次結束：{{ formatDate(status?.finished_at) }}</p>
          <p v-for="item in status?.platforms || []" :key="item.platform" class="text-xs text-slate-400">
            {{ item.platform }}：{{ item.status }}（{{ item.plans }} 個方案）
          </p>
        </div>
        <button type="button" class="flex w-full items-center justify-center gap-2 rounded-xl bg-emerald-600 px-4 py-2.5 text-sm font-semibold hover:bg-emerald-500 disabled:opacity-50"
          :disabled="busy || pendingManual" @click="refresh">
          <RefreshCw class="h-4 w-4" />{{ busy ? '送出中…' : pendingManual ? '等待同步完成…' : '立即同步價格' }}
        </button>
        <div class="flex justify-between text-xs">
          <button type="button" class="text-blue-300 hover:text-blue-200" @click="loadStatus">查詢狀態</button>
          <button type="button" class="text-slate-400 hover:text-white" @click="logout">登出</button>
        </div>
      </div>

      <p v-if="notice" role="status" class="text-sm text-emerald-300">{{ notice }}</p>
      <p v-if="error" role="alert" class="text-sm text-rose-300">{{ error }}</p>
      <p class="text-xs text-slate-500">每 10 分鐘最多手動啟動一次；原有每日自動排程維持運作。</p>
    </section>
  </div>
</template>
