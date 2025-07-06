import os, logging, json, time, random, asyncio
from flask import Flask, request, jsonify
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit
from supabase_client import get_products, get_stock, pop_one_akun, insert_order, update_order_status, get_order_user

# --- ENV
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]
XENDIT_API_KEY = os.environ["XENDIT_API_KEY"]
XENDIT_WEBHOOK_TOKEN = os.environ["XENDIT_WEBHOOK_VERIFICATION_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot = Application.builder().token(TELEGRAM_TOKEN).build()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# --- ADMIN

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

async def new_product(update: Update, ctx):
    if not is_admin(update): return
    args = " ".join(ctx.args).split("|")
    if len(args)<4: return await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")
    idp,n,h,d = [x.strip() for x in args]
    from supabase_client import HEADERS, SUPABASE_URL
    import requests
    res = requests.post(
        f"{SUPABASE_URL}/rest/v1/products",
        headers=HEADERS,
        json={"id":idp,"nama":n,"harga":int(h),"deskripsi":d}
    )
    await update.message.reply_text(f"✅ Produk '{n}' ditambahkan.")

async def add_stock(update: Update, ctx):
    if not is_admin(update): return
    try:
        pid = ctx.args[0]; akun = " ".join(ctx.args[1:])
        from supabase_client import HEADERS, SUPABASE_URL
        import requests
        res = requests.post(
            f"{SUPABASE_URL}/rest/v1/stok_akun",
            headers=HEADERS,
            json={"produk_id": pid, "detail": akun, "sold": False}
        )
        await update.message.reply_text(f"✅ Stok akun ditambahkan ke '{pid}'.")
    except:
        return await update.message.reply_text("Format: /add <produk_id> <akun_detail>")

async def info_stock(update: Update, ctx):
    if not is_admin(update): return
    rows = get_products()
    teks = "📦 Stok Produk:\n"
    for p in rows:
        stok = len(get_stock(p["id"]))
        teks += f"- {p['nama']} (`{p['id']}`): {stok} akun\n"
    await update.message.reply_text(teks, parse_mode="Markdown")

# --- USER
async def start(update: Update, ctx):
    rows = get_products()
    teks = f"**Selamat datang!** Silakan cek stok produk..."
    btn = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek")]]
    await update.message.reply_photo(photo=LOGO_URL, caption=teks, parse_mode="Markdown", reply_markup=InlineKeyboardMarkup(btn))

async def btn_handler(update: Update, ctx):
    q = update.callback_query; await q.answer()
    if q.data=="cek":
        rows = get_products()
        btns = [[InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']}", callback_data=f"buy_{p['id']}")] for p in rows if get_stock(p["id"])]
        btns.append([InlineKeyboardButton("↩️ Kembali", callback_data="back")])
        await q.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(btns))
    elif q.data.startswith("buy_"):
        pid = q.data.split("_",1)[1]
        prod = next((p for p in get_products() if p["id"]==pid), None)
        if not prod: return await q.edit_message_text("Stok habis 😢")
        await q.edit_message_text("Membuat invoice...")
        ext = f"order-{pid}-{q.from_user.id}-{int(time.time())}"
        inv = xendit.Invoice.create(
            external_id=ext,
            amount=prod["harga"],
            description=prod["nama"],
            customer={"given_names":q.from_user.full_name}
        )
        insert_order(ext,q.from_user.id,pid,prod["harga"])
        await q.edit_message_text(f"✅ Invoice siap!\n{inv.invoice_url}")
    elif q.data=="back":
        return await start(update, ctx)

async def text_handler(update: Update, ctx):
    return await update.message.reply_text("Ketik /start untuk mulai.")

# --- FLASK WEBHOOK
@app.route("/", methods=["GET"])
def home(): return "OK"

@app.route("/telegram", methods=["POST"])
def tg_webhook():
    from telegram import Update
    upd = Update.de_json(request.get_json(force=True), bot.bot)
    asyncio.run(bot.initialize())
    asyncio.run(bot.process_update(upd))
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
def xi_webhook():
    if request.headers.get("x-callback-token")!=XENDIT_WEBHOOK_TOKEN:
        return "forbidden",403
    d = request.json
    if d.get("status")=="PAID":
        extid = d.get("external_id", "")
        parts = extid.split("-")
        produk_id = parts[1] if len(parts) >= 2 else None
        if not produk_id:
            return "invalid external_id", 400
        akun = pop_one_akun(produk_id)
        update_order_status(extid, akun_id=akun["id"] if akun else None)
        user = get_order_user(extid)
        if not user: return jsonify(ok=True)
        chatid = user[0]["user_id"]
        msg = f"✅ Pembayaran diterima!\nAkun kamu: `{akun['detail']}`" if akun else "✅ Terima kasih, kami akan segera kirim akun."
        import requests
        requests.get(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage", params={
            "chat_id": chatid,
            "text": msg,
            "parse_mode": "Markdown"
        })
    return jsonify(ok=True)

# --- STARTUP BOT
async def setup():
    await bot.bot.set_my_commands([
        BotCommand("start", "Mulai bot"),
        BotCommand("newproduct", "Tambah produk (admin)"),
        BotCommand("add", "Tambah akun (admin)"),
        BotCommand("infostock", "Lihat stok (admin)")
    ])
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("newproduct", new_product))
    bot.add_handler(CommandHandler("add", add_stock))
    bot.add_handler(CommandHandler("infostock", info_stock))
    bot.add_handler(CallbackQueryHandler(btn_handler))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await bot.initialize()
    await bot.bot.set_webhook(WEBHOOK_URL+"/telegram", allowed_updates=Update.ALL_TYPES)

# --- ENTRY
if __name__=="__main__":
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT",8080)))
