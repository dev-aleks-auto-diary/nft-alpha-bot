"""
Клиент GoPlus Security API — доп. проверка NFT-контракта на признаки скама.

В отличие от простой "верифицирован/не верифицирован" на Etherscan, GoPlus
конкретно ищет вредоносные паттерны: возможность украсть чужой NFT без
апрува (sleep minting), самоуничтожение контракта, минт сверх заявленного
лимита и т.д.

Бесплатно, без обязательного API-ключа (при желании можно добавить —
увеличивает лимит запросов). Поддерживает ограниченный список сетей
(в основном крупные EVM-чейны) — для остальных просто возвращаем None
("нет данных"), это НЕ блокирует алерт.

Документация: https://docs.gopluslabs.io/reference/nft-security-api
"""

import logging

import httpx

import config

logger = logging.getLogger(__name__)

GOPLUS_API_URL = "https://api.gopluslabs.io/api/v1/nft_security/{chain_id}"


def _risk_flagged(value) -> bool:
    """
    Некоторые поля GoPlus — просто "1"/"0", другие — вложенный объект
    вида {"value": "1", "owner_address": ..., "owner_type": "eoa"}.
    Приводим оба варианта к простому True/False.
    """
    if value is None:
        return False
    if isinstance(value, dict):
        value = value.get("value")
    return str(value) == "1"


async def check_nft_security(chain: str, contract: str) -> dict | None:
    """
    Возвращает словарь с найденными рисками (пустой — если рисков нет),
    либо None, если сеть не поддерживается GoPlus или запрос не удался
    (в обоих случаях это НЕ повод отбрасывать кандидата — просто нет данных).
    """
    chain_id = config.GOPLUS_CHAIN_IDS.get(chain)
    if chain_id is None:
        return None  # сеть не поддерживается GoPlus — молча пропускаем

    url = GOPLUS_API_URL.format(chain_id=chain_id)
    params = {"contract_addresses": contract}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(url, params=params)
        data = resp.json()
    except Exception as e:
        logger.warning("Ошибка запроса к GoPlus для %s: %s", contract, e)
        return None

    if data.get("code") != 1:
        return None

    result = data.get("result", {})
    entry = result.get(contract.lower()) or result.get(contract)
    if not entry:
        return None

    risks = {}
    if _risk_flagged(entry.get("malicious_nft_contract")):
        risks["malicious_nft_contract"] = "контракт уже замечен в злонамеренных действиях"
    if entry.get("nft_open_source") == "0":
        risks["not_open_source"] = "контракт не открыт (нет исходного кода)"
    if _risk_flagged(entry.get("transfer_without_approval")):
        risks["transfer_without_approval"] = "может передавать чужие NFT без апрува (sleep minting)"
    if _risk_flagged(entry.get("self_destruct")):
        risks["self_destruct"] = "контракт может самоуничтожиться"
    if _risk_flagged(entry.get("oversupply_minting")):
        risks["oversupply_minting"] = "минт может превысить заявленный лимит"

    return risks
