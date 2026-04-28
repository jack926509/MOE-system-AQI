"""Day 0 必跑：呼叫 AQI DataID 印 fields，確認可用。

用法：
    python scripts/verify_dataids.py
"""
from __future__ import annotations

import logging
import sys

from core import Datasets, MoEnvAPIClient, load_settings

logging.basicConfig(level=logging.INFO, format="%(message)s")
logger = logging.getLogger(__name__)


TARGETS = [
    ("AQI 即時", Datasets.AQI_REALTIME),
    ("AQI 預報", Datasets.AQI_FORECAST),
]


def main() -> int:
    settings = load_settings()
    if not settings.moenv.api_key:
        logger.error("settings.moenv.api_key 為空，請先填 .env 或 settings.yaml")
        return 1

    client = MoEnvAPIClient(
        api_key=settings.moenv.api_key,
        base_url=settings.moenv.base_url,
        page_size=1,
        timeout=settings.moenv.timeout,
        max_retries=settings.moenv.max_retries,
    )
    failures: list[str] = []
    with client:
        for label, dataset_id in TARGETS:
            print(f"\n=== {label}：{dataset_id} ===")
            try:
                payload = client.fetch_page(dataset_id, offset=0, limit=1)
            except Exception as e:
                print(f"  ✗ 失敗：{e}")
                failures.append(dataset_id)
                continue
            total = payload.get("total")
            records = payload.get("records") or []
            print(f"  total={total} returned={len(records)}")
            if not records:
                print("  ⚠ 回傳 0 筆，DataID 可能存在但無資料；fields 不可得")
                failures.append(dataset_id)
                continue
            sample = records[0]
            print(f"  ✓ 回傳 1 筆，欄位 ({len(sample)}):")
            for k in sample:
                v = sample[k]
                preview = str(v)[:40] if v is not None else "<null>"
                print(f"    - {k}: {preview}")

    print("\n=== Summary ===")
    if failures:
        print(f"✗ {len(failures)} 個 DataID 需重新確認：{', '.join(failures)}")
        print("  請至 https://data.moenv.gov.tw/swagger/ 找正確 ID 後修正 core/api_client.py")
        return 1
    print("✓ 全部通過")
    return 0


if __name__ == "__main__":
    sys.exit(main())
