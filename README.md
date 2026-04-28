# 環境部空品 Telegram Bot（8 區）

> 從環境部開放資料 API 取 88 站 AQI / 預報，每小時做站/區雙模告警，每日 08:00 推 8 區日報。
>
> 排程已對齊環境部官方公佈節奏：AQI 每小時 :15、預報每日 10:30 / 16:30 / 22:00、日報每日 08:00。

## 📂 目錄結構

```
MOE-system-AQI/
├── core/                   # 環境部 API client / DB / config / Telegram
├── system_b_air/           # 8 區 Bot：ETL、告警、日報、指令處理
├── scripts/                # init_db / verify_dataids / scheduler
├── tests/                  # 40 個 unit tests（core 11 + system_b 29）
├── config/settings.example.yaml
├── requirements.txt
└── pyproject.toml
```

## 🚀 快速啟動

```bash
# 0. 前置
cp config/settings.example.yaml config/settings.yaml
cp .env.example .env
# 編輯 .env 填 MOENV_API_KEY / TELEGRAM_BOT_TOKEN / chat_ids

# 1. 安裝
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 2. Day 0 驗證 DataID
python scripts/verify_dataids.py

# 3. 初始化 DB
python scripts/init_db.py

# 4. 跑首次 ETL
python -m system_b_air.etl_realtime
python -m system_b_air.etl_forecast

# 5. 啟動 Bot
python -m system_b_air.bot

# 6. 另開終端啟動排程
python scripts/scheduler.py

# 7. 測試
pytest tests/ -v
```

## 🌏 8 區劃分

| 區 | 縣市 |
|---|---|
| 北部 | 臺北、新北、基隆、桃園 |
| 竹苗 | 新竹市、新竹縣、苗栗 |
| 中部 | 臺中、彰化、南投 |
| 雲嘉南 | 雲林、嘉義市、嘉義縣、臺南 |
| 高屏 | 高雄、屏東 |
| 宜蘭 | 宜蘭 |
| 花東 | 花蓮、臺東 |
| 離島 | 澎湖、金門、連江 |

「臺/台」字會自動 normalize（`system_b_air/regions.py`）。

## 🤖 Bot 指令（共 8 個）

| 指令 | 說明 |
|---|---|
| `/start`、`/help` | 使用說明 |
| `/regions` | 列出 8 區 |
| `/now` | 各區即時最差站 |
| `/aqi <區或站>` | 指定區/站 AQI |
| `/trend <站> [hours]` | 近 N 小時趨勢（預設 24，上限 168） |
| `/forecast <區>` | 該區明日預報 |
| `/report` | 立即發 8 區日報 |

## 🔔 告警機制（雙模）

`config/settings.yaml` 的 `air_quality_alerts`：

- **站層級**：單站 AQI ≥ 150 或 PM2.5 ≥ 35.5 µg/m³ 等個別超標即發
- **區層級**：同小時內某區 ≥ 30% 站超標時發一則區域事件

`AlertLog` 表用 `(scope, target, pollutant, publish_time)` 去重，避免同小時重發。

## 📡 排程（scripts/scheduler.py）

時區一律 `Asia/Taipei`。對齊環境部官方資料節奏：

| Job | Trigger | 為什麼是這個時間 |
|---|---|---|
| AQI ETL + 告警 | hourly **`:15`** | `aqx_p_432` 每整點公佈 1 次，但 publishtime 上線常落在整點 +5～+15 分；`:15` 後抓最穩 |
| 預報 ETL | **10:30 / 16:30 / 22:00** | `aqx_p_434` 每日 3 次正式發布的時點（每天只跑 3 次，比每 30 分省 87% API 用量） |
| 8 區日報 | daily **08:00** | 早晨彙整前 24h |

- 啟動時會呼叫 Telegram `getMe` 驗證 token，並對 admin chat 推一則「scheduler 已啟動」訊息。
- 各 job 都包 `_safe()`，單次例外不會中止 scheduler。
- `Settings` / `Database` / `TelegramNotifier` 在啟動時建立一次並重用。

## ⚠️ 前置工作

### 1. 註冊環境部 API Key
- 申請：https://data.moenv.gov.tw/api_term
- 填到 `.env` 的 `MOENV_API_KEY`

### 2. Day 0 驗證 DataID
```bash
python scripts/verify_dataids.py
```
確認 `aqx_p_432`（即時）、`aqx_p_434`（預報）。如不正確至 [Swagger](https://data.moenv.gov.tw/swagger/) 查正確 ID 後改 `core/api_client.py` 的 `Datasets`。

### 3. 建立 Telegram Bot
- 對 `@BotFather` 發 `/newbot` 取得 Token
- 加入「空品日報」「空品告警」群組，從 `getUpdates` 取得 chat_id
- 填入 `.env` 的 `TELEGRAM_BOT_TOKEN` 與 `TELEGRAM_CHAT_ID_*`

## 🧪 測試

```bash
$ pytest tests/ -v
```

涵蓋：
- `core`：API client retry/分頁、Database 工廠、民國年/publishtime 解析、Telegram 訊息切分
- `system_b`：8 區 county→region 對應 + 臺台 normalize、ETL 寫入、雙模告警產生與 batch 去重、Bot helpers（`_fmt`、`_parse_hours`）

## ⚙️ 主要優化重點

- **Notifier**：4096 字訊息自動依換行切分；5xx / 連線錯誤指數退避；Telegram 429 依 `retry_after` 等待
- **Alert dedup**：原本「N 次 commit + 抓 IntegrityError」改為「單次 SELECT + bulk INSERT」，N+1 round-trip → 2 次
- **Daily report**：8 區改成單次 query + in-memory groupby（少 7 次 round-trip）
- **Bot**：所有 DB 與 `send_daily_report` 透過 `asyncio.to_thread` 不阻塞 event loop；HTML escape；保留 0 值（不再被誤顯示為 —）
- **ETL**：批次 INSERT 切 chunk(500) 避開 SQLite 變數上限
- **Scheduler**：例外保護 `_safe()` + 啟動時一次 load settings 重用
- **Telegram getMe**：scheduler 啟動時驗證 token 並推啟動訊息

## 部署於 Zeabur

- **Service 1**：`python -m system_b_air.bot`（Bot）
- **Service 2**：`python scripts/scheduler.py`（排程）
- 共掛同一個 Volume `/data`，存 `air_quality.db`
- 環境變數：`MOENV_API_KEY` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID_*` / `TZ=Asia/Taipei`
