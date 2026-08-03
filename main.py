"""
NFT New Collections Bot v2 — точка входа (одноразовый запуск, для GitHub Actions).

Логика в два этапа:

1. ДЕТЕКТ КАНДИДАТОВ: как и раньше, ищем минты с tokenId 0/1 — но теперь
   НЕ шлём алерт сразу, а кладём кандидата в очередь ожидания (state["pending"]).

2. ОЦЕНКА НА ЧЕКПОИНТАХ: вместо одной проверки в фиксированный момент —
   несколько контрольных точек с разным порогом (см. config.CHECKPOINTS).
   Ранний чекпоинт (15 минут) с низким порогом ловит вирусные проекты,
   которые распродаются за минуты. Более поздние чекпоинты (1ч, 6ч, 24ч)
   с более высоким порогом дают шанс медленно набирающим обороты, но
   реально качественным проектам. Кандидат проверяется на каждом
   чекпоинте по очереди — прошёл хоть один, получает алерт и выходит из
   очереди; не прошёл ни один вплоть до последнего — отбрасывается молча.

Запуск:
    pip install -r requirements.txt
    export TELEGRAM_BOT_TOKEN=... TELEGRAM_CHAT_ID=... ALCHEMY_API_KEY=... ETHERSCAN_API_KEY=...
    python main.py
"""

import asyncio
import json
import logging
import time
from pathlib import Path

import config
from alchemy_client import count_unique_minters, fetch_mints_since, get_latest_block, get_tx_value_eth
from etherscan_client import is_contract_verified
from telegram_notifier import send_alert

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("main")


def load_state() -> dict:
    path = Path(config.STATE_FILE)
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def save_state(state: dict) -> None:
    Path(config.STATE_FILE).write_text(json.dumps(state))


async def init_chain_state(chain: str, base_url: str, state: dict) -> None:
    if chain not in state:
        latest = await get_latest_block(base_url)
        state[chain] = {"last_block": latest, "seen_tx": [], "pending": {}}
        logger.info("Сеть %s: начинаем отслеживание с блока %d", chain, latest)
        return

    # Совместимость со старым state-файлом (до добавления фильтров качества)
    state[chain].setdefault("pending", {})
    state[chain].setdefault("seen_tx", [])


async def collect_candidates(chain: str, base_url: str, state: dict) -> None:
    """Этап 1: находим новых кандидатов и кладём их в очередь ожидания."""
    chain_state = state[chain]
    seen_tx = set(chain_state.get("seen_tx", []))

    events, max_block = await fetch_mints_since(chain, base_url, chain_state["last_block"])
    new_events = [e for e in events if e.unique_id not in seen_tx]
    logger.info("Сеть %s: %d новых кандидатов добавлено в очередь наблюдения", chain, len(new_events))

    for event in new_events:
        seen_tx.add(event.unique_id)
        chain_state["pending"][event.contract] = {
            "token_id": event.token_id,
            "tx_hash": event.tx_hash,
            "first_seen_block": event.block_num,
            "first_seen_time": time.time(),
        }

    if max_block is not None:
        chain_state["last_block"] = max_block + 1
    chain_state["seen_tx"] = list(seen_tx)[-5000:]


async def evaluate_pending(chain: str, base_url: str, state: dict) -> None:
    """
    Этап 2: проверяем кандидатов на чекпоинтах.

    Для каждого кандидата храним checkpoint_index — на каком чекпоинте
    он сейчас "стоит в очереди". Если прошло достаточно времени с
    первого минта — оцениваем на этом чекпоинте. Прошёл фильтры —
    алерт и удаляем из очереди. Не прошёл — если это был последний
    чекпоинт, отбрасываем совсем; иначе просто ждём следующего чекпоинта
    (индекс не увеличиваем сами — он выберется естественно по времени
    при следующем вызове, когда шаг проверки дойдёт до него).
    """
    chain_state = state[chain]
    pending = chain_state.get("pending", {})
    if not pending:
        return

    now = time.time()
    latest_block = await get_latest_block(base_url)
    still_pending = {}

    for contract, info in pending.items():
        age_seconds = now - info["first_seen_time"]

        # Находим самый поздний чекпоинт, время которого уже наступило
        checkpoint_idx = None
        for idx, (delay, _min_minters) in enumerate(config.CHECKPOINTS):
            if age_seconds >= delay:
                checkpoint_idx = idx

        already_checked = info.get("last_checkpoint_checked", -1)
        if checkpoint_idx is None or checkpoint_idx <= already_checked:
            still_pending[contract] = info  # рано, либо этот чекпоинт уже проверяли
            continue

        delay, min_minters_required = config.CHECKPOINTS[checkpoint_idx]
        logger.info(
            "Оцениваю кандидата %s (%s) на чекпоинте #%d (%d минут)",
            contract, chain, checkpoint_idx, delay // 60,
        )

        mint_price = await get_tx_value_eth(base_url, info["tx_hash"])
        minters = await count_unique_minters(base_url, contract, info["first_seen_block"], latest_block)
        verified = await is_contract_verified(contract)

        passed = True
        reasons_failed = []

        if config.MIN_MINT_PRICE_ETH > 0:
            if mint_price is None or mint_price < config.MIN_MINT_PRICE_ETH:
                passed = False
                reasons_failed.append(f"цена минта {mint_price} < {config.MIN_MINT_PRICE_ETH}")

        if minters < min_minters_required:
            passed = False
            reasons_failed.append(f"минтеров {minters} < {min_minters_required} (чекпоинт #{checkpoint_idx})")

        if config.REQUIRE_VERIFIED_CONTRACT and verified is False:
            passed = False
            reasons_failed.append("контракт не верифицирован")

        if passed:
            logger.info("✅ %s прошёл чекпоинт #%d — отправляю алерт", contract, checkpoint_idx)
            await send_alert(
                {
                    "chain": chain,
                    "contract": contract,
                    "token_id": info["token_id"],
                    "mint_price_eth": mint_price,
                    "unique_minters": minters,
                    "verified": verified,
                }
            )
            # прошёл — больше не наблюдаем, убираем из очереди
            continue

        is_last_checkpoint = checkpoint_idx == len(config.CHECKPOINTS) - 1
        if is_last_checkpoint:
            logger.info("❌ %s отсеян окончательно (последний чекпоинт): %s", contract, "; ".join(reasons_failed))
            # не проваливаем: не добавляем обратно в still_pending — кандидат отброшен
        else:
            logger.info(
                "⏳ %s не прошёл чекпоинт #%d (%s), ждём следующий",
                contract, checkpoint_idx, "; ".join(reasons_failed),
            )
            info["last_checkpoint_checked"] = checkpoint_idx
            still_pending[contract] = info

    chain_state["pending"] = still_pending


async def run_once() -> None:
    state = load_state()
    logger.info("Запуск проверки. Сети: %s", list(config.CHAINS.keys()))

    for chain, network_prefix in config.CHAINS.items():
        base_url = config.alchemy_url(network_prefix)
        try:
            await init_chain_state(chain, base_url, state)
            await collect_candidates(chain, base_url, state)
            await evaluate_pending(chain, base_url, state)
        except Exception as e:
            logger.exception("Ошибка при обработке сети %s: %s", chain, e)

    save_state(state)
    logger.info("Проверка завершена")


if __name__ == "__main__":
    asyncio.run(run_once())
