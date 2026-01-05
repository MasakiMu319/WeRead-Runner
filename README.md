# wxread

在微信读书网页端模拟阅读请求的脚本，可用 GitHub Actions 定时运行，并可选把结果推送到 PushPlus / WxPusher / Telegram / Server酱。

> 仅供学习交流使用，请自行评估风险与合规性。

## 功能

- 模拟 `https://weread.qq.com/web/book/read` 阅读请求
- 自动尝试续期 cookie（`wr_skey`）
- 支持随机启动延迟、随机章节切换、阅读/休息节奏
- 可选推送：`pushplus` / `wxpusher` / `telegram` / `serverchan`

## 使用前准备：抓包得到 `WXREAD_CURL_BASH`

1. 打开 https://weread.qq.com/ 并登录
2. 任意打开一本书进入阅读页，翻到下一页
3. 在开发者工具 Network 中找到请求：`https://weread.qq.com/web/book/read`
4. 右键该请求：Copy → Copy as cURL（bash）
5. 将整条 `curl ...` 命令保存为环境变量 `WXREAD_CURL_BASH`（务必放到 **GitHub Secrets**，不要提交到仓库）

## GitHub Actions 部署（推荐）

1. Fork 本仓库
2. 仓库 Settings → Secrets and variables → Actions：
   - **Repository secrets**
     - `WXREAD_CURL_BASH`（必填）
     - `PUSH_METHOD`（可选）：`pushplus` / `wxpusher` / `telegram` / `serverchan`
     - `PUSHPLUS_TOKEN`（当 `PUSH_METHOD=pushplus`）
     - `WXPUSHER_SPT`（当 `PUSH_METHOD=wxpusher`）
     - `TELEGRAM_BOT_TOKEN`、`TELEGRAM_CHAT_ID`（当 `PUSH_METHOD=telegram`）
     - `SERVERCHAN_SPT`（当 `PUSH_METHOD=serverchan`）
     - `http_proxy`、`https_proxy`（可选，Telegram 代理）
   - **Repository variables**
     - `READ_NUM`（可选）
     - `WXREAD_BOOK_LIST`（可选）
3. 在 Actions 页面手动触发工作流，或等待定时任务

定时规则在 `.github/workflows/deploy.yml` 里，默认是北京时间 06:00 触发（对应 `cron: '0 22 * * *'`，UTC 22:00）。

## 配置项说明

| 名称 | 必填 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `WXREAD_CURL_BASH` | 是 | 无 | 抓包得到的 `curl`（bash）命令，脚本会从中提取 `headers` 和 `cookies` |
| `READ_NUM` | 否 | `40` | 最小阅读次数下限（每次请求 `rt=30s`）；脚本实际会在 `max(READ_NUM, 360)` 到其 `1.5x` 之间随机取值 |
| `WXREAD_BOOK_LIST` | 否 | `config.py` 内置 | 逗号分隔的书籍 id 列表；每次运行会随机选一本书作为入口（见下文“获取书籍 ID”） |
| `WXREAD_START_DELAY_MIN` | 否 | 空/0 | 定时触发时的随机启动延迟下限（秒） |
| `WXREAD_START_DELAY_MAX` | 否 | 空/0 | 定时触发时的随机启动延迟上限（秒） |
| `PUSH_METHOD` | 否 | 空 | 推送方式：`pushplus` / `wxpusher` / `telegram` / `serverchan`；为空则不推送 |
| `PUSHPLUS_TOKEN` | 否 | 空 | PushPlus token（`PUSH_METHOD=pushplus`） |
| `WXPUSHER_SPT` | 否 | 空 | WxPusher SPT（`PUSH_METHOD=wxpusher`） |
| `TELEGRAM_BOT_TOKEN` | 否 | 空 | Telegram bot token（`PUSH_METHOD=telegram`） |
| `TELEGRAM_CHAT_ID` | 否 | 空 | Telegram chat id（`PUSH_METHOD=telegram`） |
| `SERVERCHAN_SPT` | 否 | 空 | Server酱 SendKey（`PUSH_METHOD=serverchan`） |
| `http_proxy` / `https_proxy` | 否 | 空 | Telegram 代理（可选） |

> 说明：脚本会用北京时间判断“是否跳过启动延迟”。当北京时间 **06:10 之后**运行时，会直接跳过延迟（视为手动触发）。

## 本地运行（uv）

需要：Python `>=3.13`、`uv`。

```bash
uv sync --locked

export WXREAD_CURL_BASH="(粘贴你抓到的整条 curl bash 命令)"
export READ_NUM=360
export WXREAD_BOOK_LIST='24a320007191987a24a4603'
export PUSH_METHOD=''

uv run python main.py
```

## 获取书籍 ID（用于 `WXREAD_BOOK_LIST`）

在微信读书网页端打开阅读页，URL 形如：`https://weread.qq.com/web/reader/<bookId>`，取其中的 `<bookId>` 即可。
