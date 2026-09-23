"""
各平台爬蟲端點與元資料設定 — 單一資訊來源 (Single Source of Truth)

新增平台只需在 PLATFORMS 加一個 dict 區塊：
  1. 填寫 name / vendor / color_theme / crawler_module / official_pricing_url
  2. 建立 crawlers/{platform_id}_crawler.py
  3. 不需要修改其他任何檔案 (CRAWLER_MAP、COMPARE_GROUPS 皆自動生成)
"""

# 比價矩陣分級顯示順序
TIER_ORDER = [
    "免費方案",
    "個人入門",
    "個人進階",
    "個人旗艦",
    "頂級旗艦",
    "團隊方案",
    "企業方案",
    "教育優惠",   # 僅台灣教育機構適用
]

PLATFORMS = {
    "chatgpt": {
        "name": "ChatGPT",
        "vendor": "OpenAI",
        # 前端 Tailwind 顏色主題 (對應 frontend COLOR_MAP)
        "color_theme": "emerald",
        # 爬蟲類別名稱 (crawlers/__init__.py 需匯出)
        "crawler_module": "ChatGPTPricingCrawler",
        # URL 設定
        "base_url": "https://chatgpt.com",
        "pricing_api": "https://chatgpt.com/backend-anon/checkout_pricing_config/configs/{country_code}",
        "official_pricing_url": "https://chatgpt.com/pricing",
        # plan_id → 比價矩陣分級 (教育版 plan_id 由爬蟲解析後自動分類)
        "compare_tiers": {
            "free":                 "免費方案",
            "go":                   "個人入門",
            "plus":                 "個人進階",
            "prolite":              "個人旗艦",
            "pro":                  "頂級旗艦",
            "business":             "團隊方案",
            "business_prolite":     "企業方案",
            "business_non_profit":  "企業方案",
            # 台灣教育版 (plan_type = 'education')，若官方 API 有回傳即自動歸類
            "plus_edu":             "教育優惠",
            "team_edu":             "教育優惠",
            "edu":                  "教育優惠",
        },
    },

    "gemini": {
        "name": "Gemini (Google One AI)",
        "vendor": "Google",
        "color_theme": "blue",
        "crawler_module": "GeminiPricingCrawler",
        "plans_url": "https://one.google.com/intl/zh-TW_{country_code}/about/google-ai-plans/",
        "feed_url_template": "https://one.google.com/intl/ALL_{country_code}/about/feeds/{filename}",
        "official_pricing_url": "https://one.google.com/intl/zh-TW_tw/about/google-ai-plans/",
        "compare_tiers": {
            "free":           "免費方案",
            "ai_plus":        "個人入門",
            "ai_pro":         "個人進階",
            "ai_ultra_100":   "個人旗艦",
            "ai_ultra_200":   "頂級旗艦",
            # Google AI 台灣學生教育方案
            "ai_pro_edu":     "教育優惠",   # AI Pro 學生版 NT$160/月
            "ai_pro_edu_yt":  "教育優惠",   # AI Pro + YouTube Premium 學生版 NT$250/月
        },
    },

    "claude": {
        "name": "Claude",
        "vendor": "Anthropic",
        "color_theme": "amber",
        "crawler_module": "ClaudePricingCrawler",
        "pricing_url": "https://www.anthropic.com/pricing",
        "official_pricing_url": "https://www.anthropic.com/pricing",
        "compare_tiers": {
            "free":           "免費方案",
            "pro":            "個人進階",
            "max":            "個人旗艦",
            "team_standard":  "團隊方案",
            "team_premium":   "團隊方案",
            "enterprise":     "企業方案",
            # Claude 台灣教育版 (預留)
            "pro_edu":        "教育優惠",
            "team_edu":       "教育優惠",
        },
    },

    "perplexity": {
        "name": "Perplexity AI",
        "vendor": "Perplexity",
        "color_theme": "purple",
        "crawler_module": "PerplexityPricingCrawler",
        "pricing_url": "https://www.perplexity.ai/pro",
        "official_pricing_url": "https://www.perplexity.ai/pro",
        "compare_tiers": {
            "free":           "免費方案",
            "pro":            "個人進階",
            "max":            "個人旗艦",
            "pro_edu":        "教育優惠",   # plan_type = 'education'，台灣教育機構 $10/月
            "enterprise_pro": "企業方案",
            "enterprise_max": "企業方案",
        },
    },
}
