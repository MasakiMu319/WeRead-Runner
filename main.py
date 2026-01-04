# main.py 主逻辑：包括字段拼接、模拟请求
import re
import os
import math
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
READER_URL = "https://weread.qq.com/web/reader"
RENEW_URL = "https://weread.qq.com/web/login/renewal"
FIX_SYNCKEY_URL = "https://weread.qq.com/web/book/chapterInfos"
READ_MIN_PER_SUCCESS = 0.5
RT_SECONDS = 30
SLEEP_MIN_SECONDS = RT_SECONDS + 1
SLEEP_MAX_SECONDS = RT_SECONDS + 15
SESSION_MINUTES_MIN = 20
SESSION_MINUTES_MAX = 40
REST_MINUTES_MIN = 3
REST_MINUTES_MAX = 8
PROGRESS_INTERVAL_MIN = 10
PROGRESS_INTERVAL_READS = int(PROGRESS_INTERVAL_MIN / READ_MIN_PER_SUCCESS)
VALID_PUSH_METHODS = {"pushplus", "telegram", "wxpusher", "serverchan"}


def encode_weread_id(value):
    """微信读书的 ID 编码（来自前端逻辑）"""
    if isinstance(value, int):
        value = str(value)
    if not isinstance(value, str):
        return value
    md5_hex = hashlib.md5(value.encode()).hexdigest()
    prefix = md5_hex[:3]
    if value.isdigit():
        pieces = []
        for i in range(0, len(value), 9):
            chunk = value[i : i + 9]
            pieces.append(format(int(chunk), "x"))
        flag = "3"
    else:
        pieces = ["".join(format(ord(ch), "x") for ch in value)]
        flag = "4"
    out = prefix + flag
    out += "2" + md5_hex[-2:]
    for idx, item in enumerate(pieces):
        length_hex = format(len(item), "x")
        if len(length_hex) == 1:
            length_hex = "0" + length_hex
        out += length_hex + item
        if idx < len(pieces) - 1:
            out += "g"
    if len(out) < 0x14:
        out += md5_hex[: 0x14 - len(out)]
    out += hashlib.md5(out.encode()).hexdigest()[:3]
    return out


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


def get_start_delay_seconds():
    """根据环境变量获取启动延迟（秒）"""
    min_raw = os.getenv("WXREAD_START_DELAY_MIN")
    max_raw = os.getenv("WXREAD_START_DELAY_MAX")
    if not min_raw and not max_raw:
        return 0
    try:
        min_val = int(min_raw) if min_raw is not None else 0
    except ValueError:
        min_val = 0
    try:
        max_val = int(max_raw) if max_raw is not None else 0
    except ValueError:
        max_val = 0
    if min_val < 0:
        min_val = 0
    if max_val < 0:
        max_val = 0
    if max_val < min_val:
        min_val, max_val = max_val, min_val
    if max_val == 0 and min_val == 0:
        return 0
    return random.randint(min_val, max_val)
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


def extract_balanced_json(text, start_index):
    """提取从指定位置开始的 JSON 对象字符串"""
    depth = 0
    in_string = False
    escape = False
    for i in range(start_index, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
        else:
            if ch == '"':
                in_string = True
            elif ch == "{":
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    return text[start_index : i + 1]
    return None


def extract_json_after_marker(text, marker):
    """从类似 window.__INITIAL_STATE__=... 中提取 JSON 对象"""
    idx = text.find(marker)
    if idx == -1:
        return None
    brace_start = text.find("{", idx)
    if brace_start == -1:
        return None
    blob = extract_balanced_json(text, brace_start)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except ValueError:
        return None


def extract_json_after_key(text, key):
    """从 key: { ... } 中提取 JSON 对象"""
    idx = text.find(key)
    if idx == -1:
        return None
    colon = text.find(":", idx)
    if colon == -1:
        return None
    brace_start = text.find("{", colon)
    if brace_start == -1:
        return None
    blob = extract_balanced_json(text, brace_start)
    if not blob:
        return None
    try:
        return json.loads(blob)
    except ValueError:
        return None


def find_key_recursive(obj, target_key):
    if isinstance(obj, dict):
        if target_key in obj:
            return obj[target_key]
        for value in obj.values():
            found = find_key_recursive(value, target_key)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for item in obj:
            found = find_key_recursive(item, target_key)
            if found is not None:
                return found
    return None


def extract_initial_state(html):
    for marker in (
        "window.__INITIAL_STATE__",
        "__INITIAL_STATE__",
        "window.__NUXT__",
        "__NUXT__",
    ):
        state_obj = extract_json_after_marker(html, marker)
        if state_obj:
            return state_obj
    return None


def collect_readers(state_obj):
    readers = []

    def walk(obj):
        if isinstance(obj, dict):
            if "reader" in obj and isinstance(obj["reader"], dict):
                readers.append(obj["reader"])
            for value in obj.values():
                walk(value)
        elif isinstance(obj, list):
            for item in obj:
                walk(item)

    walk(state_obj)
    return readers


def get_reader_info(read_book_id):
    """解析 reader 页面，获取 progress 的 bookId"""
    if not read_book_id:
        logging.error("❌ 未指定 reader bookId。")
        return None
    url = f"{READER_URL}/{read_book_id}"
    try:
        response = requests.get(url, headers=headers, cookies=cookies)
    except Exception as exc:
        logging.error("❌ 获取 reader 页面失败: %s", exc)
        return None
    resp_cookie_dict = response.cookies.get_dict()
    if resp_cookie_dict:
        cookies.update(resp_cookie_dict)
    html = response.text or ""
    reader_obj = None
    readers = []
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
        logging.error("❌ reader 页面未解析到 progress bookId。")
        book_id_candidates = re.findall(r'"bookId"\s*:\s*"(\d+)"', html)[:5]
        logging.error(
            "🔎 reader 调试: url=%s status=%s len=%s has_state=%s readers=%s bookId候选=%s",
            url,
            response.status_code,
            len(html),
            True if state_obj else False,
            len(readers),
            book_id_candidates if book_id_candidates else None,
        )
        return None
    return {"progress_book_id": str(progress_book_id)}


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
    book_meta = target.get("book") or {}
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
    return chapters, book_meta


def calc_read_step(interval_sec, word_count):
    """根据时间间隔估算阅读推进量"""
    interval = max(1, int(interval_sec))
    speed = random.uniform(3.0, 6.0)
    step = max(50, int(interval * speed))
    if word_count and word_count > 0:
        max_step = max(200, int(word_count * 0.05))
        step = min(step, max_step)
    return step


def advance_chapter_pos(current_pos, readable_positions):
    """推进到下一个可读章节"""
    if not readable_positions:
        return current_pos
    for pos in readable_positions:
        if pos > current_pos:
            return pos
    return readable_positions[0]


def build_readable_positions(chapters):
    """筛选可阅读章节索引"""
    readable = []
    for i, ch in enumerate(chapters):
        if ch.get("word_count", 0) > 50:
            readable.append(i)
    if readable:
        return readable
    return [i for i, ch in enumerate(chapters)]


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


start_delay_seconds = get_start_delay_seconds()
if start_delay_seconds > 0:
    logging.info("⏳ 延迟启动：%s 秒", start_delay_seconds)
    safe_push(
        f"⏳ 任务延迟启动\n"
        f"预计延迟：{start_delay_seconds // 60}分{start_delay_seconds % 60}秒",
        PUSH_METHOD,
    )
    time.sleep(start_delay_seconds)

refresh_cookie()
index = 1
success_count = 0
stopped_reason = None
min_reads = max(READ_NUM, math.ceil(180 / READ_MIN_PER_SUCCESS))
max_reads = int(min_reads * 1.5)
target_reads = random.randint(min_reads, max_reads)
target_minutes = target_reads * READ_MIN_PER_SUCCESS
read_book_id = random.choice(book) if book else data.get("b")
progress_book_id = None
progress = None
app_id = data.get("appId")
current_idx = data.get("ci") or 1
current_offset = data.get("co") or 0
current_summary = data.get("sm") or ""
chapters = None
book_meta = {}
chapter_pos = 0
readable_positions = None
last_readable_pos = 0
session_minutes = 0.0
session_target_minutes = random.randint(SESSION_MINUTES_MIN, SESSION_MINUTES_MAX)
last_progress_push_ts = None
last_report_mono = None
logging.info(
    "⏱️ 一共需要阅读 %s 次（下限=%s次）...",
    target_reads,
    READ_NUM,
)
if not read_book_id:
    stopped_reason = "未找到可用的 bookId。"
else:
    reader_info = get_reader_info(read_book_id)
    if not reader_info:
        stopped_reason = "读取 reader 信息失败。"
    else:
        progress_book_id = reader_info["progress_book_id"]
        progress = get_progress(progress_book_id)
    if not stopped_reason and not progress:
        stopped_reason = "获取阅读进度失败。"
    elif not stopped_reason:
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
        chapters_result = get_chapter_infos(progress_book_id)
        if not chapters_result:
            stopped_reason = "获取章节信息失败。"
        else:
            chapters, book_meta = chapters_result
            readable_positions = build_readable_positions(chapters)
            if not readable_positions:
                stopped_reason = "无可读章节，无法继续。"
                readable_positions = None
            else:
                last_readable_pos = readable_positions[-1]
            if stopped_reason:
                pass
            else:
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
                logging.info(
                    "📚 书籍=%s 章节数=%s 起始章节=%s",
                    read_book_id,
                    len(chapters),
                    current_idx,
                )

if not stopped_reason:
    book_title = book_meta.get("title") if isinstance(book_meta, dict) else None
    book_author = book_meta.get("author") if isinstance(book_meta, dict) else None
    if book_title and book_author:
        book_line = f"📚 书籍：{book_title} - {book_author}"
    elif book_title:
        book_line = f"📚 书籍：{book_title}"
    elif progress_book_id:
        book_line = f"📚 书籍ID：{progress_book_id}"
    else:
        book_line = None
    start_lines = [
        "🚀 开始自动阅读",
        f"🎯 目标次数：{target_reads} 次",
        f"⏱️ 目标时长：{format_minutes(target_minutes)} 分钟",
    ]
    if book_line:
        start_lines.insert(1, book_line)
    safe_push(
        "\n".join(start_lines),
        PUSH_METHOD,
    )

    while index <= target_reads:
        data.pop("s", None)
        current_chapter = chapters[chapter_pos]
        current_idx = current_chapter["idx"]
        current_uid = current_chapter.get("uid")
        current_word_count = current_chapter.get("word_count", 0)
        chapter_title = current_chapter.get("title")
        if chapter_title:
            current_summary = chapter_title
        chapter_id = encode_weread_id(current_uid) if current_uid is not None else None
        if not chapter_id:
            stopped_reason = f"无法匹配章节ID(chapterUid={current_uid})，已停止。"
            break
        data["c"] = chapter_id
        data["appId"] = app_id
        data["b"] = read_book_id
        data["ci"] = int(current_idx)
        data["co"] = int(current_offset)
        if current_summary:
            data["sm"] = current_summary
        data["pr"] = max(0, int(current_offset // 1000))

        thisTime = int(time.time())
        data["ct"] = thisTime
        data["rt"] = RT_SECONDS
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
                success_count += 1
                index += 1

                step = calc_read_step(interval, current_word_count)
                current_offset += step
                if current_word_count <= 0:
                    chapter_pos = advance_chapter_pos(chapter_pos, readable_positions)
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
                        chapter_pos = advance_chapter_pos(
                            chapter_pos, readable_positions
                        )
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

                session_minutes += READ_MIN_PER_SUCCESS
                if session_minutes >= session_target_minutes:
                    rest_minutes = random.randint(REST_MINUTES_MIN, REST_MINUTES_MAX)
                    logging.info(
                        "😴 连续阅读 %s 分钟，休息 %s 分钟",
                        format_minutes(session_minutes),
                        rest_minutes,
                    )
                    safe_push(
                        "😴 进入休息\n"
                        f"已连续阅读：{format_minutes(session_minutes)} 分钟\n"
                        f"预计休息：{rest_minutes} 分钟",
                        PUSH_METHOD,
                    )
                    time.sleep(rest_minutes * 60)
                    session_minutes = 0.0
                    session_target_minutes = random.randint(
                        SESSION_MINUTES_MIN, SESSION_MINUTES_MAX
                    )
                    safe_push(
                        "✅ 休息结束，继续阅读\n"
                        f"下一轮目标：{session_target_minutes} 分钟",
                        PUSH_METHOD,
                    )
                time.sleep(random.randint(SLEEP_MIN_SECONDS, SLEEP_MAX_SECONDS))
                done_minutes = success_count * READ_MIN_PER_SUCCESS
                now_mono = time.monotonic()
                if last_report_mono is None:
                    report_gap = "首次上报"
                else:
                    gap_seconds = int(now_mono - last_report_mono)
                    report_gap = f"{gap_seconds}秒"
                last_report_mono = now_mono
                logging.info(
                    "✅ 阅读成功，阅读进度：%s 分钟（距上次上报：%s）",
                    format_minutes(done_minutes),
                    report_gap,
                )
                if success_count % PROGRESS_INTERVAL_READS == 0:
                    now_ts = int(time.time())
                    if last_progress_push_ts is None:
                        gap_text = "首次上报"
                    else:
                        gap_seconds = now_ts - last_progress_push_ts
                        gap_text = f"{gap_seconds // 60}分{gap_seconds % 60}秒"
                    safe_push(
                        f"📈 阅读进度：{format_minutes(done_minutes)} 分钟 / "
                        f"{format_minutes(target_minutes)} 分钟\n"
                        f"⏱️ 距上次上报：{gap_text}",
                        PUSH_METHOD,
                    )
                    last_progress_push_ts = now_ts
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
