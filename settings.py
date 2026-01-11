import os
import re
from dataclasses import dataclass
from typing import Any


DEFAULT_HEADERS = {
    "accept": "application/json, text/plain, */*",
    "accept-language": "zh-CN,zh;q=0.9,en;q=0.8,en-GB;q=0.7,en-US;q=0.6,ko;q=0.5",
    "baggage": "sentry-environment=production,sentry-release=dev-1730698697208,sentry-public_key=ed67ed71f7804a038e898ba54bd66e44,sentry-trace_id=1ff5a0725f8841088b42f97109c45862",
    "user-agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36 Edg/131.0.0.0",
}

DEFAULT_COOKIES = {
    "RK": "oxEY1bTnXf",
    "ptcz": "53e3b35a9486dd63c4d06430b05aa169402117fc407dc5cc9329b41e59f62e2b",
    "pac_uid": "0_e63870bcecc18",
    "iip": "0",
    "_qimei_uuid42": "183070d3135100ee797b08bc922054dc3062834291",
    "wr_avatar": "https%3A%2F%2Fthirdwx.qlogo.cn%2Fmmopen%2Fvi_32%2FeEOpSbFh2Mb1bUxMW9Y3FRPfXwWvOLaNlsjWIkcKeeNg6vlVS5kOVuhNKGQ1M8zaggLqMPmpE5qIUdqEXlQgYg%2F132",
    "wr_gender": "0",
}

DEFAULT_BOOK_IDS = ["24a320007191987a24a4603"]

DEFAULT_DATA = {
    "appId": "wb182564874603h266381671",
    "b": "ce032b305a9bc1ce0b0dd2a",
    "c": "7f632b502707f6ffaa6bf2e",
    "ci": 27,
    "co": 389,
    "sm": "19聚会《三体》网友的聚会地点是一处僻静",
    "pr": 74,
    "rt": 15,
    "ts": 1744264311434,
    "rn": 466,
    "sg": "2b2ec618394b99deea35104168b86381da9f8946d4bc234e062fa320155409fb",
    "ct": 1744264311,
    "ps": "4ee326507a65a465g015fae",
    "pc": "aab32e207a65a466g010615",
    "s": "36cc0815",
}


@dataclass(frozen=True)
class Settings:
    read_num: int
    push_method: str | None
    pushplus_token: str | None
    telegram_bot_token: str | None
    telegram_chat_id: str | None
    wxpusher_spt: str | None
    serverchan_spt: str | None
    headers: dict[str, str]
    cookies: dict[str, str]
    book_ids: list[str]
    data_template: dict[str, Any]
    key: str
    cookie_data: dict[str, Any]
    read_url: str
    progress_url: str
    reader_url: str
    renew_url: str
    fix_synckey_url: str
    read_min_per_success: float
    rt_seconds: int
    sleep_min_seconds: int
    sleep_max_seconds: int
    session_minutes_min: int
    session_minutes_max: int
    rest_minutes_min: int
    rest_minutes_max: int
    progress_interval_min: int
    progress_interval_reads: int
    start_delay_min_raw: str | None
    start_delay_max_raw: str | None
    http_proxy: str | None
    https_proxy: str | None


def _parse_env_list(value: str | None) -> list[str] | None:
    if not value:
        return None
    items = [v.strip() for v in value.split(",") if v.strip()]
    return items or None


def convert_curl(curl_command: str) -> tuple[dict[str, str], dict[str, str]]:
    """Extract headers and cookies from a curl command."""
    headers_temp: dict[str, str] = {}
    for match in re.findall(r"-H '([^:]+): ([^']+)'", curl_command):
        headers_temp[match[0]] = match[1]

    cookie_header = next(
        (v for k, v in headers_temp.items() if k.lower() == "cookie"), ""
    )

    cookie_b = re.search(r"-b '([^']+)'", curl_command)
    cookie_string = cookie_b.group(1) if cookie_b else cookie_header

    cookies: dict[str, str] = {}
    if cookie_string:
        for cookie in cookie_string.split("; "):
            if "=" in cookie:
                key, value = cookie.split("=", 1)
                cookies[key.strip()] = value.strip()

    headers = {k: v for k, v in headers_temp.items() if k.lower() != "cookie"}
    return headers, cookies


def load_settings() -> Settings:
    read_num = int(os.getenv("READ_NUM") or 40)
    push_method = os.getenv("PUSH_METHOD")
    pushplus_token = os.getenv("PUSHPLUS_TOKEN")
    telegram_bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    telegram_chat_id = os.getenv("TELEGRAM_CHAT_ID")
    wxpusher_spt = os.getenv("WXPUSHER_SPT")
    serverchan_spt = os.getenv("SERVERCHAN_SPT")

    curl_str = os.getenv("WXREAD_CURL_BASH")
    headers = dict(DEFAULT_HEADERS)
    cookies = dict(DEFAULT_COOKIES)
    if curl_str:
        parsed_headers, parsed_cookies = convert_curl(curl_str)
        if parsed_headers:
            headers = parsed_headers
        if parsed_cookies:
            cookies = parsed_cookies

    book_ids = _parse_env_list(os.getenv("WXREAD_BOOK_LIST")) or list(DEFAULT_BOOK_IDS)

    key = "3c5c8717f3daf09iop3423zafeqoi"
    cookie_data = {"rq": "%2Fweb%2Fbook%2FgetProgress", "ql": False}

    read_url = "https://weread.qq.com/web/book/read"
    progress_url = "https://weread.qq.com/web/book/getProgress"
    reader_url = "https://weread.qq.com/web/reader"
    renew_url = "https://weread.qq.com/web/login/renewal"
    fix_synckey_url = "https://weread.qq.com/web/book/chapterInfos"

    read_min_per_success = 0.5
    rt_seconds = 30
    sleep_min_seconds = rt_seconds + 1
    sleep_max_seconds = rt_seconds + 10
    session_minutes_min = 20
    session_minutes_max = 40
    rest_minutes_min = 3
    rest_minutes_max = 6
    progress_interval_min = 10
    progress_interval_reads = int(progress_interval_min / read_min_per_success)

    start_delay_min_raw = os.getenv("WXREAD_START_DELAY_MIN")
    start_delay_max_raw = os.getenv("WXREAD_START_DELAY_MAX")

    http_proxy = os.getenv("http_proxy")
    https_proxy = os.getenv("https_proxy")

    return Settings(
        read_num=read_num,
        push_method=push_method,
        pushplus_token=pushplus_token,
        telegram_bot_token=telegram_bot_token,
        telegram_chat_id=telegram_chat_id,
        wxpusher_spt=wxpusher_spt,
        serverchan_spt=serverchan_spt,
        headers=headers,
        cookies=cookies,
        book_ids=book_ids,
        data_template=dict(DEFAULT_DATA),
        key=key,
        cookie_data=cookie_data,
        read_url=read_url,
        progress_url=progress_url,
        reader_url=reader_url,
        renew_url=renew_url,
        fix_synckey_url=fix_synckey_url,
        read_min_per_success=read_min_per_success,
        rt_seconds=rt_seconds,
        sleep_min_seconds=sleep_min_seconds,
        sleep_max_seconds=sleep_max_seconds,
        session_minutes_min=session_minutes_min,
        session_minutes_max=session_minutes_max,
        rest_minutes_min=rest_minutes_min,
        rest_minutes_max=rest_minutes_max,
        progress_interval_min=progress_interval_min,
        progress_interval_reads=progress_interval_reads,
        start_delay_min_raw=start_delay_min_raw,
        start_delay_max_raw=start_delay_max_raw,
        http_proxy=http_proxy,
        https_proxy=https_proxy,
    )
