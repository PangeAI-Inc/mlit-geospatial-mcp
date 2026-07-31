import requests

from utils.logger_config import setup_logger

# 外部API呼び出し共通処理

logger = setup_logger(__name__)


def get(
    url: str, params: dict = None, response_type: str = "json", headers: dict = None
):
    headers = headers or {"Accept": "*/*"}

    try:
        response = requests.get(url, headers=headers, params=params, verify=False)
        response.raise_for_status()

        if response_type in ("json", "geojson"):
            return response.json()
        # elif response_type:

    except Exception as e:
        # Keys only: the values carry the API key, and a dict inside an f-string is opaque to
        # the shared scrub, which only strips URL query strings.
        param_keys = sorted(params) if params else []
        logger.error(f"API呼び出し失敗 URL:{url} param_keys:{param_keys} エラー:{e}")
        #     空配列で処理継続
        return {"data": []}
