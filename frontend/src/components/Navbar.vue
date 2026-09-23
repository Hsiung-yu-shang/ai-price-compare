<script setup>
import { Sparkles, LayoutGrid, Columns } from 'lucide-vue-next'

const props = defineProps({
  viewMode: {
    type: String,
    default: 'matrix'
  },
  country: {
    type: String,
    default: 'TW'
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

const emit = defineEmits([
  'update:viewMode',
  'update:country',
  'update:billingCycle'
])
</script>

<template>
  <header class="sticky top-0 z-40 w-full border-b border-slate-800 bg-slate-950/80 backdrop-blur-xl">
    <div class="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
      <div class="flex items-center justify-between h-16 gap-4">
        <!-- Logo & Title -->
        <div class="flex items-center gap-3">
          <div class="flex items-center justify-center w-10 h-10 rounded-xl bg-gradient-to-tr from-blue-600 to-indigo-500 text-white shadow-lg shadow-blue-500/25">
            <Sparkles class="w-5 h-5" />
          </div>
          <div>
            <div class="flex items-center gap-2">
              <h1 class="text-base sm:text-lg font-black tracking-tight text-white">
                AI 方案比價
              </h1>
              <span class="px-2 py-0.5 text-[10px] font-bold bg-blue-500/10 text-blue-400 border border-blue-500/20 rounded-full">
                即時同步
              </span>
            </div>
            <p class="hidden sm:block text-xs text-slate-400">
              ChatGPT、Claude、Gemini、Perplexity 官方最新定價
            </p>
          </div>
        </div>

        <!-- Controls Toolbar -->
        <div class="flex items-center gap-2 sm:gap-3">
          <!-- View Mode Toggle -->
          <div class="flex p-1 bg-slate-900 border border-slate-800 rounded-xl">
            <button
              class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition"
              :class="viewMode === 'matrix' ? 'bg-blue-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              @click="emit('update:viewMode', 'matrix')"
              title="矩陣比價模式"
            >
              <Columns class="w-3.5 h-3.5" />
              <span class="hidden md:inline">比價矩陣</span>
            </button>
            <button
              class="flex items-center gap-1.5 px-3 py-1.5 text-xs font-semibold rounded-lg transition"
              :class="viewMode === 'cards' ? 'bg-blue-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              @click="emit('update:viewMode', 'cards')"
              title="品牌方案卡片模式"
            >
              <LayoutGrid class="w-3.5 h-3.5" />
              <span class="hidden md:inline">方案總覽</span>
            </button>
          </div>

          <!-- Billing Cycle Toggle (Monthly / Annual) -->
          <div class="flex p-1 bg-slate-900 border border-slate-800 rounded-xl">
            <button
              class="px-3 py-1.5 text-xs font-semibold rounded-lg transition"
              :class="billingCycle === 'monthly' ? 'bg-slate-800 text-white' : 'text-slate-400 hover:text-slate-200'"
              @click="emit('update:billingCycle', 'monthly')"
            >
              月繳
            </button>
            <button
              class="flex items-center gap-1 px-3 py-1.5 text-xs font-semibold rounded-lg transition"
              :class="billingCycle === 'annual' ? 'bg-emerald-600 text-white shadow' : 'text-slate-400 hover:text-slate-200'"
              @click="emit('update:billingCycle', 'annual')"
            >
              <span>年繳</span>
              <span class="text-[9px] px-1 py-0.2 bg-emerald-400/20 text-emerald-300 rounded font-bold">優惠</span>
            </button>
          </div>

        </div>
      </div>
    </div>
  </header>
</template>
