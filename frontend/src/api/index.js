/**
 * API client module calling FastAPI endpoints
 * Dev:  /api  (由 Vite proxy 轉發到 localhost:8000)
 * Prod: /api  (與 FastAPI 同網域、同連接埠)
 */

const BASE_URL = (import.meta.env.VITE_API_BASE_URL ?? '/api')

/**
 * 解析 HTTP 錯誤，優先回傳後端 detail 訊息
 */
async function parseError(res, fallback) {
  try {
    const body = await res.json()
    return new Error(body.detail || `${fallback} (HTTP ${res.status})`)
  } catch {
    return new Error(`${fallback} (HTTP ${res.status})`)
  }
}

export async function fetchPlatforms() {
  const res = await fetch(`${BASE_URL}/platforms`)
  if (!res.ok) throw await parseError(res, '取得平台列表失敗')
  return res.json()
}

export async function fetchPlans(params = {}) {
  const query = new URLSearchParams()
  if (params.platform) query.append('platform', params.platform)
  if (params.country) query.append('country', params.country)

  const res = await fetch(`${BASE_URL}/plans?${query.toString()}`)
  if (!res.ok) throw await parseError(res, '取得方案列表失敗')
  return res.json()
}

export async function fetchCompareMatrix(country = 'TW') {
  const res = await fetch(`${BASE_URL}/compare?country=${encodeURIComponent(country)}`)
  if (!res.ok) throw await parseError(res, '取得比價矩陣失敗')
  return res.json()
}

export async function fetchPlanHistory(planDbId) {
  const res = await fetch(`${BASE_URL}/plans/${planDbId}/history`)
  if (!res.ok) throw await parseError(res, '取得價格歷史失敗')
  return res.json()
}
