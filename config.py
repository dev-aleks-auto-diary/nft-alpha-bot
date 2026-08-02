"""
Конфигурация NFT New Collections Bot (на основе Alchemy).

Регистрация: alchemy.com -> Sign up (можно через Google) -> Create App ->
выбираешь нужную сеть -> копируешь API Key. Бесплатный tier: 300M compute
units в месяц — для опроса раз в 5 минут этого более чем достаточно.
"""

import os

# ── Telegram ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")

# ── Alchemy ──────────────────────────────────────────────────────────
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "PUT_YOUR_ALCHEMY_KEY_HERE")

# Сети, которые отслеживаем. Ключ — просто удобное имя для тебя,
# значение — сетевой префикс Alchemy (см. их доки "Supported Chains").
# Пока только Ethereum — при желании потом легко добавить "base": "base-mainnet" и т.д.
CHAINS = {
    "ethereum": "eth-mainnet",
}


def alchemy_url(network_prefix: str) -> str:
    return f"https://{network_prefix}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"


# ── Логика детекта "новой коллекции" ───────────────────────────────────
# Считаем токен "первым в коллекции", если его tokenId <= этого значения.
# 0 и 1 — самые частые старты нумерации у ERC-721/1155.
GENESIS_TOKEN_ID_MAX = 1

# Сколько минтов максимум забирать за один запрос к Alchemy (лимит страницы)
MAX_TRANSFERS_PER_POLL = 1000

# Как часто опрашивать (в секундах)
POLL_INTERVAL_SECONDS = 300  # 5 минут

# Файл, где храним прогресс (последний обработанный блок на сеть + что видели)
STATE_FILE = "bot_state.json"
