import asyncio
import hashlib
import logging
import math
import random
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from client import WeReadClient
from push import PushNotification
from settings import Settings
from utils import (
    advance_chapter_pos,
    build_readable_positions,
    cal_hash,
    calc_read_step,
    encode_data,
    encode_weread_id,
    extract_safe_info,
    format_minutes,
    pick_random_chapter,
)


logger = logging.getLogger(__name__)

VALID_PUSH_METHODS = {"pushplus", "telegram", "wxpusher", "serverchan"}


@dataclass
class ReadContext:
    data: dict[str, Any]
    app_id: str | None
    read_book_id: str
    progress_book_id: str
    chapters: list[dict[str, Any]]
    book_meta: dict[str, Any]
    chapter_pos: int
    readable_positions: list[int]
    last_readable_pos: int
    current_idx: int
    current_offset: int
    current_summary: str


def _parse_delay_value(raw: str | None) -> int:
    """Parse a delay value string, returning 0 for invalid or negative values."""
    if raw is None:
        return 0
    try:
        return max(0, int(raw))
    except ValueError:
        return 0


def get_start_delay_seconds(settings: Settings) -> int:
    tz = timezone(timedelta(hours=8))
    now_cn = datetime.now(tz)
    logger.info("🕒 当前北京时间：%s", now_cn.strftime("%Y-%m-%d %H:%M:%S"))
    if now_cn.hour > 6 or (now_cn.hour == 6 and now_cn.minute >= 10):
        logger.info("🟢 判定为手动触发，跳过启动延迟。")
        return 0
    logger.info("🟡 判定为定时触发，启用随机延迟。")

    if not settings.start_delay_min_raw and not settings.start_delay_max_raw:
        return 0

    min_val = _parse_delay_value(settings.start_delay_min_raw)
    max_val = _parse_delay_value(settings.start_delay_max_raw)
    if max_val < min_val:
        min_val, max_val = max_val, min_val
    if max_val == 0:
        return 0
    return random.randint(min_val, max_val)


async def safe_push(content: str, method: str | None, notifier: PushNotification) -> bool:
    if not method:
        logger.info("ℹ️ PUSH_METHOD 为空，跳过推送。")
        return False
    method_norm = method.strip().strip('"').strip("'").lower()
    if method_norm not in VALID_PUSH_METHODS:
        logger.warning("⚠️ PUSH_METHOD 无效(%s)，跳过推送。", method)
        return False
    try:
        logger.info("📨 准备推送: method=%s", method_norm)
        await notifier.push(content, method_norm)
        logger.info("✅ 推送已触发: method=%s", method_norm)
        return True
    except Exception as exc:
        logger.error("❌ 推送失败: %s", exc)
        return False


async def refresh_cookie(client: WeReadClient) -> bool:
    logger.info("🍪 刷新cookie")
    new_skey = await client.renew_cookie()
    if new_skey:
        client.cookies["wr_skey"] = new_skey
        logger.info("✅ 密钥刷新成功，新密钥：%s", new_skey)
        logger.info("🔄 重新本次阅读。")
        return True
    logger.error("❌ 无法获取新密钥或者WXREAD_CURL_BASH配置有误，继续尝试。")
    logger.warning("⚠️ 刷新失败，继续使用旧 cookie 尝试。")
    return False


async def initialize_context(
    settings: Settings,
    client: WeReadClient,
    data: dict[str, Any],
    read_book_id: str | None,
    app_id: str | None,
    current_idx: int,
    current_offset: int,
    current_summary: str,
) -> tuple[ReadContext | None, str | None]:
    stopped_reason = None
    if not read_book_id:
        return None, "未找到可用的 bookId。"

    reader_info = await client.get_reader_info(read_book_id)
    if not reader_info:
        return None, "读取 reader 信息失败。"

    progress_book_id = reader_info["progress_book_id"]
    progress = await client.get_progress(progress_book_id)
    if not progress:
        return None, "获取阅读进度失败。"

    progress_book = progress.get("book") or {}
    app_id = progress_book.get("appId") or app_id
    if progress_book_id:
        read_book_id = encode_weread_id(progress_book_id)

    progress_idx = progress_book.get("chapterIdx")
    if progress_idx is not None:
        current_idx = progress_idx
    progress_offset = progress_book.get("chapterOffset")
    if progress_offset is not None:
        current_offset = progress_offset
    current_summary = progress_book.get("summary") or current_summary
    try:
        current_idx = int(current_idx)
    except (TypeError, ValueError):
        current_idx = 1
    try:
        current_offset = int(current_offset)
    except (TypeError, ValueError):
        current_offset = 0

    chapters_result = await client.get_chapter_infos(progress_book_id)
    if not chapters_result:
        return None, "获取章节信息失败。"

    chapters, book_meta = chapters_result
    readable_positions = build_readable_positions(chapters)
    if not readable_positions:
        return None, "无可读章节，无法继续。"

    last_readable_pos = readable_positions[-1]
    chapter_pos = next(
        (i for i, ch in enumerate(chapters) if ch["idx"] == int(current_idx)),
        None,
    )
    if chapter_pos is None or chapter_pos not in readable_positions:
        chapter_pos = readable_positions[0]
        current_idx = chapters[chapter_pos]["idx"]

    current_word_count = chapters[chapter_pos].get("word_count", 0)
    if current_word_count and current_offset >= current_word_count:
        current_offset = max(0, current_word_count - 1)
    if current_word_count <= 50:
        chapter_pos = advance_chapter_pos(chapter_pos, readable_positions)
        current_idx = chapters[chapter_pos]["idx"]

    chapter_title = chapters[chapter_pos].get("title")
    if chapter_title:
        current_summary = chapter_title

    logger.info(
        "📚 书籍=%s 章节数=%s 起始章节=%s",
        read_book_id,
        len(chapters),
        current_idx,
    )

    ctx = ReadContext(
        data=data,
        app_id=app_id,
        read_book_id=str(read_book_id),
        progress_book_id=str(progress_book_id),
        chapters=chapters,
        book_meta=book_meta,
        chapter_pos=chapter_pos,
        readable_positions=readable_positions,
        last_readable_pos=last_readable_pos,
        current_idx=current_idx,
        current_offset=current_offset,
        current_summary=current_summary,
    )
    return ctx, stopped_reason


async def run(settings: Settings) -> None:
    notifier = PushNotification(
        pushplus_token=settings.pushplus_token,
        telegram_bot_token=settings.telegram_bot_token,
        telegram_chat_id=settings.telegram_chat_id,
        wxpusher_spt=settings.wxpusher_spt,
        serverchan_spt=settings.serverchan_spt,
        http_proxy=settings.http_proxy,
        https_proxy=settings.https_proxy,
    )

    start_delay_seconds = get_start_delay_seconds(settings)
    if start_delay_seconds > 0:
        logger.info("⏳ 延迟启动：%s 秒", start_delay_seconds)
        await safe_push(
            "⏳ 任务延迟启动\n"
            f"预计延迟：{start_delay_seconds // 60}分{start_delay_seconds % 60}秒",
            settings.push_method,
            notifier,
        )
        await asyncio.sleep(start_delay_seconds)

    async with WeReadClient(settings) as client:
        await refresh_cookie(client)

        data = dict(settings.data_template)
        index = 1
        success_count = 0
        stopped_reason = None
        min_reads = max(settings.read_num, math.ceil(180 / settings.read_min_per_success))
        max_reads = int(min_reads * 1.5)
        target_reads = random.randint(min_reads, max_reads)
        target_minutes = target_reads * settings.read_min_per_success

        read_book_id = random.choice(settings.book_ids) if settings.book_ids else data.get(
            "b"
        )
        app_id = data.get("appId")
        current_idx = data.get("ci") or 1
        current_offset = data.get("co") or 0
        current_summary = data.get("sm") or ""

        session_minutes = 0.0
        session_target_minutes = random.randint(
            settings.session_minutes_min, settings.session_minutes_max
        )
        last_progress_push_ts = None
        last_report_mono = None

        logger.info(
            "⏱️ 一共需要阅读 %s 次（下限=%s次）...",
            target_reads,
            settings.read_num,
        )

        ctx, stopped_reason = await initialize_context(
            settings,
            client,
            data,
            read_book_id,
            app_id,
            current_idx,
            current_offset,
            current_summary,
        )

        if not stopped_reason and ctx:
            book_title = (
                ctx.book_meta.get("title") if isinstance(ctx.book_meta, dict) else None
            )
            book_author = (
                ctx.book_meta.get("author") if isinstance(ctx.book_meta, dict) else None
            )
            if book_title and book_author:
                book_line = f"📚 书籍：{book_title} - {book_author}"
            elif book_title:
                book_line = f"📚 书籍：{book_title}"
            elif ctx.progress_book_id:
                book_line = f"📚 书籍ID：{ctx.progress_book_id}"
            else:
                book_line = None

            start_lines = [
                "🚀 开始自动阅读",
                f"🎯 目标次数：{target_reads} 次",
                f"⏱️ 目标时长：{format_minutes(target_minutes)} 分钟",
            ]
            if book_line:
                start_lines.insert(1, book_line)
            await safe_push("\n".join(start_lines), settings.push_method, notifier)

        if not ctx or stopped_reason:
            total_minutes = success_count * settings.read_min_per_success
            if stopped_reason:
                logger.error("🛑 阅读已停止：%s", stopped_reason)
                await safe_push(
                    "🛑 微信读书自动阅读已停止\n"
                    f"{stopped_reason}\n"
                    f"⏱️ 已完成：{format_minutes(total_minutes)} 分钟",
                    settings.push_method,
                    notifier,
                )
            return

        while index <= target_reads:
            ctx.data.pop("s", None)
            current_chapter = ctx.chapters[ctx.chapter_pos]
            ctx.current_idx = current_chapter["idx"]
            current_uid = current_chapter.get("uid")
            current_word_count = current_chapter.get("word_count", 0)
            chapter_title = current_chapter.get("title")
            if chapter_title:
                ctx.current_summary = chapter_title
            chapter_id = encode_weread_id(current_uid) if current_uid is not None else None
            if not chapter_id:
                stopped_reason = f"无法匹配章节ID(chapterUid={current_uid})，已停止。"
                break

            ctx.data["c"] = chapter_id
            ctx.data["appId"] = ctx.app_id
            ctx.data["b"] = ctx.read_book_id
            ctx.data["ci"] = int(ctx.current_idx)
            ctx.data["co"] = int(ctx.current_offset)
            if ctx.current_summary:
                ctx.data["sm"] = ctx.current_summary
            ctx.data["pr"] = max(0, int(ctx.current_offset // 1000))

            this_time = int(time.time())
            ctx.data["ct"] = this_time
            ctx.data["rt"] = settings.rt_seconds
            ctx.data["ts"] = int(this_time * 1000) + random.randint(0, 1000)
            ctx.data["rn"] = random.randint(0, 1000)
            ctx.data["sg"] = hashlib.sha256(
                f"{ctx.data['ts']}{ctx.data['rn']}{settings.key}".encode()
            ).hexdigest()
            ctx.data["s"] = cal_hash(encode_data(ctx.data))

            logger.info("⏱️ 尝试第 %s 次阅读...", index)
            logger.info("📕 data: %s", ctx.data)
            res_data = await client.post_read(ctx.data)
            logger.info("📕 response: %s", res_data)

            if "succ" in res_data:
                if "synckey" in res_data:
                    interval = ctx.data["rt"]
                    success_count += 1
                    index += 1

                    step = calc_read_step(interval, current_word_count)
                    ctx.current_offset += step
                    if current_word_count <= 0:
                        ctx.chapter_pos = advance_chapter_pos(
                            ctx.chapter_pos, ctx.readable_positions
                        )
                        next_chapter = ctx.chapters[ctx.chapter_pos]
                        ctx.current_idx = next_chapter["idx"]
                        ctx.current_offset = 0
                        if next_chapter.get("title"):
                            ctx.current_summary = next_chapter["title"]
                    elif ctx.current_offset >= current_word_count:
                        if ctx.chapter_pos == ctx.last_readable_pos:
                            (
                                ctx.chapter_pos,
                                ctx.current_offset,
                                new_summary,
                            ) = pick_random_chapter(
                                ctx.chapters, ctx.readable_positions
                            )
                            ctx.current_idx = ctx.chapters[ctx.chapter_pos]["idx"]
                            if new_summary:
                                ctx.current_summary = new_summary
                        else:
                            ctx.chapter_pos = advance_chapter_pos(
                                ctx.chapter_pos, ctx.readable_positions
                            )
                            next_chapter = ctx.chapters[ctx.chapter_pos]
                            ctx.current_idx = next_chapter["idx"]
                            next_word_count = next_chapter.get("word_count", 0)
                            if next_word_count > 0:
                                ctx.current_offset = random.randint(
                                    10, min(80, max(10, next_word_count // 50))
                                )
                            else:
                                ctx.current_offset = 0
                            if next_chapter.get("title"):
                                ctx.current_summary = next_chapter["title"]

                    session_minutes += settings.read_min_per_success
                    if session_minutes >= session_target_minutes:
                        rest_minutes = random.randint(
                            settings.rest_minutes_min, settings.rest_minutes_max
                        )
                        logger.info(
                            "😴 连续阅读 %s 分钟，休息 %s 分钟",
                            format_minutes(session_minutes),
                            rest_minutes,
                        )
                        await safe_push(
                            "😴 进入休息\n"
                            f"已连续阅读：{format_minutes(session_minutes)} 分钟\n"
                            f"预计休息：{rest_minutes} 分钟",
                            settings.push_method,
                            notifier,
                        )
                        await asyncio.sleep(rest_minutes * 60)
                        session_minutes = 0.0
                        session_target_minutes = random.randint(
                            settings.session_minutes_min, settings.session_minutes_max
                        )
                        await safe_push(
                            "✅ 休息结束，继续阅读\n"
                            f"下一轮目标：{session_target_minutes} 分钟",
                            settings.push_method,
                            notifier,
                        )

                    await asyncio.sleep(
                        random.randint(settings.sleep_min_seconds, settings.sleep_max_seconds)
                    )
                    done_minutes = success_count * settings.read_min_per_success
                    now_mono = time.monotonic()
                    if last_report_mono is None:
                        report_gap = "首次上报"
                    else:
                        gap_seconds = int(now_mono - last_report_mono)
                        report_gap = f"{gap_seconds}秒"
                    last_report_mono = now_mono
                    logger.info(
                        "✅ 阅读成功，阅读进度：%s 分钟（距上次上报：%s）",
                        format_minutes(done_minutes),
                        report_gap,
                    )

                    if success_count % settings.progress_interval_reads == 0:
                        now_ts = int(time.time())
                        if last_progress_push_ts is None:
                            gap_text = "首次上报"
                        else:
                            gap_seconds = now_ts - last_progress_push_ts
                            gap_text = f"{gap_seconds // 60}分{gap_seconds % 60}秒"
                        await safe_push(
                            "📈 阅读进度："
                            f"{format_minutes(done_minutes)} 分钟 / "
                            f"{format_minutes(target_minutes)} 分钟\n"
                            f"⏱️ 距上次上报：{gap_text}",
                            settings.push_method,
                            notifier,
                        )
                        last_progress_push_ts = now_ts
                else:
                    logger.warning("❌ 无synckey, 尝试修复...")
                    await client.fix_no_synckey(ctx.progress_book_id)
            else:
                logger.warning("❌ 阅读失败，尝试刷新cookie...")
                refresh_ok = await refresh_cookie(client)
                if not refresh_ok:
                    safe_info = extract_safe_info(res_data) or {}
                    reason_parts = ["阅读接口失败且刷新cookie失败，已停止。"]
                    if safe_info:
                        reason_parts.append(f"原因：{safe_info}")
                    stopped_reason = " ".join(reason_parts)
                    break

        total_minutes = success_count * settings.read_min_per_success
        if stopped_reason:
            logger.error("🛑 阅读已停止：%s", stopped_reason)
            await safe_push(
                "🛑 微信读书自动阅读已停止\n"
                f"{stopped_reason}\n"
                f"⏱️ 已完成：{format_minutes(total_minutes)} 分钟",
                settings.push_method,
                notifier,
            )
        else:
            logger.info("🎉 阅读脚本已完成！")
            await safe_push(
                "🎉 微信读书自动阅读完成！\n"
                f"⏱️ 阅读时长：{format_minutes(total_minutes)} 分钟。",
                settings.push_method,
                notifier,
            )
