# 環境部空品 Telegram Bot（8 區）

> 從環境部開放資料 API 取 88 站 AQI / 預報，每小時做站/區雙模告警，每日 08:00 推 8 區日報。

## 📂 目錄結構

```
MOE-system-AQI/
├── core/                   # 環境部 API client / DB / config / Telegram
├── system_b_air/           # 8 區 Bot：ETL、告警、日報、指令處理
├── scripts/                # init_db / verify_dataids / scheduler
├── tests/                  # 22 個 unit tests（core 4 + system_b 18）
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
| `/trend <站> [hours]` | 24h 趨勢（預設 24） |
| `/forecast [區]` | 明日預報 |
| `/report` | 立即發 8 區日報 |

## 🔔 告警機制（雙模）

`config/settings.yaml` 的 `air_quality_alerts`：

- **站層級**：單站 AQI ≥ 150 或 PM2.5 ≥ 35.5 µg/m³ 等個別超標即發
- **區層級**：同小時內某區 ≥ 30% 站超標時發一則區域事件

`AlertLog` 表用 `(scope, target, pollutant, publish_time)` 去重，避免同小時重發。

## 📡 排程（scripts/scheduler.py）

| Job | Trigger |
|---|---|
| AQI ETL + 告警 | hourly :05 |
| 預報 ETL | every 30 min |
| 8 區日報 | daily 08:00 (Asia/Taipei) |

啟動時呼叫 Telegram `getMe` 驗證 token，並對 admin chat 發一則啟動訊息。

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
- `core`：API client retry/分頁、Database 工廠、民國年/publishtime 解析
- `system_b`：8 區 county→region 對應 + 臺台 normalize、ETL 寫入、雙模告警產生與去重

## 部署於 Zeabur

- **Service 1**：`python -m system_b_air.bot`（Bot）
- **Service 2**：`python scripts/scheduler.py`（排程）
- 共掛同一個 Volume `/data`，存 `air_quality.db`
- 環境變數：`MOENV_API_KEY` / `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID_*` / `TZ=Asia/Taipei`
