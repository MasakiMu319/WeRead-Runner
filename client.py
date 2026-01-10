import json
import logging
import re
from typing import Any

import httpx

from settings import Settings
from utils import collect_readers, extract_initial_state, extract_json_after_key, extract_safe_info


logger = logging.getLogger(__name__)


class WeReadClient:
    def __init__(self, settings: Settings, timeout: float = 30.0) -> None:
        self.settings = settings
        self._client = httpx.AsyncClient(
            headers=dict(settings.headers),
            cookies=dict(settings.cookies),
            timeout=httpx.Timeout(timeout),
            follow_redirects=True,
        )

    async def __aenter__(self) -> "WeReadClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self._client.aclose()

    @property
    def cookies(self) -> httpx.Cookies:
        return self._client.cookies

    async def get_reader_info(self, read_book_id: str) -> dict[str, str] | None:
        if not read_book_id:
            logger.error("❌ 未指定 reader bookId。")
            return None
        url = f"{self.settings.reader_url}/{read_book_id}"
        try:
            response = await self._client.get(url)
        except Exception as exc:
            logger.error("❌ 获取 reader 页面失败: %s", exc)
            return None

        html = response.text or ""
        reader_obj = None
        readers: list[dict[str, Any]] = []
        state_obj = extract_initial_state(html)
        if state_obj:
            readers = collect_readers(state_obj)
            for item in readers:
                if (
                    isinstance(item, dict)
                    and item.get("chapterInfos")
                    and (item.get("bookId") or item.get("book", {}).get("bookId"))
                ):
                    reader_obj = item
                    break
            if not reader_obj and readers:
                reader_obj = readers[0]
        if not reader_obj:
            reader_obj = extract_json_after_key(html, '"reader"')

        progress_book_id = None
        if isinstance(reader_obj, dict):
            progress_book_id = reader_obj.get("bookId") or reader_obj.get("book", {}).get(
                "bookId"
            )
        if not progress_book_id:
            match = re.search(r'"bookId"\s*:\s*"(\d+)"', html)
            if match:
                progress_book_id = match.group(1)
        if not progress_book_id:
            logger.error("❌ reader 页面未解析到 progress bookId。")
            book_id_candidates = re.findall(r'"bookId"\s*:\s*"(\d+)"', html)[:5]
            logger.error(
                "🔎 reader 调试: url=%s status=%s len=%s has_state=%s readers=%s bookId候选=%s",
                url,
                response.status_code,
                len(html),
                bool(state_obj),
                len(readers),
                book_id_candidates or None,
            )
            return None
        return {"progress_book_id": str(progress_book_id)}

    async def get_progress(self, book_id: str) -> dict[str, Any] | None:
        if not book_id:
            logger.error("❌ 未指定 bookId，无法获取阅读进度。")
            return None
        try:
            response = await self._client.get(
                self.settings.progress_url, params={"bookId": book_id}
            )
            res_data = response.json()
        except Exception as exc:
            logger.error("❌ 获取阅读进度失败: %s", exc)
            return None
        if not isinstance(res_data, dict):
            logger.error("❌ 获取阅读进度返回非对象。")
            return None
        safe_info = extract_safe_info(res_data)
        if safe_info:
            logger.info("🔁 进度响应: %s", safe_info)
        if "book" not in res_data:
            logger.error("❌ 获取阅读进度缺少 book 字段。")
            return None
        return res_data

    async def get_chapter_infos(
        self, book_id: str
    ) -> tuple[list[dict[str, Any]], dict[str, Any]] | None:
        if not book_id:
            logger.error("❌ 未指定 bookId，无法获取章节信息。")
            return None

        payload = json.dumps({"bookIds": [str(book_id)]}, separators=(",", ":"))
        response = await self._client.post(
            self.settings.fix_synckey_url,
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            res_data = response.json()
        except ValueError:
            logger.error("❌ 章节信息返回非 JSON。")
            return None
        if not isinstance(res_data, dict):
            logger.error("❌ 章节信息返回非对象。")
            return None
        items = res_data.get("data") or []
        if not items:
            logger.error("❌ 章节信息为空。")
            return None
        target = next(
            (item for item in items if str(item.get("bookId")) == str(book_id)), items[0]
        )
        book_meta = target.get("book") or {}
        updated = target.get("updated") or []
        chapters: list[dict[str, Any]] = []
        for item in updated:
            idx = item.get("chapterIdx")
            uid = item.get("chapterUid")
            if idx is None or uid is None:
                continue
            chapters.append(
                {
                    "idx": int(idx),
                    "uid": uid,
                    "word_count": int(item.get("wordCount") or 0),
                    "title": item.get("title"),
                }
            )
        chapters.sort(key=lambda x: x["idx"])
        if not chapters:
            logger.error("❌ 章节信息解析为空。")
            return None
        return chapters, book_meta

    async def renew_cookie(self) -> str | None:
        payload = json.dumps(self.settings.cookie_data, separators=(",", ":"))
        response = await self._client.post(
            self.settings.renew_url,
            content=payload,
            headers={"Content-Type": "application/json"},
        )

        wr_skey = response.cookies.get("wr_skey")
        if not wr_skey:
            set_cookie = response.headers.get("set-cookie", "")
            match = re.search(r"wr_skey=([^;]+)", set_cookie)
            if match:
                wr_skey = match.group(1)
                self._client.cookies.set("wr_skey", wr_skey)

        logger.info(
            "🔁 续期响应: status=%s, set_cookie=%s, wr_skey=%s",
            response.status_code,
            "present" if "set-cookie" in response.headers else "missing",
            "found" if wr_skey else "missing",
        )
        try:
            resp_json = response.json()
        except ValueError:
            resp_json = None
        if isinstance(resp_json, dict):
            safe_keys = ("errcode", "errmsg", "succ", "code", "message")
            safe_info = {k: resp_json.get(k) for k in safe_keys if k in resp_json}
            if safe_info:
                logger.info("🔁 续期JSON: %s", safe_info)
        return wr_skey if wr_skey else None

    async def fix_no_synckey(self, book_id: str) -> None:
        if not book_id:
            return
        payload = json.dumps({"bookIds": [str(book_id)]}, separators=(",", ":"))
        await self._client.post(
            self.settings.fix_synckey_url,
            content=payload,
            headers={"Content-Type": "application/json"},
        )

    async def post_read(self, data: dict[str, Any]) -> dict[str, Any]:
        payload = json.dumps(data, separators=(",", ":"))
        response = await self._client.post(
            self.settings.read_url,
            content=payload,
            headers={"Content-Type": "application/json"},
        )
        try:
            return response.json()
        except ValueError:
            return {"message": "non-json response", "status": response.status_code}
