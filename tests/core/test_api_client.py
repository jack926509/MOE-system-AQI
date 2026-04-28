import respx
from httpx import Response

from core.api_client import MoEnvAPIClient


@respx.mock
def test_fetch_page():
    route = respx.get("https://data.moenv.gov.tw/api/v2/aqx_p_432").mock(
        return_value=Response(200, json={"records": [{"sitename": "中山"}]})
    )
    with MoEnvAPIClient(api_key="x", page_size=1) as c:
        payload = c.fetch_page("aqx_p_432", offset=0, limit=1)
    assert route.called
    assert payload["records"][0]["sitename"] == "中山"


@respx.mock
def test_fetch_all_pagination():
    page_size = 2

    def respond(request):
        offset = int(request.url.params.get("offset", "0"))
        # 4 筆共 2 頁
        all_data = [{"i": i} for i in range(4)]
        slice_ = all_data[offset:offset + page_size]
        return Response(200, json={"records": slice_})

    respx.get("https://data.moenv.gov.tw/api/v2/foo").mock(side_effect=respond)
    with MoEnvAPIClient(api_key="x", page_size=page_size) as c:
        rows = c.fetch_all("foo")
    assert len(rows) == 4


def test_requires_api_key():
    import pytest
    with pytest.raises(ValueError):
        MoEnvAPIClient(api_key="")
