"""
generator.py
Генерирует крутые ники через Claude API, проверяет доступность
через t.me и автоматически пополняет каталог.
"""

import asyncio
import aiohttp
import ssl
import logging
import re
import json
import os
import random
from datetime import datetime

logger = logging.getLogger(__name__)

ANTHROPIC_KEY = os.getenv("ANTHROPIC_API_KEY", "")
CHECK_CONCURRENCY = 10  # сколько ников проверять параллельно
CATALOG_TARGET = 467    # сколько ников держать в каталоге
GENERATE_BATCH = 120    # сколько генерировать за раз

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
    return len(set(s)) == len(s)


# Curated phonetic building blocks — sound good, not random garbage
_ONSETS  = ["k","v","z","r","n","m","l","s","t","d","f","b","g","j","p","w",
             "kr","vr","zr","dr","tr","gr","br","fr","pl","kl","gl","sl","fl",
             "sk","sp","st","sn","sm","sw","sh","ch","th"]
_NUCLEI  = ["a","e","i","o","u","ai","ae","ei","io","oa","ui","au","ea","ue",
             "ao","ia","oi","ou"]
_CODAS   = ["x","k","n","m","l","r","t","s","v","z","p","f","g","d",
             "ks","nx","lv","rk","xt","nd","st","lt","nk","vn","rt","rm"]
_DIGITS  = ["0","1","2","3","4","7","9"]  # visually clean digits

# Category → (preferred onsets, preferred nuclei, color)
_CAT_PROFILE = {
    "Природа":    (["r","v","st","sn","sm","gr","br","fl"],  ["a","e","o","ea","ao"],   "#2d9e5e"),
    "Статус":     (["k","v","r","z","dr","kr","tr"],         ["e","o","i","ei","io"],   "#c0a030"),
    "Технологии": (["n","z","v","sk","s","t","sh"],          ["e","i","u","ei","ui"],   "#5b8dd9"),
    "Стиль":      (["z","v","k","m","fl","sl","gl"],         ["o","u","a","ao","oa"],   "#9b5de5"),
    "Финансы":    (["k","v","f","g","gr","tr","pl"],         ["a","o","u","ai","ou"],   "#e56b2d"),
    "Космос":     (["n","z","v","st","sp","kr","vr"],        ["o","u","e","oa","ui"],   "#4ecdc4"),
    "Имена":      (["k","l","m","n","r","j","d","b"],        ["a","i","e","ai","ia"],   "#e84393"),
    "Премиум":    (["k","v","z","x"],                        ["e","i","o"],             "#ffffff"),
}


def _generate_local(count: int) -> list[dict]:
    """
    Syllable-based generator using curated onsets/nuclei/codas.
    Produces pronounceable, brand-like nicks with per-category flavour.
    """
    categories = list(CATEGORIES.keys())
    result = []
    seen   = set()
    attempts = 0

    while len(result) < count and attempts < count * 80:
        attempts += 1
        cat = random.choice(categories)
        prof = _CAT_PROFILE.get(cat, (None, None, None))
        onsets = prof[0] or _ONSETS
        nuclei = prof[1] or _NUCLEI

        # Pick a length tier — digit nicks rare (only 8% total)
        tier = random.choices(
            ["3", "4", "5", "6", "7", "4d", "5d", "6d"],
            weights=[5, 28, 26, 18, 12, 3, 4, 4]
        )[0]
        has_digit = tier.endswith("d")
        tlen = int(tier[0])

        # Build nick from syllables
        u = ""
        if tlen == 3:
            # onset + nucleus, 2-3 total chars
            o = random.choice(onsets[:14])   # short onsets only
            n = random.choice(nuclei[:8])     # single vowels
            u = o + n
            if len(u) < 3:
                u += random.choice(_CODAS[:8])
        elif tlen == 4:
            o = random.choice(onsets[:14])
            n = random.choice(nuclei[:8])
            c = random.choice(_CODAS[:12])
            u = o + n + c
            if len(u) > 5: u = u[:4]
            if len(u) < 4:
                u += random.choice(list("aeiou"))
        elif tlen == 5:
            # two-syllable: onset+nucleus + onset+nucleus+coda or similar
            o1 = random.choice(onsets[:14]); n1 = random.choice(nuclei[:8])
            o2 = random.choice(onsets[:14]); n2 = random.choice(nuclei[:8])
            u = (o1+n1+o2+n2)[:6]
            while len(u) < 5:
                u += random.choice(list("aeious"))
            u = u[:5]
        elif tlen == 6:
            o1=random.choice(onsets[:14]); n1=random.choice(nuclei[:8])
            o2=random.choice(onsets[:14]); n2=random.choice(nuclei[:8])
            c =random.choice(_CODAS[:10])
            u = (o1+n1+o2+n2+c)[:7]
            while len(u) < 6: u += random.choice(list("aeiou"))
            u = u[:6]
        else:  # 7
            o1=random.choice(onsets[:14]); n1=random.choice(nuclei[:8])
            o2=random.choice(onsets[:14]); n2=random.choice(nuclei[:8])
            c1=random.choice(_CODAS[:10]); c2=random.choice(_CODAS[:8])
            u = (o1+n1+o2+n2+c1+c2)[:8]
            while len(u) < 7: u += random.choice(list("aeionrs"))
            u = u[:7]

        # Insert digit if tier ends with 'd'
        if has_digit and len(u) >= 2:
            pos = random.randint(1, len(u)-1)
            d   = random.choice(_DIGITS)
            u   = u[:pos] + d + u[pos:]
            u   = u[:12]

        u = u.lower()
        if not re.match(r'^[a-z][a-z0-9]{2,11}$', u):
            continue
        if u in seen:
            continue
        seen.add(u)

        l       = len(u)
        has_rep = not _no_repeat(u)
        read    = 9 if l <= 4 else 8 if l <= 5 else 7 if l <= 6 else 6
        uniq    = 10 if (l <= 4 and not has_rep) else 9 if not has_rep else 7 if l <= 6 else 6

        result.append({
            "username":    u,
            "category":    cat,
            "readability": read,
            "uniqueness":  uniq,
            "reason":      "syllable-generated",
        })

    return result


# ── Генератор ников для капсул ───────────────

def generate_budget_nick(tier: int) -> str:
    """
    Генерирует дешёвый ник для капсульных покупок.
    tier=250 → 9-11 символов, много повторов.
    tier=500 → 7-8 символов, меньше повторов.
    Доступность НЕ проверяется — риск капсулы.
    """
    consonants = list("bcdfghjklmnpqrstvwxyz")
    vowels     = list("aeiou")

    if tier <= 250:
        # Длинные и некрасивые
        pats = ["CVCCVCCVCD", "CVCVCVCVCC", "CVCCVCVCVC", "CVCCVCVCCV"]
    else:
        # Чуть получше
        pats = ["CVCVCVC", "CVCCVCV", "CVCVCVD", "CVCCVCC", "CVCVCCV"]

    pattern = random.choice(pats)
    u = ""
    for ch in pattern:
        if ch == "C": u += random.choice(consonants)
        elif ch == "V": u += random.choice(vowels)
        elif ch == "D": u += str(random.randint(2, 9))
    return u


# ── Проверка доступности ─────────────────────

async def check_telegram(session: aiohttp.ClientSession, username: str) -> bool:
    """True если ник свободен на Telegram."""
    try:
        async with session.get(
            f"https://t.me/{username}",
            timeout=aiohttp.ClientTimeout(total=8),
            allow_redirects=True,
            headers=HEADERS_TG
        ) as resp:
            html = await resp.text()
            # Свободный ник: og:title = "Telegram: Contact @xxx" или нет профиля
            # Занятый: og:title = реальное имя пользователя/канала
            title_m = re.search(r'<meta property="og:title" content="([^"]+)"', html, re.I)
            if not title_m:
                return True
            title = title_m.group(1)
            # Свободен если title содержит "Telegram: Contact" (страница-заглушка)
            if re.search(r'Telegram:\s*(Contact|Join)', title, re.I):
                return True
            return False
    except Exception:
        return False


async def check_fragment(session: aiohttp.ClientSession, username: str) -> bool:
    """True если ник реально выставлен на Fragment (не редирект на поиск)."""
    try:
        async with session.get(
            f"https://fragment.com/username/{username}",
            timeout=aiohttp.ClientTimeout(total=8),
            allow_redirects=True,
            headers=HEADERS_TG
        ) as resp:
            final_url = str(resp.url)
            # Если редиректнуло на поиск — ника нет на Fragment
            if "query=" in final_url or final_url.rstrip("/") == "https://fragment.com":
                return False
            if resp.status == 404:
                return False
            html = await resp.text()
            # Ник реально на Fragment если есть цена в TON
            return bool(re.search(r'(\d+[\.,]\d+\s*TON|Place a Bid|Buy Now)', html, re.I))
    except Exception:
        return False


async def check_available(session: aiohttp.ClientSession, username: str) -> bool:
    """Ник свободен только если его нет ни на Telegram, ни на Fragment."""
    tg_free, frag_taken = await asyncio.gather(
        check_telegram(session, username),
        check_fragment(session, username),
    )
    return tg_free and not frag_taken


def _make_connector():
    """Коннектор без строгой проверки SSL (нужно для macOS и некоторых серверов)."""
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    return aiohttp.TCPConnector(ssl=ctx)


async def check_batch(usernames: list[str]) -> dict[str, bool]:
    """Проверяет список ников параллельно, возвращает {username: is_free}."""
    sem = asyncio.Semaphore(CHECK_CONCURRENCY)
    results = {}

    async with aiohttp.ClientSession(connector=_make_connector(), headers=HEADERS_TG) as session:
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
    Ценообразование: чистые короткие буквенные ники = премиум.
    Ники с цифрами — бюджетный сегмент.
    Комиссия Telegram 30% включена.
    """
    l = len(username)
    has_digit  = any(c.isdigit() for c in username)
    has_repeat = len(set(username)) < len(username)

    if has_digit:
        # Цифры резко снижают ценность
        if l <= 5:   base = 1200
        elif l <= 7: base = 600
        else:        base = 250
        bonus = 0
    else:
        # Чистые буквенные ники
        if l <= 3:   base = 9500
        elif l <= 4: base = 8000
        elif l <= 5: base = 6000
        elif l <= 6: base = 3500
        elif l <= 7: base = 2000
        elif l <= 8: base = 1100
        else:        base = 500

        # Штраф за повторяющиеся буквы
        if has_repeat:
            base = int(base * 0.72)

        # Бонус за читаемость и уникальность (только для буквенных)
        bonus = int((readability / 10) * 700 + (uniqueness / 10) * 450)

    total   = int((base + bonus) * 1.30)
    rounded = round(total / 50) * 50
    return max(100, min(10000, rounded))


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
