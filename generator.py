"""
generator.py
Генерирует крутые ники через Claude API, проверяет доступность
через t.me и автоматически пополняет каталог.
"""

import asyncio
import aiohttp
import logging
import re
import json
import os
import random
from datetime import datetime

logger = logging.getLogger(__name__)

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CHECK_CONCURRENCY = 5   # сколько ников проверять параллельно
CATALOG_TARGET = 30     # сколько ников держать в каталоге
GENERATE_BATCH = 40     # сколько генерировать за раз

HEADERS_TG = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                  "AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/124.0 Safari/537.36"
}

# ── Категории и промпты ──────────────────────

CATEGORIES = {
    "Природа":      ("wolf bear fox eagle hawk raven storm snow ice fire rain thunder"
                     " river stone moon sun", "#2d9e5e"),
    "Статус":       ("king boss alpha elite prime vip rex apex titan lord chief"
                     " legend crown gold", "#c0a030"),
    "Технологии":   ("neo dev hack byte code pixel zero void cyber dark matrix"
                     " shell root kernel", "#5b8dd9"),
    "Стиль":        ("cool vibe raw pure mono mute zen ghost stealth onyx noir"
                     " blaze flux edge", "#9b5de5"),
    "Финансы":      ("rich cash flux coin mint gain profit vault fund stack"
                     " yield asset trade", "#e56b2d"),
    "Космос":       ("nova star orbit comet void nebula pulse quasar zenith"
                     " apex dawn dusk rise", "#4ecdc4"),
    "Имена":        ("max leo kai rex zara nora mila ivan luka alex kira"
                     " dima mike jake", "#e84393"),
    "Премиум":      ("x pro one a the i", "#ffffff"),
}


async def generate_usernames_ai(count: int = GENERATE_BATCH) -> list[dict]:
    """
    Просит Claude придумать крутые короткие ники.
    Возвращает список { username, category, readability, uniqueness, reason }
    """
    if not ANTHROPIC_KEY:
        return _generate_local(count)

    prompt = f"""Придумай {count} крутых Telegram-юзернеймов для продажи.

ПРАВИЛА:
- Только латинские буквы и цифры, без пробелов
- Длина от 3 до 12 символов
- Никаких подчёркиваний
- Короткие (3-6 букв) ценятся выше
- Должны звучать круто, быть запоминаемыми
- Категории: Природа, Статус, Технологии, Стиль, Финансы, Космос, Имена, Премиум

Верни ТОЛЬКО JSON массив без пояснений:
[
  {{"username": "volk", "category": "Природа", "readability": 9, "uniqueness": 8, "reason": "короткое, мощное слово"}},
  ...
]

Придумывай оригинально — не только популярные слова, но и крутые комбинации типа zerov, noxe, kael, ryvn, luxo."""

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.anthropic.com/v1/messages",
                headers={
                    "x-api-key": ANTHROPIC_KEY,
                    "anthropic-version": "2023-06-01",
                    "content-type": "application/json",
                },
                json={
                    "model": "claude-haiku-4-5-20251001",
                    "max_tokens": 2000,
                    "messages": [{"role": "user", "content": prompt}]
                },
                timeout=aiohttp.ClientTimeout(total=30)
            ) as resp:
                data = await resp.json()
                text = data["content"][0]["text"]
                # вырезаем JSON из ответа
                match = re.search(r'\[.*\]', text, re.DOTALL)
                if match:
                    items = json.loads(match.group())
                    # валидация
                    result = []
                    for item in items:
                        u = item.get("username", "").lower().strip()
                        if re.match(r'^[a-z][a-z0-9]{2,11}$', u):
                            result.append({
                                "username":    u,
                                "category":    item.get("category", "Стиль"),
                                "readability": int(item.get("readability", 7)),
                                "uniqueness":  int(item.get("uniqueness", 7)),
                                "reason":      item.get("reason", ""),
                            })
                    logger.info(f"AI generated {len(result)} valid usernames")
                    return result
    except Exception as e:
        logger.error(f"AI generation error: {e}")

    return _generate_local(count)


def _generate_local(count: int) -> list[dict]:
    """Локальная генерация если нет API ключа."""
    prefixes = ["x","z","neo","rex","vox","nox","kael","ryvn","luxo","zero",
                "nova","dark","iron","wolf","hawk","byte","code","void","flux"]
    suffixes = ["","x","z","o","a","us","ix","ex","ar","on","an","yr","ox"]
    words = {
        "Природа":    ["wolf","bear","fox","hawk","eagle","storm","snow","ice","fire","rain","stone","moon"],
        "Статус":     ["king","boss","alpha","elite","prime","vip","rex","apex","titan","lord","chief"],
        "Технологии": ["neo","dev","byte","code","pixel","zero","void","cyber","dark","shell","root"],
        "Стиль":      ["cool","vibe","raw","pure","mono","zen","ghost","stealth","onyx","noir","blaze"],
        "Финансы":    ["rich","cash","coin","mint","gain","vault","fund","stack","yield","asset"],
        "Космос":     ["nova","star","orbit","comet","pulse","zenith","dawn","dusk","rise","glow"],
        "Имена":      ["max","leo","kai","zara","nora","mila","luka","alex","kira","dima","jake"],
        "Премиум":    ["x","pro","one","a"],
    }

    result = []
    seen = set()
    attempts = 0

    while len(result) < count and attempts < count * 10:
        attempts += 1
        cat = random.choice(list(words.keys()))
        pool = words[cat]

        mode = random.randint(0, 3)
        if mode == 0:
            u = random.choice(pool)
        elif mode == 1:
            u = random.choice(prefixes) + random.choice(pool)
        elif mode == 2:
            u = random.choice(pool) + random.choice(suffixes)
        else:
            # два коротких слова
            w1 = random.choice(pool)
            w2 = random.choice(pool)
            if w1 != w2:
                u = w1 + w2

        u = u.lower()
        if u in seen or not re.match(r'^[a-z][a-z0-9]{2,11}$', u):
            continue
        seen.add(u)

        read = 9 if len(u) <= 4 else 8 if len(u) <= 6 else 7 if len(u) <= 8 else 6
        uniq = 9 if len(u) <= 4 else 7 if len(u) <= 6 else 6

        result.append({
            "username":   u,
            "category":   cat,
            "readability": read,
            "uniqueness":  uniq,
            "reason":      "local generation",
        })

    return result


# ── Проверка доступности ─────────────────────

async def check_available(session: aiohttp.ClientSession, username: str) -> bool:
    """
    Проверяет свободен ли ник через t.me/username.
    Свободный ник — страница без og:title профиля / редирект на главную.
    """
    try:
        url = f"https://t.me/{username}"
        async with session.get(
            url,
            timeout=aiohttp.ClientTimeout(total=8),
            allow_redirects=True,
            headers=HEADERS_TG
        ) as resp:
            # Редирект на telegram.org = ник не существует = свободен
            if "telegram.org" in str(resp.url) and "t.me" not in str(resp.url):
                return True

            html = await resp.text()

            # Занятый профиль имеет og:title с реальным именем
            has_profile = bool(re.search(
                r'<meta property="og:title" content=".{3,}"', html, re.I
            ))
            # Страница с предложением "View in Telegram" без профиля = группа/канал
            # но без имени пользователя в og:title — может быть свободен
            is_free = not has_profile

            return is_free

    except Exception:
        return False  # при ошибке не добавляем — лучше пропустить


async def check_batch(usernames: list[str]) -> dict[str, bool]:
    """Проверяет список ников параллельно, возвращает {username: is_free}."""
    sem = asyncio.Semaphore(CHECK_CONCURRENCY)
    results = {}

    async with aiohttp.ClientSession(headers=HEADERS_TG) as session:
        async def check_one(u):
            async with sem:
                free = await check_available(session, u)
                results[u] = free
                await asyncio.sleep(0.3)  # небольшая пауза между запросами

        await asyncio.gather(*[check_one(u) for u in usernames])

    return results


# ── Оценка цены ──────────────────────────────

def calc_price(username: str, readability: int, uniqueness: int) -> int:
    """Считает цену в Stars. Комиссия Telegram 30% уже включена."""
    l = len(username)

    if l <= 3:   length_score = 10
    elif l <= 4: length_score = 9
    elif l <= 5: length_score = 8
    elif l <= 6: length_score = 7
    elif l <= 8: length_score = 5
    else:        length_score = 3

    weighted = (length_score * 0.45 + readability * 0.35 + uniqueness * 0.20)
    raw = 100 + ((weighted / 10) ** 2.8) * 9900
    with_commission = raw * 1.30
    rounded = round(with_commission / 50) * 50
    return max(100, min(10000, int(rounded)))


# ── Главная функция автопополнения ───────────

async def autofill_catalog(db_module) -> dict:
    """
    Генерирует ники → проверяет доступность → добавляет свободные в каталог.
    Вызывать периодически из фонового воркера.
    Возвращает { generated, checked, added }
    """
    from database import get_catalog, add_username

    current = get_catalog()
    available_count = len(current)

    if available_count >= CATALOG_TARGET:
        logger.info(f"Catalog full ({available_count}/{CATALOG_TARGET}), skipping")
        return {"generated": 0, "checked": 0, "added": 0}

    need = CATALOG_TARGET - available_count + 10  # с запасом

    # Получаем уже существующие ники чтобы не дублировать
    existing = {r["username"] for r in current}

    logger.info(f"Generating {GENERATE_BATCH} username ideas...")
    candidates = await generate_usernames_ai(GENERATE_BATCH)

    # Убираем уже существующие
    candidates = [c for c in candidates if c["username"] not in existing]

    if not candidates:
        return {"generated": 0, "checked": 0, "added": 0}

    logger.info(f"Checking availability of {len(candidates)} usernames...")
    usernames_to_check = [c["username"] for c in candidates]
    availability = await check_batch(usernames_to_check)

    added = 0
    cand_map = {c["username"]: c for c in candidates}

    for username, is_free in availability.items():
        if not is_free:
            continue
        if added >= need:
            break

        info = cand_map[username]
        price = calc_price(username, info["readability"], info["uniqueness"])

        success = add_username(
            username=username,
            price=price,
            category=info["category"],
            readability=info["readability"],
            uniqueness=info["uniqueness"],
            description=info.get("reason", ""),
        )
        if success:
            added += 1
            logger.info(f"  ✓ Added @{username} ({price}⭐, {info['category']})")

    logger.info(f"Autofill done: generated={len(candidates)}, "
                f"free={sum(availability.values())}, added={added}")

    return {
        "generated": len(candidates),
        "checked":   len(availability),
        "free":      sum(availability.values()),
        "added":     added,
    }
