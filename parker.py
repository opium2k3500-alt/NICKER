"""
parker.py — парковка ников через Telegram-аккаунт.

Когда бот находит свободный ник, parker создаёт канал @nick —
ник «припаркован» и не может быть занят случайным человеком.
После продажи канал удаляется, покупатель сразу ставит себе ник.

Требует:
  PARKER_SESSION  — строка сессии (генерируется setup_parker.py)
  PARKER_API_ID   — int, из my.telegram.org
  PARKER_API_HASH — str, из my.telegram.org
"""

import os
import asyncio
import logging

logger = logging.getLogger(__name__)

PARKER_SESSION = os.getenv("PARKER_SESSION", "")
PARKER_API_ID  = int(os.getenv("PARKER_API_ID", "0"))
PARKER_API_HASH = os.getenv("PARKER_API_HASH", "")

_client = None
_client_lock = asyncio.Lock()


def is_configured() -> bool:
    return bool(PARKER_SESSION and PARKER_API_ID and PARKER_API_HASH)


async def get_client():
    global _client
    if not is_configured():
        return None
    async with _client_lock:
        if _client is not None:
            try:
                if _client.is_connected:
                    return _client
            except Exception:
                pass
        try:
            from pyrogram import Client
            _client = Client(
                name="parker",
                api_id=PARKER_API_ID,
                api_hash=PARKER_API_HASH,
                session_string=PARKER_SESSION,
                in_memory=True,
                no_updates=True,
            )
            await _client.start()
            me = await _client.get_me()
            logger.info(f"Parker client ready: @{me.username}")
            return _client
        except Exception as e:
            logger.error(f"Parker client error: {e}")
            _client = None
            return None


async def park_nick(username: str) -> int | None:
    """
    Создаёт канал @username. Возвращает channel_id или None при ошибке.
    Ники короче 5 букв пропускаем (Telegram не даёт им username).
    """
    if len(username) < 5:
        return None

    client = await get_client()
    if not client:
        return None

    try:
        from pyrogram.errors import FloodWait, UsernameOccupied, UsernameInvalid
        chat = await client.create_channel(
            title=f"@{username} — НИКЕР",
            description="Этот ник продаётся на НИКЕР. t.me/NICKERbot",
        )
        await asyncio.sleep(2)
        await client.set_chat_username(chat.id, username)
        logger.info(f"Parker: парковал @{username} → channel {chat.id}")
        return chat.id

    except Exception as e:
        err = str(e)
        if "FLOOD_WAIT" in err or "FloodWait" in err:
            # FloodWait — просто пропускаем этот ник сейчас
            logger.warning(f"Parker FloodWait на @{username}: {e}")
        elif "USERNAME_OCCUPIED" in err or "USERNAME_INVALID" in err:
            logger.info(f"Parker: @{username} занят или невалиден")
        else:
            logger.warning(f"Parker: не смог припарковать @{username}: {e}")
        return None


async def unpark_nick(channel_id: int) -> bool:
    """Удаляет парковочный канал. Покупатель может сразу занять ник."""
    if not channel_id:
        return False

    client = await get_client()
    if not client:
        return False

    try:
        await client.delete_channel(channel_id)
        logger.info(f"Parker: удалил канал {channel_id}")
        return True
    except Exception as e:
        logger.warning(f"Parker: не смог удалить канал {channel_id}: {e}")
        return False
