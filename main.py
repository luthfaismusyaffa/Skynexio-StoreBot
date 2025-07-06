# main.py - Skynexio Store Bot terintegrasi dengan Supabase

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
from supabase import create_client, Client
import xendit

# --- KONFIGURASI ---
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
ADMIN_CHAT_ID = os.environ.get("ADMIN_CHAT_ID")
ADMIN_USERNAME = os.environ.get("ADMIN_USERNAME", "username_admin_anda")
XENDIT_API_KEY = os.environ.get("XENDIT_API_KEY")
XENDIT_WEBHOOK_VERIFICATION_TOKEN = os.environ.get("XENDIT_WEBHOOK_VERIFICATION_TOKEN")
WEBHOOK_URL = os.environ.get("WEBHOOK_URL")
SUPABASE_URL = os.environ.get("SUPABASE_URL")
SUPABASE_KEY = os.environ.get("SUPABASE_KEY")

supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)
xendit.api_key = XENDIT_API_KEY
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)
app = Flask(__name__)
bot_app = Application.builder().token(TELEGRAM_TOKEN).build()

# --- UTILITY ---
def fmt_rp(n): return f"Rp{n:,}".replace(",", ".")

# --- HANDLER BOT ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    counters = supabase.table("counters").select("*").limit(1).execute().data
    if not counters:
        supabase.table("counters").insert({"total_orders": 5561, "total_turnover": 54000000}).execute()
        total_orders, total_turnover = 5561, 54000000
    else:
        total_orders, total_turnover = counters[0]['total_orders'], counters[0]['total_turnover']
        supabase.table("counters").update({
            "total_orders": total_orders + random.randint(1, 3)
        }).eq("id", counters[0]['id']).execute()

    keyboard = [[InlineKeyboardButton("✅ Cek Stok Ready", callback_data='cek_stok')]]
    await update.message.reply_text(
        f"**Selamat Datang di Skynexio Store!**\n\n"
        f"📈 Total Pesanan Dilayani: {total_orders:,}\n"
        f"💰 Total Transaksi: {fmt_rp(total_turnover)}\n\n"
        "Kami siap melayani Anda 24/7 dengan proses instan.",
        parse_mode='Markdown', reply_markup=InlineKeyboardMarkup(keyboard))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query; await query.answer()
    chat_id = query.message.chat_id
    if query.data == 'cek_stok':
        products = supabase.table("products").select("*").execute().data
        stok = supabase.table("stok_akun").select("produk_id", count="exact").execute().data
        stok_map = {s['produk_id']: s['count'] for s in stok if s['count'] > 0}
        keyboard = [[InlineKeyboardButton(f"{p['nama']} - {fmt_rp(p['harga'])}", callback_data=f"order_{p['id']}")
                     for p in products if p['id'] in stok_map]]
        await context.bot.send_message(chat_id=chat_id, text="Pilih produk:", reply_markup=InlineKeyboardMarkup(keyboard))
    elif query.data.startswith('order_'):
        produk_id = query.data.split('_')[1]
        produk = supabase.table("products").select("*").eq("id", produk_id).execute().data
        if not produk:
            await context.bot.send_message(chat_id, "Produk tidak ditemukan.")
            return
        produk = produk[0]
        external_id = f"skynexio-{produk_id}-{update.effective_user.id}-{int(time.time())}"
        invoice = xendit.Invoice.create(external_id=external_id, amount=produk['harga'],
                                        description=produk['nama'], customer={'given_names': update.effective_user.full_name})
        supabase.table("orders").insert({
            "external_id": external_id,
            "produk_id": produk_id,
            "user_id": update.effective_user.id,
            "harga": produk['harga'],
            "status": "PENDING"
        }).execute()
        await query.edit_message_text(f"Tiketmu siap! Klik link bayar:
{invoice.invoice_url}")

@app.route('/')
def index(): return "Bot aktif."

@app.route('/telegram', methods=['POST'])
async def telegram_webhook():
    try:
        await bot_app.initialize()
        await bot_app.process_update(Update.de_json(request.get_json(force=True), bot_app.bot))
        return jsonify({'status': 'ok'})
    except Exception as e:
        logger.error(f"Webhook error: {e}")
        return jsonify({'status': 'error'}), 500

@app.route('/webhook/xendit', methods=['POST'])
async def xendit_webhook():
    if request.headers.get('x-callback-token') != XENDIT_WEBHOOK_VERIFICATION_TOKEN:
        return jsonify({'status': 'unauthorized'}), 403
    data = request.get_json()
    if data.get("status") == "PAID":
        ext_id = data.get("external_id")
        order = supabase.table("orders").select("*").eq("external_id", ext_id).execute().data
        if not order: return jsonify({'status': 'not found'}), 404
        order = order[0]
        supabase.table("orders").update({"status": "PAID"}).eq("external_id", ext_id).execute()
        stok = supabase.table("stok_akun").select("*").eq("produk_id", order['produk_id']).limit(1).execute().data
        if stok:
            akun = stok[0]['data']; akun_id = stok[0]['id']
            supabase.table("stok_akun").delete().eq("id", akun_id).execute()
            await bot_app.bot.send_message(order['user_id'], f"✅ Ini akun kamu:\n{akun}")
            await bot_app.bot.send_message(ADMIN_CHAT_ID, f"✅ Order dari {order['user_id']} berhasil. Produk: {order['produk_id']}\n{akun}")
        else:
            await bot_app.bot.send_message(order['user_id'], "✅ Bayar berhasil tapi stok kosong. Admin akan kirim manual.")
    return jsonify({'status': 'success'})

async def setup():
    await bot_app.initialize()
    await bot_app.bot.set_webhook(f"{WEBHOOK_URL}/telegram")
    await bot_app.bot.set_my_commands([BotCommand("start", "Mulai bot")])

def main():
    loop = asyncio.new_event_loop(); asyncio.set_event_loop(loop)
    loop.run_until_complete(setup())
    serve(app, host="0.0.0.0", port=int(os.environ.get("PORT", 8080)))

if __name__ == '__main__':
    main()
