import asyncio
import json
import logging
import random
from typing import Any, Awaitable, Callable

import httpx

logger = logging.getLogger(__name__)


class PushNotification:
    def __init__(
        self,
        *,
        pushplus_token: str | None,
        telegram_bot_token: str | None,
        telegram_chat_id: str | None,
        wxpusher_spt: str | None,
        serverchan_spt: str | None,
        http_proxy: str | None,
        https_proxy: str | None,
    ) -> None:
        self.pushplus_url = "https://www.pushplus.plus/send"
        self.telegram_url = "https://api.telegram.org/bot{}/sendMessage"
        self.server_chan_url = "https://sctapi.ftqq.com/{}.send"
        self.wxpusher_simple_url = "https://wxpusher.zjiecode.com/api/send/message/{}/{}"
        self.headers = {"Content-Type": "application/json"}
        self.pushplus_token = pushplus_token
        self.telegram_bot_token = telegram_bot_token
        self.telegram_chat_id = telegram_chat_id
        self.wxpusher_spt = wxpusher_spt
        self.serverchan_spt = serverchan_spt
        self.proxy = https_proxy or http_proxy

    async def _retry_request(
        self,
        request_func: Callable[[], Awaitable[httpx.Response]],
        service_name: str,
        attempts: int = 5,
    ) -> None:
        """Execute a request with retry logic."""
        for attempt in range(attempts):
            try:
                response = await request_func()
                response.raise_for_status()
                logger.info("✅ %s响应: %s", service_name, response.text)
                return
            except httpx.RequestError as exc:
                logger.error("❌ %s推送失败: %s", service_name, exc)
                if attempt < attempts - 1:
                    sleep_time = random.randint(180, 360)
                    logger.info("将在 %d 秒后重试...", sleep_time)
                    await asyncio.sleep(sleep_time)

    async def push_pushplus(self, content: str) -> None:
        if not self.pushplus_token:
            raise ValueError("PushPlus token missing")
        payload = {
            "token": self.pushplus_token,
            "title": "微信阅读推送...",
            "content": content,
        }

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.post(
                    self.pushplus_url,
                    content=json.dumps(payload).encode("utf-8"),
                    headers=self.headers,
                )

        await self._retry_request(request, "PushPlus")

    async def push_telegram(self, content: str) -> bool:
        if not self.telegram_bot_token or not self.telegram_chat_id:
            raise ValueError("Telegram token/chat_id missing")
        url = self.telegram_url.format(self.telegram_bot_token)
        payload = {"chat_id": self.telegram_chat_id, "text": content}
        try:
            async with httpx.AsyncClient(timeout=30, proxy=self.proxy) as client:
                response = await client.post(url, json=payload)
                logger.info("✅ Telegram响应: %s", response.text)
                response.raise_for_status()
                return True
        except Exception as exc:
            logger.error("❌ Telegram代理发送失败: %s", exc)
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.post(url, json=payload)
                    response.raise_for_status()
                    return True
            except Exception as exc:
                logger.error("❌ Telegram发送失败: %s", exc)
                return False

    async def push_wxpusher(self, content: str) -> None:
        if not self.wxpusher_spt:
            raise ValueError("WxPusher spt missing")
        url = self.wxpusher_simple_url.format(self.wxpusher_spt, content)

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.get(url)

        await self._retry_request(request, "WxPusher")

    async def push_serverchan(self, content: str) -> None:
        if not self.serverchan_spt:
            raise ValueError("ServerChan spt missing")
        url = self.server_chan_url.format(self.serverchan_spt)
        title = "微信阅读失败！！" if "自动阅读完成" not in content else "微信阅读推送..."
        payload = {"title": title, "desp": content}

        async def request() -> httpx.Response:
            async with httpx.AsyncClient(timeout=10) as client:
                return await client.post(
                    url,
                    content=json.dumps(payload).encode("utf-8"),
                    headers=self.headers,
                )

        await self._retry_request(request, "ServerChan")

    async def push(self, content: str, method: str) -> Any:
        handlers = {
            "pushplus": self.push_pushplus,
            "telegram": self.push_telegram,
            "wxpusher": self.push_wxpusher,
            "serverchan": self.push_serverchan,
        }
        handler = handlers.get(method)
        if handler:
            return await handler(content)
        raise ValueError(
            "❌ 无效的通知渠道，请选择 'pushplus'、'telegram'、'wxpusher' 或 'serverchan'"
        )
