from supabase import create_client
import os

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")
supabase = create_client(url, key)

# Fungsi CRUD:
def get_products_ready():
    return supabase.table("products").select("id, nama, harga, deskripsi").execute().data

def get_stock_for_product(produk_id):
    return supabase.table("stok_akun")\
        .select("*")\
        .eq("produk_id", produk_id)\
        .eq("sold", False)\
        .limit(1).execute().data

def mark_stock_sold(akun_id):
    supabase.table("stok_akun").update({"sold": True}).eq("id", akun_id).execute()

def create_order(record):
    return supabase.table("orders").insert(record).execute().data

def update_order_status(external_id, akun_id=None):
    update_data = {"status": "PAID"}
    if akun_id: update_data["akun_id"] = akun_id
    supabase.table("orders").update(update_data).eq("external_id", external_id).execute()
