<script setup>
import { ref, onMounted } from 'vue'
import { Sparkles, ShieldAlert } from 'lucide-vue-next'
import Navbar from './components/Navbar.vue'
import CompareMatrix from './components/CompareMatrix.vue'
import PlatformCards from './components/PlatformCards.vue'
import HistoryModal from './components/HistoryModal.vue'
import AdminPanel from './components/AdminPanel.vue'
import { fetchPlatforms, fetchPlans, fetchCompareMatrix } from './api'

const loading = ref(true)
const error = ref(null)

const viewMode = ref('matrix') // 'matrix' | 'cards'
const country = ref('TW')
const billingCycle = ref('monthly') // 'monthly' | 'annual'
const usdRate = ref(32.5) // USD to TWD reference rate

const platforms = ref([])
const plans = ref([])
const compareData = ref({ groups: [] })

const selectedHistoryPlan = ref(null)
const showHistoryModal = ref(false)
const showAdminPanel = ref(false)

const loadData = async () => {
  loading.value = true
  error.value = null
  try {
    const [platformsRes, plansRes, compareRes] = await Promise.all([
      fetchPlatforms(),
      fetchPlans({ country: country.value }),
      fetchCompareMatrix(country.value)
    ])
    platforms.value = platformsRes
    plans.value = plansRes
    compareData.value = compareRes
  } catch (err) {
    error.value = err.message || '載入資料失敗，請確認後端 FastAPI 是否已啟動'
  } finally {
    loading.value = false
  }
}

const handleOpenHistory = (plan) => {
  selectedHistoryPlan.value = plan
  showHistoryModal.value = true
}

onMounted(() => {
  loadData()
})
</script>

<template>
  <div class="min-h-screen bg-slate-950 text-slate-100 flex flex-col selection:bg-blue-600 selection:text-white">
    <!-- Top Navbar -->
    <Navbar
      v-model:viewMode="viewMode"
      v-model:country="country"
      v-model:billingCycle="billingCycle"
      :usdRate="usdRate"
      @openAdmin="showAdminPanel = true"
    />

    <!-- Main Container -->
    <main class="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 sm:py-12 space-y-10">
      <!-- Hero Section -->
      <section class="text-center max-w-3xl mx-auto space-y-4 pt-4 sm:pt-6">
        <div class="inline-flex items-center gap-2 px-3.5 py-1.5 rounded-full bg-blue-500/10 border border-blue-500/20 text-blue-400 text-xs font-bold tracking-wide uppercase">
          <Sparkles class="w-3.5 h-3.5" />
          全台最新 AI 訂閱方案透明比價
        </div>
        <h2 class="text-3xl sm:text-5xl font-black tracking-tight text-white leading-tight">
          找到最適合你的 <br class="hidden sm:block" />
          <span class="bg-gradient-to-r from-blue-400 via-indigo-400 to-emerald-400 bg-clip-text text-transparent">
            AI 旗艦模型與訂閱方案
          </span>
        </h2>
        <p class="text-sm sm:text-base text-slate-400 leading-relaxed">
          每日自動整理 OpenAI、Anthropic、Google、Perplexity 官方最新價格與方案規格，即時掌握變動、年繳折扣與幣別換算。
        </p>

        <!-- Quick Summary Badges -->
        <div class="flex flex-wrap items-center justify-center gap-4 pt-2 text-xs font-semibold text-slate-300">
          <div class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900/80 border border-slate-800 rounded-xl">
            <span class="w-2 h-2 rounded-full bg-emerald-400"></span>
            <span>ChatGPT (OpenAI)</span>
          </div>
          <div class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900/80 border border-slate-800 rounded-xl">
            <span class="w-2 h-2 rounded-full bg-amber-400"></span>
            <span>Claude (Anthropic)</span>
          </div>
          <div class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900/80 border border-slate-800 rounded-xl">
            <span class="w-2 h-2 rounded-full bg-blue-400"></span>
            <span>Gemini (Google One)</span>
          </div>
          <div class="flex items-center gap-1.5 px-3 py-1.5 bg-slate-900/80 border border-slate-800 rounded-xl">
            <span class="w-2 h-2 rounded-full bg-purple-400"></span>
            <span>Perplexity AI</span>
          </div>
        </div>
      </section>

      <!-- Loading State -->
      <div v-if="loading" class="flex flex-col items-center justify-center py-24 space-y-4">
        <div class="animate-spin rounded-full h-12 w-12 border-4 border-blue-500 border-t-transparent"></div>
        <p class="text-sm font-medium text-slate-400">正在同步最新比價資料庫...</p>
      </div>

      <!-- Error State -->
      <div v-else-if="error" class="p-8 bg-rose-500/10 border border-rose-500/30 rounded-3xl text-center space-y-4 max-w-xl mx-auto">
        <ShieldAlert class="w-10 h-10 text-rose-400 mx-auto" />
        <h3 class="text-lg font-bold text-white">資料載入失敗</h3>
        <p class="text-sm text-rose-300 leading-relaxed">{{ error }}</p>
        <button
          class="px-5 py-2.5 bg-rose-600 hover:bg-rose-500 text-white text-xs font-bold rounded-xl transition shadow"
          @click="loadData"
        >
          重新整理重試
        </button>
      </div>

      <!-- Main Views -->
      <div v-else class="space-y-8">
        <!-- Matrix View -->
        <CompareMatrix
          v-if="viewMode === 'matrix'"
          :compareData="compareData"
          :platforms="platforms"
          :billingCycle="billingCycle"
          :usdRate="usdRate"
          @openHistory="handleOpenHistory"
        />

        <!-- Cards View -->
        <PlatformCards
          v-else-if="viewMode === 'cards'"
          :plans="plans"
          :platforms="platforms"
          :billingCycle="billingCycle"
          :usdRate="usdRate"
          @openHistory="handleOpenHistory"
        />
      </div>
    </main>

    <!-- History Trend Modal -->
    <HistoryModal
      :plan="selectedHistoryPlan"
      :show="showHistoryModal"
      @close="showHistoryModal = false"
    />

    <AdminPanel
      :show="showAdminPanel"
      @close="showAdminPanel = false"
      @refreshData="loadData"
    />

    <!-- Footer -->
    <footer class="border-t border-slate-800/80 bg-slate-950 py-8 text-center text-xs text-slate-500 space-y-2">
      <p>© 2026 AI 平台比價網 — 自動化即時爬蟲與資料分析系統</p>
      <p class="text-[11px] text-slate-600">
        定價資料皆擷取自各平台公開定價頁面，實際計費請以官方結帳當下標示為準。
      </p>
    </footer>
  </div>
</template>
