<script setup>
import { computed } from 'vue'
import {
  Check,
  Minus,
  TrendingUp,
  Info,
  Receipt,
  ExternalLink,
  GraduationCap
} from 'lucide-vue-next'

const props = defineProps({
  compareData: {
    type: Object,
    default: () => ({ groups: [] })
  },
  platforms: {
    type: Array,
    default: () => []
  },
  billingCycle: {
    type: String,
    default: 'monthly'
  },
  usdRate: {
    type: Number,
    default: 32.5
  }
})

const emit = defineEmits(['openHistory'])

/**
 * 前端顏色主題對照表
 * 對應 platform_config.py 的 color_theme 欄位
 * 新增平台時只需在 platform_config.py 選一個已存在的顏色，
 * 或在此表新增一行即可，不需要修改其他前端程式碼
 */
const COLOR_MAP = {
  emerald: {
    badge:  'bg-emerald-500/10 text-emerald-300 border-emerald-500/30',
    dot:    'bg-emerald-400',
  },
  amber: {
    badge:  'bg-amber-500/10 text-amber-300 border-amber-500/30',
    dot:    'bg-amber-400',
  },
  blue: {
    badge:  'bg-blue-500/10 text-blue-300 border-blue-500/30',
    dot:    'bg-blue-400',
  },
  purple: {
    badge:  'bg-purple-500/10 text-purple-300 border-purple-500/30',
    dot:    'bg-purple-400',
  },
  rose: {
    badge:  'bg-rose-500/10 text-rose-300 border-rose-500/30',
    dot:    'bg-rose-400',
  },
  indigo: {
    badge:  'bg-indigo-500/10 text-indigo-300 border-indigo-500/30',
    dot:    'bg-indigo-400',
  },
  teal: {
    badge:  'bg-teal-500/10 text-teal-300 border-teal-500/30',
    dot:    'bg-teal-400',
  },
}

const DEFAULT_COLOR = COLOR_MAP.blue

/**
 * 從 platforms prop 建立快速查找表
 * { platform_id → { badge, dot, official_url, name, vendor } }
 * 完全由 API 驅動，新增平台不需要改前端
 */
const platformMetaMap = computed(() =>
  Object.fromEntries(
    props.platforms.map(p => [
      p.platform_id,
      {
        ...(COLOR_MAP[p.color_theme] ?? DEFAULT_COLOR),
        name: p.platform_name,
        vendor: p.vendor,
        official_url: p.official_url,
      }
    ])
  )
)

/**
 * 平台顯示順序：依 platforms prop 的回傳順序
 * (API 已按 platform_id 排序，新增平台自動出現)
 */
const orderedPlatforms = computed(() => props.platforms)

/**
 * 計算單一方案的格式化價格資訊
 */
function formatPrice(plan) {
  if (!plan) return null
  if (plan.monthly_price === 0) return { label: '免費', isAnnual: false, approxTwd: null }

  let price = plan.monthly_price
  let isAnnual = false

  if (props.billingCycle === 'annual' && plan.annual_monthly_price) {
    price = plan.annual_monthly_price
    isAnnual = true
  }

  const approxTwd = plan.currency === 'USD' ? Math.round(price * props.usdRate) : null

  return {
    rawPrice: price,
    currency: plan.currency,
    isAnnual,
    approxTwd,
    label: `${plan.currency} $${price.toLocaleString()}`
  }
}

/**
 * 預先計算每個分組每個平台的方案 + 價格資訊
 * 避免 template 裡重複呼叫 formatPrice()
 */
const enrichedGroups = computed(() =>
  props.compareData.groups.map(group => ({
    ...group,
    platformsInfo: Object.fromEntries(
      orderedPlatforms.value.map(p => {
        const plan = group.platforms?.[p.platform_id] ?? null
        return [p.platform_id, { plan, price: formatPrice(plan) }]
      })
    )
  }))
)
</script>

<template>
  <div class="space-y-8">
    <!-- Notice Banner -->
    <div class="flex items-start gap-3 p-4 bg-slate-900/60 border border-slate-800 rounded-2xl text-xs text-slate-300">
      <Info class="w-4 h-4 text-blue-400 shrink-0 mt-0.5" />
      <div>
        <span class="font-bold text-slate-200">價格單位與計費說明：</span>
        {{ compareData?.currency_note || 'ChatGPT 與 Gemini 台灣為台幣定價；Claude 目前僅提供美金定價。' }}
        <span class="text-slate-400">（美金換算參考匯率：1 USD ≈ {{ usdRate }} TWD）</span>
      </div>
    </div>

    <!-- Groups Container -->
    <div class="space-y-10">
      <section
        v-for="(group, gIdx) in enrichedGroups"
        :key="gIdx"
        class="bg-slate-900/40 border border-slate-800/80 rounded-3xl p-6 lg:p-8 backdrop-blur-sm"
      >
        <!-- Group Header -->
        <div class="flex items-center gap-3 mb-6 pb-4 border-b border-slate-800/80">
          <div class="w-2.5 h-6 rounded-full bg-gradient-to-b from-blue-500 to-indigo-500"></div>
          <div>
            <div class="flex items-center gap-2">
              <h3 class="text-xl font-black text-white tracking-tight">{{ group.group_name }}</h3>
              <!-- 教育優惠分級標記 -->
              <span
                v-if="group.group_name === '教育優惠'"
                class="flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 rounded-full"
              >
                <GraduationCap class="w-3 h-3" />
                台灣教育機構適用
              </span>
            </div>
            <p class="text-xs text-slate-400 mt-0.5">跨平台相同定位之方案對照</p>
          </div>
        </div>

        <!-- N-Column Comparison Grid (自動依平台數量決定欄數) -->
        <div
          class="grid gap-5"
          :class="orderedPlatforms.length <= 3
            ? 'grid-cols-1 md:grid-cols-3'
            : 'grid-cols-1 sm:grid-cols-2 lg:grid-cols-4'"
        >
          <div
            v-for="platform in orderedPlatforms"
            :key="platform.platform_id"
            class="flex flex-col justify-between bg-slate-950/70 border rounded-2xl p-5 transition-all hover:border-slate-700 relative overflow-hidden"
            :class="group.platformsInfo[platform.platform_id]?.plan
              ? 'border-slate-800'
              : 'border-slate-900 opacity-60 bg-slate-950/30'"
          >
            <!-- Platform Brand Pill -->
            <div class="flex items-center justify-between mb-4">
              <span
                class="px-2.5 py-1 text-xs font-bold rounded-lg border"
                :class="platformMetaMap[platform.platform_id]?.badge ?? DEFAULT_COLOR.badge"
              >
                {{ platformMetaMap[platform.platform_id]?.name ?? platform.platform_id }}
              </span>
              <span class="text-[11px] text-slate-500 font-medium">
                {{ platformMetaMap[platform.platform_id]?.vendor }}
              </span>
            </div>

            <!-- Content when plan exists -->
            <template v-if="group.platformsInfo[platform.platform_id]?.plan">
              <div class="space-y-4">
                <!-- Plan Title & Tax Badge -->
                <div>
                  <h4 class="text-base font-bold text-white leading-snug">
                    {{ group.platformsInfo[platform.platform_id].plan.plan_name }}
                  </h4>
                  <div class="flex items-center gap-2 mt-1.5 flex-wrap">
                    <span
                      class="px-2 py-0.5 text-[10px] font-semibold rounded-md flex items-center gap-1"
                      :class="group.platformsInfo[platform.platform_id].plan.tax_mode === 'tax_inclusive'
                        ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                        : 'bg-slate-800 text-slate-300'"
                    >
                      <Receipt class="w-2.5 h-2.5" />
                      {{ group.platformsInfo[platform.platform_id].plan.tax_mode === 'tax_inclusive' ? '含稅' : '未稅 / 依結帳' }}
                    </span>
                    <span
                      v-if="group.platformsInfo[platform.platform_id].price?.isAnnual"
                      class="px-1.5 py-0.5 text-[10px] font-bold bg-emerald-500/20 text-emerald-300 rounded"
                    >
                      年繳換算
                    </span>
                    <!-- 教育版標記 -->
                    <span
                      v-if="group.platformsInfo[platform.platform_id].plan.plan_type === 'education'"
                      class="flex items-center gap-0.5 px-1.5 py-0.5 text-[10px] font-bold bg-blue-500/10 text-blue-300 border border-blue-500/20 rounded"
                    >
                      <GraduationCap class="w-2.5 h-2.5" />
                      教育版
                    </span>
                  </div>
                </div>

                <!-- Price Block -->
                <div class="py-3 px-3.5 bg-slate-900/90 rounded-xl border border-slate-800/80">
                  <div class="flex items-baseline gap-1.5">
                    <span class="text-2xl font-black text-white tracking-tight">
                      {{ group.platformsInfo[platform.platform_id].price?.label }}
                    </span>
                    <span class="text-xs text-slate-400 font-medium">/ 月</span>
                  </div>
                  <div
                    v-if="group.platformsInfo[platform.platform_id].price?.approxTwd"
                    class="text-xs text-slate-400 mt-1"
                  >
                    ≈ NT$ {{ group.platformsInfo[platform.platform_id].price.approxTwd.toLocaleString() }} / 月
                  </div>
                </div>

                <!-- Features -->
                <div class="space-y-2 pt-2 border-t border-slate-800/60">
                  <span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">包含特色功能</span>
                  <ul class="space-y-2">
                    <li
                      v-for="(feat, fIdx) in group.platformsInfo[platform.platform_id].plan.features"
                      :key="fIdx"
                      class="flex items-start gap-2 text-xs text-slate-300 leading-relaxed"
                    >
                      <Check class="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
                      <span>{{ feat }}</span>
                    </li>
                  </ul>
                </div>
              </div>

              <!-- Action Buttons -->
              <div class="pt-5 mt-4 border-t border-slate-800/60 flex gap-2">
                <button
                  class="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 text-xs font-semibold text-slate-300 bg-slate-900 hover:bg-slate-800 hover:text-white border border-slate-800 rounded-xl transition"
                  @click="emit('openHistory', group.platformsInfo[platform.platform_id].plan)"
                >
                  <TrendingUp class="w-3.5 h-3.5 text-blue-400" />
                  <span>價格走勢</span>
                </button>
                <a
                  :href="platformMetaMap[platform.platform_id]?.official_url"
                  target="_blank"
                  rel="noopener noreferrer"
                  class="flex-1 flex items-center justify-center gap-1.5 py-2 px-3 text-xs font-semibold text-white bg-blue-600 hover:bg-blue-500 rounded-xl transition"
                >
                  <ExternalLink class="w-3.5 h-3.5" />
                  <span>前往官網</span>
                </a>
              </div>
            </template>

            <!-- No plan in this tier -->
            <template v-else>
              <div class="flex flex-col items-center justify-center py-12 text-slate-600 text-center space-y-2">
                <Minus class="w-6 h-6 text-slate-700" />
                <span class="text-xs font-medium">該品牌無此定位之方案</span>
              </div>
            </template>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>
