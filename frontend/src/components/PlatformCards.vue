<script setup>
import { ref, computed } from 'vue'
import { Check, TrendingUp, Receipt, ExternalLink, GraduationCap } from 'lucide-vue-next'

const props = defineProps({
  plans: {
    type: Array,
    default: () => []
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

const selectedPlatform = ref('all')

const filteredPlans = computed(() => {
  if (selectedPlatform.value === 'all') return props.plans
  return props.plans.filter(p => p.platform_id === selectedPlatform.value)
})

/**
 * 前端顏色主題對照表
 * 對應 platform_config.py 的 color_theme 欄位
 * 新增平台只需在此加一行（或直接復用已有顏色）
 */
const COLOR_MAP = {
  emerald: { badge: 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30', dot: 'bg-emerald-400' },
  amber:   { badge: 'bg-amber-500/10 text-amber-400 border-amber-500/30',       dot: 'bg-amber-400'   },
  blue:    { badge: 'bg-blue-500/10 text-blue-400 border-blue-500/30',           dot: 'bg-blue-400'    },
  purple:  { badge: 'bg-purple-500/10 text-purple-400 border-purple-500/30',     dot: 'bg-purple-400'  },
  rose:    { badge: 'bg-rose-500/10 text-rose-400 border-rose-500/30',           dot: 'bg-rose-400'    },
  indigo:  { badge: 'bg-indigo-500/10 text-indigo-400 border-indigo-500/30',     dot: 'bg-indigo-400'  },
  teal:    { badge: 'bg-teal-500/10 text-teal-400 border-teal-500/30',           dot: 'bg-teal-400'    },
}
const DEFAULT_COLOR = COLOR_MAP.blue

/**
 * 從 platforms prop 建立快速查找表（完全由 API 驅動）
 * { platform_id → { badge, dot, name, official_url } }
 */
const platformMetaMap = computed(() =>
  Object.fromEntries(
    props.platforms.map(p => [
      p.platform_id,
      {
        ...(COLOR_MAP[p.color_theme] ?? DEFAULT_COLOR),
        name: p.platform_name,
        official_url: p.official_url,
      }
    ])
  )
)

// 官方連結快速查找
const officialUrlMap = computed(() =>
  Object.fromEntries(props.platforms.map(p => [p.platform_id, p.official_url]))
)
</script>

<template>
  <div class="space-y-6">
    <!-- Platform Filter Tabs -->
    <div class="flex items-center gap-2 overflow-x-auto pb-2 scrollbar-none">
      <button
        class="px-4 py-2 text-xs font-bold rounded-xl transition whitespace-nowrap"
        :class="selectedPlatform === 'all'
          ? 'bg-blue-600 text-white shadow-md'
          : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'"
        @click="selectedPlatform = 'all'"
      >
        全部平台 ({{ plans.length }})
      </button>
      <button
        v-for="p in platforms"
        :key="p.platform_id"
        class="px-4 py-2 text-xs font-bold rounded-xl transition whitespace-nowrap"
        :class="selectedPlatform === p.platform_id
          ? 'bg-blue-600 text-white shadow-md'
          : 'bg-slate-900 text-slate-400 hover:text-white border border-slate-800'"
        @click="selectedPlatform = p.platform_id"
      >
        {{ p.platform_name }}
      </button>
    </div>

    <!-- Cards Grid -->
    <div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-6">
      <div
        v-for="plan in filteredPlans"
        :key="plan.id"
        class="flex flex-col justify-between bg-slate-900/60 border border-slate-800/90 hover:border-slate-700 rounded-3xl p-6 transition-all shadow-lg hover:shadow-xl relative overflow-hidden"
      >
        <!-- Top row: platform badge & tax -->
        <div class="flex items-center justify-between gap-2 mb-4">
          <div class="flex items-center gap-2">
            <span
              class="px-2.5 py-1 text-xs font-bold rounded-lg border"
              :class="platformMetaMap[plan.platform_id]?.badge ?? DEFAULT_COLOR.badge"
            >
              {{ platformMetaMap[plan.platform_id]?.name ?? plan.platform_id }}
            </span>
            <!-- 教育版標記 -->
            <span
              v-if="plan.plan_type === 'education'"
              class="flex items-center gap-1 px-2 py-0.5 text-[10px] font-bold bg-blue-500/10 text-blue-300 border border-blue-500/20 rounded-full"
            >
              <GraduationCap class="w-3 h-3" />
              教育版
            </span>
          </div>
          <span
            class="px-2 py-0.5 text-[10px] font-semibold rounded-md flex items-center gap-1"
            :class="plan.tax_mode === 'tax_inclusive'
              ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
              : 'bg-slate-800 text-slate-400'"
          >
            <Receipt class="w-2.5 h-2.5" />
            {{ plan.tax_mode === 'tax_inclusive' ? '含稅' : '未稅' }}
          </span>
        </div>

        <!-- Plan Name -->
        <h4 class="text-lg font-black text-white tracking-tight mb-3">
          {{ plan.plan_name }}
        </h4>

        <!-- Price Display -->
        <div class="p-4 bg-slate-950/80 rounded-2xl border border-slate-800/80 mb-5">
          <div class="flex items-baseline gap-1.5">
            <span class="text-3xl font-black text-white">
              {{ plan.currency }} ${{ (billingCycle === 'annual' && plan.annual_monthly_price
                ? plan.annual_monthly_price
                : plan.monthly_price).toLocaleString() }}
            </span>
            <span class="text-xs text-slate-400 font-medium">/ 月</span>
          </div>

          <!-- Approx TWD for USD -->
          <div v-if="plan.currency === 'USD' && plan.monthly_price > 0" class="text-xs text-slate-400 mt-1">
            ≈ NT$ {{ Math.round((billingCycle === 'annual' && plan.annual_monthly_price
              ? plan.annual_monthly_price
              : plan.monthly_price) * usdRate).toLocaleString() }} / 月
          </div>

          <!-- Annual note -->
          <div v-if="plan.annual_price" class="text-[11px] text-emerald-400 mt-2 font-medium">
            年繳方案總額: {{ plan.currency }} ${{ plan.annual_price.toLocaleString() }}
          </div>
        </div>

        <!-- Features -->
        <div class="space-y-2.5 flex-1 mb-6">
          <span class="text-[11px] font-bold text-slate-400 uppercase tracking-wider">方案特色</span>
          <ul class="space-y-2">
            <li
              v-for="(feat, fIdx) in plan.features"
              :key="fIdx"
              class="flex items-start gap-2 text-xs text-slate-300 leading-relaxed"
            >
              <Check class="w-3.5 h-3.5 text-blue-400 shrink-0 mt-0.5" />
              <span>{{ feat }}</span>
            </li>
          </ul>
        </div>

        <!-- Footer Actions: 走勢 + 官方購買 -->
        <div class="pt-4 border-t border-slate-800/80 flex gap-2">
          <button
            class="group flex-1 flex items-center justify-center gap-2 py-2.5 px-3 text-xs font-bold text-slate-300 bg-slate-800 hover:bg-slate-700 rounded-xl transition shadow"
            @click="emit('openHistory', plan)"
          >
            <TrendingUp class="w-4 h-4 text-blue-400 group-hover:text-white transition" />
            <span>價格走勢</span>
          </button>
          <a
            :href="officialUrlMap[plan.platform_id]"
            target="_blank"
            rel="noopener noreferrer"
            class="flex-1 flex items-center justify-center gap-2 py-2.5 px-3 text-xs font-bold text-white bg-blue-600 hover:bg-blue-500 rounded-xl transition shadow"
          >
            <ExternalLink class="w-4 h-4" />
            <span>前往官網</span>
          </a>
        </div>
      </div>
    </div>
  </div>
</template>
