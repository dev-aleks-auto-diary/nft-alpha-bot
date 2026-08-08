"""
Отправка алертов о новых коллекциях в Telegram (v2).
"""

import logging

import httpx

import config

logger = logging.getLogger(__name__)

EXPLORERS = {
    "ethereum": "https://etherscan.io/address",
    "apechain": "https://apescan.io/address",
    "robinhood": "https://robinhoodchain.blockscout.com/address",
}


def _explorer_url(chain: str, contract: str) -> str:
    base = EXPLORERS.get(chain, "https://etherscan.io/address")
    return f"{base}/{contract}"


def _opensea_url(chain: str, contract: str, token_id: int) -> str:
    return f"https://opensea.io/assets/{chain}/{contract}/{token_id}"


MECHANIC_LABELS = {
    "vault_lock": "🔒 Vault/lock — заморозка NFT навсегда",
    "buyback": "💰 Buyback — выкуп командой",
    "burn_to_mint": "🔥 Burn-to-mint",
    "revenue_share": "📈 Revenue share",
}


def _format_message(candidate: dict) -> str:
    mechanics = candidate.get("mechanics") or []

    lines = ["🎯 <b>Обнаружена особая механика!</b>"]
    for m in mechanics:
        lines.append(MECHANIC_LABELS.get(m, m))
    lines.append("")

    lines += [
        f"Сеть: {candidate['chain']}",
        f"Контракт: <code>{candidate['contract']}</code>",
        "",
        f"🔗 <a href='{_explorer_url(candidate['chain'], candidate['contract'])}'>Explorer</a>",
        f"🔗 <a href='{_opensea_url(candidate['chain'], candidate['contract'], candidate['token_id'])}'>OpenSea</a>",
    ]

    return "\n".join(lines)


async def send_alert(candidate: dict) -> None:
    if "PUT_YOUR" in config.TELEGRAM_BOT_TOKEN:
        logger.warning("TELEGRAM_BOT_TOKEN не задан — алерт не отправлен")
        return

    message = _format_message(candidate)
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
            logger.info("Алерт отправлен: %s (%s)", candidate["contract"], candidate["chain"])
