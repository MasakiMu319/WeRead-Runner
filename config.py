from settings import load_settings

settings = load_settings()

READ_NUM = settings.read_num
PUSH_METHOD = settings.push_method
PUSHPLUS_TOKEN = settings.pushplus_token
TELEGRAM_BOT_TOKEN = settings.telegram_bot_token
TELEGRAM_CHAT_ID = settings.telegram_chat_id
WXPUSHER_SPT = settings.wxpusher_spt
SERVERCHAN_SPT = settings.serverchan_spt

headers = settings.headers
cookies = settings.cookies
book = settings.book_ids

data = settings.data_template
