"""
Клиент Alchemy Transfers API.

Логика: ищем ERC-721/ERC-1155 переводы, у которых `from` — нулевой адрес
(это и есть минт — токен только что создан). Если у такого перевода
tokenId маленький (0 или 1) — это, с высокой вероятностью, самый первый
токен в только что запущенной коллекции.

Документация метода: alchemy_getAssetTransfers
https://www.alchemy.com/docs/data/transfers-api/transfers-endpoints/alchemy-get-asset-transfers
"""

import logging
from dataclasses import dataclass

import httpx

import config

logger = logging.getLogger(__name__)

ZERO_ADDRESS = "0x0000000000000000000000000000000000000000"


@dataclass
class MintEvent:
    chain: str
    contract: str
    token_id: int
    tx_hash: str
    unique_id: str
    to_address: str
    block_num: int
    asset_name: str | None


def _hex_to_int(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value, 16)
    except (ValueError, TypeError):
        return None


async def get_latest_block(base_url: str) -> int:
    payload = {"jsonrpc": "2.0", "id": 1, "method": "eth_blockNumber", "params": []}
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.post(base_url, json=payload)
    data = resp.json()
    return int(data["result"], 16)


async def fetch_mints_since(chain: str, base_url: str, from_block: int) -> tuple[list[MintEvent], int | None]:
    """
    Возвращает (список минтов, номер последнего обработанного блока).
    Если новых транзакций нет — второй элемент будет None.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": hex(from_block),
                "toBlock": "latest",
                "category": ["erc721", "erc1155"],
                "fromAddress": ZERO_ADDRESS,
                "withMetadata": False,
                "excludeZeroValue": False,
                "order": "asc",
                "maxCount": hex(config.MAX_TRANSFERS_PER_POLL),
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(base_url, json=payload)

    if resp.status_code != 200:
        logger.error("Alchemy API ошибка (%s, %s): %s", chain, resp.status_code, resp.text[:300])
        return [], None

    data = resp.json()
    if "error" in data:
        logger.error("Alchemy API вернул ошибку (%s): %s", chain, data["error"])
        return [], None

    raw_transfers = data.get("result", {}).get("transfers", [])

    events: list[MintEvent] = []
    max_block: int | None = None

    for t in raw_transfers:
        block_num = _hex_to_int(t.get("blockNum"))
        if block_num is not None:
            max_block = block_num if max_block is None else max(max_block, block_num)

        token_id_hex = t.get("erc721TokenId") or (t.get("tokenId"))
        token_id = _hex_to_int(token_id_hex)
        if token_id is None:
            continue  # erc1155 batch-переводы без явного одиночного tokenId — пропускаем в MVP

        if token_id > config.GENESIS_TOKEN_ID_MAX:
            continue  # не самый первый токен — не считаем сигналом "новая коллекция"

        contract = (t.get("rawContract") or {}).get("address")
        if not contract:
            continue

        events.append(
            MintEvent(
                chain=chain,
                contract=contract,
                token_id=token_id,
                tx_hash=t.get("hash", ""),
                unique_id=t.get("uniqueId", t.get("hash", "")),
                to_address=t.get("to", ""),
                block_num=block_num or from_block,
                asset_name=t.get("asset"),
            )
        )

    return events, max_block
