# main.py

import os
import logging
import json
import asyncio
import time
import random
from flask import Flask, request, jsonify
from waitress import serve
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from telegram.ext import Application, ContextTypes, CommandHandler, CallbackQueryHandler, MessageHandler, filters
import xendit

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "adminmu")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
xendit.api_key = XENDIT_API_KEY

app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# --- FUNGSI DATA ---
def muat_data(file_path):
    try:
        with open(file_path, 'r') as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return [] if 's.json' in file_path else {}

def simpan_data(data, file_path):
    with open(file_path, 'w') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def ambil_akun_dari_stok(produk_id):
    products = muat_data('products.json')
    for p in products:
        if p['id'] == produk_id and p.get('stok_akun'):
            akun = p['stok_akun'].pop(0)
            simpan_data(products, 'products.json')
            return akun
    return None

def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

# --- ADMIN COMMAND ---
async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id, akun_baru = context.args[0], " ".join(context.args[1:])
        if not akun_baru:
            await update.message.reply_text("Format salah.")
            return
        products = muat_data('products.json')
        for p in products:
            if p['id'] == produk_id:
                p.setdefault('stok_akun', []).append(akun_baru)
                simpan_data(products, 'products.json')
                await update.message.reply_text(f"✅ Stok ditambahkan ke: {produk_id}")
                return
        await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("Format: /add <id_produk> <akun>")

async def new_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        id_produk, nama_produk, harga, deskripsi = [x.strip() for x in " ".join(context.args).split('|')]
        products = muat_data('products.json')
        if any(p['id'] == id_produk for p in products):
            await update.message.reply_text(f"❌ ID '{id_produk}' sudah ada.")
            return
        products.append({
            "id": id_produk,
            "nama": nama_produk,
            "harga": int(harga),
            "deskripsi": deskripsi,
            "stok_akun": []
        })
        simpan_data(products, 'products.json')
        await update.message.reply_text(f"✅ Produk '{nama_produk}' ditambahkan.")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("Format: /newproduct <id>|<nama>|<harga>|<deskripsi>")

async def del_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id = context.args[0]
        products = muat_data('products.json')
        baru = [p for p in products if p['id'] != produk_id]
        if len(baru) < len(products):
            simpan_data(baru, 'products.json')
            await update.message.reply_text(f"✅ Produk '{produk_id}' dihapus.")
        else:
            await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except:
        await update.message.reply_text("Format: /delproduct <id>")

async def edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id, field, new_value = context.args[0], context.args[1].lower(), " ".join(context.args[2:])
        products = muat_data('products.json')
        for p in products:
            if p['id'] == produk_id:
                if field == 'harga':
                    p[field] = int(new_value)
                else:
                    p[field] = new_value
                simpan_data(products, 'products.json')
                await update.message.reply_text("✅ Produk berhasil diupdate.")
                return
        await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except Exception as e:
        logger.error(e)
        await update.message.reply_text("Format: /edit <id> <field> <new_value>")

async def info_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = muat_data('products.json')
    pesan = "📦 Daftar Stok Produk:\n\n"
    for p in products:
        pesan += f"- {p['nama']} (`{p['id']}`): {len(p.get('stok_akun', []))} akun\n"
    await update.message.reply_text(pesan, parse_mode='Markdown')

# --- HANDLER PENGGUNA ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = muat_data('counter.json')
    counters.setdefault('total_orders', 1000)
    counters.setdefault('total_turnover', 5000000)
    counters['total_orders'] += random.randint(1, 3)
    simpan_data(counters, 'counter.json')

    keyboard = [[InlineKeyboardButton("✅ Cek Stok", callback_data="cek_stok")]]
    pesan = (
        f"**Selamat datang di Skynexio Store!**\n\n"
        f"📈 Total Pesanan: **{counters['total_orders']:,}**\n"
        f"💰 Total Transaksi: **Rp{counters['total_turnover']:,}**\n\n"
        "Silakan klik tombol di bawah untuk melihat produk yang tersedia 👇"
    )
    await update.message.reply_photo(photo=LOGO_URL, caption=pesan, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hai! Untuk memulai, silakan ketik /start ya.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat.id
    data = query.data

    if data == 'cek_stok':
        products = muat_data('products.json')
        keyboard = []
        for p in products:
            if p.get('stok_akun'):
                keyboard.append([InlineKeyboardButton(f"{p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}")])
        keyboard.append([InlineKeyboardButton("⬅️ Kembali", callback_data='kembali')])
        await query.edit_message_text("Pilih produk yang ingin kamu beli:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif data.startswith('order_'):
        produk_id = data.split('_', 1)[1]
        produk = next((p for p in muat_data('products.json') if p['id'] == produk_id), None)
        if not produk:
            await query.edit_message_text("Waduh, produknya udah gaib atau stoknya baru saja habis. Coba /start lagi.")
            return
        await query.edit_message_text("Sedang membuat invoice...")
        try:
            external_id = f"order-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk['harga'],
                description=produk['nama'],
                customer={'given_names': update.effective_user.full_name}
            )
            orders = muat_data('orders.json')
            orders.append({'external_id': external_id, 'user_id': update.effective_user.id, 'produk_id': produk_id, 'harga': produk['harga'], 'status': 'PENDING'})
            simpan_data(orders, 'orders.json')
            await context.bot.send_message(chat_id, f"Silakan selesaikan pembayaranmu di link ini:\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(e)
            await query.edit_message_text("Gagal membuat invoice.")

    elif data == 'kembali':
        await query.message.delete()
        class Fake:
            def __init__(self, m): self.message = m
        await start_command(Fake(query.message), context)

# --- WEBHOOK FLASK ---
@app.route('/')
def index():
    return "Skynexio Store Bot server is running."

@app.route('/telegram', methods=['POST'])
async def telegram_webhook():
    try:
        update = Update.de_json(request.get_json(force=True), bot_app.bot)
        await bot_app.update_queue.put(update)
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(e)
        return jsonify({'status': 'error'}), 500

@app.route('/webhook/xendit', methods=['POST'])
async def xendit_webhook():
    if request.headers.get('x-callback-token') != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return jsonify({'status': 'forbidden'}), 403
    data = request.json
    if data.get('status') == 'PAID':
        external_id = data.get('external_id')
        orders = muat_data('orders.json')
        order = next((o for o in orders if o['external_id'] == external_id and o['status'] == 'PENDING'), None)
        if order:
            order['status'] = 'PAID'
            simpan_data(orders, 'orders.json')

            akun = ambil_akun_dari_stok(order['produk_id'])
            if akun:
                msg = f"✅ Pembayaran sukses!\n\nBerikut akun kamu:\n`{akun}`\n\nGaransi? Hubungi: @{ADMIN_USERNAME}"
                await bot_app.bot.send_message(order['user_id'], msg, parse_mode='Markdown')
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Penjualan: {akun}")
            else:
                await bot_app.bot.send_message(order['user_id'], "Pembayaran berhasil, tapi stok habis. Admin akan segera hubungi kamu.")
    return jsonify({'status': 'ok'})

# --- SETUP ---
async def setup():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram", allowed_updates=Update.ALL_TYPES)
    await bot_app.bot.set_my_commands([
        BotCommand("start", "Mulai bot"),
        BotCommand("infostok", "Lihat laporan stok (admin)")
    ])
    logger.info("Bot & webhook siap digunakan.")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == "__main__":
    main()
