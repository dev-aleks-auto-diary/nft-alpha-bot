"""
NFT New Collections Bot — версия для GitHub Actions.

В отличие от main.py в локальной версии, тут НЕТ бесконечного цикла —
скрипт делает ОДИН проход (проверяет новые минты, шлёт алерты) и
завершается. GitHub Actions сам запускает его по расписанию (см.
.github/workflows/poll.yml), а состояние (последний обработанный блок)
сохраняется в файл bot_state.json, который workflow коммитит обратно
в репозиторий после каждого запуска.
"""

import asyncio
import json
import logging
from pathlib import Path

import config
from alchemy_client import fetch_mints_since, get_latest_block
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
    if chain in state:
        return
    latest = await get_latest_block(base_url)
    state[chain] = {"last_block": latest, "seen_tx": []}
    logger.info("Сеть %s: начинаем отслеживание с блока %d", chain, latest)


async def poll_chain(chain: str, base_url: str, state: dict) -> None:
    chain_state = state[chain]
    seen_tx = set(chain_state.get("seen_tx", []))

    events, max_block = await fetch_mints_since(chain, base_url, chain_state["last_block"])

    new_events = [e for e in events if e.unique_id not in seen_tx]
    logger.info("Сеть %s: %d кандидатов в новые коллекции", chain, len(new_events))

    for event in new_events:
        seen_tx.add(event.unique_id)
        try:
            await send_alert(event)
        except Exception as e:
            logger.warning("Не удалось отправить алерт по %s: %s", event.contract, e)
        await asyncio.sleep(1)

    if max_block is not None:
        chain_state["last_block"] = max_block + 1

    chain_state["seen_tx"] = list(seen_tx)[-5000:]


async def run_once() -> None:
    state = load_state()
    logger.info("Запуск проверки. Сети: %s", list(config.CHAINS.keys()))

    for chain, network_prefix in config.CHAINS.items():
        base_url = config.alchemy_url(network_prefix)
        try:
            await init_chain_state(chain, base_url, state)
            await poll_chain(chain, base_url, state)
        except Exception as e:
            logger.exception("Ошибка при опросе сети %s: %s", chain, e)

    save_state(state)
    logger.info("Проверка завершена")


if __name__ == "__main__":
    asyncio.run(run_once())
