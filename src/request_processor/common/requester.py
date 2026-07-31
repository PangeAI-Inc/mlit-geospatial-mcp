import re

import requests

from utils.logger_config import setup_logger

# 外部API呼び出し共通処理

logger = setup_logger(__name__)

# requests/urllib3 echo the full request URL, query string included, inside their own
# exception text (e.g. connection errors, HTTPError from raise_for_status), so the API
# key leaks there too even once we stop logging `params` ourselves.
_QUERY_STRING_RE = re.compile(r"\?\S+")


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
        param_keys = sorted(params) if params else []
        safe_error = _QUERY_STRING_RE.sub("?[Redacted]", str(e))
        logger.error(f"API呼び出し失敗 URL:{url} param_keys:{param_keys} エラー:{safe_error}")
        #     空配列で処理継続
        return {"data": []}
