# main.py 主逻辑：包括字段拼接、模拟请求
import re
import json
import time
import random
import logging
import hashlib
import requests
import urllib.parse
from push import push
from config import data, headers, cookies, READ_NUM, PUSH_METHOD, book

# 配置日志格式
logger = logging.getLogger(__name__)
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(levelname)-8s - %(message)s"
)

# 加密盐及其它默认值
KEY = "3c5c8717f3daf09iop3423zafeqoi"
COOKIE_DATA = {"rq": "%2Fweb%2Fbook%2FgetProgress", "ql": False}
READ_URL = "https://weread.qq.com/web/book/read"
PROGRESS_URL = "https://weread.qq.com/web/book/getProgress"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
FIX_SYNCKEY_URL = "https://weread.qq.com/web/book/chapterInfos"
READ_MIN_PER_SUCCESS = 0.5
PROGRESS_INTERVAL_MIN = 10
PROGRESS_INTERVAL_READS = int(PROGRESS_INTERVAL_MIN / READ_MIN_PER_SUCCESS)
VALID_PUSH_METHODS = {"pushplus", "telegram", "wxpusher", "serverchan"}


def encode_data(data):
    """数据编码"""
    return "&".join(
        f"{k}={urllib.parse.quote(str(data[k]), safe='')}" for k in sorted(data.keys())
    )


def cal_hash(input_string):
    """计算哈希值"""
    _7032f5 = 0x15051505
    _cc1055 = _7032f5
    length = len(input_string)
    _19094e = length - 1

    while _19094e > 0:
        _7032f5 = 0x7FFFFFFF & (
            _7032f5 ^ ord(input_string[_19094e]) << (length - _19094e) % 30
        )
        _cc1055 = 0x7FFFFFFF & (
            _cc1055 ^ ord(input_string[_19094e - 1]) << _19094e % 30
        )
        _19094e -= 2

    return hex(_7032f5 + _cc1055)[2:].lower()


def format_minutes(value):
    """格式化分钟数，避免 10.0 这种显示"""
    if value == int(value):
        return str(int(value))
    return f"{value:.1f}"


def extract_safe_info(res_data):
    """提取安全字段用于失败原因描述"""
    if isinstance(res_data, dict):
        keys = ("errcode", "errmsg", "code", "message", "succ")
        return {k: res_data.get(k) for k in keys if k in res_data}
    return None


def safe_push(content, method):
    """安全推送：避免因推送配置错误导致主流程崩溃"""
    if method in (None, ""):
        logging.info("ℹ️ PUSH_METHOD 为空，跳过推送。")
        return False
    method_norm = method.lower() if isinstance(method, str) else method
    if method_norm not in VALID_PUSH_METHODS:
        logging.warning("⚠️ PUSH_METHOD 无效(%s)，跳过推送。", method)
        return False
    try:
        push(content, method_norm)
        return True
    except Exception as exc:
        logging.error("❌ 推送失败: %s", exc)
        return False


def get_progress(book_id):
    """获取指定书籍的阅读进度"""
    if not book_id:
        logging.error("❌ 未指定 bookId，无法获取阅读进度。")
        return None
    try:
        response = requests.get(
            PROGRESS_URL, headers=headers, cookies=cookies, params={"bookId": book_id}
        )
        res_data = response.json()
    except Exception as exc:
        logging.error("❌ 获取阅读进度失败: %s", exc)
        return None
    if not isinstance(res_data, dict):
        logging.error("❌ 获取阅读进度返回非对象。")
        return None
    safe_info = extract_safe_info(res_data)
    if safe_info:
        logging.info("🔁 进度响应: %s", safe_info)
    if "book" not in res_data:
        logging.error("❌ 获取阅读进度缺少 book 字段。")
        return None
    return res_data


def get_chapter_infos(book_id):
    """获取章节信息列表"""
    if not book_id:
        logging.error("❌ 未指定 bookId，无法获取章节信息。")
        return None
    response = requests.post(
        FIX_SYNCKEY_URL,
        headers=headers,
        cookies=cookies,
        data=json.dumps({"bookIds": [str(book_id)]}, separators=(",", ":")),
    )
    try:
        res_data = response.json()
    except ValueError:
        logging.error("❌ 章节信息返回非 JSON。")
        return None
    if not isinstance(res_data, dict):
        logging.error("❌ 章节信息返回非对象。")
        return None
    items = res_data.get("data") or []
    if not items:
        logging.error("❌ 章节信息为空。")
        return None
    target = next(
        (item for item in items if str(item.get("bookId")) == str(book_id)), items[0]
    )
    updated = target.get("updated") or []
    chapters = []
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
        logging.error("❌ 章节信息解析为空。")
        return None
    return chapters


def calc_read_step(interval_sec, word_count):
    """根据时间间隔估算阅读推进量"""
    interval = max(1, int(interval_sec))
    speed = random.uniform(3.0, 6.0)
    step = max(50, int(interval * speed))
    if word_count and word_count > 0:
        max_step = max(200, int(word_count * 0.05))
        step = min(step, max_step)
    return step


def advance_chapter_pos(chapters, current_pos):
    """推进到下一个较大的章节"""
    if not chapters:
        return current_pos
    for _ in range(len(chapters)):
        current_pos = (current_pos + 1) % len(chapters)
        if chapters[current_pos].get("word_count", 0) > 50:
            return current_pos
    return current_pos


def build_readable_positions(chapters):
    """筛选可阅读章节索引"""
    readable = [i for i, ch in enumerate(chapters) if ch.get("word_count", 0) > 50]
    return readable if readable else list(range(len(chapters)))


def pick_random_chapter(chapters, readable_positions):
    """随机选择章节并返回位置、偏移、摘要"""
    pos = random.choice(readable_positions) if readable_positions else 0
    chapter = chapters[pos]
    word_count = chapter.get("word_count", 0)
    if word_count and word_count > 0:
        offset = random.randint(10, min(80, max(10, word_count // 50)))
    else:
        offset = 0
    return pos, offset, chapter.get("title")


def get_wr_skey():
    """刷新cookie密钥"""
    response = requests.post(
        RENEW_URL,
        headers=headers,
        cookies=cookies,
        data=json.dumps(COOKIE_DATA, separators=(",", ":")),
    )
    resp_cookie_dict = response.cookies.get_dict()
    if resp_cookie_dict:
        cookies.update(resp_cookie_dict)
    wr_skey = resp_cookie_dict.get("wr_skey") if resp_cookie_dict else response.cookies.get("wr_skey")
    if not wr_skey:
        set_cookie = response.headers.get("Set-Cookie", "")
        match = re.search(r"wr_skey=([^;]+)", set_cookie)
        if match:
            wr_skey = match.group(1)
            cookies["wr_skey"] = wr_skey
    logging.info(
        "🔁 续期响应: status=%s, set_cookie=%s, wr_skey=%s",
        response.status_code,
        "present" if "Set-Cookie" in response.headers else "missing",
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
            logging.info("🔁 续期JSON: %s", safe_info)
    return wr_skey if wr_skey else None


def fix_no_synckey(book_id):
    if not book_id:
        return
    requests.post(
        FIX_SYNCKEY_URL,
        headers=headers,
        cookies=cookies,
        data=json.dumps({"bookIds": [str(book_id)]}, separators=(",", ":")),
    )


def refresh_cookie():
    logging.info(f"🍪 刷新cookie")
    new_skey = get_wr_skey()
    if new_skey:
        cookies["wr_skey"] = new_skey
        logging.info(f"✅ 密钥刷新成功，新密钥：{new_skey}")
        logging.info(f"🔄 重新本次阅读。")
        return True
    else:
        ERROR_CODE = "❌ 无法获取新密钥或者WXREAD_CURL_BASH配置有误，继续尝试。"
        logging.error(ERROR_CODE)
        logging.warning("⚠️ 刷新失败，继续使用旧 cookie 尝试。")
        return False


refresh_cookie()
index = 1
success_count = 0
stopped_reason = None
target_minutes = READ_NUM * READ_MIN_PER_SUCCESS
read_book_id = random.choice(book) if book else data.get("b")
progress_book_id = None
app_id = data.get("appId")
current_idx = data.get("ci") or 1
current_offset = data.get("co") or 0
current_summary = data.get("sm") or ""
chapters = None
chapter_pos = 0
readable_positions = None
last_readable_pos = 0
chapter_uid_warned = False
lastTime = int(time.time()) - 30
logging.info(f"⏱️ 一共需要阅读 {READ_NUM} 次...")
if not read_book_id:
    stopped_reason = "未找到可用的 bookId。"
else:
    progress = get_progress(read_book_id)
    if not progress:
        stopped_reason = "获取阅读进度失败。"
    else:
        progress_book_id = progress.get("bookId") or read_book_id
        progress_book = progress.get("book") or {}
        app_id = progress_book.get("appId") or app_id
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
        chapters = get_chapter_infos(progress_book_id)
        if not chapters:
            stopped_reason = "获取章节信息失败。"
        else:
            readable_positions = build_readable_positions(chapters)
            last_readable_pos = readable_positions[-1] if readable_positions else 0
            chapter_pos = next(
                (i for i, ch in enumerate(chapters) if ch["idx"] == int(current_idx)),
                None,
            )
            if chapter_pos is None:
                chapter_pos = readable_positions[0] if readable_positions else 0
                current_idx = chapters[chapter_pos]["idx"]
            current_word_count = chapters[chapter_pos].get("word_count", 0)
            if current_word_count and current_offset >= current_word_count:
                current_offset = max(0, current_word_count - 1)
            if current_word_count <= 50:
                chapter_pos = advance_chapter_pos(chapters, chapter_pos)
                current_idx = chapters[chapter_pos]["idx"]
            logging.info(
                "📚 书籍=%s 章节数=%s 起始章节=%s",
                read_book_id,
                len(chapters),
                current_idx,
            )

if not stopped_reason:
    safe_push(
        f"🚀 开始自动阅读\n🎯 目标次数：{READ_NUM} 次\n⏱️ 目标时长：{format_minutes(target_minutes)} 分钟",
        PUSH_METHOD,
    )

    while index <= READ_NUM:
        data.pop("s", None)
        current_chapter = chapters[chapter_pos]
        current_idx = current_chapter["idx"]
        current_uid = current_chapter.get("uid")
        current_word_count = current_chapter.get("word_count", 0)
        if current_uid is not None:
            data["c"] = str(current_uid)
        elif not chapter_uid_warned:
            logging.warning("⚠️ 章节缺少 chapterUid，沿用原始 c 字段。")
            chapter_uid_warned = True
        data["appId"] = app_id
        data["b"] = read_book_id
        data["ci"] = int(current_idx)
        data["co"] = int(current_offset)
        if current_summary:
            data["sm"] = current_summary
        data["pr"] = max(0, int(current_offset // 1000))

        thisTime = int(time.time())
        data["ct"] = thisTime
        data["rt"] = thisTime - lastTime
        data["ts"] = int(thisTime * 1000) + random.randint(0, 1000)
        data["rn"] = random.randint(0, 1000)
        data["sg"] = hashlib.sha256(f"{data['ts']}{data['rn']}{KEY}".encode()).hexdigest()
        data["s"] = cal_hash(encode_data(data))

        logging.info(f"⏱️ 尝试第 {index} 次阅读...")
        logging.info(f"📕 data: {data}")
        response = requests.post(
            READ_URL,
            headers=headers,
            cookies=cookies,
            data=json.dumps(data, separators=(",", ":")),
        )
        try:
            resData = response.json()
        except ValueError:
            resData = {"message": "non-json response", "status": response.status_code}
        logging.info(f"📕 response: {resData}")

        if "succ" in resData:
            if "synckey" in resData:
                interval = data["rt"]
                lastTime = thisTime
                success_count += 1
                index += 1

                step = calc_read_step(interval, current_word_count)
                current_offset += step
                if current_word_count <= 0:
                    chapter_pos = advance_chapter_pos(chapters, chapter_pos)
                    next_chapter = chapters[chapter_pos]
                    current_idx = next_chapter["idx"]
                    current_offset = 0
                    if next_chapter.get("title"):
                        current_summary = next_chapter["title"]
                elif current_offset >= current_word_count:
                    if chapter_pos == last_readable_pos:
                        chapter_pos, current_offset, new_summary = pick_random_chapter(
                            chapters, readable_positions
                        )
                        current_idx = chapters[chapter_pos]["idx"]
                        if new_summary:
                            current_summary = new_summary
                    else:
                        chapter_pos = advance_chapter_pos(chapters, chapter_pos)
                        next_chapter = chapters[chapter_pos]
                        current_idx = next_chapter["idx"]
                        next_word_count = next_chapter.get("word_count", 0)
                        if next_word_count and next_word_count > 0:
                            current_offset = random.randint(
                                10, min(80, max(10, next_word_count // 50))
                            )
                        else:
                            current_offset = 0
                        if next_chapter.get("title"):
                            current_summary = next_chapter["title"]

                time.sleep(random.randint(25, 45))
                done_minutes = success_count * READ_MIN_PER_SUCCESS
                logging.info(f"✅ 阅读成功，阅读进度：{format_minutes(done_minutes)} 分钟")
                if success_count % PROGRESS_INTERVAL_READS == 0:
                    safe_push(
                        f"📈 阅读进度：{format_minutes(done_minutes)} 分钟 / "
                        f"{format_minutes(target_minutes)} 分钟",
                        PUSH_METHOD,
                    )
            else:
                logging.warning("❌ 无synckey, 尝试修复...")
                fix_no_synckey(progress_book_id)
        else:
            logging.warning("❌ 阅读失败，尝试刷新cookie...")
            refresh_ok = refresh_cookie()
            if not refresh_ok:
                safe_info = extract_safe_info(resData) or {}
                reason_parts = ["阅读接口失败且刷新cookie失败，已停止。"]
                if safe_info:
                    reason_parts.append(f"原因：{safe_info}")
                stopped_reason = " ".join(reason_parts)
                break

total_minutes = success_count * READ_MIN_PER_SUCCESS
if stopped_reason:
    logging.error("🛑 阅读已停止：%s", stopped_reason)
    safe_push(
        f"🛑 微信读书自动阅读已停止\n"
        f"{stopped_reason}\n"
        f"⏱️ 已完成：{format_minutes(total_minutes)} 分钟",
        PUSH_METHOD,
    )
else:
    logging.info("🎉 阅读脚本已完成！")
    safe_push(
        f"🎉 微信读书自动阅读完成！\n⏱️ 阅读时长：{format_minutes(total_minutes)} 分钟。",
        PUSH_METHOD,
    )
