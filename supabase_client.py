from supabase import create_client, Client
import os

# Ambil ENV dari Railway
url: str = os.getenv("SUPABASE_URL")
key: str = os.getenv("SUPABASE_KEY")

# Validasi
if not url or not key:
    raise ValueError("❌ SUPABASE_URL atau SUPABASE_KEY tidak ditemukan di environment variables.")

supabase: Client = create_client(url, key)

# Ambil produk yang masih punya stok ready
def get_products_ready():
    response = supabase.table("products").select("id, nama, harga, deskripsi").execute()
    return response.data if response and response.data else []

# Ambil 1 stok akun yang belum terjual untuk produk tertentu
def get_stock_for_product(produk_id):
    response = supabase.table("stok_akun")\
        .select("*")\
        .eq("produk_id", produk_id)\
        .eq("sold", False)\
        .limit(1)\
        .execute()
    return response.data[0] if response and response.data else None

# Tandai akun sebagai sudah terjual
def mark_stock_sold(akun_id):
    supabase.table("stok_akun").update({"sold": True}).eq("id", akun_id).execute()

# Buat order baru
def create_order(record):
    response = supabase.table("orders").insert(record).execute()
    return response.data[0] if response and response.data else None

# Update status order menjadi PAID (dan simpan akun_id jika ada)
def update_order_status(external_id, akun_id=None):
    update_data = {"status": "PAID"}
    if akun_id:
        update_data["akun_id"] = akun_id
    supabase.table("orders").update(update_data).eq("external_id", external_id).execute()
