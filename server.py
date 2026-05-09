import os
import requests as rq
from dotenv import load_dotenv
from flask import Flask, jsonify, request, send_file
from flask_cors import CORS
from database import (init_db, get_catalog, get_username, get_stats,
                      reserve, check_reservation, watch_add, upsert_user)

load_dotenv()
app = Flask(__name__)
CORS(app)
init_db()


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

    res = reserve(username, user_id)
    if not res["ok"]:
        return jsonify({"error": res["reason"], "minutes": res.get("minutes")}), 409

    token = os.getenv("BOT_TOKEN", "")
    resp = rq.post(
        f"https://api.telegram.org/bot{token}/createInvoiceLink",
        json={
            "title":       f"Ник @{username}",
            "description": f"{item['category']} · {item['length']} символов",
            "payload":     f"buy:{username}",
            "currency":    "XTR",
            "prices":      [{"label": f"@{username}", "amount": item["price"]}],
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
            "title":       f"🎰 {label}",
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


_OWNER_ID = 5968081460  # telegram user id of the shop owner

@app.route("/api/check-admin")
def check_admin():
    user_id  = request.args.get("user_id", type=int)
    env_str  = os.getenv("ADMIN_ID", "").strip()
    admin_id = int(env_str) if env_str.isdigit() else _OWNER_ID
    return jsonify({"is_admin": user_id is not None and user_id == admin_id})


if __name__ == "__main__":
    port = int(os.getenv("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
