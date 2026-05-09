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


def _no_repeat(s: str) -> bool:
    """True если в строке нет повторяющихся символов."""
    return len(set(s)) == len(s)


def _generate_local(count: int) -> list[dict]:
    """
    Генерирует нестандартные произносимые ники БЕЗ повторяющихся букв.
    4-5 символов — приоритет. Никаких популярных слов.
    """
    consonants = list("bcdfghjklmnpqrstvwxyz")
    vowels     = list("aeiou")

    # Паттерны (C=согласная, V=гласная, D=цифра)
    patterns = [
        "CVCV",   # keva, zoli, mabe  — 4 буквы
        "CVCC",   # kelt, zorn, vark
        "CCVC",   # zkol, brex, kliv
        "CVCVC",  # kevan, zolik, maber — 5 букв
        "CVCCV",  # kelto, varke, mirba
        "CCVCV",  # zkola, brexo, klive
        "CVC",    # kev, zol, mir — 3 буквы (редко, дорого)
        "CVCD",   # kev3, zol9 — с цифрой
        "CVCVD",  # keva3, zoli9
    ]
    # Веса: 4-буквенные приоритетны
    weights = [30, 20, 20, 25, 15, 10, 5, 15, 10]

    categories = list(CATEGORIES.keys())
    result = []
    seen   = set()
    attempts = 0

    while len(result) < count and attempts < count * 60:
        attempts += 1
        pattern = random.choices(patterns, weights=weights)[0]

        used_chars = set()
        u = ""
        valid = True

        for ch in pattern:
            if ch == "C":
                pool = [c for c in consonants if c not in used_chars]
                if not pool: valid = False; break
                c = random.choice(pool)
                u += c; used_chars.add(c)
            elif ch == "V":
                pool = [v for v in vowels if v not in used_chars]
                if not pool: valid = False; break
                v = random.choice(pool)
                u += v; used_chars.add(v)
            elif ch == "D":
                u += str(random.randint(1, 9))  # цифра (не 0 в начале не будет)

        if not valid or not u or u in seen:
            continue
        if not re.match(r'^[a-z][a-z0-9]{2,11}$', u):
            continue

        seen.add(u)
        cat  = random.choice(categories)
        l    = len(u)
        read = 9 if l <= 4 else 8 if l <= 5 else 7
        uniq = 10 if (l <= 4 and _no_repeat(u)) else 9 if _no_repeat(u) else 7

        result.append({
            "username":    u,
            "category":    cat,
            "readability": read,
            "uniqueness":  uniq,
            "reason":      "generated",
        })

    return result


# ── Проверка доступности ─────────────────────

async def check_telegram(session: aiohttp.ClientSession, username: str) -> bool:
    """True если ник свободен на Telegram (нет профиля/канала/группы)."""
    try:
        async with session.get(
            f"https://t.me/{username}",
            timeout=aiohttp.ClientTimeout(total=8),
            allow_redirects=True,
            headers=HEADERS_TG
        ) as resp:
            if "telegram.org" in str(resp.url):
                return True
            html = await resp.text()
            has_profile = bool(re.search(
                r'<meta property="og:title" content=".{3,}"', html, re.I
            ))
            return not has_profile
    except Exception:
        return False


async def check_fragment(session: aiohttp.ClientSession, username: str) -> bool:
    """True если ник есть на Fragment (занят/продаётся за TON — не подходит)."""
    try:
        async with session.get(
            f"https://fragment.com/username/{username}",
            timeout=aiohttp.ClientTimeout(total=8),
            allow_redirects=True,
            headers=HEADERS_TG
        ) as resp:
            if resp.status == 404:
                return False
            html = await resp.text()
            # Ник на Fragment — занят
            on_fragment = bool(re.search(
                r'(Bid|Buy|Place a bid|floor price|TON|auction|username-not-found)',
                html, re.I
            ))
            return on_fragment
    except Exception:
        return False


async def check_available(session: aiohttp.ClientSession, username: str) -> bool:
    """Ник свободен только если его нет ни на Telegram, ни на Fragment."""
    tg_free, frag_taken = await asyncio.gather(
        check_telegram(session, username),
        check_fragment(session, username),
    )
    return tg_free and not frag_taken


async def check_batch(usernames: list[str]) -> dict[str, bool]:
    """Проверяет список ников параллельно, возвращает {username: is_free}."""
    sem = asyncio.Semaphore(CHECK_CONCURRENCY)
    results = {}

    async with aiohttp.ClientSession(headers=HEADERS_TG) as session:
        async def check_one(u):
            async with sem:
                free = await check_available(session, u)
                results[u] = free
                await asyncio.sleep(0.5)

        await asyncio.gather(*[check_one(u) for u in usernames])

    return results


# ── Оценка цены ──────────────────────────────

def calc_price(username: str, readability: int, uniqueness: int) -> int:
    """
    Цена в Stars. Короче + без повторов = дороже.
    Комиссия Telegram 30% уже включена.
    """
    l = len(username)
    has_repeat = len(set(username)) < len(username)

    if l <= 3:   base = 9500
    elif l <= 4: base = 7500
    elif l <= 5: base = 5000
    elif l <= 6: base = 3000
    elif l <= 8: base = 1500
    else:        base = 700

    # Штраф за повторяющиеся буквы
    if has_repeat:
        base = int(base * 0.7)

    # Бонус за читаемость и уникальность
    bonus = int((readability / 10) * 800 + (uniqueness / 10) * 500)
    total = base + bonus

    # Включаем комиссию Telegram 30%
    total = int(total * 1.30)
    rounded = round(total / 50) * 50
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
