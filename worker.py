"""
worker.py — фоновые задачи:
  • каждые 30 мин генерирует/проверяет/добавляет ники
  • каждую минуту снимает просроченные резервации
  • при добавлении ника уведомляет подписчиков
"""

import asyncio
import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)

AUTOFILL_INTERVAL = int(os.getenv("AUTOFILL_INTERVAL", "1800"))   # 30 минут
RESERVE_CHECK_INTERVAL = 60                                         # 1 минута


class Worker:
    def __init__(self, bot):
        self.bot = bot   # telegram.Bot instance
        self.running = False

    async def start(self):
        self.running = True
        logger.info("Worker started")
        await asyncio.gather(
            self._loop_autofill(),
            self._loop_reservations(),
        )

    def stop(self):
        self.running = False

    # ── Автопополнение каталога ──────────────

    async def _loop_autofill(self):
        # Первый запуск через 10 секунд после старта
        await asyncio.sleep(10)
        while self.running:
            try:
                await self._do_autofill()
            except Exception as e:
                logger.error(f"Autofill error: {e}")
            await asyncio.sleep(AUTOFILL_INTERVAL)

    async def _do_autofill(self):
        from generator import autofill_catalog
        import database as db_mod

        logger.info("Starting autofill cycle...")
        result = await autofill_catalog(db_mod)
        logger.info(f"Autofill: {result}")

        # Уведомить подписчиков о новых никах
        if result.get("added", 0) > 0:
            await self._notify_watchers_for_new_items()

    async def _notify_watchers_for_new_items(self):
        """После каждого автофилла проверяем — появились ли ники из вотчлистов."""
        from database import get_catalog, watch_get_subscribers, watch_remove

        catalog = get_catalog()
        catalog_names = {item["username"] for item in catalog}

        # Получаем все уникальные ники из вотчлистов
        import sqlite3, os
        db_path = os.getenv("DB_PATH", "market.db")
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT DISTINCT username FROM watchlist")
        watched = [r["username"] for r in cur.fetchall()]
        conn.close()

        for username in watched:
            if username not in catalog_names:
                continue

            # Этот ник теперь в каталоге — уведомляем подписчиков
            subs = watch_get_subscribers(username)
            item = next((i for i in catalog if i["username"] == username), None)
            if not item:
                continue

            for user_id in subs:
                try:
                    await self.bot.send_message(
                        chat_id=user_id,
                        text=(
                            f"🔔 <b>Ник появился в продаже!</b>\n\n"
                            f"<code>@{username}</code> теперь доступен.\n"
                            f"💫 Цена: <b>{item['price']} ⭐</b>\n"
                            f"📂 Категория: {item['category']}\n\n"
                            f"Открой магазин чтобы купить!"
                        ),
                        parse_mode="HTML"
                    )
                    # Удаляем из вотчлиста после уведомления
                    watch_remove(user_id, username)
                    logger.info(f"Notified user {user_id} about @{username}")
                except Exception as e:
                    logger.warning(f"Failed to notify {user_id}: {e}")

    # ── Снятие резерваций ────────────────────

    async def _loop_reservations(self):
        while self.running:
            try:
                from database import release_expired
                n = release_expired()
                if n:
                    logger.info(f"Released {n} expired reservations")
            except Exception as e:
                logger.error(f"Reservation release error: {e}")
            await asyncio.sleep(RESERVE_CHECK_INTERVAL)
