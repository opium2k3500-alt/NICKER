#!/usr/bin/env python3
"""
Запусти один раз:  python3 setup_parker.py
Скопируй SESSION STRING → добавь в Railway как PARKER_SESSION.
"""
import asyncio


async def main():
    print("\n=== Настройка парковщика ников ===\n")
    print("Нужен отдельный аккаунт Telegram (не основной).")
    print("API_ID и API_HASH → https://my.telegram.org → 'API development tools'\n")

    api_id   = int(input("PARKER_API_ID  : ").strip())
    api_hash = input("PARKER_API_HASH: ").strip()
    phone    = input("Телефон (+7...): ").strip()

    from pyrogram import Client
    from pyrogram.errors import SessionPasswordNeeded

    client = Client(
        name="parker_setup",
        api_id=api_id,
        api_hash=api_hash,
        phone_number=phone,
        in_memory=True,
    )

    await client.connect()
    sent = await client.send_code(phone)

    code = input("Код из Telegram: ").strip()
    try:
        await client.sign_in(phone, sent.phone_code_hash, code)
    except SessionPasswordNeeded:
        pwd = input("Пароль 2FA: ").strip()
        await client.check_password(pwd)

    session = await client.export_session_string()
    await client.disconnect()

    print("\n" + "="*60)
    print("✅ PARKER_SESSION (скопируй в Railway):\n")
    print(session)
    print("\n" + "="*60)
    print(f"Также добавь в Railway:")
    print(f"  PARKER_API_ID  = {api_id}")
    print(f"  PARKER_API_HASH = {api_hash}")


if __name__ == "__main__":
    asyncio.run(main())
