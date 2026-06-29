import telebot
import requests
import sqlite3
import logging
import uuid
from datetime import datetime
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

# -------------------- CONFIG --------------------
BOT_TOKEN = "8971645884:AAGzC9O2Kuau4E1Ll09ON_6oFZcDFpv6zs8"   # <-- Yahan naya token daalo
SEND_OTP_URL = "https://citymall.live/web-api/auth/send-otp"
VERIFY_OTP_URL = "https://citymall.live/web-api/auth/verify-otp"
HOMEPAGE_URL = "https://citymall.live/"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# -------------------- DATABASE --------------------
def init_db():
    conn = sqlite3.connect('citymall_bot.db')
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
    return sqlite3.connect('citymall_bot.db')

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

# -------------------- BOT --------------------
bot = telebot.TeleBot(BOT_TOKEN)
user_states = {}  # tid -> {'state': 'AWAITING_PHONE'|'AWAITING_OTP', 'phone':..., 'session':...}

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
    kb.add(InlineKeyboardButton("🛒 Let my coupon work", callback_data="open_store"))
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
        InlineKeyboardButton("🏠 Home", callback_data="home")
    )
    return kb

# -------------------- API FUNCTIONS --------------------
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

# -------------------- HANDLERS --------------------
@bot.message_handler(commands=['start'])
def start_cmd(message):
    tid = message.chat.id
    get_or_create_user(tid)
    bot.send_message(tid, "<b>CityMall Bot</b>\n\nManage your accounts easily.", reply_markup=main_menu(), parse_mode='HTML')

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
        bot.send_message(tid, f"✅ Account linked!\n\n{get_account_details(acc_id)}", reply_markup=account_actions_kb(acc_id))

@bot.callback_query_handler(func=lambda call: True)
def callback(call):
    tid = call.message.chat.id
    data = call.data
    print("Callback:", data)

    if data == "home":
        bot.edit_message_text("<b>CityMall Bot</b>\n\nManage your accounts.", tid, call.message.message_id, reply_markup=main_menu(), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif data == "new_login":
        user_states[tid] = {'state': 'AWAITING_PHONE'}
        bot.edit_message_text("📱 Enter your 10-digit number:", tid, call.message.message_id, reply_markup=InlineKeyboardMarkup().add(InlineKeyboardButton("🔙 Cancel", callback_data="home")))
        bot.answer_callback_query(call.id)

    elif data == "my_accounts":
        accounts = get_accounts(tid)
        if not accounts:
            bot.answer_callback_query(call.id, "No accounts.")
            bot.edit_message_text("❌ No accounts found.", tid, call.message.message_id, reply_markup=main_menu())
            return
        bot.edit_message_text("<b>My Accounts</b>", tid, call.message.message_id, reply_markup=account_list_kb(accounts), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif data.startswith("select_"):
        acc_id = int(data.split("_")[1])
        acc = get_account(acc_id)
        if not acc:
            bot.answer_callback_query(call.id, "Not found.")
            return
        set_user_active(tid, acc_id)
        details = get_account_details(acc_id)
        bot.edit_message_text(f"<b>ACCOUNT READY</b>\n\n{details}", tid, call.message.message_id, reply_markup=account_actions_kb(acc_id), parse_mode='HTML')
        bot.answer_callback_query(call.id)

    elif data.startswith("cart_"):
        bot.answer_callback_query(call.id)
        bot.send_message(tid, "🛒 Cart feature coming soon!")

    elif data.startswith("wallet_"):
        bot.answer_callback_query(call.id)
        bot.send_message(tid, "💰 Wallet feature coming soon!")

    elif data.startswith("referral_"):
        bot.answer_callback_query(call.id)
        bot.send_message(tid, "🎁 Referral feature coming soon!")

    elif data == "open_store":
        bot.answer_callback_query(call.id)
        bot.send_message(tid, "🛒 <a href='https://citymall.live'>Open CityMall Store</a>", parse_mode='HTML')

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
