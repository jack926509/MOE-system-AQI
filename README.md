# 環境部開放資料三系統 — Claude Code 開發 Spec 總覽

> 三份獨立的開發規格文件，每份都是**給 Claude Code 一次到位執行的完整 spec**。

## 📦 三份 Spec

| 系統 | 檔名 | 估計工時 | 技術棧重點 |
|---|---|---|---|
| **B** | `系統B_空品Bot_開發規格.md` | 5–7 天 | Python + python-telegram-bot + APScheduler |
| **C** | `系統C_排放清冊儀表板_開發規格.md` | 11 天 | FastAPI + Next.js 14 + shadcn/ui + Recharts |
| **D** | `系統D_環評查詢_開發規格.md` | 8 天 | FastAPI + Whoosh + jieba + Jinja2 |

---

## 🎯 Claude Code 使用建議

### 方法 1：一次開一個系統的 repo（推薦）

每個系統各自一個 repo，互不影響：

```bash
# 三個獨立 repo
mkdir moenv-air-bot && cd moenv-air-bot
claude-code --spec ../系統B_空品Bot_開發規格.md

mkdir ../moenv-emission-dashboard && cd ../moenv-emission-dashboard
claude-code --spec ../系統C_排放清冊儀表板_開發規格.md

mkdir ../moenv-eia-search && cd ../moenv-eia-search
claude-code --spec ../系統D_環評查詢_開發規格.md
```

### 方法 2：monorepo（共用 core）

若想共享 `core/` 模組，可在同一個 repo 下開三個子目錄：

```
moenv-platform/
├── core/                 # 共用底層
├── system_b_air/
├── system_c_emission/
└── system_d_eia/
```

→ 將每份 spec 中的 `core/` 部分省略，只實作各系統的業務模組。

---

## 🚀 建議開發順序

依優先級：

1. **B 先做**（5–7 天）：最快出成果、立刻有可用的 Telegram Bot 監看廠界
2. **C 後端先做**（4 天）：API 跑起來，先用 curl/Postman 用，公文佐證匯出可立即上線
3. **D 全部**（8 天）：D 較獨立，可平行進行
4. **C 前端最後**（5–7 天）：等 API 穩定後再做前端

---

## ⚠️ 三系統共用的關鍵前置工作

無論先做哪一個，這些事**必須先處理**：

### 1. 註冊環境部 API Key

- 網址：https://data.moenv.gov.tw/api_term
- 註冊會員後寄到信箱
- 系統 B、C、D 都用同一把 Key

### 2. 確認大潭、台中電廠的 fac_no

- **這是系統 C 最大風險點**
- 建議寫一支小腳本先撈：

```python
# 暫用腳本：從 TEDS 找到自家 fac_no
from core import MoEnvAPIClient
client = MoEnvAPIClient(api_key="xxx")
records = client.fetch_all("aqx_p_07")  # TEDS 固定源
candidates = [r for r in records if "大潭" in r.get("fac_name", "")
                                  or "台中" in r.get("fac_name", "")]
for c in candidates:
    print(c["fac_no"], c["fac_name"], c.get("county"))
```

### 3. 建立 Telegram Bot

- 在 Telegram 對 `@BotFather` 說 `/newbot` 取得 Token
- 建立兩個群組：「空品日報」「空品告警」
- 將 Bot 加入群組
- 取得 chat_id（用 `https://api.telegram.org/bot<TOKEN>/getUpdates`）

### 4. 從 Swagger 確認真實 DataID

- 環境部 Swagger：https://data.moenv.gov.tw/swagger/
- spec 中提供的 DataID（如 `aqx_p_24`、`eiap_p_01`）為**估計值**
- 開發前用 swagger 介面確認 CEMS、TEDS、許可、裁處、環評相關的真實 DataID
- 把確認後的 DataID 填回 `core/api_client.py` 的 `Datasets` 常數

---

## 📋 三系統共用元件清單

每份 spec 都包含 `core/` 模組，內容相同：

```
core/
├── api_client.py    # 環境部 API 封裝（含分頁、重試）
├── db.py            # SQLAlchemy 基礎
├── config.py        # 設定載入
└── notifier.py      # Telegram 推播（系統 B 主用，C、D 可選）
```

如果走 monorepo，這部分只要寫一次。

---

## 🔍 驗收方式（給 Claude Code）

每份 spec 末尾都有「自我驗收清單」，建議在 Claude Code 完成後逐項勾選確認。

關鍵驗收點：

| 系統 | 最終驗收 |
|---|---|
| B | `python -m system_b.bot` 啟動後，Telegram 中 `/now` 能即時返回各廠數值 |
| C | `npm run build` 通過 + `curl /api/cems/latest` 回傳資料 + 公文佐證 Excel 能下載開啟 |
| D | 在 HTML 介面搜尋「燃氣」能返回相關環評案件 + `/api/eia/conclusion-keywords?industry=電力` 回傳關鍵字陣列 |

---

## 📝 spec 設計原則

每份 spec 都遵守以下原則，方便 Claude Code 一次到位：

1. **明確的目錄結構**：每個檔案都列出，避免 Claude 自己決定架構
2. **完整的 schema 定義**：所有 ORM 模型欄位都明列
3. **API 端點完整列表**：包含 query params、response 格式
4. **重要實作細節獨立列出**：避免踩到日期格式、欄位名稱等坑
5. **不要做的事**：列出禁區，避免過度設計
6. **自我驗收清單**：明確驗收標準
7. **常見問題**：預先解答容易卡住的點

---

## 🛠 各系統獨立性

三個系統可完全獨立部署：

| 系統 | 端口 | DB | 是否依賴他系統 |
|---|---|---|---|
| B | Telegram（無端口） | data/air_quality.db | 無 |
| C | 8000 | data/emission.db | 無 |
| D | 8001 | data/eia.db | 無 |

只有「共用 settings.yaml」是選擇性整合，可以三系統各自一份設定檔。

---

## 💡 給 Claude Code 的提示

在開始任何系統前，建議先給 Claude Code 這段 prompt：

```
請閱讀 spec 檔案，並在開始實作前回答：
1. 你計劃用哪些套件（含版本）？
2. 目錄結構是否與 spec 完全一致？
3. 你是否有計畫偏離 spec 的地方？為什麼？
4. 預計總共需要產生多少檔案？
等我確認後再開始實作。
```

這樣可以避免 Claude Code 偷偷改架構或加無關套件。

---

## 📞 部署後支援

部署完成後，常見維運場景：

- **環境部 API 回傳格式變動** → 改 ETL 的 `parse_*` 函式
- **新增監看廠區** → 編輯 `settings.yaml` 的 `plants` 區塊，重啟服務
- **告警閾值調整** → 編輯 `settings.yaml` 的 `air_quality_alerts`，重啟 alert 排程
- **新增 Telegram 群組** → 編輯 `chat_ids` 即可

---

## ❓ 為什麼三系統不寫成同一份 spec？

有意分開，原因：

1. **Claude Code 上下文限制**：單一份規格塞進三系統會超出 context window 上限
2. **獨立部署彈性**：三系統可在不同主機、不同時程上線
3. **獨立技術棧**：B 是 Bot、C 是全端 Web、D 是 HTML，三套技術棧差異大
4. **開發節奏**：可平行交給不同人或不同時段開發

但所有三份共用一致的 `core/` 模組設計與 `settings.yaml` 結構，整合時無痛。
