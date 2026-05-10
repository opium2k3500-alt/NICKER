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

PARKER_SESSION  = os.getenv("PARKER_SESSION", "")
PARKER_API_ID   = int(os.getenv("PARKER_API_ID", "0") or "0")
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


async def _oneshot(coro_fn):
    """Runs a coroutine with a fresh Pyrogram client — safe to call from Flask/asyncio.run()."""
    if not is_configured():
        return None
    from pyrogram import Client
    async with Client(
        name="parker_oneshot",
        api_id=PARKER_API_ID,
        api_hash=PARKER_API_HASH,
        session_string=PARKER_SESSION,
        in_memory=True,
        no_updates=True,
    ) as client:
        return await coro_fn(client)


async def park_nick_oneshot(username: str) -> int | None:
    """For use from Flask (asyncio.run). Creates its own client."""
    async def _do(client):
        bot_username = os.getenv("BOT_USERNAME", "findyuruser_bot").lstrip("@")
        desc = f"Этот ник продаётся в магазине НИКЕР. @{bot_username}"
        try:
            from pyrogram.errors import FloodWait
            existing = None
            try:
                existing = await client.get_chat(username)
            except Exception:
                pass
            if existing and getattr(existing, 'username', '').lower() == username.lower():
                logger.info(f"Parker oneshot: уже владеем @{username} → {existing.id}")
                return existing.id
            chat = await client.create_channel(title=f"@{username}", description=desc)
            await asyncio.sleep(3)
            await client.set_chat_username(chat.id, username)
            logger.info(f"Parker oneshot: парковал @{username} → {chat.id}")
            return chat.id
        except Exception as e:
            logger.warning(f"Parker oneshot error for @{username}: {e}")
            return None
    try:
        return await _oneshot(_do)
    except Exception as e:
        logger.error(f"Parker oneshot failed: {e}")
        return None


async def sync_channels_oneshot() -> tuple[list, int]:
    """For use from Flask. Returns (named_channels, orphans_deleted)."""
    async def _do(client):
        from pyrogram.enums import ChatType
        named   = []
        orphans = 0
        async for dialog in client.get_dialogs():
            try:
                chat = dialog.chat
                if chat.type not in (ChatType.CHANNEL, ChatType.SUPERGROUP):
                    continue
                if chat.username:
                    named.append({"username": chat.username.lower(), "id": chat.id})
                else:
                    try:
                        await client.delete_channel(chat.id)
                        orphans += 1
                    except Exception:
                        pass
            except Exception:
                pass
        return named, orphans
    return await _oneshot(_do)


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

    bot_username = os.getenv("BOT_USERNAME", "findyuruser_bot").lstrip("@")
    desc = f"Этот ник продаётся в магазине НИКЕР. @{bot_username}"

    chat = None
    try:
        from pyrogram.errors import FloodWait, UsernameOccupied, UsernameInvalid

        # Check if we already own a channel with this username
        try:
            existing = await client.get_chat(username)
            if existing and hasattr(existing, 'username') and existing.username and existing.username.lower() == username.lower():
                logger.info(f"Parker: уже владеем каналом @{username} → {existing.id}")
                return existing.id
        except Exception:
            pass

        chat = await client.create_channel(title=f"@{username}", description=desc)
        await asyncio.sleep(3)
        await client.set_chat_username(chat.id, username)
        logger.info(f"Parker: парковал @{username} → channel {chat.id}")
        return chat.id

    except Exception as e:
        err = str(e)
        if chat:
            try:
                await client.delete_channel(chat.id)
                logger.info(f"Parker: удалил orphan канал для @{username}")
            except Exception:
                pass
        if "FLOOD_WAIT" in err or "FloodWait" in err:
            logger.warning(f"Parker FloodWait на @{username}: {e}")
        elif "USERNAME_OCCUPIED" in err or "USERNAME_INVALID" in err:
            logger.info(f"Parker: @{username} занят или невалиден — пропускаем")
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
