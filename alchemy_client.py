"""
Клиент Alchemy Transfers API.

Три задачи:
1. fetch_mints_since — находит кандидатов в "новую коллекцию" (минт с
   нулевого адреса, tokenId 0/1), как и раньше.
2. get_tx_value — узнаёт, сколько ETH было заплачено в транзакции минта
   (для фильтра "цена минта > 0").
3. count_unique_minters — считает, сколько разных адресов заминтили
   коллекцию за период наблюдения (для фильтра "не менее N минтеров").
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


async def _rpc_call(base_url: str, method: str, params: list) -> dict:
    payload = {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(base_url, json=payload)
    return resp.json()


async def get_latest_block(base_url: str) -> int:
    data = await _rpc_call(base_url, "eth_blockNumber", [])
    return int(data["result"], 16)


async def fetch_mints_since(chain: str, base_url: str, from_block: int) -> tuple[list[MintEvent], int | None]:
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
                "withMetadata": True,
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

        token_id_hex = t.get("erc721TokenId")
        token_id = _hex_to_int(token_id_hex)

        if token_id is None:
            # ERC-1155 может минтить пачкой — тогда одиночного tokenId нет,
            # а есть список erc1155Metadata с несколькими tokenId сразу.
            # Берём минимальный tokenId из пачки: если среди заминченных
            # в этой транзакции токенов есть genesis-номер — считаем это
            # тем же сигналом "похоже на самый первый минт коллекции".
            batch = t.get("erc1155Metadata") or []
            batch_ids = [_hex_to_int(item.get("tokenId")) for item in batch]
            batch_ids = [b for b in batch_ids if b is not None]
            if not batch_ids:
                continue
            token_id = min(batch_ids)

        if token_id > config.GENESIS_TOKEN_ID_MAX:
            continue

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


async def get_tx_value_eth(base_url: str, tx_hash: str) -> float | None:
    """Сколько ETH было отправлено в транзакции (цена минта, если платили напрямую)."""
    data = await _rpc_call(base_url, "eth_getTransactionByHash", [tx_hash])
    result = data.get("result")
    if not result:
        return None
    value_wei = _hex_to_int(result.get("value"))
    if value_wei is None:
        return None
    return value_wei / 1e18


async def count_unique_minters(base_url: str, contract: str, from_block: int, to_block: int) -> int:
    """Считает уникальные адреса, которые заминтили токены этого контракта в диапазоне блоков."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "alchemy_getAssetTransfers",
        "params": [
            {
                "fromBlock": hex(from_block),
                "toBlock": hex(to_block),
                "category": ["erc721", "erc1155"],
                "fromAddress": ZERO_ADDRESS,
                "contractAddresses": [contract],
                "withMetadata": False,
                "order": "asc",
                "maxCount": hex(config.MAX_TRANSFERS_PER_POLL),
            }
        ],
    }

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(base_url, json=payload)

    if resp.status_code != 200:
        logger.warning("Ошибка подсчёта минтеров для %s: %s", contract, resp.text[:200])
        return 0

    data = resp.json()
    transfers = data.get("result", {}).get("transfers", [])
    unique_addresses = {t.get("to") for t in transfers if t.get("to")}
    return len(unique_addresses)
