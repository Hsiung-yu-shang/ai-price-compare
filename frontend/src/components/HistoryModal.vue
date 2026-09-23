<script setup>
import { ref, watch, nextTick } from 'vue'
import { X, TrendingUp, Calendar, AlertCircle } from 'lucide-vue-next'
import { Chart } from 'chart.js'
// ✅ Chart.register() 已移到 main.js 全域執行一次，這裡不重複呼叫
import { fetchPlanHistory } from '../api'

const props = defineProps({
  plan: {
    type: Object,
    default: null
  },
  show: {
    type: Boolean,
    default: false
  }
})

const emit = defineEmits(['close'])

const loading = ref(false)
const error = ref(null)
const historyList = ref([])
const chartCanvas = ref(null)
let chartInstance = null

// ── Esc 鍵關閉 Modal ──────────────────────────────────────
const handleEsc = (e) => {
  if (e.key === 'Escape') emit('close')
}

const loadHistory = async () => {
  if (!props.plan?.id) return
  loading.value = true
  error.value = null
  try {
    const data = await fetchPlanHistory(props.plan.id)
    historyList.value = data
    await nextTick()
    renderChart(data)
  } catch (err) {
    error.value = err.message || '載入歷史資料失敗'
  } finally {
    loading.value = false
  }
}

const renderChart = (data) => {
  if (!chartCanvas.value) return
  if (chartInstance) {
    chartInstance.destroy()
    chartInstance = null
  }

  // 若只有 1 筆或 0 筆，補一個「現在」點讓折線可視
  const labels = data.length > 0
    ? data.map(item => new Date(item.changed_at).toLocaleDateString('zh-TW'))
    : ['目前價格']

  const prices = data.length > 0
    ? data.map(item => item.new_monthly_price)
    : [props.plan.monthly_price]

  if (labels.length === 1) {
    labels.push('現在')
    prices.push(props.plan.monthly_price)
  }

  const ctx = chartCanvas.value.getContext('2d')
  chartInstance = new Chart(ctx, {
    type: 'line',
    data: {
      labels,
      datasets: [
        {
          label: `${props.plan.plan_name} (${props.plan.currency})`,
          data: prices,
          borderColor: '#3b82f6',
          backgroundColor: 'rgba(59, 130, 246, 0.1)',
          borderWidth: 3,
          fill: true,
          tension: 0.3,
          pointBackgroundColor: '#60a5fa',
          pointRadius: 6,
          pointHoverRadius: 8,
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: {
          labels: { color: '#94a3b8', font: { family: 'inherit' } }
        },
        tooltip: {
          backgroundColor: '#0f172a',
          titleColor: '#f8fafc',
          bodyColor: '#cbd5e1',
          borderColor: '#334155',
          borderWidth: 1,
          padding: 10,
          callbacks: {
            label: (ctx) => `${ctx.dataset.label}: ${props.plan.currency} ${ctx.parsed.y}`
          }
        }
      },
      scales: {
        x: {
          grid: { color: 'rgba(51, 65, 85, 0.4)' },
          ticks: { color: '#94a3b8' }
        },
        y: {
          grid: { color: 'rgba(51, 65, 85, 0.4)' },
          ticks: {
            color: '#94a3b8',
            callback: (val) => `${props.plan.currency} ${val}`
          }
        }
      }
    }
  })
}

watch(() => props.show, (newVal) => {
  if (newVal) {
    // ✅ 開啟時先清空上一個方案的舊資料，避免短暫殘留
    historyList.value = []
    error.value = null
    window.addEventListener('keydown', handleEsc)
    loadHistory()
  } else {
    // ✅ 關閉時清理 Chart 與 Esc 監聽器
    window.removeEventListener('keydown', handleEsc)
    if (chartInstance) {
      chartInstance.destroy()
      chartInstance = null
    }
  }
})
</script>

<template>
  <div
    v-if="show"
    class="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/70 backdrop-blur-sm animate-fadeIn"
    @click.self="emit('close')"
  >
    <div class="relative w-full max-w-2xl bg-slate-900 border border-slate-800 rounded-2xl shadow-2xl overflow-hidden">
      <!-- Header -->
      <div class="flex items-center justify-between px-6 py-4 border-b border-slate-800 bg-slate-900/80">
        <div class="flex items-center gap-3">
          <div class="p-2 bg-blue-500/10 text-blue-400 rounded-xl">
            <TrendingUp class="w-5 h-5" />
          </div>
          <div>
            <h3 class="text-lg font-bold text-white">{{ plan?.plan_name }} — 價格歷史走勢</h3>
            <p class="text-xs text-slate-400">追蹤官方價格變動與歷史紀錄｜按 Esc 鍵可關閉</p>
          </div>
        </div>
        <button
          class="p-2 text-slate-400 hover:text-white rounded-lg hover:bg-slate-800 transition"
          @click="emit('close')"
        >
          <X class="w-5 h-5" />
        </button>
      </div>

      <!-- Content -->
      <div class="p-6 space-y-6">
        <!-- Current Summary -->
        <div class="grid grid-cols-3 gap-3 p-4 bg-slate-950/60 border border-slate-800/80 rounded-xl">
          <div>
            <span class="text-xs text-slate-400">目前月費</span>
            <div class="text-lg font-bold text-emerald-400">
              {{ plan?.currency }} {{ plan?.monthly_price }}
            </div>
          </div>
          <div>
            <span class="text-xs text-slate-400">年繳月均</span>
            <div class="text-lg font-bold text-blue-400">
              {{ plan?.annual_monthly_price ? `${plan.currency} ${plan.annual_monthly_price}` : '無年繳' }}
            </div>
          </div>
          <div>
            <span class="text-xs text-slate-400">最後確認時間</span>
            <div class="text-xs font-medium text-slate-300 mt-1">
              {{ plan?.fetched_at ? new Date(plan.fetched_at).toLocaleDateString('zh-TW') : '-' }}
            </div>
          </div>
        </div>

        <!-- Chart Container -->
        <div class="relative h-64 w-full bg-slate-950/40 rounded-xl p-3 border border-slate-800/50">
          <div v-if="loading" class="absolute inset-0 flex items-center justify-center bg-slate-900/50 backdrop-blur-sm">
            <div class="animate-spin rounded-full h-8 w-8 border-2 border-blue-500 border-t-transparent"></div>
          </div>
          <div v-else-if="error" class="absolute inset-0 flex flex-col items-center justify-center text-rose-400 gap-2">
            <AlertCircle class="w-6 h-6" />
            <span class="text-sm">{{ error }}</span>
          </div>
          <canvas ref="chartCanvas"></canvas>
        </div>

        <!-- History Records Table -->
        <div>
          <h4 class="text-sm font-semibold text-slate-300 mb-3 flex items-center gap-2">
            <Calendar class="w-4 h-4 text-slate-400" />
            歷史變動紀錄清單
          </h4>
          <div class="max-h-40 overflow-y-auto border border-slate-800 rounded-xl bg-slate-950/40">
            <table class="w-full text-left text-xs text-slate-300">
              <thead class="bg-slate-900/90 text-slate-400 border-b border-slate-800 sticky top-0">
                <tr>
                  <th class="py-2.5 px-3">時間</th>
                  <th class="py-2.5 px-3">事件</th>
                  <th class="py-2.5 px-3">舊價格</th>
                  <th class="py-2.5 px-3">新價格</th>
                </tr>
              </thead>
              <tbody class="divide-y divide-slate-800/60">
                <tr v-if="historyList.length === 0 && !loading">
                  <td colspan="4" class="py-4 text-center text-slate-500">暫無價格異動紀錄（價格保持穩定）</td>
                </tr>
                <tr v-for="(item, idx) in historyList" :key="idx" class="hover:bg-slate-800/30">
                  <td class="py-2.5 px-3 text-slate-400">
                    {{ new Date(item.changed_at).toLocaleDateString('zh-TW') }}
                  </td>
                  <td class="py-2.5 px-3">
                    <span
                      class="px-2 py-0.5 rounded-md text-[10px] font-medium"
                      :class="item.change_type === 'new_plan'
                        ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                        : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'"
                    >
                      {{ item.change_type === 'new_plan' ? '方案初次上線' : '價格調整' }}
                    </span>
                  </td>
                  <td class="py-2.5 px-3 text-slate-400">
                    {{ item.old_monthly_price != null ? `${plan.currency} ${item.old_monthly_price}` : '-' }}
                  </td>
                  <td class="py-2.5 px-3 font-semibold text-emerald-400">
                    {{ plan.currency }} {{ item.new_monthly_price }}
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
@keyframes fadeIn {
  from { opacity: 0; transform: scale(0.98); }
  to { opacity: 1; transform: scale(1); }
}
.animate-fadeIn {
  animation: fadeIn 0.15s ease-out;
}
</style>
