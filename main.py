import os, logging, json, time, random, asyncio
from flask import Flask, request, jsonify
from telegram import Update, BotCommand, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit
from supabase import create_client, Client

# — ENV/INIT
TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
ADMIN_CHAT_ID = os.environ["ADMIN_CHAT_ID"]
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "@watchingnemo")
XENDIT_API_KEY = os.environ["XENDIT_API_KEY"]
XENDIT_WEBHOOK_TOKEN = os.environ["XENDIT_WEBHOOK_VERIFICATION_TOKEN"]
WEBHOOK_URL = os.environ["WEBHOOK_URL"]
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

xendit.api_key = XENDIT_API_KEY
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
app = Flask(__name__)
bot = Application.builder().token(TELEGRAM_TOKEN).build()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# — FUNGSI DATABASE
def get_products():
    data = supabase.table("products").select("*").execute()
    return data.data or []

def get_stock(produk_id):
    data = supabase.table("stok_akun").select("*").eq("produk_id", produk_id).execute()
    return data.data or []

def pop_one_akun(produk_id):
    stok = get_stock(produk_id)
    if not stok: return None
    akun = stok[0]
    # hapus entry
    supabase.table("stok_akun").delete().eq("id", akun["id"]).execute()
    return akun

def insert_order(external_id, user_id, produk_id, harga):
    return supabase.table("orders").insert({
        "external_id": external_id,
        "user_id": user_id,
        "produk_id": produk_id,
        "harga": harga
    }).execute()

# — FUNGSI ADMIN
def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

async def new_product(update: Update, ctx):
    if not is_admin(update): return
    args = " ".join(ctx.args).split("|")
    if len(args)<4: return await update.message.reply_text("Format: /newproduct id|nama|harga|deskripsi")
    idp,n,h,d = [x.strip() for x in args]
    supabase.table("products").insert({"id":idp,"nama":n,"harga":int(h),"deskripsi":d}).execute()
    await update.message.reply_text(f"✅ Produk '{n}' ditambahkan.")

async def add_stock(update: Update, ctx):
    if not is_admin(update): return
    try:
        pid = ctx.args[0]; akun = " ".join(ctx.args[1:])
        supabase.table("stok_akun").insert({"produk_id": pid, "detail": akun}).execute()
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
    await update.message.reply_text(teks)

# — HANDLER PENGGUNA
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
        inv = xendit.Invoice.create(external_id=ext,amount=prod["harga"],description=prod["nama"],customer={"given_names":q.from_user.full_name})
        insert_order(ext,q.from_user.id,pid,prod["harga"])
        await q.edit_message_text(f"✅ Invoice siap!\n{inv.invoice_url}")
    elif q.data=="back":
        return await start(update, ctx)

async def text_handler(update: Update, ctx):
    return await update.message.reply_text("Ketik /start untuk mulai.")

# — WEBHOOKS
@app.route("/", methods=["GET"])
def home(): return "OK"

@app.route("/telegram", methods=["POST"])
async def tg_webhook():
    upd = Update.de_json(request.get_json(force=True), bot.bot)
    await bot.initialize(); await bot.process_update(upd)
    return jsonify(ok=True)

@app.route("/webhook/xendit", methods=["POST"])
def xi_webhook():
    if request.headers.get("x-callback-token")!=XENDIT_WEBHOOK_TOKEN:
        return "forbidden",403
    d = request.json
    if d.get("status")=="PAID":
        supabase.table("orders").update({"status":"PAID"}).eq("external_id",d["external_id"]).execute()
        akun = pop_one_akun(d["external_id"].split("-")[1])
        chatid = supabase.table("orders").select("user_id").eq("external_id",d["external_id"]).execute().data[0]["user_id"]
        msg = f"✅ Pembayaran diterima!\nAkun kamu: `{akun['detail']}`"
        bot.bot.send_message(chatid, msg, parse_mode="Markdown")
    return jsonify(ok=True)

# — INIT BOT
async def setup():
    for cmd in ["/start","/newproduct","/add","/infostock"]: 
        await bot.bot.set_my_commands([BotCommand(cmd,"")])
    bot.add_handler(CommandHandler("start", start))
    bot.add_handler(CommandHandler("newproduct", new_product))
    bot.add_handler(CommandHandler("add", add_stock))
    bot.add_handler(CommandHandler("infostock", info_stock))
    bot.add_handler(CallbackQueryHandler(btn_handler))
    bot.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_handler))
    await bot.initialize()
    await bot.bot.set_webhook(WEBHOOK_URL+"/telegram", allowed_updates=Update.ALL_TYPES)

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    from waitress import serve
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT",8080)))

if __name__=="__main__":
    main()
