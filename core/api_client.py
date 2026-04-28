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

    AQI_REALTIME = "aqx_p_432"        # 空氣品質指標(AQI) 即時，每小時
    AQI_FORECAST = "aqf_p_01"         # 空氣品質預報，每日 10:30/16:30/22:00 發布


class _Retryable(Exception):
    """內部 marker：給 tenacity 用，標示「值得重試」的錯誤。"""


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
        self.max_retries = max(1, int(max_retries))
        self._client = httpx.Client(
            timeout=timeout,
            headers={"User-Agent": "moe-system-aqi/1.0"},
        )

    def __enter__(self) -> "MoEnvAPIClient":
        return self

    def __exit__(self, *exc: Any) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def _do_get(self, dataset_id: str, params: dict[str, Any]) -> dict[str, Any]:
        # 環境部 v2 路徑要求小寫
        path = dataset_id.lower()
        url = f"{self.base_url}/{path}"
        merged = {"api_key": self.api_key, "format": "json", **params}
        try:
            resp = self._client.get(url, params=merged)
        except httpx.TimeoutException as e:
            logger.warning("MoEnv %s timeout: %s", path, e)
            raise _Retryable(str(e)) from e
        except httpx.TransportError as e:
            logger.warning("MoEnv %s transport error: %s", path, e)
            raise _Retryable(str(e)) from e

        sc = resp.status_code
        if sc >= 500:
            logger.warning("MoEnv %s 5xx %s", path, sc)
            raise _Retryable(f"{sc} from {path}")
        if sc == 429:
            logger.warning("MoEnv %s 429 rate limit", path)
            raise _Retryable("429 rate limit")
        if 400 <= sc < 500:
            # 401 / 403 / 404：通常是 api_key 或 dataset id 錯，重試無益
            body_preview = resp.text[:200].replace("\n", " ")
            raise httpx.HTTPStatusError(
                f"MoEnv {path} {sc}: {body_preview}",
                request=resp.request,
                response=resp,
            )

        try:
            return resp.json()
        except ValueError as e:
            preview = resp.text[:200].replace("\n", " ")
            raise RuntimeError(
                f"MoEnv {path} 回應非 JSON：{preview}"
            ) from e

    def _get(self, dataset_id: str, params: dict[str, Any]) -> dict[str, Any]:
        @retry(
            stop=stop_after_attempt(self.max_retries),
            wait=wait_exponential(multiplier=1, min=2, max=16),
            retry=retry_if_exception_type(_Retryable),
            reraise=True,
        )
        def _call() -> dict[str, Any]:
            return self._do_get(dataset_id, params)

        try:
            return _call()
        except _Retryable as e:
            raise RuntimeError(
                f"MoEnv {dataset_id} 重試 {self.max_retries} 次後仍失敗：{e}"
            ) from e

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
        first_total: int | None = None
        while True:
            payload = self.fetch_page(
                dataset_id, offset=offset, limit=self.page_size, **filters
            )
            records = payload.get("records") or []
            if first_total is None:
                first_total = payload.get("total")
                logger.info(
                    "fetch_all %s total=%s first_page=%d",
                    dataset_id, first_total, len(records),
                )
            if not records:
                if offset == 0:
                    logger.warning(
                        "fetch_all %s 第一頁回傳 0 筆 (total=%s)；"
                        "請以 verify_dataids.py 檢查 DataID 與 api_key",
                        dataset_id, first_total,
                    )
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
