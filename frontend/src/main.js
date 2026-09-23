import { createApp } from 'vue'
import { Chart, registerables } from 'chart.js'
import App from './App.vue'
import './assets/main.css'

// 全域只註冊一次，避免 HistoryModal 每次 import 重複執行
Chart.register(...registerables)

createApp(App).mount('#app')
