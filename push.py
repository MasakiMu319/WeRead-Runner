import asyncio
import json
import logging
import random
from typing import Any

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

    async def push_pushplus(self, content: str) -> None:
        if not self.pushplus_token:
            raise ValueError("PushPlus token missing")
        attempts = 5
        payload = {
            "token": self.pushplus_token,
            "title": "微信阅读推送...",
            "content": content,
        }
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        self.pushplus_url,
                        content=json.dumps(payload).encode("utf-8"),
                        headers=self.headers,
                    )
                    response.raise_for_status()
                    logger.info("✅ PushPlus响应: %s", response.text)
                    break
            except httpx.RequestError as exc:
                logger.error("❌ PushPlus推送失败: %s", exc)
                if attempt < attempts - 1:
                    sleep_time = random.randint(180, 360)
                    logger.info("将在 %d 秒后重试...", sleep_time)
                    await asyncio.sleep(sleep_time)

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
        attempts = 5
        url = self.wxpusher_simple_url.format(self.wxpusher_spt, content)
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.get(url)
                    response.raise_for_status()
                    logger.info("✅ WxPusher响应: %s", response.text)
                    break
            except httpx.RequestError as exc:
                logger.error("❌ WxPusher推送失败: %s", exc)
                if attempt < attempts - 1:
                    sleep_time = random.randint(180, 360)
                    logger.info("将在 %d 秒后重试...", sleep_time)
                    await asyncio.sleep(sleep_time)

    async def push_serverchan(self, content: str) -> None:
        if not self.serverchan_spt:
            raise ValueError("ServerChan spt missing")
        attempts = 5
        url = self.server_chan_url.format(self.serverchan_spt)

        title = "微信阅读推送..."
        if "自动阅读完成" not in content:
            title = "微信阅读失败！！"

        payload = {"title": title, "desp": content}
        for attempt in range(attempts):
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    response = await client.post(
                        url,
                        content=json.dumps(payload).encode("utf-8"),
                        headers=self.headers,
                    )
                    response.raise_for_status()
                    logger.info("✅ ServerChan响应: %s", response.text)
                    break
            except httpx.RequestError as exc:
                logger.error("❌ ServerChan推送失败: %s", exc)
                if attempt < attempts - 1:
                    sleep_time = random.randint(180, 360)
                    logger.info("将在 %d 秒后重试...", sleep_time)
                    await asyncio.sleep(sleep_time)

    async def push(self, content: str, method: str) -> Any:
        if method == "pushplus":
            return await self.push_pushplus(content)
        if method == "telegram":
            return await self.push_telegram(content)
        if method == "wxpusher":
            return await self.push_wxpusher(content)
        if method == "serverchan":
            return await self.push_serverchan(content)
        raise ValueError(
            "❌ 无效的通知渠道，请选择 'pushplus'、'telegram'、'wxpusher' 或 'serverchan'"
        )
