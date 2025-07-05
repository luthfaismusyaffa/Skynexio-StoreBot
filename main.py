# main.py - VERSI FINAL DENGAN PERBAIKAN ID PRODUK MENGANDUNG UNDERSCORE

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
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "username_admin_anda")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
LOGO_URL = os.environ.get("LOGO_URL", "https://i.imgur.com/default-logo.png")

# Inisialisasi
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)
xendit.api_key = XENDIT_API_KEY
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# --- FUNGSI DATABASE & STOK ---
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

# --- PERINTAH ADMIN ---
def is_admin(update: Update):
    return str(update.effective_user.id) == ADMIN_CHAT_ID

async def add_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id, akun_baru = context.args[0], " ".join(context.args[1:])
        products = muat_data('products.json')
        for p in products:
            if p['id'] == produk_id:
                p.setdefault('stok_akun', []).append(akun_baru)
                simpan_data(products, 'products.json')
                await update.message.reply_text(f"✅ Stok ditambahkan ke: {produk_id}")
                return
        await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except:
        await update.message.reply_text("Format: /add <id_produk> <detail_akun>")

async def new_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        id_produk, nama_produk, harga, deskripsi = [x.strip() for x in " ".join(context.args).split('|')]
        products = muat_data('products.json')
        if any(p['id'] == id_produk for p in products):
            await update.message.reply_text(f"❌ ID '{id_produk}' sudah ada.")
            return
        products.append({"id": id_produk, "nama": nama_produk, "harga": int(harga), "deskripsi": deskripsi, "stok_akun": []})
        simpan_data(products, 'products.json')
        await update.message.reply_text(f"✅ Produk '{nama_produk}' dibuat.")
    except Exception as e:
        logger.error(f"Error newproduct: {e}")
        await update.message.reply_text("Format: /newproduct <id> | <nama> | <harga> | <deskripsi>")

async def del_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id = context.args[0]
        products = muat_data('products.json')
        products = [p for p in products if p['id'] != produk_id]
        simpan_data(products, 'products.json')
        await update.message.reply_text(f"✅ Produk '{produk_id}' dihapus.")
    except:
        await update.message.reply_text("Format: /delproduct <id_produk>")

async def edit_product(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    try:
        produk_id, field, new_value = context.args[0], context.args[1].lower(), " ".join(context.args[2:])
        if field not in ['nama', 'harga', 'deskripsi']:
            await update.message.reply_text("Field: 'nama', 'harga', 'deskripsi'.")
            return
        products = muat_data('products.json')
        for p in products:
            if p['id'] == produk_id:
                p[field] = int(new_value) if field == 'harga' else new_value
                simpan_data(products, 'products.json')
                await update.message.reply_text(f"✅ Produk '{produk_id}' diupdate.")
                return
        await update.message.reply_text(f"❌ Produk ID '{produk_id}' tidak ditemukan.")
    except:
        await update.message.reply_text("Format: /edit <id_produk> <field> <nilai_baru>")

async def info_stock(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not is_admin(update): return
    products = muat_data('products.json')
    pesan_stok = "📦 **Laporan Stok Saat Ini** 📦\n\n"
    for p in products:
        pesan_stok += f"- `{p['id']}`\n  Nama: {p['nama']}\n  Stok: **{len(p.get('stok_akun', []))}** akun\n\n"
    await update.message.reply_text(pesan_stok, parse_mode='Markdown')

# --- HANDLER PENGGUNA ---
async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = muat_data('counter.json')
    counters.setdefault('total_orders', 5530)
    counters.setdefault('total_turnover', 54000000)
    counters['total_orders'] += random.randint(1, 3)
    simpan_data(counters, 'counter.json')

    keyboard = [[InlineKeyboardButton("✅ Cek Stok Ready", callback_data='cek_stok')]]
    pesan = f"**Selamat Datang di Skynexio Store!** ✨\n\nPusatnya akun premium untuk segala kebutuhan digitalmu!\n\n---\n📈 Total Pesanan: **{counters['total_orders']:,}**\n💰 Total Transaksi: **Rp{counters['total_turnover']:,}**\n---\n\nYuk mulai belanja!"
    await update.message.reply_photo(photo=LOGO_URL, caption=pesan, parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hai! Untuk memulai, silakan ketik /start ya.")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    chat_id = query.message.chat_id

    if query.data == 'cek_stok':
        await query.message.delete()
        products = muat_data('products.json')
        keyboard = [[InlineKeyboardButton(f"✅ {p['nama']} - Rp{p['harga']:,}", callback_data=f"order_{p['id']}") for p in products if p.get('stok_akun')]]
        keyboard.append([InlineKeyboardButton("⬅️ Kembali ke Menu Awal", callback_data='kembali_ke_awal')])
        await context.bot.send_message(chat_id=chat_id, text="Pilih produk yang kamu mau:", reply_markup=InlineKeyboardMarkup(keyboard))

    elif query.data == 'kembali_ke_awal':
        await query.message.delete()

        class MockMessage:
            def __init__(self, original_message):
                self.message = original_message

        await start_command(MockMessage(query.message), context)

    elif query.data.startswith('order_'):
        produk_id = query.data.replace("order_", "", 1)
        produk = next((p for p in muat_data('products.json') if p['id'] == produk_id), None)
        if not produk:
            await context.bot.send_message(chat_id=chat_id, text="Produk tidak ditemukan atau stok habis.")
            await query.message.delete()
            return

        await query.edit_message_text("Membuat invoice pembayaran... ⏳")
        try:
            external_id = f"trx-{produk_id}-{update.effective_user.id}-{int(time.time())}"
            invoice = xendit.Invoice.create(
                external_id=external_id,
                amount=produk['harga'],
                description=f"Pembelian {produk['nama']}",
                customer={'given_names': update.effective_user.full_name}
            )
            orders = muat_data('orders.json')
            orders.append({'external_id': external_id, 'user_id': update.effective_user.id, 'produk_id': produk_id, 'harga': produk['harga'], 'status': 'PENDING'})
            simpan_data(orders, 'orders.json')
            await query.edit_message_text(f"✅ Invoice siap dibayar:\n{invoice.invoice_url}")
        except Exception as e:
            logger.error(f"Invoice error: {e}")
            await query.edit_message_text("❌ Gagal membuat invoice.")

# --- ROUTE FLASK ---
@app.route('/')
def index():
    return "Bot aktif."

@app.route('/telegram', methods=['POST'])
async def telegram_webhook():
    try:
        await bot_app.initialize()
        await bot_app.process_update(Update.de_json(request.get_json(force=True), bot_app.bot))
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Telegram webhook error: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/webhook/xendit', methods=['POST'])
async def xendit_webhook():
    if request.headers.get('x-callback-token') != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return jsonify({'status': 'unauthorized'}), 403

    data = request.json
    if data.get('status') == 'PAID':
        external_id = data.get('external_id')
        orders = muat_data('orders.json')
        order = next((o for o in orders if o['external_id'] == external_id and o['status'] == 'PENDING'), None)
        if order:
            await bot_app.initialize()
            order['status'] = 'PAID'
            akun = ambil_akun_dari_stok(order['produk_id'])
            simpan_data(orders, 'orders.json')
            counters = muat_data('counter.json')
            counters['total_orders'] += 1
            counters['total_turnover'] += order['harga']
            simpan_data(counters, 'counter.json')

            if akun:
                parts = akun.split('|')
                pesan = f"Login: `{parts[0]}`"
                if len(parts) > 1:
                    pesan += f"\nProfil: **{parts[1]}**"
                if len(parts) > 2:
                    pesan += f"\nPIN: `{parts[2]}`"
                pesan += f"\n\nGaransi? Hubungi [Admin](https://t.me/{ADMIN_USERNAME}) dengan bukti login."
                await bot_app.bot.send_message(order['user_id'], pesan, parse_mode='Markdown')
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Order berhasil:\nID: {external_id}\nAkun: {akun}")
            else:
                await bot_app.bot.send_message(order['user_id'], "Pembayaran diterima, tapi stok kosong. Admin akan hubungi Anda.")
                await bot_app.bot.send_message(ADMIN_CHAT_ID, f"⚠️ STOK HABIS untuk ID: {external_id}")
    return jsonify({'status': 'received'})

# --- SETUP BOT ---
async def setup():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(url=f"{WEBHOOK_URL}/telegram", allowed_updates=Update.ALL_TYPES)
    await bot_app.bot.set_my_commands([
        BotCommand("start", "🚀 Mulai Bot"),
        BotCommand("infostok", "📦 Info Stok (Admin)")
    ])
    logger.info("Webhook dan perintah bot diatur.")

def main():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    port = int(os.environ.get("PORT", 8080))
    serve(app, host="0.0.0.0", port=port)

if __name__ == '__main__':
    main()
