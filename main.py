import os, logging, json, time, random, asyncio
from flask import Flask, request, jsonify
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
from supabase_py import create_client, Client
import xendit

# — ENV & INIT
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "@admin")
XENDIT_API_KEY = os.getenv("XENDIT_API_KEY")
XENDIT_WEBHOOK_TOKEN = os.getenv("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
SUPABASE_URL = os.getenv("SUPABASE_URL")
SUPABASE_KEY = os.getenv("SUPABASE_KEY")
LOGO_URL = os.getenv("LOGO_URL", "https://i.imgur.com/default-logo.png")

xendit.api_key = XENDIT_API_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)
bot = Application.builder().token(TELEGRAM_TOKEN).build()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# — DATABASE FUNCTIONS
def get_products():
    return supabase.table("products").select("*").execute().data or []

def get_stock(produk_id):
    return supabase.table("stok_akun").select("*").eq("produk_id", produk_id).eq("sold", False).execute().data or []

def pop_one_akun(produk_id):
    stok = get_stock(produk_id)
    if not stok: return None
    akun = stok[0]
    supabase.table("stok_akun").update({"sold": True}).eq("id", akun["id"]).execute()
    return akun

def insert_order(external_id, user_id, produk_id, harga):
    return supabase.table("orders").insert({
        "external_id": external_id,
        "user_id": user_id,
        "produk_id": produk_id,
        "harga": harga,
        "status": "PENDING"
    }).execute()

# — ADMIN COMMANDS
def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

async def new_product(update: Update, ctx):
    if not is_admin(update): return
    try:
        idp, nama, harga, deskripsi = [x.strip() for x in " ".join(ctx.args).split("|")]
        supabase.table("products").insert({
            "id": idp,
            "nama": nama,
            "harga": int(harga),
            "deskripsi": deskripsi
        }).execute()
        await update.message.reply_text(f"✅ Produk '{nama}' berhasil ditambahkan.")
    except:
        await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")

async def add_stock(update: Update, ctx):
    if not is_admin(update): return
    try:
        pid = ctx.args[0]
        akun = " ".join(ctx.args[1:])
        supabase.table("stok_akun").insert({"produk_id": pid, "detail": akun, "sold": False}).execute()
        await update.message.reply_text(f"✅ Stok ditambahkan ke '{pid}'.")
    except:
        await update.message.reply_text("Format: /add <produk_id> <akun_detail>")

async def info_stock(update: Update, ctx):
    if not is_admin(update): return
    teks = "📦 Stok Produk:\n"
    for p in get_products():
        stok = len(get_stock(p["id"]))
        teks += f"- {p['nama']} (`{p['id']}`): {stok} akun\n"
    await update.message.reply_text(teks)

# — USER HANDLERS
async def start(update: Update, ctx):
    btn = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek")]]
    await update.message.reply_photo(
        photo=LOGO_URL,
        caption="**Selamat datang di toko!**\nSilakan tekan tombol di bawah untuk cek produk.",
        parse_mode="Markdown",
        reply_markup=InlineKeyboardMarkup(btn)
    )

async def btn_handler(update: Update, ctx):
    q = update.callback_query
    await q.answer()
    if q.data == "cek":
        btns = []
        for p in get_products():
            if get_stock(p["id"]):
                btns.append([InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']}", callback_data=f"buy_{p['id']}")])
        btns.append([InlineKeyboardButton("↩️ Kembali", callback_data="back")])
        await q.edit_message_text("Pilih produk:", reply_markup=InlineKeyboardMarkup(btns))
    elif q.data.startswith("buy_"):
        pid = q.data.split("_")[1]
        produk = next((p for p in get_products() if p["id"] == pid), None)
        if not produk: return await q.edit_message_text("Stok kosong.")
        extid = f"order-{pid}-{q.from_user.id}-{int(time.time())}"
        inv = xendit.Invoice.create(
            external_id=extid,
            amount=produk["harga"],
            description=produk["nama"],
            customer={"given_names": q.from_user.full_name}
        )
        insert_order(extid, q.from_user.id, pid, produk["harga"])
        await q.edit_message_text(f"✅ Invoice siap dibayar!\n{inv.invoice_url}")
    elif q.data == "back":
        await start(update, ctx)

async def text_handler(update: Update, ctx):
    await update.message.reply_text("Ketik /start untuk mulai.")

# — WEBHOOKS
@app.route("/")
def root(): return "Bot aktif!"

@app.route("/telegram", methods=["POST"])
async def telegram_webhook():
    update = Update.de_json(request.get_json(force=True), bot.bot)
    await bot.initialize()
    await bot.process_update(update)
    return jsonify({"status": "ok"})

@app.route("/webhook/xendit", methods=["POST"])
def xendit_webhook():
    if request.headers.get("x-callback-token") != XENDIT_WEBHOOK_TOKEN:
        return "unauthorized", 403
    d = request.json
    if d.get("status") == "PAID":
        external_id = d["external_id"]
        supabase.table("orders").update({"status": "PAID"}).eq("external_id", external_id).execute()
        produk_id = external_id.split("-")[1]
        akun = pop_one_akun(produk_id)
        user_data = supabase.table("orders").select("user_id").eq("external_id", external_id).execute().data
        if akun and user_data:
            chatid = user_data[0]["user_id"]
            bot.bot.send_message(chatid, f"✅ Pembayaran diterima!\n\nAkun kamu: `{akun['detail']}`", parse_mode="Markdown")
    return jsonify({"status": "success"})

# — SETUP
async def setup_bot():
    cmds = [
        BotCommand("start", "Mulai bot"),
        BotCommand("newproduct", "Tambah produk (admin)"),
        BotCommand("add", "Tambah stok (admin)"),
        BotCommand("infostock", "Lihat stok (admin)"),
    ]
    await bot.bot.set_my_commands(cmds)
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("newproduct", new_product))
    bot.add_handler(CommandHandler("add", add_stock))
    bot.add_handler(CommandHandler("infostock", info_stock))
    bot.add_handler(CallbackQueryHandler(btn_handler))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await bot.initialize()
    await bot.bot.set_webhook(WEBHOOK_URL + "/telegram", allowed_updates=Update.ALL_TYPES)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup_bot())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == "__main__":
    main()
