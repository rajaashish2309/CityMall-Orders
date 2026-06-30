import telebot
import requests
import sqlite3
import logging
import uuid
import os
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# -------------------- CONFIG --------------------
BOT_TOKEN = os.getenv("BOT_TOKEN")
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN environment variable not set!")

SEND_OTP_URL = "https://citymall.live/web-api/auth/send-otp"
VERIFY_OTP_URL = "https://citymall.live/web-api/auth/verify-otp"
HOMEPAGE_URL = "https://citymall.live/"
CART_API_URL = "https://citymall.live/web-api/cart/full?activateSsaver=false"
ORDERS_API_URL = "https://citymall.live/web-api/orders?limit=50&offset=0&activePill=ALL_ORDERS"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
def init_db():
    conn = sqlite3.connect('/app/data/citymall_bot.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS users (telegram_id INTEGER PRIMARY KEY, active_account_id INTEGER)''')
    c.execute('''CREATE TABLE IF NOT EXISTS accounts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id INTEGER,
        phone TEXT,
        auth_cookie TEXT,
        device_id TEXT,
        created_at TEXT,
        FOREIGN KEY(telegram_id) REFERENCES users(telegram_id)
    )''')
    conn.commit()
    conn.close()

init_db()

def get_db():
    return sqlite3.connect('/app/data/citymall_bot.db')

# -------------------- HELPERS --------------------
def get_or_create_user(tid):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT telegram_id FROM users WHERE telegram_id = ?", (tid,))
    if not cur.fetchone():
        cur.execute("INSERT INTO users (telegram_id) VALUES (?)", (tid,))
        db.commit()
    db.close()

def get_user_active(tid):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT active_account_id FROM users WHERE telegram_id = ?", (tid,))
    row = cur.fetchone()
    db.close()
    return row[0] if row and row[0] else None

def set_user_active(tid, acc_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("UPDATE users SET active_account_id = ? WHERE telegram_id = ?", (acc_id, tid))
    db.commit()
    db.close()

def save_account(tid, phone, auth_cookie):
    db = get_db()
    cur = db.cursor()
    now = datetime.now().isoformat()
    device_id = str(uuid.uuid4())
    cur.execute('''INSERT INTO accounts (telegram_id, phone, auth_cookie, device_id, created_at)
                   VALUES (?, ?, ?, ?, ?)''', (tid, phone, auth_cookie, device_id, now))
    acc_id = cur.lastrowid
    db.commit()
    db.close()
    return acc_id

def get_accounts(tid):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, phone FROM accounts WHERE telegram_id = ? ORDER BY created_at DESC", (tid,))
    rows = cur.fetchall()
    db.close()
    return rows

def get_account(acc_id):
    db = get_db()
    cur = db.cursor()
    cur.execute("SELECT id, phone, auth_cookie FROM accounts WHERE id = ?", (acc_id,))
    row = cur.fetchone()
    db.close()
    return row

def get_account_details(acc_id):
    acc = get_account(acc_id)
    if acc:
        return f"📱 {acc[1]}\n✅ OTP Login\n📍 Gurgaon"
    return "Account not found."

# -------------------- API FUNCTIONS --------------------
def fetch_cart(auth_cookie):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
        'Cookie': f'cm_auth={auth_cookie}',
        'Content-Type': 'application/json'
    }
    try:
        resp = requests.get(CART_API_URL, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            return True, resp.json()
        else:
            return False, f"Error: {resp.status_code}"
    except Exception as e:
        return False, str(e)

def fetch_orders(auth_cookie):
    headers = {
        'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36',
        'Cookie': f'cm_auth={auth_cookie}',
        'Content-Type': 'application/json'
    }
    try:
        resp = requests.get(ORDERS_API_URL, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            return True, resp.json()
        else:
            return False, f"Error: {resp.status_code}"
    except Exception as e:
        return False, str(e)

def format_cart(data):
    try:
        cart_page = data.get('cartPage', {})
        items = cart_page.get('items', {})
        total = cart_page.get('totalPayable', 0)
        if not items:
            return "🛒 Your cart is empty."
        msg = "🛒 **Your Cart**\n\n"
        for key, item in items.items():
            if isinstance(item, dict) and 'name' in item:
                name = item.get('name', 'Unknown')
                qty = item.get('quantity', 1)
                price = item.get('price', 0)
                msg += f"• {name} x{qty} = ₹{price*qty}\n"
        msg += f"\n**Total Payable: ₹{total}**"
        return msg
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

def format_orders(data):
    try:
        orders = data.get('orders', [])
        if not orders:
            return "📦 No orders found."
        msg = "📦 **Your Orders**\n\n"
        for order in orders[:10]:
            order_id = order.get('order_id', 'N/A')
            created_at = order.get('created_at', 'N/A')
            status = order.get('status', 'Unknown')
            total = order.get('amount', 0) or order.get('total', 0)
            delivery_otp = order.get('delivery_otp', order.get('otp', 'N/A'))
            msg += f"**Order #{order_id}**\n"
            msg += f"📅 {created_at}\n"
            msg += f"💰 ₹{total}\n"
            msg += f"📊 Status: {status}\n"
            if status.lower() in ['out for delivery', 'dispatched', 'on the way', 'confirmed']:
                msg += f"🔑 Delivery OTP: `{delivery_otp}`\n"
            msg += "\n"
        return msg
    except Exception as e:
        return f"⚠️ Error: {str(e)}"

# -------------------- BOT --------------------
bot = telebot.TeleBot(BOT_TOKEN)
user_states = {}

# -------------------- KEYBOARDS --------------------
def main_menu():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("📱 My Accounts", callback_data="my_accounts"),
        InlineKeyboardButton("🏠 Home", callback_data="home")
    )
    kb.add(
        InlineKeyboardButton("💰 Wallet", callback_data="wallet"),
        InlineKeyboardButton("➕ New Login", callback_data="new_login")
    )
    kb.add(InlineKeyboardButton("📦 View Orders", callback_data="view_orders"))
    return kb

def account_list_kb(accounts):
    kb = InlineKeyboardMarkup(row_width=1)
    for acc_id, phone in accounts:
        masked = phone[:3] + "****" + phone[-4:]
        kb.add(InlineKeyboardButton(masked, callback_data=f"select_{acc_id}"))
    kb.add(InlineKeyboardButton("🔙 Back", callback_data="home"))
    return kb

def account_actions_kb(acc_id):
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(
        InlineKeyboardButton("🛒 View Cart", callback_data=f"cart_{acc_id}"),
        InlineKeyboardButton("💰 Wallet", callback_data=f"wallet_{acc_id}")
    )
    kb.add(
        InlineKeyboardButton("🎁 Referral", callback_data=f"referral_{acc_id}"),
        InlineKeyboardButton("📦 View Orders", callback_data=f"orders_{acc_id}")
    )
    kb.add(InlineKeyboardButton("🏠 Home", callback_data="home"))
    return kb

# -------------------- OTP FUNCTIONS --------------------
def send_otp(phone):
    headers = {'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36', 'Content-Type': 'application/json'}
    session = requests.Session()
    try:
        session.get(HOMEPAGE_URL, timeout=5)
    except:
        pass
    payload = {'phone_number': phone}
    try:
        resp = session.post(SEND_OTP_URL, json=payload, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            return True, "OTP sent.", session
        else:
            return False, f"Failed: {resp.status_code}", None
    except Exception as e:
        return False, str(e), None

def verify_otp(phone, otp, session):
    headers = {'User-Agent': 'Mozilla/5.0 (Linux; Android 10) AppleWebKit/537.36', 'Content-Type': 'application/json'}
    payload = {'phone_number': phone, 'otp': otp, 'source': 'web', 'device_id': '', 'idfa': '', 'device_info': '', 'tracking_info': ''}
    try:
        resp = session.post(VERIFY_OTP_URL, json=payload, headers=headers, timeout=10, verify=False)
        if resp.status_code == 200:
            cookies = session.cookies.get_dict()
            auth_cookie = cookies.get('cm_auth')
            if not auth_cookie:
                set_cookie = resp.headers.get('Set-Cookie', '')
                for part in set_cookie.split(','):
                    if 'cm_auth=' in part:
                        auth_cookie = part.split('cm_auth=')[1].split(';')[0]
                        break
            if auth_cookie:
                return True, auth_cookie, "Login successful!"
            else:
                return False, None, "No auth cookie"
        else:
            return False, None, f"Status {resp.status_code}"
    except Exception as e:
        return False, None, str(e)

# -------------------- HANDLERS (NO CHANNEL CHECK) --------------------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    tid = message.chat.id
    get_or_create_user(tid)
    bot.send_message(
        tid,
        "<b>CityMall Orders</b>\n\nManage your accounts, view cart and orders.",
        reply_markup=main_menu(),
        parse_mode='HTML'
    )

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    tid = message.chat.id
    state = user_states.get(tid)
    if not state:
        return bot.reply_to(message, "⚠️ Use the buttons below.", reply_markup=main_menu())
    if state.get('state') == 'AWAITING_PHONE':
        phone = message.text.strip()
        if not phone.isdigit() or len(phone) != 10:
            return bot.reply_to(message, "❌ Enter valid 10-digit number.")
        ok, msg, session = send_otp(phone)
        if not ok:
            return bot.reply_to(message, f"❌ {msg}")
        user_states[tid] = {'state': 'AWAITING_OTP', 'phone': phone, 'session': session}
        bot.reply_to(message, f"✅ OTP sent to {phone}. Enter OTP:")
    elif state.get('state') == 'AWAITING_OTP':
        otp = message.text.strip()
        if not otp.isdigit() or len(otp) != 4:
            return bot.reply_to(message, "❌ Enter valid 4-digit OTP.")
        phone = state['phone']
        session = state.get('session')
        if not session:
            user_states[tid] = None
            return bot.reply_to(message, "❌ Session expired. Start /start again.")
        ok, auth_cookie, msg = verify_otp(phone, otp, session)
        if not ok:
            user_states[tid] = None
            return bot.reply_to(message, f"❌ {msg}")
        acc_id = save_account(tid, phone, auth_cookie or "")
        set_user_active(tid, acc_id)
        user_states[tid] = None
        bot.send_message(
            tid,
            f"✅ Account linked!\n\n{get_account_details(acc_id)}",
            reply_markup=account_actions_kb(acc_id)
        )

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    tid = call.message.chat.id
    data = call.data
    print("Callback:", data)

    if data == "home":
        bot.edit_message_text(
            "<b>CityMall Orders</b>\n\nManage your accounts.",
            tid,
            call.message.message_id,
            reply_markup=main_menu(),
            parse_mode='HTML'
        )
        bot.answer_callback_query(call.id)

    elif data == "new_login":
        user_states[tid] = {'state': 'AWAITING_PHONE'}
        bot.edit_message_text(
            "📱 Enter your 10-digit number:",
            tid,
            call.message.message_id,
            reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Cancel", callback_data="home"))
        )
        bot.answer_callback_query(call.id)

    elif data == "my_accounts":
        accounts = get_accounts(tid)
        if not accounts:
            bot.answer_callback_query(call.id, "No accounts.")
            bot.edit_message_text("❌ No accounts found.", tid, call.message.message_id, reply_markup=main_menu())
            return
        bot.edit_message_text(
            "<b>My Accounts</b>",
            tid,
            call.message.message_id,
            reply_markup=account_list_kb(accounts),
            parse_mode='HTML'
        )
        bot.answer_callback_query(call.id)

    elif data == "view_orders":
        active_id = get_user_active(tid)
        if not active_id:
            bot.answer_callback_query(call.id, "No active account.")
            return
        acc = get_account(active_id)
        if not acc:
            bot.answer_callback_query(call.id, "Account not found.")
            return
        ok, orders_data = fetch_orders(acc[2])
        if ok:
            msg = format_orders(orders_data)
            bot.send_message(tid, msg, parse_mode='Markdown')
        else:
            bot.send_message(tid, f"❌ Failed to fetch orders: {orders_data}")
        bot.answer_callback_query(call.id)

    elif data.startswith("select_"):
        acc_id = int(data.split("_")[1])
        acc = get_account(acc_id)
        if not acc:
            bot.answer_callback_query(call.id, "Not found.")
            return
        set_user_active(tid, acc_id)
        details = get_account_details(acc_id)
        bot.edit_message_text(
            f"<b>ACCOUNT READY</b>\n\n{details}",
            tid,
            call.message.message_id,
            reply_markup=account_actions_kb(acc_id),
            parse_mode='HTML'
        )
        bot.answer_callback_query(call.id)

    elif data.startswith("cart_"):
        acc_id = int(data.split("_")[1])
        acc = get_account(acc_id)
        if not acc:
            bot.answer_callback_query(call.id, "Account not found.")
            return
        ok, cart_data = fetch_cart(acc[2])
        if ok:
            msg = format_cart(cart_data)
            bot.send_message(tid, msg, parse_mode='Markdown')
        else:
            bot.send_message(tid, f"❌ Failed to fetch cart: {cart_data}")
        bot.answer_callback_query(call.id)

    elif data.startswith("orders_"):
        acc_id = int(data.split("_")[1])
        acc = get_account(acc_id)
        if not acc:
            bot.answer_callback_query(call.id, "Account not found.")
            return
        ok, orders_data = fetch_orders(acc[2])
        if ok:
            msg = format_orders(orders_data)
            bot.send_message(tid, msg, parse_mode='Markdown')
        else:
            bot.send_message(tid, f"❌ Failed to fetch orders: {orders_data}")
        bot.answer_callback_query(call.id)

    elif data.startswith("wallet_"):
        bot.answer_callback_query(call.id)
        bot.send_message(tid, "💰 Wallet feature coming soon!")

    elif data.startswith("referral_"):
        bot.answer_callback_query(call.id)
        bot.send_message(tid, "🎁 Referral feature coming soon!")

    elif data == "wallet":
        active = get_user_active(tid)
        if not active:
            bot.answer_callback_query(call.id, "No active account.")
            return
        bot.answer_callback_query(call.id)
        bot.send_message(tid, "💰 Wallet feature coming soon!")

    else:
        bot.answer_callback_query(call.id, "Unknown action.")

# -------------------- MAIN --------------------
if __name__ == "__main__":
    print("Bot started...")
    bot.infinity_polling()
