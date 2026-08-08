"""
Конфигурация NFT New Collections Bot (v2 — с фильтрами качества).
"""

import os

# ── Telegram ──────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")

# ── Alchemy ──────────────────────────────────────────────────────────
ALCHEMY_API_KEY = os.getenv("ALCHEMY_API_KEY", "PUT_YOUR_ALCHEMY_KEY_HERE")

CHAINS = {
    "ethereum": "eth-mainnet",
    "apechain": "apechain-mainnet",
    "robinhood": "robinhood-mainnet",
}


def alchemy_url(network_prefix: str) -> str:
    return f"https://{network_prefix}.g.alchemy.com/v2/{ALCHEMY_API_KEY}"


# ── Etherscan (для проверки верификации контракта) ─────────────────────
# Бесплатный ключ: https://etherscan.io/apis
ETHERSCAN_API_KEY = os.getenv("ETHERSCAN_API_KEY", "PUT_YOUR_ETHERSCAN_KEY_HERE")
ETHERSCAN_API_URL = "https://api.etherscan.io/api"

# ── Детект кандидата в "новую коллекцию" ───────────────────────────────
GENESIS_TOKEN_ID_MAX = 1
MAX_TRANSFERS_PER_POLL = 1000

# ── GoPlus Security (проверка на признаки скама, оставляем как страховку) ─
# Бесплатно, без обязательного ключа. Поддерживает не все сети — там,
# где сети нет в этом списке, проверка просто пропускается (не блокирует).
GOPLUS_CHAIN_IDS = {
    "ethereum": "1",
}

# ── Детект специфичных механик (buyback / vault / lock / burn) ─────────
# Единственный способ обнаружения в этой версии: ищем в исходнике
# контракта (через Etherscan) паттерны конкретных механик. Найдено —
# шлём алерт сразу. Не найдено (или контракт ещё не верифицирован) —
# продолжаем перепроверять, пока не пройдёт MAX_CANDIDATE_AGE_SECONDS.
#
# Слова специально общие и в одно слово (а не точные фразы) — так выше
# шанс совпасть с реальными именами переменных/функций в разных контрактах
# (например "lockUntil", "vaultDeposit", "freezeToken" всё равно содержат
# "lock"/"vault"/"freeze"). Да, будет больше ложных совпадений — это
# осознанный компромисс в пользу того, чтобы вообще что-то ловить.
MECHANIC_KEYWORDS = {
    "vault_lock": ["vault", "lockforever", "permalock", "tokenlock", "freeze", "diamondhand"],
    "buyback": ["buyback", "buy back", "treasurybuy"],
    "burn_to_mint": ["burntomint", "burn to mint", "burntoearn", "burn to earn"],
    "revenue_share": ["revenueshare", "royaltyshare", "holderreward", "profitshare"],
}

# Работает только там, где Etherscan знает исходник (сейчас — Ethereum).
MECHANIC_CHECK_CHAINS = ["ethereum"]

# Сколько времени продолжаем перепроверять кандидата на механики, прежде
# чем сдаться (верификация исходника иногда происходит не сразу после
# деплоя, а через часы или дни).
MAX_CANDIDATE_AGE_SECONDS = 3 * 24 * 3600  # 3 дня

# ── Общие настройки ─────────────────────────────────────────────────────
POLL_INTERVAL_SECONDS = 300  # 5 минут
STATE_FILE = "bot_state.json"
