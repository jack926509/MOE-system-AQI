# 系統 B：空氣品質即時監看 Telegram Bot — Claude Code 開發規格

> **給 Claude Code 的指示**：請依本文件從零建置完整可運行的 Python 專案。所有檔案結構、資料庫 schema、API 介接、Telegram Bot 指令、排程都已明確定義，請逐一實作並通過自我測試。

---

## 0. 專案目標

建立一個 Python Telegram Bot，每小時自動拉取環境部空氣品質開放資料，監看大潭電廠與台中發電廠周界 10 個空品測站，超過告警閾值時自動推播到 Telegram 群組，並提供互動式查詢指令。

**最終可執行檔**：
- `python scripts/init_db.py` — 初始化 SQLite
- `python -m system_b.etl` — 拉資料
- `python -m system_b.bot` — 啟動 Bot
- `python scripts/scheduler.py` — 自動化排程

---

## 1. 技術棧（嚴格遵守）

| 類別 | 套件 | 版本 |
|---|---|---|
| Python | python | 3.11+ |
| HTTP | requests | >=2.31 |
| 資料庫 | SQLAlchemy | >=2.0 |
| Telegram | python-telegram-bot | >=20.7 |
| 排程 | APScheduler | >=3.10 |
| 設定 | PyYAML | >=6.0 |
| 資料處理 | pandas | >=2.1 |

**不要引入**：Django、FastAPI、Redis、Celery、Docker（保持輕量）。

---

## 2. 目錄結構（必須完全照建）

```
system_b_air_quality/
├── README.md
├── requirements.txt
├── .gitignore
├── .env.example
├── config/
│   └── settings.example.yaml
├── core/
│   ├── __init__.py
│   ├── api_client.py        # 環境部 API 客戶端
│   ├── db.py                # SQLAlchemy 基礎
│   ├── config.py            # 設定載入
│   └── notifier.py          # Telegram 推播
├── system_b/
│   ├── __init__.py
│   ├── models.py            # AQIRecord、AlertLog
│   ├── etl.py               # AQI ETL
│   ├── alert.py             # 告警判定
│   ├── bot.py               # Telegram Bot 主程式
│   └── daily_report.py      # 每日空品摘要
├── scripts/
│   ├── init_db.py
│   └── scheduler.py
├── tests/
│   ├── test_api_client.py
│   ├── test_alert.py
│   └── test_etl.py
└── data/                    # 執行時建立，放 SQLite 檔
```

---

## 3. 環境部 API 規格

### 3.1 認證與基本資訊

- Base URL：`https://data.moenv.gov.tw/api/v2/`
- 認證：URL 參數 `api_key`（須使用者註冊取得，從 settings.yaml 讀）
- 資料格式：JSON / XML / CSV（本專案用 JSON）
- 單次最大回傳：10,000 筆
- 速率：未公告，但建議每次呼叫間隔 0.3 秒

### 3.2 本系統使用的資料集

| 用途 | DataID（小寫） | 更新頻率 | 主要欄位 |
|---|---|---|---|
| **空氣品質指標 AQI（主資料）** | `aqx_p_432` | 每小時 | siteid, sitename, county, aqi, pollutant, status, so2, co, o3, pm10, pm2.5, no2, nox, no, wind_speed, wind_direc, publishtime |
| 空氣品質預報 | `aqx_p_434` | 每 30 分 | content, area, publishtime, forecastdate, aqi, status, minorpollutant, minorpollutantaqi |
| 空品監測小時值（歷史） | `aqx_p_488` | 年度 QA 後 | siteid, sitename, itemname, monitordate, monitorvalue |

### 3.3 API 呼叫範例

```
GET https://data.moenv.gov.tw/api/v2/aqx_p_432?api_key=YOUR_KEY&limit=1000&offset=0&format=json
```

**Response 結構**：
```json
{
  "fields": [...],
  "resource_id": "aqx_p_432",
  "__extras": {...},
  "include_total": true,
  "total": 88,
  "records": [
    {
      "siteid": "1",
      "sitename": "基隆",
      "county": "基隆市",
      "aqi": "47",
      "pollutant": "",
      "status": "良好",
      "so2": "1.5",
      "co": "0.21",
      "o3": "31",
      "pm10": "26",
      "pm2.5": "11",
      "no2": "8",
      "nox": "10",
      "no": "2",
      "wind_speed": "2.4",
      "wind_direc": "63",
      "publishtime": "2026/04/28 10:00:00"
    }
  ]
}
```

### 3.4 注意事項（容易踩雷）

1. `pm2.5` 欄位名稱有「.」，Python dict access 需用 `rec["pm2.5"]`，ORM 欄位名要轉成 `pm2_5`。
2. 數值欄位回傳的是字串，可能是 `""`、`"-"`、`"x"`、`"ND"`，需安全轉 float。
3. `publishtime` 格式為 `"2026/04/28 10:00:00"`（斜線分隔）。
4. 環境部偶爾調整欄位，ETL 須用 `dict.get()` 避免 KeyError。

---

## 4. 資料庫 Schema

### 4.1 AQIRecord（空品紀錄）

```python
class AQIRecord(Base):
    __tablename__ = "aqi_records"

    id: int               # PK, autoincrement
    site_id: str(20)      # index
    site_name: str(50)    # index
    county: str(20)
    aqi: float | None
    pollutant: str(50)    # 主要污染物
    status: str(20)       # 良好/普通/...
    so2: float | None     # ppb
    co: float | None      # ppm
    o3: float | None      # ppb
    pm10: float | None    # μg/m³
    pm2_5: float | None   # μg/m³
    no2: float | None     # ppb
    nox: float | None     # ppb
    no: float | None      # ppb
    wind_speed: float | None  # m/s
    wind_direc: float | None  # 度
    publish_time: datetime    # index
    fetched_at: datetime      # default=now

    # 複合索引
    __table_args__ = (Index("ix_site_publish", "site_name", "publish_time"),)
```

**重複判定規則**：同 `site_name` + `publish_time` 視為同一筆，已存在則跳過。

### 4.2 AlertLog（告警紀錄）

```python
class AlertLog(Base):
    __tablename__ = "alert_logs"

    id: int
    plant_id: str(20)         # datan / taichung
    site_name: str(50)
    alert_type: str(20)       # warning / critical
    pollutant: str(20)        # AQI / PM2.5 / SO2 / NO2
    value: float
    threshold: float
    publish_time: datetime    # 用於去重
    notified_at: datetime
```

**去重規則**：同 `site_name` + `pollutant` + `publish_time` 已通報過則不重複推播。

---

## 5. 設定檔規格（config/settings.example.yaml）

```yaml
moenv:
  api_key: "YOUR_MOENV_API_KEY"
  base_url: "https://data.moenv.gov.tw/api/v2/"
  timeout: 30
  retry: 3

telegram:
  bot_token: "YOUR_BOT_TOKEN_FROM_BOTFATHER"
  chat_ids:
    daily_report: "-1001234567890"   # 日報群組
    alert: "-1001234567891"          # 告警群組
    admin: "123456789"               # 管理員私訊（除錯用）

database:
  path: "data/air_quality.db"

# 監看廠區
plants:
  - name: "大潭電廠"
    id: "datan"
    fac_no: "H0000000"
    location: { lat: 25.0461, lng: 121.1814 }
    nearby_stations: ["大園", "龍潭", "桃園", "中壢", "觀音"]

  - name: "台中發電廠"
    id: "taichung"
    fac_no: "B0000000"
    location: { lat: 24.2117, lng: 120.4953 }
    nearby_stations: ["沙鹿", "西屯", "忠明", "大里", "彰化"]

# 告警閾值
air_quality_alerts:
  aqi_warning: 100
  aqi_critical: 150
  pm25_warning: 35.4
  pm25_critical: 54.4
  so2_warning: 100
  no2_warning: 100

daily_report:
  time: "08:00"
  timezone: "Asia/Taipei"
```

---

## 6. 核心模組實作要點

### 6.1 core/api_client.py

```python
class MoEnvAPIClient:
    BASE_URL = "https://data.moenv.gov.tw/api/v2/"

    def __init__(self, api_key, base_url=None, timeout=30, retry=3):
        # requests.Session + Retry adapter
        # status_forcelist=[429, 500, 502, 503, 504]

    def fetch(self, dataset_id, limit=1000, offset=0, sort=None,
              filters=None, format="json", yyyy_mm=None) -> dict:
        # 單次呼叫，回傳 JSON dict
        # 注意 dataset_id 需轉小寫（環境部 URL 路徑要求）

    def fetch_all(self, dataset_id, page_size=1000, max_pages=100, **kwargs) -> list[dict]:
        # 自動分頁直到 records 為空或不滿 page_size
        # 每頁間 sleep 0.3 秒
```

### 6.2 core/db.py

```python
class Base(DeclarativeBase): pass

class Database:
    def __init__(self, db_path: str):
        # mkdir parents
        # create_engine with check_same_thread=False, timeout=30

    @contextmanager
    def session(self):
        # try/yield/commit, except/rollback, finally/close
```

### 6.3 core/notifier.py

```python
class TelegramNotifier:
    def __init__(self, bot_token: str): ...

    def send_message(self, chat_id, text, parse_mode="HTML",
                     disable_notification=False) -> bool:
        # POST https://api.telegram.org/bot{token}/sendMessage
        # text 截斷 4096 字元

    def send_document(self, chat_id, file_path, caption=None) -> bool: ...
```

### 6.4 system_b/etl.py

**邏輯**：

1. 載入設定，建立 API client
2. 從 settings.plants 收集所有 nearby_stations 做為過濾清單
3. 呼叫 `fetch_all("aqx_p_432", page_size=1000)`（全國資料一次拉完，約 88 站）
4. 過濾出監看測站
5. 解析 publishtime（格式 `"2026/04/28 10:00:00"`）
6. 重複檢查（site_name + publish_time）
7. 安全 float 轉換（處理 `""`, `"-"`, `"x"`, `"ND"`）
8. 寫入 SQLite
9. 回傳新增筆數

**安全 float 函式**：
```python
def parse_float(v) -> float | None:
    if v is None or v in ("", "-", "x", "ND", "N/A"):
        return None
    try:
        return float(v)
    except (ValueError, TypeError):
        return None
```

### 6.5 system_b/alert.py

**邏輯**：

1. 對每個 plant、每個 nearby_station，取最新一筆 AQIRecord
2. 跳過 publish_time < now - 2h 的舊資料
3. 比對閾值：AQI、PM2.5、SO2、NO2
4. AQI 與 PM2.5 有兩級（warning / critical）
5. 去重檢查：(site_name, pollutant, publish_time) 已通報過跳過
6. 推播 HTML 訊息到 alert chat_id
7. 寫入 AlertLog

**告警訊息格式**：
```
🔴 大潭電廠 周界空品告警

📍 測站：大園
💨 污染物：AQI = 165
⚠️ 閾值：150
🕐 時間：2026/04/28 10:00
狀態：對敏感族群不健康
```

Critical 用 🔴，Warning 用 🟡。

### 6.6 system_b/bot.py

**指令清單**（必須全實作）：

| 指令 | 函式 | 行為 |
|---|---|---|
| `/start` | cmd_start | 顯示歡迎訊息與指令清單 |
| `/help` | cmd_help | 同 /start |
| `/now` | cmd_now | 各廠周界即時空品總覽 |
| `/aqi <測站名>` | cmd_aqi | 單一測站完整資料 |
| `/trend <測站名>` | cmd_trend | 過去 24h 趨勢（最近 12 筆） |
| `/report` | cmd_report | 立即產生今日空品摘要 |

**AQI 顏色映射函式**（共用）：
```python
def aqi_color(aqi: float | None) -> str:
    if aqi is None: return "⚪"
    if aqi <= 50: return "🟢"
    if aqi <= 100: return "🟡"
    if aqi <= 150: return "🟠"
    if aqi <= 200: return "🔴"
    if aqi <= 300: return "🟣"
    return "🟤"
```

**`/now` 訊息格式範例**：
```
🌬️ 各廠周界即時空品

📍 大潭電廠
  🟢 大園：AQI=45 PM2.5=12
  🟡 龍潭：AQI=85 PM2.5=28
  🟢 桃園：AQI=42 PM2.5=10
  🟢 中壢：AQI=48 PM2.5=14
  🟢 觀音：AQI=38 PM2.5=9

📍 台中發電廠
  🟡 沙鹿：AQI=78 PM2.5=22
  🟢 西屯：AQI=55 PM2.5=18
  ...

更新：10:23
```

**`/aqi <測站名>` 訊息格式**：
```
🟡 大園 測站（桃園市）

AQI：85（普通）
主要污染物：PM2.5

PM2.5：28 μg/m³
PM10：45 μg/m³
SO₂：3.2 ppb
NO₂：12 ppb
O₃：38 ppb
CO：0.32 ppm

風速：2.4 m/s 風向：63°

2026/04/28 10:00
```

### 6.7 system_b/daily_report.py

**邏輯**：

1. 接受 target_date 參數，預設今天
2. 計算 [start, end) = [當天 00:00, 隔天 00:00)
3. 對每個 plant 的每個 station 做聚合查詢：
   - AVG(aqi), MAX(aqi)
   - AVG(pm2_5), MAX(pm2_5)
4. 撈當日所有 AlertLog
5. 組成 HTML 訊息回傳

**輸出格式**：
```
📊 2026/04/28 空品日報

📍 大潭電廠
  大園：AQI 均/峰 52/85，PM2.5 均/峰 18/35
  龍潭：AQI 均/峰 68/95，PM2.5 均/峰 25/45
  ...

📍 台中發電廠
  ...

⚠️ 今日告警 3 筆
  🟡 14:00 龍潭 AQI=110.5
  🟡 15:00 沙鹿 PM2.5=42.0
  🔴 16:00 大園 AQI=160.0
```

### 6.8 scripts/scheduler.py

使用 APScheduler `BlockingScheduler(timezone="Asia/Taipei")`：

| Job | 觸發時間 | 動作 |
|---|---|---|
| etl_and_alert | 每小時 :05 | fetch_and_store_aqi() + check_thresholds_and_alert() |
| daily_report | 每日 08:00 | generate_daily_report() + 推送到 daily_report 群組 |

每個 job 都要包 try/except，避免單次失敗中斷排程。

---

## 7. 測試規格（tests/）

### 7.1 test_api_client.py

- `test_parse_float_normal`：3.14 → 3.14
- `test_parse_float_dash`：`"-"` → None
- `test_parse_float_nd`：`"ND"` → None
- `test_parse_float_empty`：`""` → None
- `test_fetch_url_construction`：mock requests，驗證 URL 包含 api_key、limit、offset

### 7.2 test_alert.py

- `test_aqi_warning_triggered`：aqi=120 → warning
- `test_aqi_critical_triggered`：aqi=160 → critical
- `test_aqi_below_threshold`：aqi=80 → 無告警
- `test_dedup`：同站同時間第二次不重複推播

### 7.3 test_etl.py

- `test_filter_monitored_stations`：非監看測站不入庫
- `test_skip_duplicate`：同 site+publish_time 已存在則跳過
- `test_parse_publish_time`：`"2026/04/28 10:00:00"` → datetime

執行：`pytest tests/`

---

## 8. .gitignore

```
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
data/*.db
data/*.db-journal
config/settings.yaml
.env
*.log
.pytest_cache/
.coverage
.DS_Store
```

---

## 9. README.md 必含內容

1. 專案目的（一段話說明）
2. 系統架構圖（ASCII）
3. 安裝步驟
4. 設定檔填寫指引（特別是 Telegram Bot Token 取得方式）
5. 啟動指令（init_db → etl → bot → scheduler）
6. 排程說明
7. 故障排除（常見錯誤：API Key 錯誤、測站名打錯、Telegram chat_id 取得方式）

---

## 10. Claude Code 開發步驟（建議順序）

1. **先建目錄結構與設定檔**：建立所有資料夾、`requirements.txt`、`.gitignore`、`settings.example.yaml`
2. **實作 core 模組**：api_client → db → config → notifier，每個寫完跑語法檢查 `python -m py_compile`
3. **實作 system_b/models.py**：定義 ORM
4. **實作 system_b/etl.py**：先用 mock 資料測試，再接真 API
5. **寫 scripts/init_db.py**：執行確認 SQLite 檔正常建立
6. **實作 system_b/alert.py**：寫 unit test
7. **實作 system_b/bot.py**：手動測試每個指令
8. **實作 system_b/daily_report.py**
9. **實作 scripts/scheduler.py**
10. **寫測試**：tests/ 目錄完整覆蓋
11. **跑 pytest，全綠後寫 README**

---

## 11. 自我驗收清單

開發完成後，請確認以下指令都能正常運行：

```bash
# 1. 安裝
pip install -r requirements.txt

# 2. 設定
cp config/settings.example.yaml config/settings.yaml
# 編輯 settings.yaml

# 3. 初始化
python scripts/init_db.py
# 預期輸出：✅ 系統 B（空品）DB 初始化完成

# 4. 拉資料
python -m system_b.etl
# 預期輸出：取得 88 筆 AQI 資料、儲存 N 筆新紀錄

# 5. 測試告警（手動觸發）
python -m system_b.alert

# 6. 啟動 Bot
python -m system_b.bot
# 在 Telegram 測試 /now /aqi 大園 /trend 大園 /report

# 7. 跑測試
pytest tests/ -v
# 預期全綠

# 8. 啟動排程
python scripts/scheduler.py
# 預期輸出排程列表
```

---

## 12. 常見問題與解答（給 Claude Code 參考）

**Q1：DataID 大小寫問題？**
A：環境部新版 API URL 路徑是小寫（如 `aqx_p_432`），但官方文件常寫大寫。實作時統一在 `MoEnvAPIClient.fetch()` 內 `.lower()` 處理。

**Q2：python-telegram-bot v20 與舊版差異？**
A：v20 全面改為 async/await。所有 handler 函式都要 `async def`，回覆用 `await update.message.reply_text(...)`。

**Q3：APScheduler 時區問題？**
A：建立 scheduler 時必須指定 `timezone="Asia/Taipei"`，否則 cron 會用 UTC。

**Q4：SQLite 多執行緒？**
A：Bot（async）與 ETL（sync）不會同時寫入，但保險起見 engine 設 `check_same_thread=False, timeout=30`。

**Q5：fac_no 在系統 B 用不到？**
A：對，系統 B 只看 site_name。但 settings.yaml 仍保留 fac_no 欄位以便日後與系統 C 共用設定檔。

---

## 13. 交付物

1. 完整可運行的 Python 專案
2. README.md（包含截圖佔位）
3. 通過所有 pytest 測試
4. settings.example.yaml 含詳細註解
5. requirements.txt 鎖定版本

完成後請以指令 `tree -L 3 -I '__pycache__|*.pyc|venv|data'` 列出最終目錄結構作為驗收。
