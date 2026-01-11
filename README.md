# WeRead-Runner

A script that simulates reading requests on WeRead web platform. Can be scheduled with GitHub Actions and optionally push notifications via PushPlus / WxPusher / Telegram / ServerChan.

> For educational purposes only. Please evaluate risks and compliance on your own.

## Features

- Simulates `https://weread.qq.com/web/book/read` reading requests
- Automatically attempts to renew cookie (`wr_skey`)
- Supports random startup delay, random chapter switching, reading/rest rhythm
- Optional push notifications: `pushplus` / `wxpusher` / `telegram` / `serverchan`

## Prerequisites: Capture `WXREAD_CURL_BASH`

1. Open https://weread.qq.com/ and log in
2. Open any book to enter reading page, flip to next page
3. In Developer Tools Network tab, find request: `https://weread.qq.com/web/book/read`
4. Right-click the request: Copy → Copy as cURL (bash)
5. Save the entire `curl ...` command as environment variable `WXREAD_CURL_BASH` (must be stored in **GitHub Secrets**, do not commit to repository)

## GitHub Actions Deployment (Recommended)

1. Fork this repository
2. Repository Settings → Secrets and variables → Actions:
   - **Repository secrets**
     - `WXREAD_CURL_BASH` (required)
     - `PUSH_METHOD` (optional): `pushplus` / `wxpusher` / `telegram` / `serverchan`
     - `PUSHPLUS_TOKEN` (when `PUSH_METHOD=pushplus`)
     - `WXPUSHER_SPT` (when `PUSH_METHOD=wxpusher`)
     - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (when `PUSH_METHOD=telegram`)
     - `SERVERCHAN_SPT` (when `PUSH_METHOD=serverchan`)
     - `http_proxy`, `https_proxy` (optional, for Telegram proxy)
   - **Repository variables**
     - `READ_NUM` (optional)
     - `WXREAD_BOOK_LIST` (optional)
3. Manually trigger the workflow on Actions page, or wait for scheduled task

The schedule is defined in `.github/workflows/main.yml`, defaults to 06:00 Beijing Time (corresponds to `cron: '0 22 * * *'`, UTC 22:00).

## Configuration Options

| Name | Required | Default | Description |
| --- | --- | --- | --- |
| `WXREAD_CURL_BASH` | Yes | None | Captured `curl` (bash) command, script will extract `headers` and `cookies` from it |
| `READ_NUM` | No | `40` | Minimum read count lower bound (each request `rt=30s`); script will randomly pick a value between `max(READ_NUM, 360)` and its `1.5x` |
| `WXREAD_BOOK_LIST` | No | Built-in `config.py` | Comma-separated book ID list; each run randomly selects one book as entry point (see "Get Book ID" below) |
| `WXREAD_START_DELAY_MIN` | No | Empty/0 | Random startup delay lower bound in seconds for scheduled triggers |
| `WXREAD_START_DELAY_MAX` | No | Empty/0 | Random startup delay upper bound in seconds for scheduled triggers |
| `WXREAD_MAX_RUNTIME_SECONDS` | No | `20700` | Runtime budget in seconds. Enabled by default in GitHub Actions (`GITHUB_ACTIONS=true`) to avoid hitting 6h limit; will "finish normally" with explanation when budget is reached |
| `WXREAD_EXIT_GRACE_SECONDS` | No | `120` | Buffer time in seconds for early exit when approaching budget, used for push/cleanup; avoids forced timeout failure by GitHub |
| `PUSH_METHOD` | No | Empty | Push method: `pushplus` / `wxpusher` / `telegram` / `serverchan`; no push if empty |
| `PUSHPLUS_TOKEN` | No | Empty | PushPlus token (when `PUSH_METHOD=pushplus`) |
| `WXPUSHER_SPT` | No | Empty | WxPusher SPT (when `PUSH_METHOD=wxpusher`) |
| `TELEGRAM_BOT_TOKEN` | No | Empty | Telegram bot token (when `PUSH_METHOD=telegram`) |
| `TELEGRAM_CHAT_ID` | No | Empty | Telegram chat ID (when `PUSH_METHOD=telegram`) |
| `SERVERCHAN_SPT` | No | Empty | ServerChan SendKey (when `PUSH_METHOD=serverchan`) |
| `http_proxy` / `https_proxy` | No | Empty | Telegram proxy (optional) |

> Note: The script uses Beijing Time to determine "whether to skip startup delay". When running **after 06:10 Beijing Time**, it will skip the delay directly (treated as manual trigger).

## Local Run (uv)

Requirements: Python `>=3.13`, `uv`.

```bash
uv sync --locked

export WXREAD_CURL_BASH="(paste your captured curl bash command)"
export READ_NUM=360
export WXREAD_BOOK_LIST='24a320007191987a24a4603'
export PUSH_METHOD=''

uv run python main.py
```

## Get Book ID (for `WXREAD_BOOK_LIST`)

Open reading page on WeRead web platform, URL format: `https://weread.qq.com/web/reader/<bookId>`, extract the `<bookId>` part.
