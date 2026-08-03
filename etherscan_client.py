"""
Проверка через Etherscan: верифицирован ли контракт (есть ли открытый
исходный код). Спам/шаблонные коллекции часто вообще не верифицируют
контракт — это дешёвый, но полезный фильтр качества.
"""

import logging

import httpx

import config

logger = logging.getLogger(__name__)


async def is_contract_verified(contract_address: str) -> bool | None:
    """
    True — верифицирован, False — не верифицирован, None — не удалось
    проверить (например, не задан ключ или ошибка сети). При None фильтр
    в main.py не блокирует алерт, чтобы не терять сигналы из-за сбоя API.
    """
    if not config.ETHERSCAN_API_KEY or "PUT_YOUR" in config.ETHERSCAN_API_KEY:
        logger.warning("ETHERSCAN_API_KEY не задан — пропускаю проверку верификации")
        return None

    params = {
        "module": "contract",
        "action": "getsourcecode",
        "address": contract_address,
        "apikey": config.ETHERSCAN_API_KEY,
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(config.ETHERSCAN_API_URL, params=params)
        data = resp.json()
    except Exception as e:
        logger.warning("Ошибка запроса к Etherscan для %s: %s", contract_address, e)
        return None

    if data.get("status") != "1" or not data.get("result"):
        return None

    source_code = data["result"][0].get("SourceCode", "")
    return bool(source_code.strip())
