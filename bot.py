
import os
import time
import sqlite3
import threading
import requests

import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton

=========================================================

SETTINGS

=========================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
CRYPTO_PAY_TOKEN = os.getenv("CRYPTO_PAY_TOKEN")
SIM5_API_KEY = os.getenv("SIM5_API_KEY")

PROOF_CHANNEL = os.getenv("PROOF_CHANNEL", "@LadaNumber1473")
BOT_LINK = os.getenv("BOT_LINK", "https://t.me/LadaNumber")

DB_FILE = "lada_number.db"

if not BOT_TOKEN:
raise RuntimeError("BOT_TOKEN is missing from environment variables")

if not CRYPTO_PAY_TOKEN:
raise RuntimeError("CRYPTO_PAY_TOKEN is missing from environment variables")

if not SIM5_API_KEY:
raise RuntimeError("SIM5_API_KEY is missing from environment variables")

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

=========================================================

DATABASE

=========================================================

db_lock = threading.Lock()

def get_db():
conn = sqlite3.connect(
DB_FILE,
check_same_thread=False
)
conn.row_factory = sqlite3.Row
return conn

db = get_db()

def init_db():
with db_lock:
db.execute("""
CREATE TABLE IF NOT EXISTS users (
user_id INTEGER PRIMARY KEY,
balance REAL NOT NULL DEFAULT 0,
created_at INTEGER NOT NULL
)
""")

db.execute("""  
        CREATE TABLE IF NOT EXISTS invoices (  
            invoice_id TEXT PRIMARY KEY,  
            user_id INTEGER NOT NULL,  
            amount REAL NOT NULL,  
            status TEXT NOT NULL DEFAULT 'active',  
            created_at INTEGER NOT NULL,  
            paid_at INTEGER  
        )  
    """)  

    db.execute("""  
        CREATE TABLE IF NOT EXISTS orders (  
            id INTEGER PRIMARY KEY AUTOINCREMENT,  
            user_id INTEGER NOT NULL,  
            country TEXT NOT NULL,  
            price REAL NOT NULL,  
            status TEXT NOT NULL DEFAULT 'pending',  
            reference TEXT,  
            provider_phone TEXT,  
            created_at INTEGER NOT NULL,  
            completed_at INTEGER  
        )  
    """)  
    db.commit()

init_db()

=========================================================

USER FUNCTIONS

=========================================================

def ensure_user(user_id):
with db_lock:
db.execute("""
INSERT OR IGNORE INTO users
(user_id, balance, created_at)
VALUES (?, 0, ?)
""", (user_id, int(time.time())))
db.commit()

def get_balance(user_id):
ensure_user(user_id)
row = db.execute("""
SELECT balance
FROM users
WHERE user_id = ?
""", (user_id,)).fetchone()
return float(row["balance"])

def add_balance(user_id, amount):
with db_lock:
ensure_user(user_id)
db.execute("""
UPDATE users
SET balance = balance + ?
WHERE user_id = ?
""", (amount, user_id))
db.commit()

def subtract_balance(user_id, amount):
with db_lock:
ensure_user(user_id)
row = db.execute("""
SELECT balance
FROM users
WHERE user_id = ?
""", (user_id,)).fetchone()

balance = float(row["balance"])  
    if balance < amount:  
        return False  

    db.execute("""  
        UPDATE users  
        SET balance = balance - ?  
        WHERE user_id = ?  
    """, (amount, user_id))  
    db.commit()  
    return True

=========================================================

CRYPTO PAY

=========================================================

CRYPTO_URL = "https://pay.crypt.bot/api"

def crypto_request(method, data=None):
headers = {
"Crypto-Pay-API-Token": CRYPTO_PAY_TOKEN
}
response = requests.post(
f"{CRYPTO_URL}/{method}",
headers=headers,
json=data or {},
timeout=20
)
response.raise_for_status()
result = response.json()
if not result.get("ok"):
raise RuntimeError(
result.get("error", "Crypto Pay API error")
)
return result["result"]

def create_invoice(user_id, amount):
result = crypto_request(
"createInvoice",
{
"asset": "USDT",
"amount": str(amount),
"description": f"Lada Number balance - {user_id}",
"payload": str(user_id),
"allow_comments": False,
"allow_anonymous": False
}
)
invoice_id = str(result["invoice_id"])
pay_url = result["pay_url"]

with db_lock:  
    db.execute("""  
        INSERT INTO invoices  
        (invoice_id, user_id, amount, status, created_at)  
        VALUES (?, ?, ?, 'active', ?)  
    """, (  
        invoice_id,  
        user_id,  
        amount,  
        int(time.time())  
    ))  
    db.commit()  
return invoice_id, pay_url

def get_invoice(invoice_id):
result = crypto_request(
"getInvoices",
{
"invoice_ids": str(invoice_id)
}
)
items = result.get("items", [])
if not items:
return None
return items[0]

=========================================================

PAYMENT MONITOR

=========================================================

def payment_monitor():
print("Payment monitor started.")
while True:
try:
rows = db.execute("""
SELECT invoice_id, user_id, amount
FROM invoices
WHERE status = 'active'
ORDER BY created_at ASC
LIMIT 50
""").fetchall()

for row in rows:  
            invoice_id = row["invoice_id"]  
            try:  
                invoice = get_invoice(invoice_id)  
                if not invoice or invoice.get("status") != "paid":  
                    continue  

                with db_lock:  
                    current = db.execute("""  
                        SELECT status  
                        FROM invoices  
                        WHERE invoice_id = ?  
                    """, (invoice_id,)).fetchone()  

                    if not current or current["status"] == "paid":  
                        continue  

                    db.execute("""  
                        UPDATE invoices  
                        SET status = 'paid',  
                            paid_at = ?  
                        WHERE invoice_id = ?  
                    """, (  
                        int(time.time()),  
                        invoice_id  
                    ))  
                    db.commit()  

                amount = float(row["amount"])  
                user_id = int(row["user_id"])  
                add_balance(user_id, amount)  

                try:  
                    bot.send_message(  
                        user_id,  
                        "✅ <b>تم تأكيد الدفع</b>\n\n"  
                        f"💰 تمت إضافة <b>{amount:.2f} USDT</b> "  
                        "إلى رصيدك.\n\n"  
                        f"💳 رصيدك الحالي: "  
                        f"<b>{get_balance(user_id):.2f} USDT</b>"  
                    )  
                except Exception as e:  
                    print("Telegram payment notification error:", e)  

            except Exception as e:  
                print(f"Invoice {invoice_id} check error:", repr(e))  
    except Exception as e:  
        print("Payment monitor error:", repr(e))  
    time.sleep(20)

=========================================================

UI

=========================================================

def main_keyboard():
markup = InlineKeyboardMarkup(row_width=1)
markup.add(InlineKeyboardButton("🌍 الخدمات", callback_data="services"))
markup.add(InlineKeyboardButton("💳 شحن الرصيد", callback_data="deposit"))
markup.add(InlineKeyboardButton("💰 رصيدي", callback_data="balance"))
markup.add(InlineKeyboardButton("📦 طلباتي", callback_data="orders"))
markup.add(InlineKeyboardButton("📢 قناة الإثباتات", url=PROOF_CHANNEL.replace("@", "https://t.me/")))
return markup

def show_main(chat_id):
ensure_user(chat_id)
balance = get_balance(chat_id)
text = (
"✨ <b>مرحباً بك في Lada Number</b>\n\n"
f"💰 رصيدك: <b>{balance:.2f} USDT</b>\n\n"
"اختار من القائمة:"
)
bot.send_message(chat_id, text, reply_markup=main_keyboard())

@bot.message_handler(commands=["start"])
def start(message):
ensure_user(message.from_user.id)
show_main(message.chat.id)

=========================================================

20 COUNTRIES PRICING HANDLERS

=========================================================

TARGET_COUNTRIES = {
"russia": "🇷🇺 روسيا",
"indonesia": "🇮🇩 إندونيسيا",
"vietnam": "🇻🇳 فييتنام",
"ukraine": "🇺🇦 أوكرانيا",
"kazakhstan": "🇰🇿 كازاخستان",
"philippines": "🇵🇭 الفلبين",
"malaysia": "🇲🇾 ماليزيا",
"india": "🇮🇳 الهند",
"kyrgyzstan": "🇰🇬 قيرغيزستان",
"brazil": "🇧🇷 البرازيل",
"egypt": "🇪🇬 مصر",
"usa": "🇺🇸 أمريكا",
"uk": "🇬🇧 بريطانيا",
"canada": "🇨🇦 كندا",
"pakistan": "🇵🇰 باكستان",
"bangladesh": "🇧🇩 بنغلاديش",
"thailand": "🇹🇭 تايلاند",
"morocco": "🇲🇦 المغرب",
"algeria": "🇩🇿 الجزائر",
"iraq": "🇮🇶 العراق"
}

@bot.callback_query_handler(func=lambda call: call.data == "services")
def cb_services(call):
user_id = call.from_user.id
chat_id = call.message.chat.id
ensure_user(user_id)

try:  
    bot.answer_callback_query(call.id, "⏳ جاري عرض الدول المتاحة...")  
except:  
    pass  

prices_url = "https://5sim.net/v1/guest/prices"  
  
try:  
    response = requests.get(prices_url, timeout=15)  
    prices_data = response.json()  
except Exception as e:  
    print("Live Prices API Error:", repr(e))  
    bot.send_message(chat_id, "❌ حدث خطأ أثناء الاتصال بموقع الأرقام.")  
    return  

markup = InlineKeyboardMarkup(row_width=2)  
buttons = []  

try:  
    for code, arabic_name in TARGET_COUNTRIES.items():  
        if code in prices_data:  
            services = prices_data[code]  
            if not isinstance(services, dict) or "telegram" not in services:  
                continue  
              
            telegram_data = services["telegram"]  
            min_price = 999999  
            total_count = 0  
              
            if isinstance(telegram_data, dict):  
                for op_name, op_info in telegram_data.items():  
                    if isinstance(op_info, dict):  
                        cost = float(op_info.get("cost", op_info.get("price", 0)))  
                        count = int(op_info.get("count", 0))  
                          
                        if cost > 0 and count > 0:  
                            total_count += count  
                            if cost < min_price:  
                                min_price = cost  

            if min_price != 999999 and total_count > 0:  
                if min_price <= 0.20:  
                    final_price = round(min_price * 2.5, 2)  
                else:  
                    final_price = round(min_price * 1.7, 2)  
                  
                buttons.append(InlineKeyboardButton(f"{arabic_name} ({final_price:.2f}$)", callback_data=f"buy_{code}"))  
except Exception as e:  
    print("Parsing Prices Error:", repr(e))  

if not buttons:  
    bot.send_message(chat_id, "❌ لا توجد أرقام متاحة لتليجرام حالياً في هذه الدول.")  
    return  

markup.add(*buttons)  
markup.add(InlineKeyboardButton("⬅️ رجوع", callback_data="home"))  
  
try:  
    bot.edit_message_text("🌍 <b>اختر الدولة المطلوبة لحسابات تليجرام:</b>", chat_id, call.message.message_id, reply_markup=markup)  
except:  
    bot.send_message(chat_id, "🌍 <b>اختر الدولة المطلوبة لحسابات تليجرام:</b>", reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data == "balance")
def cb_balance(call):
user_id = call.from_user.id
chat_id = call.message.chat.id
ensure_user(user_id)
balance = get_balance(user_id)

markup = InlineKeyboardMarkup()  
markup.add(InlineKeyboardButton("💳 شحن الرصيد", callback_data="deposit"))  
markup.add(InlineKeyboardButton("⬅️ رجوع", callback_data="home"))  
  
try:  
    bot.edit_message_text(f"💰 <b>رصيدك الحالي</b>\n\n<code>{balance:.2f} USDT</code>", chat_id, call.message.message_id, reply_markup=markup)  
except:  
    pass

@bot.callback_query_handler(func=lambda call: call.data == "deposit")
def cb_deposit(call):
user_id = call.from_user.id
chat_id = call.message.chat.id
ensure_user(user_id)

markup = InlineKeyboardMarkup()  
markup.add(InlineKeyboardButton("⬅️ رجوع", callback_data="home"))  
  
try:  
    bot.edit_message_text("💳 <b>شحن الرصيد</b>\n\nأرسل المبلغ الذي تريد شحنه بالدولار (مثلاً: <code>1</code> أو <code>5</code>):", chat_id, call.message.message_id, reply_markup=markup)  
except:  
    pass  
bot.register_next_step_handler(call.message, create_deposit)

@bot.callback_query_handler(func=lambda call: call.data == "orders")
def cb_orders(call):
user_id = call.from_user.id
chat_id = call.message.chat.id
ensure_user(user_id)

rows = db.execute("SELECT * FROM orders WHERE user_id = ? ORDER BY id DESC LIMIT 10", (user_id,)).fetchall()  
if not rows:  
    text = "📦 <b>طلباتك</b>\n\nلا توجد طلبات."  
else:  
    text = "📦 <b>آخر طلباتك</b>\n\n"  
    for row in rows:  
        status_map = {"pending": "⏳ قيد المعالجة", "completed": "✅ مكتمل", "cancelled": "❌ ملغي"}  
        status = status_map.get(row["status"], row["status"])  
        text += f"🆔 <code>#{row['id']}</code>\n🌍 {row['country']}\n💵 {row['price']:.2f} USDT\n📌 {status}\n\n"  

markup = InlineKeyboardMarkup()  
markup.add(InlineKeyboardButton("⬅️ رجوع", callback_data="home"))  
try:  
    bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup)  
except:  
    pass

@bot.callback_query_handler(func=lambda call: call.data == "home")
def cb_home(call):
chat_id = call.message.chat.id
try:
bot.delete_message(chat_id, call.message.message_id)
except:
pass
show_main(chat_id)

=========================================================

1. INITIAL BUY SELECTION & PRE-CONFIRMATION DISPLAY

=========================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("buy_"))
def cb_buy_number(call):
user_id = call.from_user.id
chat_id = call.message.chat.id
ensure_user(user_id)

parts = call.data.split("_")  
if len(parts) != 2:  
    return  

country_code = parts[1]  

try:  
    bot.edit_message_text("⏳ جاري التحقق من السعر الحي والمخزون...", chat_id, call.message.message_id)  
except:  
    bot.send_message(chat_id, "⏳ جاري التحقق من السعر الحي والمخزون...")  

prices_url = "https://5sim.net/v1/guest/prices"  
try:  
    response = requests.get(prices_url, timeout=15)  
    prices_data = response.json()  
      
    if country_code not in prices_data:  
        raise RuntimeError("Country not found")  
          
    services = prices_data[country_code]  
    if not isinstance(services, dict) or "telegram" not in services:  
        raise RuntimeError("Service not found")  
          
    telegram_data = services["telegram"]  
    min_price = 999999  
    total_count = 0  
      
    if isinstance(telegram_data, dict):  
        for op_name, op_info in telegram_data.items():  
            if isinstance(op_info, dict):  
                cost = float(op_info.get("cost", op_info.get("price", 0)))  
                count = int(op_info.get("count", 0))  
                if cost > 0 and count > 0:  
                    total_count += count  
                    if cost < min_price:  
                        min_price = cost  

    if min_price == 999999 or total_count <= 0:  
        markup = InlineKeyboardMarkup()  
        markup.add(InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="home"))  
        bot.send_message(chat_id, "❌ عذراً، نفدت الأرقام أو تغيرت حالة الدولة.", reply_markup=markup)  
        return  

    if min_price <= 0.20:  
        final_price = round(min_price * 2.5, 2)  
    else:  
        final_price = round(min_price * 1.7, 2)  

except Exception as e:  
    print("Live Verification Error:", repr(e))  
    bot.send_message(chat_id, "❌ حدث خطأ أثناء التحقق من السعر الحي. حاول مرة أخرى.")  
    return  

balance = get_balance(user_id)  
if balance < final_price:  
    bot.answer_callback_query(call.id, f"رصيدك غير كافٍ. تحتاج {final_price:.2f} USDT.", show_alert=True)  
    return  

arabic_name = TARGET_COUNTRIES.get(country_code, country_code)  
markup = InlineKeyboardMarkup(row_width=2)  
markup.add(  
    InlineKeyboardButton("✅ تأكيد الشراء", callback_data=f"confirm_{country_code}"),  
    InlineKeyboardButton("❌ إلغاء", callback_data="services")  
)  
  
try:  
    bot.edit_message_text(  
        f"⚠️ <b>تأكيد عملية الشراء</b>\n\n"  
        f"🌍 الدولة: <b>{arabic_name}</b>\n"  
        f"💵 السعر الحالي: <b>{final_price:.2f} USDT</b>\n\n"  
        f"💳 رصيدك الحالي: <b>{balance:.2f} USDT</b>\n\n"  
        f"هل تريد إتمام الشراء الآن؟",  
        chat_id, call.message.message_id, reply_markup=markup  
    )  
except:  
    bot.send_message(  
        chat_id,  
        f"⚠️ <b>تأكيد عملية الشراء</b>\n\n"  
        f"🌍 الدولة: <b>{arabic_name}</b>\n"  
        f"💵 السعر الحالي: <b>{final_price:.2f} USDT</b>\n\n"  
        f"💳 رصيدك الحالي: <b>{balance:.2f} USDT</b>\n\n"  
        f"هل تريد إتمام الشراء الآن?",  
        reply_markup=markup  
    )

=========================================================

2. FINAL RE-VERIFICATION, DEDUCTION, & PURCHASE

=========================================================

@bot.callback_query_handler(func=lambda call: call.data.startswith("confirm_"))
def cb_confirm_buy(call):
user_id = call.from_user.id
chat_id = call.message.chat.id
ensure_user(user_id)

parts = call.data.split("_")  
if len(parts) != 2:  
    return  

country_code = parts[1]  

try:  
    bot.edit_message_text("⏳ جاري الفحص النهائي للسعر والبدء بالشراء الفوري...", chat_id, call.message.message_id)  
except:  
    bot.send_message(chat_id, "⏳ جاري الفحص النهائي للسعر والبدء بالشراء الفوري...")  

# فحص أخير دقيق جداً لحظة الضغط على التأكيد لمنع أي فرق في السعر  
prices_url = "https://5sim.net/v1/guest/prices"  
try:  
    response = requests.get(prices_url, timeout=15)  
    prices_data = response.json()  
      
    if country_code not in prices_data or "telegram" not in prices_data[country_code]:  
        raise RuntimeError("Unavailable")  

    telegram_data = prices_data[country_code]["telegram"]  
    min_price = 999999  
    if isinstance(telegram_data, dict):  
        for op_name, op_info in telegram_data.items():  
            if isinstance(op_info, dict):  
                cost = float(op_info.get("cost", op_info.get("price", 0)))  
                count = int(op_info.get("count", 0))  
                if cost > 0 and count > 0 and cost < min_price:  
                    min_price = cost  

    if min_price == 999999:  
        raise RuntimeError("Out of stock")  

    if min_price <= 0.20:  
        final_price = round(min_price * 2.5, 2)  
    else:  
        final_price = round(min_price * 1.7, 2)  

except Exception as e:  
    markup = InlineKeyboardMarkup()  
    markup.add(InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="home"))  
    bot.send_message(chat_id, "❌ عذراً، نفدت الأرقام أو تغير السعر المفاجئ.", reply_markup=markup)  
    return  

balance = get_balance(user_id)  
if balance < final_price:  
    bot.answer_callback_query(call.id, f"رصيدك غير كافٍ. السعر الحالي أصبح {final_price:.2f} USDT.", show_alert=True)  
    return  

# خصم السعر المحدث والفعلي من رصيد المستخدم  
if not subtract_balance(user_id, final_price):  
    bot.answer_callback_query(call.id, "حدث خطأ في خصم الرصيد.", show_alert=True)  
    return  

buy_url = f"https://5sim.net/v1/user/buy/activation/{country_code}/any/telegram"  
headers = {"Authorization": f"Bearer {SIM5_API_KEY}"}  

try:  
    response = requests.get(buy_url, headers=headers, timeout=20)  
    data = response.json()  

    if "phone" in data and "id" in data:  
        phone = data["phone"]  
        activation_id = data["id"]  

        # تسجيل الطلب بأمان في قاعدة البيانات أولاً  
        with db_lock:  
            cursor = db.execute("""  
                INSERT INTO orders  
                (user_id, country, price, status, reference, provider_phone, created_at)  
                VALUES (?, ?, ?, 'pending', ?, ?, ?)  
            """, (user_id, country_code, final_price, str(activation_id), str(phone), int(time.time())))  
            order_id = cursor.lastrowid  
            db.commit()  

        markup = InlineKeyboardMarkup()  
        markup.add(InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="home"))  

        bot.send_message(  
            chat_id,  
            f"✅ <b>تم شراء الرقم بنجاح!</b>\n\n"  
            f"🆔 الطلب: <code>#{order_id}</code>\n"  
            f"📱 الرقم: <code>+{phone}</code>\n\n"  
            f"⏳ جاري انتظار وصول كود التفعيل الحقيقي...",  
            reply_markup=markup  
        )  

        # بدء خيط المراقبة مع تمرير السعر الفعلي المخصوم لضمان الإثباتات السليمة  
        threading.Thread(target=monitor_sms_and_complete, args=(user_id, chat_id, order_id, activation_id, phone, country_code, final_price), daemon=True).start()  

    else:  
        # لو لم يتم توفير الرقم، يتم استرجاع المبلغ فوراً للعميل  
        add_balance(user_id, final_price)  
        markup = InlineKeyboardMarkup()  
        markup.add(InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="home"))  
        bot.send_message(chat_id, "❌ عذراً، لا توجد أرقام متاحة حالياً، وتم إرجاع المبلغ لرصيدك.", reply_markup=markup)  

except Exception as e:  
    add_balance(user_id, final_price)  
    bot.send_message(chat_id, "❌ حدث خطأ أثناء الاتصال بموقع الأرقام، وتم إرجاع المبلغ لرصيدك.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("checkpay_"))
def check_payment(call):
user_id = call.from_user.id
invoice_id = call.data.replace("checkpay_", "")

row = db.execute("""  
    SELECT *  
    FROM invoices  
    WHERE invoice_id = ?  
    AND user_id = ?  
""", (invoice_id, user_id)).fetchone()  

if not row:  
    bot.answer_callback_query(call.id, "الفاتورة غير موجودة.", show_alert=True)  
    return  

try:  
    invoice = get_invoice(invoice_id)  
    if not invoice or invoice.get("status") != "paid":  
        bot.answer_callback_query(call.id, "الدفع لم يتم تأكيده بعد.", show_alert=True)  
        return  

    if row["status"] == "paid":  
        bot.answer_callback_query(call.id, "الفاتورة مضافة بالفعل.", show_alert=True)  
        return  

    with db_lock:  
        db.execute("""  
            UPDATE invoices  
            SET status = 'paid',  
                paid_at = ?  
            WHERE invoice_id = ?  
        """, (int(time.time()), invoice_id))  
        db.commit()  

    amount = float(row["amount"])  
    add_balance(user_id, amount)  

    bot.answer_callback_query(call.id, "تم إضافة الرصيد ✅", show_alert=True)  
    bot.send_message(  
        user_id,  
        "🎉 <b>تم تأكيد الدفع!</b>\n\n"  
        f"💰 تمت إضافة: <b>{amount:.2f} USDT</b>\n"  
        f"💳 رصيدك: <b>{get_balance(user_id):.2f} USDT</b>"  
    )  
except Exception as e:  
    print("Payment check error:", repr(e))  
    bot.answer_callback_query(call.id, "حدث خطأ أثناء فحص الدفع.", show_alert=True)

=========================================================

AUTOMATIC SMS MONITOR, 5SIM REFUND, & PROOF PUBLISHER

=========================================================

def monitor_sms_and_complete(user_id, chat_id, order_id, activation_id, phone, country, price):
headers = {"Authorization": f"Bearer {SIM5_API_KEY}"}
sms_code = None

for _ in range(18):  
    time.sleep(5)  
    try:  
        check_url = f"https://5sim.net/v1/user/check/{activation_id}"  
        check_res = requests.get(check_url, headers=headers, timeout=15).json()  
        if check_res.get("sms") and len(check_res["sms"]) > 0:  
            sms_code = check_res["sms"][0].get("code")  
            break  
    except:  
        pass  

markup = InlineKeyboardMarkup()  
markup.add(InlineKeyboardButton("⬅️ القائمة الرئيسية", callback_data="home"))  

if sms_code:  
    with db_lock:  
        db.execute("""  
            UPDATE orders  
            SET status = 'completed',  
                completed_at = ?  
            WHERE id = ?  
        """, (int(time.time()), order_id))  
        db.commit()  

    bot.send_message(  
        chat_id,  
        f"🎉 <b>وصل كود التفعيل الحقيقي!</b>\n\n"  
        f"📱 الرقم: <code>+{phone}</code>\n"  
        f"💬 <b>الكود:</b> <code>{sms_code}</code>",  
        reply_markup=markup,  
        parse_mode="HTML"  
    )  

    proof_text = (  
        "✨ <b>Lada Number — إثبات تسليم</b>\n\n"  
        "✅ <b>Service Completed</b>\n\n"  
        f"🌍 Country: <b>{country}</b>\n"  
        f"🆔 Order ID: <code>#{order_id}</code>\n"  
        f"💵 Price: <b>{price:.2f} USDT</b>\n"  
        f"👤 Buyer: <code>{mask_id(user_id)}</code>"  
    )  
    proof_markup = InlineKeyboardMarkup()  
    proof_markup.add(InlineKeyboardButton("↗️ اذهب إلى البوت", url=BOT_LINK))  

    try:  
        bot.send_message(PROOF_CHANNEL, proof_text, reply_markup=proof_markup)  
    except Exception as e:  
        print("Proof channel error:", repr(e))  

else:  
    # حماية حقوق العميل: إذا انتهت الـ 18 محاولة بدون وصول الكود، يتم إلغاء الرقم لدى 5sim واسترجاع المبلغ للعميل فوراً  
    try:  
        cancel_url = f"https://5sim.net/v1/user/cancel/{activation_id}"  
        requests.get(cancel_url, headers=headers, timeout=15)  
    except Exception as e:  
        print("5sim cancel error:", repr(e))  

    with db_lock:  
        db.execute("""  
            UPDATE orders  
            SET status = 'cancelled',  
                completed_at = ?  
            WHERE id = ?  
        """, (int(time.time()), order_id))  
        db.commit()  

    add_balance(user_id, price)  

    bot.send_message(  
        chat_id,  
        f"⚠️ انتهت المهلة ولم يُرسل الكود للرقم `+{phone}`.\n"  
        f"🔄 <b>تم إلغاء الرقم وإرجاع مبلغ {price:.2f} USDT إلى رصيدك تلقائياً.</b>",  
        reply_markup=markup  
    )

=========================================================

DEPOSIT

=========================================================

def create_deposit(message):
user_id = message.from_user.id
try:
amount = float(message.text.strip())
if amount <= 0:
raise ValueError
if amount > 10000:
bot.reply_to(message, "❌ الحد الأقصى للفاتورة 10000 USDT.")
return
except:
bot.reply_to(
message,
"❌ أرسل مبلغاً صحيحاً مثل:\n<code>1</code>\n<code>5</code>\n<code>10.50</code>"
)
return

try:  
    invoice_id, pay_url = create_invoice(user_id, amount)  
    markup = InlineKeyboardMarkup()  
    markup.add(InlineKeyboardButton("💳 ادفع الآن", url=pay_url))  
    markup.add(InlineKeyboardButton("💰 فحص الدفع", callback_data=f"checkpay_{invoice_id}"))  

    bot.send_message(  
        message.chat.id,  
        "🧾 <b>تم إنشاء الفاتورة</b>\n\n"  
        f"💵 المبلغ: <b>{amount:.2f} USDT</b>\n"  
        f"🆔 Invoice: <code>{invoice_id}</code>\n\n"  
        "بعد الدفع اضغط على فحص الدفع أو سيتم تأكيدها تلقائياً.",  
        reply_markup=markup  
    )  
except Exception as e:  
    print("Create invoice error:", repr(e))  
    bot.send_message(message.chat.id, "❌ حدث خطأ أثناء إنشاء الفاتورة.")

=========================================================

HELPERS

=========================================================

def mask_id(user_id):
value = str(user_id)
if len(value) <= 4:
return "" * len(value)
return value[:2] + "" * (len(value) - 4) + value[-2:]

=========================================================

RUN

=========================================================

if name == "main":
print("================================")
print("Lada Number Bot - Fully Automated")
print("Starting...")
print("================================")

payment_thread = threading.Thread(target=payment_monitor, daemon=True)  
payment_thread.start()  

bot.infinity_polling(skip_pending=True, timeout=30, long_polling_timeout=30 
