import logging
import os
import asyncio
from dotenv import load_dotenv
from telegram import (Update, InlineKeyboardButton, InlineKeyboardMarkup,
                       WebAppInfo, LabeledPrice)
from telegram.ext import (Application, CommandHandler, CallbackQueryHandler,
                           MessageHandler, PreCheckoutQueryHandler,
                           filters, ContextTypes)
from database import (init_db, upsert_user, get_catalog, get_username,
                      get_user_purchases, get_stats, mark_sold,
                      reserve, check_reservation,
                      watch_add, watch_remove, watch_list)
from worker import Worker

load_dotenv()

logging.basicConfig(level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

BOT_TOKEN  = os.getenv("BOT_TOKEN", "")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-domain.com")


async def cmd_start(update, ctx):
    u = update.effective_user
    upsert_user(u.id, u.username, u.first_name)
    kb = [
        [InlineKeyboardButton("🚀 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("📦 Мои покупки", callback_data="my_purchases"),
         InlineKeyboardButton("⭐ Вотчлист", callback_data="watchlist")],
        [InlineKeyboardButton("ℹ️ Как это работает", callback_data="about")],
    ]
    await update.message.reply_text(
        f"👋 Привет, <b>{u.first_name}</b>!\n\n"
        "Добро пожаловать в <b>Username Market</b> — магазин крутых Telegram-ников.\n\n"
        "🤖 Бот сам генерирует уникальные ники и проверяет доступность\n"
        "💫 Оплата звёздами Telegram\n"
        "🔒 Ник резервируется на 30 минут при покупке\n"
        "🔔 Подпишись на ник — узнаешь когда он появится",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def cb_my_purchases(update, ctx):
    q = update.callback_query
    await q.answer()
    purchases = get_user_purchases(q.from_user.id)
    if not purchases:
        text = "📦 У вас пока нет покупок.\n\nОткройте магазин и найдите свой ник!"
    else:
        text = "📦 <b>Ваши покупки:</b>\n\n"
        for p in purchases:
            text += f"✅ <code>@{p['username']}</code> — {p['stars_paid']}⭐ · {p['created_at'][:10]}\n"
    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def cb_watchlist(update, ctx):
    q = update.callback_query
    await q.answer()
    items = watch_list(q.from_user.id)
    if not items:
        text = ("⭐ <b>Ваш вотчлист пуст</b>\n\n"
                "Напишите: <code>/watch username</code>\n\n"
                "Как только ник появится — пришлю уведомление!")
    else:
        text = "⭐ <b>Вы следите за этими никами:</b>\n\n"
        for item in items:
            if item["in_catalog"]:
                text += f"🟢 <code>@{item['username']}</code> — уже в продаже! {item['price']}⭐\n"
            else:
                text += f"⏳ <code>@{item['username']}</code> — ждём появления\n"
        text += "\n<i>Отписаться: /unwatch username</i>"
    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def cb_about(update, ctx):
    q = update.callback_query
    await q.answer()
    text = (
        "ℹ️ <b>Как работает Username Market</b>\n\n"
        "🤖 <b>Автоматическая генерация</b>\n"
        "Бот придумывает крутые ники и проверяет каждый на доступность. "
        "Свободные автоматически попадают в каталог.\n\n"
        "🔒 <b>Резервирование</b>\n"
        "При нажатии «Купить» ник блокируется на 30 минут только для тебя.\n\n"
        "🔔 <b>Вотчлист</b>\n"
        "Напиши <code>/watch username</code> — получишь уведомление "
        "как только ник появится в продаже.\n\n"
        "💫 <b>Оплата</b>\n"
        "Только Telegram Stars. Цена: 100 — 10 000 ⭐\n"
        "Комиссия Telegram 30% уже включена в цену.\n\n"
        "⚠️ <b>Важно</b>\n"
        "После оплаты сразу устанавливай ник. "
        "<b>Возвраты не производятся</b> — если не успел занять ник, "
        "это твоя ответственность. Действуй быстро!"
    )
    kb = [[InlineKeyboardButton("🔙 Назад", callback_data="back")]]
    await q.edit_message_text(text, reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def cb_back(update, ctx):
    q = update.callback_query
    await q.answer()
    kb = [
        [InlineKeyboardButton("🚀 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))],
        [InlineKeyboardButton("📦 Мои покупки", callback_data="my_purchases"),
         InlineKeyboardButton("⭐ Вотчлист", callback_data="watchlist")],
        [InlineKeyboardButton("ℹ️ Как это работает", callback_data="about")],
    ]
    await q.edit_message_text("🏠 <b>Главное меню</b>",
        reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")


async def handle_webapp_data(update, ctx):
    import json
    data = json.loads(update.effective_message.web_app_data.data)
    action   = data.get("action")
    username = data.get("username", "").lower()
    user_id  = update.effective_user.id

    if action == "buy":
        item = get_username(username)
        if not item or item["is_sold"]:
            await update.message.reply_text("❌ Этот ник уже недоступен.")
            return
        res = reserve(username, user_id)
        if not res["ok"]:
            if res["reason"] == "reserved":
                await update.message.reply_text(
                    f"⏳ Ник занят другим пользователем ещё {res['minutes']} мин. Попробуй позже!")
            else:
                await update.message.reply_text("❌ Ник недоступен.")
            return
        await ctx.bot.send_invoice(
            chat_id=user_id,
            title=f"Ник @{username}",
            description=f"{item['category']} · {item['length']} символов · читаемость {item['readability']}/10",
            payload=f"buy:{username}",
            currency="XTR",
            prices=[LabeledPrice(f"@{username}", item["price"])],
            provider_token="",
        )

    elif action == "watch":
        added = watch_add(user_id, username)
        msg = (f"🔔 Подписка на <code>@{username}</code> оформлена!\nПришлю уведомление как только появится."
               if added else f"Вы уже следите за <code>@{username}</code>")
        await update.message.reply_text(msg, parse_mode="HTML")


async def precheckout(update, ctx):
    q = update.pre_checkout_query
    if not q.invoice_payload.startswith("buy:"):
        await q.answer(ok=False, error_message="Неверный запрос")
        return
    username = q.invoice_payload[4:]
    status = check_reservation(username, q.from_user.id)
    if status["available"]:
        await q.answer(ok=True)
    else:
        msgs = {"sold": "Ник уже куплен", "taken": "Ник занят другим пользователем",
                "not_found": "Ник не найден"}
        await q.answer(ok=False, error_message=msgs.get(status["reason"], "Ник недоступен"))


async def successful_payment(update, ctx):
    payment  = update.message.successful_payment
    username = payment.invoice_payload[4:]
    user_id  = update.effective_user.id
    stars    = payment.total_amount

    mark_sold(username, user_id, stars)

    # Чек
    await update.message.reply_text(
        f"🧾 <b>ЧЕК ОБ ОПЛАТЕ</b>\n"
        f"{'─' * 26}\n"
        f"Ник:    <code>@{username}</code>\n"
        f"Сумма:  <b>{stars} ⭐</b>\n"
        f"Статус: ✅ Оплачено\n"
        f"{'─' * 26}\n"
        f"Сохрани это сообщение!",
        parse_mode="HTML"
    )

    # Инструкция
    await update.message.reply_text(
        f"🏃 <b>БЕГИ МЕНЯТЬ НИК ПРЯМО СЕЙЧАС!</b>\n\n"
        f"Твой новый ник — нажми чтобы скопировать:\n"
        f"<code>{username}</code>\n\n"
        f"<b>Как установить за 10 секунд:</b>\n"
        f"1. Telegram → Настройки\n"
        f"2. Нажми на своё имя → <b>Изменить</b>\n"
        f"3. Поле <b>Имя пользователя</b> → вставь <code>{username}</code>\n"
        f"4. Нажми <b>Готово ✓</b>\n\n"
        f"⚡ Не тяни — ник ждёт тебя!\n"
        f"⚠️ <b>Возвраты не производятся.</b>",
        parse_mode="HTML"
    )
    logger.info(f"SOLD @{username} to {user_id} for {stars}⭐")


async def cmd_watch(update, ctx):
    if not ctx.args:
        await update.message.reply_text(
            "Использование: <code>/watch username</code>", parse_mode="HTML")
        return
    username = ctx.args[0].lower().lstrip("@")
    user_id  = update.effective_user.id
    item = get_username(username)
    if item and not item["is_sold"]:
        kb = [[InlineKeyboardButton("🚀 Открыть магазин", web_app=WebAppInfo(url=WEBAPP_URL))]]
        await update.message.reply_text(
            f"✅ <code>@{username}</code> уже в продаже!\n💫 Цена: <b>{item['price']} ⭐</b>",
            reply_markup=InlineKeyboardMarkup(kb), parse_mode="HTML")
        return
    added = watch_add(user_id, username)
    msg = (f"🔔 Подписка на <code>@{username}</code> оформлена!\nПришлю уведомление как только появится."
           if added else f"Вы уже следите за <code>@{username}</code>")
    await update.message.reply_text(msg, parse_mode="HTML")


async def cmd_unwatch(update, ctx):
    if not ctx.args:
        await update.message.reply_text("Использование: /unwatch username")
        return
    username = ctx.args[0].lower().lstrip("@")
    watch_remove(update.effective_user.id, username)
    await update.message.reply_text(f"✅ Отписались от <code>@{username}</code>", parse_mode="HTML")


async def cmd_stats(update, ctx):
    s = get_stats()
    await update.message.reply_text(
        f"📊 В продаже: {s['t']} | Продано: {s['sold']} | Цены: {s['mn']}–{s['mx']} ⭐",
        parse_mode="HTML")


async def post_init(application):
    worker = Worker(application.bot)
    asyncio.create_task(worker.start())
    logger.info("Worker started")


def main():
    init_db()
    asyncio.set_event_loop(asyncio.new_event_loop())
    app = (Application.builder().token(BOT_TOKEN).post_init(post_init).build())
    app.add_handler(CommandHandler("start",   cmd_start))
    app.add_handler(CommandHandler("watch",   cmd_watch))
    app.add_handler(CommandHandler("unwatch", cmd_unwatch))
    app.add_handler(CommandHandler("stats",   cmd_stats))
    app.add_handler(CallbackQueryHandler(cb_my_purchases, pattern="my_purchases"))
    app.add_handler(CallbackQueryHandler(cb_watchlist,    pattern="^watchlist$"))
    app.add_handler(CallbackQueryHandler(cb_about,        pattern="about"))
    app.add_handler(CallbackQueryHandler(cb_back,         pattern="back"))
    app.add_handler(MessageHandler(filters.StatusUpdate.WEB_APP_DATA, handle_webapp_data))
    app.add_handler(PreCheckoutQueryHandler(precheckout))
    app.add_handler(MessageHandler(filters.SUCCESSFUL_PAYMENT, successful_payment))
    logger.info("Bot started")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
