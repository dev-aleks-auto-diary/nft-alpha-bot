"""
Отправка алертов о новых коллекциях в Telegram.
"""

import logging

import httpx

import config
from alchemy_client import MintEvent

logger = logging.getLogger(__name__)

EXPLORERS = {
    "ethereum": "https://etherscan.io/address",
    "base": "https://basescan.org/address",
    "arbitrum": "https://arbiscan.io/address",
}

OPENSEA_CHAIN_SLUG = {
    "ethereum": "ethereum",
    "base": "base",
    "arbitrum": "arbitrum",
}


def _explorer_url(event: MintEvent) -> str:
    base = EXPLORERS.get(event.chain, "https://etherscan.io/address")
    return f"{base}/{event.contract}"


def _opensea_url(event: MintEvent) -> str:
    slug = OPENSEA_CHAIN_SLUG.get(event.chain, "ethereum")
    return f"https://opensea.io/assets/{slug}/{event.contract}/{event.token_id}"


def _format_message(event: MintEvent) -> str:
    lines = [
        "🆕 <b>Похоже, новая коллекция</b>",
        f"Сеть: {event.chain}",
        f"Контракт: <code>{event.contract}</code>",
        f"Первый токен: #{event.token_id}",
        "",
        f"🔗 <a href='{_explorer_url(event)}'>Explorer</a>",
        f"🔗 <a href='{_opensea_url(event)}'>OpenSea</a>",
    ]
    return "\n".join(lines)


async def send_alert(event: MintEvent) -> None:
    if "PUT_YOUR" in config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — алерт не отправлен")
        return

    message = _format_message(event)
    url = f"https://api.telegram.org/bot{config.TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": config.TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }

    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(url, json=payload)
        if resp.status_code != 200:
            logger.error("Ошибка отправки в Telegram: %s", resp.text)
        else:
            logger.info("Алерт отправлен: %s (%s)", event.contract, event.chain)
