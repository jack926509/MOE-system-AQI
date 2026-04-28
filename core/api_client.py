"""環境部 OpenAPI v2 客戶端。"""
from __future__ import annotations

import logging
from typing import Any, Iterator

import httpx
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class Datasets:
    """環境部 DataID 常數。需用 verify_dataids.py 確認後修正。"""

    AQI_REALTIME = "aqx_p_432"        # 空氣品質指標(AQI) 即時
    AQI_FORECAST = "aqx_p_434"        # 空氣品質預報


class MoEnvAPIClient:
    """環境部 OpenAPI v2 同步客戶端，含分頁與 retry。"""

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://data.moenv.gov.tw/api/v2",
        page_size: int = 1000,
        timeout: float = 30.0,
        max_retries: int = 3,
    ) -> None:
        if not api_key:
            raise ValueError("MoEnvAPIClient requires non-empty api_key")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.page_size = page_size
        self.timeout = timeout
        self.max_retries = max_retries
        self._client = httpx.Client(timeout=timeout)

    def __enter__(self) -> "MoEnvAPIClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=16),
        retry=retry_if_exception_type((httpx.HTTPError, httpx.TimeoutException)),
        reraise=True,
    )
    def _get(self, dataset_id: str, params: dict[str, Any]) -> dict[str, Any]:
        url = f"{self.base_url}/{dataset_id}"
        merged = {"api_key": self.api_key, "format": "json", **params}
        resp = self._client.get(url, params=merged)
        resp.raise_for_status()
        return resp.json()

    def fetch_page(
        self,
        dataset_id: str,
        offset: int = 0,
        limit: int | None = None,
        **filters: Any,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "offset": offset,
            "limit": limit or self.page_size,
        }
        # filters 直接傳，例如 sort='publishtime desc' 或 filters={'fac_no,EQ,12345'}
        params.update(filters)
        return self._get(dataset_id, params)

    def fetch_all(
        self,
        dataset_id: str,
        max_records: int | None = None,
        **filters: Any,
    ) -> list[dict[str, Any]]:
        """自動分頁，回傳所有 records。"""
        all_records: list[dict[str, Any]] = []
        offset = 0
        while True:
            payload = self.fetch_page(
                dataset_id, offset=offset, limit=self.page_size, **filters
            )
            records = payload.get("records") or []
            if not records:
                break
            all_records.extend(records)
            logger.info(
                "fetch_all %s offset=%s got=%s total=%s",
                dataset_id,
                offset,
                len(records),
                len(all_records),
            )
            if len(records) < self.page_size:
                break
            if max_records is not None and len(all_records) >= max_records:
                all_records = all_records[:max_records]
                break
            offset += self.page_size
        return all_records

    def iter_all(
        self,
        dataset_id: str,
        **filters: Any,
    ) -> Iterator[dict[str, Any]]:
        """大資料集逐筆迭代版本。"""
        offset = 0
        while True:
            payload = self.fetch_page(
                dataset_id, offset=offset, limit=self.page_size, **filters
            )
            records = payload.get("records") or []
            if not records:
                break
            for r in records:
                yield r
            if len(records) < self.page_size:
                break
            offset += self.page_size
