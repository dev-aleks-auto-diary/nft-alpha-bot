"""
NFT New Collections Bot v2 — точка входа (одноразовый запуск, для GitHub Actions).

Упрощённая логика (по договорённости — только один способ обнаружения):

1. ДЕТЕКТ КАНДИДАТОВ: ищем минты с tokenId 0/1 (в том числе внутри пачки
   ERC-1155) — это сигнал "похоже на самый первый минт новой коллекции".
   Не шлём алерт сразу, а кладём кандидата в очередь ожидания.

2. ПРОВЕРКА НА МЕХАНИКИ: на каждом запуске смотрим исходник контракта
   (через Etherscan, поддерживается только Ethereum) на ключевые слова
   конкретных механик — vault/lock, buyback, burn-to-mint, revenue-share
   (см. config.MECHANIC_KEYWORDS). Нашли — и GoPlus не считает контракт
   рискованным — шлём алерт сразу. Не нашли (например, контракт ещё не
   успели верифицировать) — ждём следующего запуска и проверяем заново,
   пока не пройдёт config.MAX_CANDIDATE_AGE_SECONDS — тогда молча отбрасываем.

Никакой оценки по числу минтеров/популярности больше нет — единственный
критерий "это интересно" — конкретная механика в коде контракта.

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
from alchemy_client import fetch_mints_since, get_latest_block
from etherscan_client import find_mechanic_keywords
from goplus_client import check_nft_security
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

    # Совместимость со старым state-файлом
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


async def evaluate_pending(chain: str, state: dict) -> None:
    """
    Этап 2: проверяем кандидатов на ключевые слова механик.

    Проверка контракта возможна только там, где Etherscan знает исходник
    (config.MECHANIC_CHECK_CHAINS) — для остальных сетей кандидат просто
    ждёт истечения MAX_CANDIDATE_AGE_SECONDS и тихо отбрасывается, так как
    альтернативного способа оценки в этой версии нет.
    """
    chain_state = state[chain]
    pending = chain_state.get("pending", {})
    if not pending:
        return

    now = time.time()
    still_pending = {}
    can_check_mechanics = chain in config.MECHANIC_CHECK_CHAINS

    for contract, info in pending.items():
        age_seconds = now - info["first_seen_time"]

        mechanics_found = []
        if can_check_mechanics:
            mechanics_found = await find_mechanic_keywords(contract)

        if mechanics_found:
            goplus_risks = await check_nft_security(chain, contract)
            if goplus_risks:
                logger.info(
                    "⚠️ %s: механика %s найдена, но GoPlus нашёл риски — не шлём: %s",
                    contract, mechanics_found, "; ".join(goplus_risks.values()),
                )
            else:
                logger.info("🎯 %s: обнаружена механика %s — отправляю алерт", contract, mechanics_found)
                await send_alert(
                    {
                        "chain": chain,
                        "contract": contract,
                        "token_id": info["token_id"],
                        "mechanics": mechanics_found,
                    }
                )
                continue  # прошёл — из очереди убираем

        if age_seconds >= config.MAX_CANDIDATE_AGE_SECONDS:
            logger.info("❌ %s отсеян окончательно (истёк максимальный возраст, механик не найдено)", contract)
            # не добавляем обратно в still_pending — кандидат отброшен
        else:
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
            await evaluate_pending(chain, state)
        except Exception as e:
            logger.exception("Ошибка при обработке сети %s: %s", chain, e)

    save_state(state)
    logger.info("Проверка завершена")


if __name__ == "__main__":
    asyncio.run(run_once())
