import os
import asyncio
import ssl
import requests as rq
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from database import (init_db, get_catalog, get_username, get_stats,
                      reserve, check_reservation, watch_add, upsert_user,
                      roulette_create_session, roulette_get_result,
                      increment_view, update_verified_at, remove_username)

load_dotenv()
app = Flask(__name__)
CORS(app)
init_db()


def _live_check(username: str) -> bool:
    """Sync wrapper around async availability check. Used before invoice creation."""
    try:
        import aiohttp
        from generator import check_available

        async def _run():
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            conn = aiohttp.TCPConnector(ssl=ctx)
            async with aiohttp.ClientSession(connector=conn) as session:
                return await check_available(session, username)

        return asyncio.run(_run())
    except Exception:
        return True  # assume free on error — don't block purchase


@app.route("/")
def webapp():
    return send_file("webapp/index.html")


@app.route("/api/catalog")
def catalog():
    items = get_catalog(
        category  = request.args.get("category"),
        sort      = request.args.get("sort", "price_desc"),
        max_price = request.args.get("max_price", type=int),
        max_length= request.args.get("max_length", type=int),
        search    = request.args.get("search"),
    )
    return jsonify({"items": items, "total": len(items)})


@app.route("/api/item/<username>")
def item(username):
    row = get_username(username)
    if not row:
        return jsonify({"error": "not found"}), 404
    increment_view(username)
    return jsonify(row)


@app.route("/api/stats")
def stats():
    return jsonify(get_stats())


@app.route("/api/reserve", methods=["POST"])
def do_reserve():
    d = request.json or {}
    username = d.get("username", "").lower()
    user_id  = d.get("user_id")
    if not username or not user_id:
        return jsonify({"error": "missing fields"}), 400
    return jsonify(reserve(username, user_id))


@app.route("/api/reservation_status")
def reservation_status():
    username = request.args.get("username", "").lower()
    user_id  = request.args.get("user_id", type=int)
    return jsonify(check_reservation(username, user_id))


@app.route("/api/categories")
def categories():
    items = get_catalog()
    cats  = sorted(set(i["category"] for i in items))
    return jsonify({"categories": ["Все"] + cats})


@app.route("/api/invoice-link")
def invoice_link():
    username = request.args.get("username", "").lower()
    user_id  = request.args.get("user_id", type=int)
    if not username or not user_id:
        return jsonify({"error": "missing"}), 400

    item = get_username(username)
    if not item or item["is_sold"]:
        return jsonify({"error": "not_found"}), 404

    # Live-verify only unparked nicks — parked nicks show as "taken" because we own the channel
    if not item.get("is_parked"):
        if not _live_check(username):
            remove_username(username)
            return jsonify({"error": "taken", "msg": "Ник только что заняли — удалили из каталога"}), 409

    update_verified_at(username)

    res = reserve(username, user_id)
    if not res["ok"]:
        return jsonify({"error": res["reason"], "minutes": res.get("minutes")}), 409

    token = os.getenv("BOT_TOKEN", "")
    masked = username[0] + '✦' * (len(username) - 1)
    resp = rq.post(
        f"https://api.telegram.org/bot{token}/createInvoiceLink",
        json={
            "title":       f"🎁 Ник @{masked}",
            "description": f"{item['category']} · {item['length']} символов · Ник раскроется после оплаты",
            "payload":     f"buy:{username}",
            "currency":    "XTR",
            "prices":      [{"label": f"Ник @{masked}", "amount": item["price"]}],
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("ok"):
        return jsonify({"url": data["result"]})
    return jsonify({"error": "tg_error", "detail": str(data)}), 500


@app.route("/api/capsule-invoice-link")
def capsule_invoice_link():
    tier    = request.args.get("tier", type=int, default=250)
    user_id = request.args.get("user_id", type=int)
    if tier not in (250, 500) or not user_id:
        return jsonify({"error": "invalid"}), 400

    token = os.getenv("BOT_TOKEN", "")
    label = "Базовая капсула" if tier == 250 else "Стандартная капсула"
    desc  = "9–11 символов · случайный ник" if tier == 250 else "7–8 символов · случайный ник"
    resp = rq.post(
        f"https://api.telegram.org/bot{token}/createInvoiceLink",
        json={
            "title":       f"📦 {label}",
            "description": desc,
            "payload":     f"capsule:{tier}",
            "currency":    "XTR",
            "prices":      [{"label": label, "amount": tier}],
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("ok"):
        return jsonify({"url": data["result"]})
    return jsonify({"error": "tg_error", "detail": str(data)}), 500


@app.route("/api/roulette-invoice-link")
def roulette_invoice_link():
    user_id = request.args.get("user_id", type=int)
    if not user_id:
        return jsonify({"error": "missing"}), 400
    session_id = roulette_create_session(user_id)
    token = os.getenv("BOT_TOKEN", "")
    resp = rq.post(
        f"https://api.telegram.org/bot{token}/createInvoiceLink",
        json={
            "title":       "🎰 Рулетка НИКЕР",
            "description": "Шанс 1/30 выиграть лучший ник из каталога",
            "payload":     f"roulette:{session_id}",
            "currency":    "XTR",
            "prices":      [{"label": "Прокрут рулетки", "amount": 500}],
        },
        timeout=10,
    )
    data = resp.json()
    if data.get("ok"):
        return jsonify({"url": data["result"], "session_id": session_id})
    return jsonify({"error": "tg_error", "detail": str(data)}), 500


@app.route("/api/roulette-result")
def roulette_result_api():
    session_id = request.args.get("session_id", "")
    user_id    = request.args.get("user_id", type=int)
    result = roulette_get_result(session_id, user_id)
    if not result:
        return jsonify({"error": "not_found"}), 404
    return jsonify(result)


_OWNER_ID = 5968081460  # telegram user id of the shop owner

@app.route("/api/admin/delete-nick", methods=["POST"])
def admin_delete_nick():
    d        = request.json or {}
    user_id  = d.get("user_id")
    username = d.get("username", "").lower()

    env_str  = os.getenv("ADMIN_ID", "").strip()
    admin_id = int(env_str) if env_str.isdigit() else _OWNER_ID
    if user_id != admin_id:
        return jsonify({"error": "forbidden"}), 403

    from database import get_channel_id, remove_username
    from parker import unpark_nick, is_configured as parker_ok
    if parker_ok():
        cid = get_channel_id(username)
        if cid:
            async def _unpark():
                await unpark_nick(cid)
            try:
                asyncio.run(_unpark())
            except Exception:
                pass
    remove_username(username)
    return jsonify({"ok": True})


@app.route("/api/admin/add-nick", methods=["POST"])
def admin_add_nick():
    d        = request.json or {}
    user_id  = d.get("user_id")
    username = d.get("username", "").lower().strip().lstrip("@")
    price    = d.get("price")

    env_str  = os.getenv("ADMIN_ID", "").strip()
    admin_id = int(env_str) if env_str.isdigit() else _OWNER_ID
    if user_id != admin_id:
        return jsonify({"error": "forbidden"}), 403

    import re
    if not re.match(r'^[a-z][a-z0-9]{2,11}$', username):
        return jsonify({"error": "invalid_username"}), 400

    from generator import calc_price
    from database import add_username
    if not price:
        price = calc_price(username, 9, 9)

    added = add_username(username, int(price), "Премиум", 9, 9, "добавлен администратором")
    if not added:
        return jsonify({"error": "already_exists"}), 409
    return jsonify({"ok": True, "price": price})


@app.route("/api/admin/park", methods=["POST"])
def admin_park():
    d        = request.json or {}
    user_id  = d.get("user_id")
    username = d.get("username", "").lower()

    env_str  = os.getenv("ADMIN_ID", "").strip()
    admin_id = int(env_str) if env_str.isdigit() else _OWNER_ID
    if user_id != admin_id:
        return jsonify({"error": "forbidden"}), 403

    item = __import__("database").get_username(username)
    if not item:
        return jsonify({"error": "not_found"}), 404
    if item.get("is_parked"):
        return jsonify({"error": "already_parked"}), 400

    from parker import park_nick, is_configured as parker_ok
    from database import set_parked
    if not parker_ok():
        return jsonify({"error": "parker_not_configured"}), 503

    async def _do():
        return await park_nick(username)

    cid = asyncio.run(_do())
    if cid:
        set_parked(username, cid)
        return jsonify({"ok": True, "channel_id": cid})
    return jsonify({"error": "park_failed"}), 500


@app.route("/api/check-admin")
def check_admin():
    user_id  = request.args.get("user_id", type=int)
    env_str  = os.getenv("ADMIN_ID", "").strip()
    admin_id = int(env_str) if env_str.isdigit() else _OWNER_ID
    return jsonify({"is_admin": user_id is not None and user_id == admin_id})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
