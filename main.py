import os
import logging
import asyncio
import random
import string
import re
import json
import io
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from fastapi import FastAPI, Request
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
)
import psycopg2
from psycopg2 import pool
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz
import uvicorn

# ==================== تنظیمات اولیه ====================
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = "@mottasel1333"
ADMIN_IDS = [6056483071, 7241184581]
SUPPORT_USERNAME = "@Amireerfani"

BANK_CARD = "6219861847420634"
BANK_OWNER = "عرفانی نیا"

PRICE_PER_GB_ECONOMY = 169000
PRICE_PER_GB_SUPERFAST = 229000
AGENT_PRICE_PER_GB_ECONOMY = 153000
AGENT_PRICE_PER_GB_SUPERFAST = 212000
AGENT_REGISTRATION_FEE = 4000000

CONFIG_NAME = "کانفیگ"
AVAILABLE_VOLUMES = list(range(1, 11))

RENDER_BASE_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("RAILWAY_STATIC_URL") or "https://OnePercentVPN12.railway.app"
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{RENDER_BASE_URL}{WEBHOOK_PATH}"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO
)

app = FastAPI()

# ==================== توابع کمکی ====================
def persian_number(number):
    persian_digits = {'0': '۰', '1': '۱', '2': '۲', '3': '۳', '4': '۴', '5': '۵', '6': '۶', '7': '۷', '8': '۸', '9': '۹'}
    return ''.join(persian_digits.get(ch, ch) for ch in str(number))

def english_number(persian_str):
    english_digits = {'۰': '0', '۱': '1', '۲': '2', '۳': '3', '۴': '4', '۵': '5', '۶': '6', '۷': '7', '۸': '8', '۹': '9'}
    result = ''
    for ch in persian_str:
        result += english_digits.get(ch, ch)
    return result

def format_price(price):
    return persian_number(f"{price:,}") + " تومان"

def get_price_for_volume(volume: int, quantity: int = 1, is_agent: bool = False, subscription_type: str = "economy") -> int:
    if subscription_type == "superfast":
        if is_agent:
            return volume * quantity * AGENT_PRICE_PER_GB_SUPERFAST
        return volume * quantity * PRICE_PER_GB_SUPERFAST
    else:
        if is_agent:
            return volume * quantity * AGENT_PRICE_PER_GB_ECONOMY
        return volume * quantity * PRICE_PER_GB_ECONOMY

def get_display_text_for_volume(volume: int, is_agent: bool = False, subscription_type: str = "economy") -> str:
    price = get_price_for_volume(volume, 1, is_agent, subscription_type)
    type_name = "اکونومی ⭐️" if subscription_type == "economy" else "سوپر فست 💎"
    if is_agent:
        return f"{persian_number(volume)} گیگ {type_name} | {format_price(price)} | نماینده"
    return f"{persian_number(volume)} گیگ {type_name} | {format_price(price)}"

# ==================== کیبوردها ====================
def get_main_keyboard(is_agent: bool = False):
    keyboard = [
        [KeyboardButton("🛍️ خرید اشتراک")],
        [KeyboardButton("💰 موجودی")],
        [KeyboardButton("🆘 پشتیبانی")],
        [KeyboardButton("🗂️ اشتراک‌های من"), KeyboardButton("📚 آموزش اتصال")],
        [KeyboardButton("👨‍💼 درخواست نمایندگی")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_back_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)

def get_subscription_type_keyboard():
    keyboard = [
        [KeyboardButton("⭐️ اشتراک اکونومی ⭐️")],
        [KeyboardButton("💎 اشتراک سوپر فست 💎")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_subscription_keyboard(is_agent: bool = False, subscription_type: str = "economy"):
    keyboard = []
    for volume in AVAILABLE_VOLUMES:
        keyboard.append([KeyboardButton(get_display_text_for_volume(volume, is_agent, subscription_type))])
    keyboard.append([KeyboardButton("↩️ بازگشت به منو")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_payment_method_keyboard(has_balance: bool = False):
    keyboard = [[KeyboardButton("🏧 انتقال کارت به کارت")]]
    if has_balance:
        keyboard.append([KeyboardButton("💳 پرداخت از موجودی")])
    keyboard.append([KeyboardButton("↩️ بازگشت به منو")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_connection_guide_keyboard():
    keyboard = [
        [KeyboardButton("📱 اندروید")],
        [KeyboardButton("🍏 آیفون/مک")],
        [KeyboardButton("🖥️ ویندوز")],
        [KeyboardButton("🐧 لینوکس")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_main_keyboard():
    keyboard = [
        [KeyboardButton("🛍️ خرید اشتراک")],
        [KeyboardButton("💰 موجودی")],
        [KeyboardButton("🆘 پشتیبانی")],
        [KeyboardButton("🗂️ اشتراک‌های من"), KeyboardButton("📚 آموزش اتصال")],
        [KeyboardButton("👨‍💼 درخواست نمایندگی")],
        [KeyboardButton("⚙️ مدیریت ادمین"), KeyboardButton("💳 مدیریت کارت")],
        [KeyboardButton("👥 مدیریت کاربران"), KeyboardButton("⚙️ مدیریت کانفیگ")],
        [KeyboardButton("📊 آمار"), KeyboardButton("🔌 خاموش/روشن")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_config_keyboard():
    keyboard = [
        [KeyboardButton("➕ اضافه کردن کانفیگ اکونومی")],
        [KeyboardButton("➕ اضافه کردن کانفیگ سوپر فست")],
        [KeyboardButton("📊 مشاهده موجودی کانفیگ‌ها")],
        [KeyboardButton("📋 لیست تمام کانفیگ‌ها")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_volume_selection_keyboard():
    keyboard = []
    row = []
    for i in range(1, 11):
        row.append(KeyboardButton(f"{persian_number(i)} گیگ"))
        if len(row) == 3:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)
    keyboard.append([KeyboardButton("↩️ انصراف")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_admin_management_keyboard():
    keyboard = [
        [KeyboardButton("➕ اضافه کردن ادمین جدید")],
        [KeyboardButton("➖ حذف ادمین")],
        [KeyboardButton("📋 لیست ادمین‌ها")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_bank_management_keyboard():
    keyboard = [
        [KeyboardButton("➕ اضافه کردن کارت جدید")],
        [KeyboardButton("💳 کارت‌های ذخیره شده")],
        [KeyboardButton("🔄 تغییر کارت اصلی")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_notification_keyboard():
    keyboard = [
        [KeyboardButton("📢 ارسال به همه کاربران")],
        [KeyboardButton("👑 ارسال به نمایندگان")],
        [KeyboardButton("👤 ارسال به یک نفر")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_coupon_recipient_keyboard():
    return ReplyKeyboardMarkup([
        [KeyboardButton("🌎 همه کاربران")],
        [KeyboardButton("👤 یک کاربر خاص")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ], resize_keyboard=True)

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ==================== توابع تشخیص ====================
def extract_volume_and_type(text: str) -> Tuple[Optional[int], Optional[str]]:
    for volume in range(1, 11):
        if f"{persian_number(volume)} گیگ" in text:
            if "اکونومی" in text:
                return volume, "economy"
            elif "سوپر فست" in text:
                return volume, "superfast"
    return None, None

def parse_configs_from_text(text: str) -> List[str]:
    lines = text.strip().split('\n')
    configs = []
    for line in lines:
        line = line.strip()
        if line and (line.startswith('http://') or line.startswith('https://') or 
                     line.startswith('vless://') or line.startswith('vmess://') or 
                     line.startswith('trojan://') or line.startswith('ss://')):
            configs.append(line)
    return configs

# ==================== دیتابیس ====================
DATABASE_URL = os.getenv("DATABASE_URL")
db_pool = None

def init_db_pool():
    global db_pool
    db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL, sslmode='require')

def close_db_pool():
    global db_pool
    if db_pool:
        db_pool.closeall()

def _db_execute_sync(query, params=(), fetch=False, fetchone=False, returning=False):
    conn = db_pool.getconn()
    cur = conn.cursor()
    try:
        cur.execute(query, params)
        if returning:
            result = cur.fetchone()[0] if cur.rowcount > 0 else None
        elif fetchone:
            result = cur.fetchone()
        elif fetch:
            result = cur.fetchall()
        else:
            result = None
        if not query.strip().lower().startswith("select"):
            conn.commit()
        return result
    finally:
        cur.close()
        db_pool.putconn(conn)

async def db_execute(query, params=(), fetch=False, fetchone=False, returning=False):
    return await asyncio.to_thread(_db_execute_sync, query, params, fetch, fetchone, returning)

# ==================== ساخت جداول ====================
async def create_tables():
    await db_execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            username TEXT,
            balance BIGINT DEFAULT 0,
            invited_by BIGINT,
            is_agent BOOLEAN DEFAULT FALSE,
            is_member BOOLEAN DEFAULT FALSE,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS payments (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            amount BIGINT,
            status TEXT,
            type TEXT,
            payment_method TEXT,
            description TEXT,
            coupon_code TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS subscriptions (
            id SERIAL PRIMARY KEY,
            user_id BIGINT,
            payment_id INTEGER,
            plan TEXT,
            config TEXT,
            status TEXT DEFAULT 'pending',
            start_date TIMESTAMP,
            duration_days INTEGER,
            volume INTEGER,
            quantity INTEGER DEFAULT 1,
            subscription_type TEXT DEFAULT 'economy'
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS config_pool (
            id SERIAL PRIMARY KEY,
            volume INTEGER NOT NULL,
            config_text TEXT NOT NULL,
            is_sold BOOLEAN DEFAULT FALSE,
            sold_to_user BIGINT,
            subscription_type TEXT DEFAULT 'economy',
            created_by BIGINT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id BIGINT PRIMARY KEY
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS bank_settings (
            id INTEGER PRIMARY KEY DEFAULT 1,
            card_number TEXT,
            owner_name TEXT
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS bank_cards (
            id SERIAL PRIMARY KEY,
            card_number TEXT,
            owner_name TEXT
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS banned_users (
            user_id BIGINT PRIMARY KEY
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS coupons (
            code TEXT PRIMARY KEY,
            discount_percent INTEGER,
            user_id BIGINT,
            is_used BOOLEAN DEFAULT FALSE,
            expiry_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP + INTERVAL '3 days'
        )
    """)
    await db_execute("""
        CREATE TABLE IF NOT EXISTS bot_status (
            id INTEGER PRIMARY KEY DEFAULT 1,
            is_active BOOLEAN DEFAULT TRUE
        )
    """)
    
    for admin_id in ADMIN_IDS:
        await db_execute("INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (admin_id,))
    
    await db_execute("INSERT INTO bank_settings (id, card_number, owner_name) VALUES (1, %s, %s) ON CONFLICT DO NOTHING", (BANK_CARD, BANK_OWNER))

# ==================== توابع کاربر ====================
async def ensure_user(user_id, username, invited_by=None):
    row = await db_execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,), fetchone=True)
    if not row:
        await db_execute("INSERT INTO users (user_id, username, invited_by, balance) VALUES (%s, %s, %s, 0)", (user_id, username, invited_by))
        if invited_by and invited_by != user_id:
            await db_execute("UPDATE users SET balance = balance + 15000 WHERE user_id = %s", (invited_by,))

async def get_user_balance(user_id):
    row = await db_execute("SELECT balance FROM users WHERE user_id = %s", (user_id,), fetchone=True)
    return row[0] if row else 0

async def add_balance(user_id, amount):
    await db_execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", (amount, user_id))

async def subtract_balance(user_id, amount):
    current = await get_user_balance(user_id)
    if current >= amount:
        await db_execute("UPDATE users SET balance = balance - %s WHERE user_id = %s", (amount, user_id))
        return True
    return False

async def is_user_agent(user_id):
    row = await db_execute("SELECT is_agent FROM users WHERE user_id = %s", (user_id,), fetchone=True)
    return row[0] if row else False

async def set_user_agent(user_id):
    await db_execute("UPDATE users SET is_agent = TRUE WHERE user_id = %s", (user_id,))

async def add_payment(user_id, amount, ptype, payment_method, description="", coupon_code=None):
    new_id = await db_execute(
        "INSERT INTO payments (user_id, amount, status, type, payment_method, description, coupon_code) VALUES (%s, %s, 'pending', %s, %s, %s, %s) RETURNING id",
        (user_id, amount, ptype, payment_method, description, coupon_code), returning=True
    )
    if coupon_code:
        await db_execute("UPDATE coupons SET is_used = TRUE WHERE code = %s", (coupon_code,))
    return new_id

async def add_balance_payment(user_id, amount, payment_method, description=""):
    return await add_payment(user_id, amount, "add_balance", payment_method, description)

async def add_subscription(user_id, payment_id, plan, volume, quantity, subscription_type):
    await db_execute(
        "INSERT INTO subscriptions (user_id, payment_id, plan, status, start_date, duration_days, volume, quantity, subscription_type) VALUES (%s, %s, %s, 'pending', CURRENT_TIMESTAMP, 30, %s, %s, %s)",
        (user_id, payment_id, plan, volume, quantity, subscription_type)
    )

async def update_subscription_config(subscription_id, config):
    await db_execute("UPDATE subscriptions SET config = %s, status = 'active' WHERE id = %s", (config, subscription_id))

async def update_payment_status(payment_id, status):
    await db_execute("UPDATE payments SET status = %s WHERE id = %s", (status, payment_id))

async def get_pending_subscriptions():
    rows = await db_execute("""
        SELECT s.id, s.user_id, s.volume, s.plan, s.quantity, s.subscription_type 
        FROM subscriptions s JOIN payments p ON s.payment_id = p.id 
        WHERE s.status = 'pending' AND p.status = 'approved'
    """, fetch=True)
    return [{"subscription_id": r[0], "user_id": r[1], "volume": r[2], "plan": r[3], "quantity": r[4], "subscription_type": r[5]} for r in rows]

async def get_available_configs(volume: int, quantity: int, subscription_type: str):
    rows = await db_execute(
        "SELECT id, config_text FROM config_pool WHERE volume = %s AND is_sold = FALSE AND subscription_type = %s ORDER BY id LIMIT %s",
        (volume, subscription_type, quantity), fetch=True
    )
    if rows and len(rows) == quantity:
        return [{"id": r[0], "config_text": r[1]} for r in rows]
    return None

async def mark_configs_as_sold(config_ids: List[int], user_id: int):
    for cid in config_ids:
        await db_execute("UPDATE config_pool SET is_sold = TRUE, sold_to_user = %s WHERE id = %s", (user_id, cid))

async def get_available_configs_count(volume: int, subscription_type: str):
    row = await db_execute("SELECT COUNT(*) FROM config_pool WHERE volume = %s AND is_sold = FALSE AND subscription_type = %s", (volume, subscription_type), fetchone=True)
    return row[0] if row else 0

# قفل برای جلوگیری از ارسال دوباره
_send_locks = set()

async def send_multiple_configs_to_user(subscription_id: int, user_id: int, volume: int, quantity: int, plan: str, bot, subscription_type: str):
    lock_key = f"send_config_{subscription_id}"
    if lock_key in _send_locks:
        logging.warning(f"Duplicate send attempt blocked for subscription {subscription_id}")
        return False
    _send_locks.add(lock_key)
    
    try:
        sub_status = await db_execute("SELECT status FROM subscriptions WHERE id = %s", (subscription_id,), fetchone=True)
        if sub_status and sub_status[0] == 'active':
            logging.info(f"Subscription {subscription_id} already active")
            return True
        
        configs = await get_available_configs(volume, quantity, subscription_type)
        if configs and len(configs) == quantity:
            configs_text = "\n\n".join([c['config_text'] for c in configs])
            await update_subscription_config(subscription_id, configs_text)
            await mark_configs_as_sold([c['id'] for c in configs], user_id)
            type_name = "اکونومی ⭐️" if subscription_type == "economy" else "سوپر فست 💎"
            await bot.send_message(user_id, f"✅ اشتراک {type_name} {plan} شما فعال شد!\n\n🔐 کانفیگ:\n```\n{configs_text}\n```", parse_mode="Markdown")
            return True
        return False
    finally:
        _send_locks.discard(lock_key)

async def check_user_membership(user_id: int) -> bool:
    try:
        member = await application.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        is_member = member.status in ["member", "administrator", "creator"]
        await db_execute("UPDATE users SET is_member = %s WHERE user_id = %s", (is_member, user_id))
        return is_member
    except:
        return False

async def get_all_users():
    return await db_execute("SELECT user_id FROM users", fetch=True)

async def get_all_agents():
    return await db_execute("SELECT user_id FROM users WHERE is_agent = TRUE", fetch=True)

async def send_notification_to_users(context, users, text):
    sent = 0
    failed = 0
    for uid in users:
        try:
            await context.bot.send_message(chat_id=uid[0], text=f"📢 پیام سیستم:\n\n{text}")
            sent += 1
        except:
            failed += 1
    return sent, failed

async def create_coupon(code, discount, user_id=None):
    await db_execute("INSERT INTO coupons (code, discount_percent, user_id) VALUES (%s, %s, %s)", (code, discount, user_id))

async def validate_coupon(code, user_id):
    row = await db_execute("SELECT discount_percent, user_id, is_used, expiry_date FROM coupons WHERE code = %s", (code,), fetchone=True)
    if not row:
        return None, "❌ کد تخفیف معتبر نیست"
    if row[2]:
        return None, "❌ این کد قبلاً استفاده شده"
    if datetime.now() > row[3]:
        return None, "❌ کد تخفیف منقضی شده"
    if row[1] and row[1] != user_id:
        return None, "❌ این کد متعلق به شما نیست"
    if await is_user_agent(user_id):
        return None, "⚠️ نمایندگان نمی‌توانند از کد تخفیف استفاده کنند"
    return row[0], None

async def get_user_subscriptions(user_id):
    rows = await db_execute("SELECT id, plan, status, volume, quantity, subscription_type FROM subscriptions WHERE user_id = %s ORDER BY id DESC", (user_id,), fetch=True)
    return rows

async def get_total_income():
    row = await db_execute("SELECT COALESCE(SUM(amount),0) FROM payments WHERE status = 'approved'", fetchone=True)
    return row[0] if row else 0

async def get_total_configs_sold():
    row = await db_execute("SELECT COUNT(*) FROM config_pool WHERE is_sold = TRUE", fetchone=True)
    return row[0] if row else 0

async def get_pending_balance_payments():
    rows = await db_execute("SELECT id, user_id, amount, description FROM payments WHERE type = 'add_balance' AND status = 'pending'", fetch=True)
    return [{"payment_id": r[0], "user_id": r[1], "amount": r[2], "description": r[3]} for r in rows]

async def get_pending_agent_payments():
    rows = await db_execute("SELECT id, user_id, amount, description FROM payments WHERE type = 'agent_registration' AND status = 'pending'", fetch=True)
    return [{"payment_id": r[0], "user_id": r[1], "amount": r[2], "description": r[3]} for r in rows]

async def get_bot_status():
    row = await db_execute("SELECT is_active FROM bot_status WHERE id = 1", fetchone=True)
    return row[0] if row else True

async def set_bot_status(active: bool):
    await db_execute("UPDATE bot_status SET is_active = %s WHERE id = 1", (active,))

async def is_user_banned(user_id):
    row = await db_execute("SELECT user_id FROM banned_users WHERE user_id = %s", (user_id,), fetchone=True)
    return row is not None

async def send_long_message(chat_id, text, context, reply_markup=None, parse_mode=None):
    if len(text) <= 4000:
        await context.bot.send_message(chat_id, text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    for i in range(0, len(text), 4000):
        await context.bot.send_message(chat_id, text[i:i+4000], reply_markup=reply_markup if i == 0 else None, parse_mode=parse_mode)

# ==================== مدیریت کانفیگ ادمین ====================
async def add_multiple_configs_to_pool(volume: int, configs: List[str], admin_id: int, sub_type: str):
    success = 0
    for cfg in configs:
        try:
            await db_execute("INSERT INTO config_pool (volume, config_text, subscription_type, created_by) VALUES (%s, %s, %s, %s)", (volume, cfg, sub_type, admin_id))
            success += 1
        except:
            pass
    return success, len(configs) - success

async def get_config_pool_stats():
    total = await db_execute("SELECT COUNT(*) FROM config_pool", fetchone=True)
    sold = await db_execute("SELECT COUNT(*) FROM config_pool WHERE is_sold = TRUE", fetchone=True)
    available = await db_execute("SELECT COUNT(*) FROM config_pool WHERE is_sold = FALSE", fetchone=True)
    
    by_volume = await db_execute("""
        SELECT volume, subscription_type, COUNT(*) as total, SUM(CASE WHEN is_sold THEN 1 ELSE 0 END) as sold 
        FROM config_pool GROUP BY volume, subscription_type ORDER BY volume
    """, fetch=True)
    
    return {
        "total": total[0], 
        "sold": sold[0], 
        "available": available[0],
        "by_volume": [{"volume": r[0], "type": r[1], "total": r[2], "sold": r[3], "available": r[2] - r[3]} for r in by_volume]
    }

async def get_all_configs():
    rows = await db_execute("SELECT id, volume, config_text, is_sold, sold_to_user, subscription_type FROM config_pool ORDER BY id DESC LIMIT 100", fetch=True)
    return [{"id": r[0], "volume": r[1], "config_text": r[2][:50], "is_sold": r[3], "sold_to": r[4], "type": "اکونومی" if r[5] == "economy" else "سوپر فست"} for r in rows]

# ==================== بکاپ ====================
scheduler = AsyncIOScheduler(timezone=pytz.timezone('Asia/Tehran'))

async def backup_config_pool_only():
    configs = await db_execute("SELECT id, volume, config_text, subscription_type FROM config_pool WHERE is_sold = FALSE", fetch=True)
    backup = {
        "backup_date": datetime.now().isoformat(),
        "backup_type": "config_pool_only",
        "config_pool": {
            "total": len(configs),
            "items": [{"id": r[0], "volume": r[1], "config_text": r[2], "subscription_type": r[3]} for r in configs]
        }
    }
    return backup

async def create_and_send_backup():
    try:
        backup = await backup_config_pool_only()
        if not backup["config_pool"]["items"]:
            return
        backup_json = json.dumps(backup, ensure_ascii=False, indent=2)
        temp_file = f"/tmp/backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(backup_json)
        for admin_id in ADMIN_IDS:
            with open(temp_file, 'rb') as f:
                await application.bot.send_document(admin_id, f, caption=f"📦 بکاپ خودکار - {persian_number(len(backup['config_pool']['items']))} کانفیگ")
        os.remove(temp_file)
    except Exception as e:
        logging.error(f"Backup error: {e}")

async def backup_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("📦 در حال تهیه بکاپ...")
    backup = await backup_config_pool_only()
    backup_json = json.dumps(backup, ensure_ascii=False, indent=2)
    file_io = io.BytesIO(backup_json.encode('utf-8'))
    file_io.name = f"backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    await context.bot.send_document(update.effective_user.id, file_io, caption=f"📦 بکاپ - {persian_number(len(backup['config_pool']['items']))} کانفیگ")

async def restore_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("⚠️ فایل JSON بکاپ را ارسال کنید", reply_markup=get_back_keyboard())
    user_states[update.effective_user.id] = "awaiting_restore"

async def handle_restore(update, context):
    user_id = update.effective_user.id
    if not is_admin(user_id) or not update.message.document:
        return
    
    file = await update.message.document.get_file()
    content = await file.download_as_bytearray()
    try:
        data = json.loads(content.decode('utf-8'))
        configs = data.get("config_pool", {}).get("items", [])
        if not configs:
            await update.message.reply_text("⚠️ کانفیگی یافت نشد", reply_markup=get_admin_main_keyboard())
            return
        
        await db_execute("DELETE FROM config_pool WHERE is_sold = FALSE")
        success = 0
        for cfg in configs:
            try:
                await db_execute("INSERT INTO config_pool (volume, config_text, subscription_type) VALUES (%s, %s, %s)", (cfg['volume'], cfg['config_text'], cfg.get('subscription_type', 'economy')))
                success += 1
            except:
                pass
        await update.message.reply_text(f"✅ {persian_number(success)} کانفیگ بازیابی شد", reply_markup=get_admin_main_keyboard())
    except:
        await update.message.reply_text("❌ فایل نامعتبر", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

# ==================== وضعیت کاربر ====================
user_states = {}

# ==================== توابع ربات (قبل از ثبت هندلرها) ====================
async def shutdown_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await set_bot_status(False)
    await update.message.reply_text("🔴 ربات برای کاربران عادی خاموش شد")

async def startup_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await set_bot_status(True)
    await update.message.reply_text("🟢 ربات برای کاربران عادی روشن شد")

async def toggle_status_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    current = await get_bot_status()
    new_status = not current
    await set_bot_status(new_status)
    status_text = "روشن" if new_status else "خاموش"
    await update.message.reply_text(f"🟢 وضعیت ربات: {status_text}", reply_markup=get_admin_main_keyboard())

# ==================== هندلرها ====================
application = Application.builder().token(TOKEN).build()

async def start(update, context):
    user = update.effective_user
    if await is_user_banned(user.id) and not is_admin(user.id):
        await update.message.reply_text("🚫 شما بن شده‌اید")
        return
    
    if not await get_bot_status() and not is_admin(user.id):
        await update.message.reply_text("🔴 ربات غیرفعال است")
        return
    
    if not is_admin(user.id) and not await check_user_membership(user.id):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}"),
            InlineKeyboardButton("✅ تایید عضویت", callback_data="check_membership")
        ]])
        await update.message.reply_text(f"❌ ابتدا در کانال {CHANNEL_USERNAME} عضو شوید", reply_markup=kb)
        return
    
    invited_by = context.user_data.get("invited_by")
    await ensure_user(user.id, user.username or "", invited_by)
    
    if is_admin(user.id):
        await update.message.reply_text("🌐 به ربات OnePercentVPN12 خوش آمدید!", reply_markup=get_admin_main_keyboard())
    else:
        is_agent = await is_user_agent(user.id)
        await update.message.reply_text("🌐 به ربات OnePercentVPN12 خوش آمدید!", reply_markup=get_main_keyboard(is_agent))
    user_states.pop(user.id, None)

async def start_with_param(update, context):
    args = context.args
    if args:
        try:
            invited_by = int(args[0])
            if invited_by != update.effective_user.id:
                context.user_data["invited_by"] = invited_by
        except:
            pass
    await start(update, context)

async def check_membership_callback(update, context):
    query = update.callback_query
    await query.answer()
    user = update.effective_user
    
    if await check_user_membership(user.id):
        await ensure_user(user.id, user.username or "")
        await query.edit_message_text("✅ عضویت تأیید شد!")
        if is_admin(user.id):
            await query.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        else:
            is_agent = await is_user_agent(user.id)
            await query.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent))
    else:
        await query.edit_message_text("❌ هنوز عضو نشده‌اید")

# ==================== هندلر خرید اشتراک ====================
async def handle_buy_subscription(update, context, user_id, text):
    is_agent_user = await is_user_agent(user_id)
    
    if text == "🛍️ خرید اشتراک":
        await update.message.reply_text("💳 نوع اشتراک را انتخاب کنید:", reply_markup=get_subscription_type_keyboard())
    
    elif text == "⭐️ اشتراک اکونومی ⭐️":
        await update.message.reply_text("📊 حجم مورد نظر را انتخاب کنید:", reply_markup=get_subscription_keyboard(is_agent_user, "economy"))
        user_states[user_id] = "awaiting_economy_volume"
    
    elif text == "💎 اشتراک سوپر فست 💎":
        await update.message.reply_text("📊 حجم مورد نظر را انتخاب کنید:", reply_markup=get_subscription_keyboard(is_agent_user, "superfast"))
        user_states[user_id] = "awaiting_superfast_volume"
    
    elif text == "↩️ بازگشت به منو":
        if is_admin(user_id):
            await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        else:
            await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent_user))
        user_states.pop(user_id, None)
    
    else:
        volume, sub_type = extract_volume_and_type(text)
        if volume and sub_type:
            state = user_states.get(user_id)
            expected_type = "economy" if state == "awaiting_economy_volume" else "superfast" if state == "awaiting_superfast_volume" else None
            if expected_type and expected_type == sub_type:
                user_states[user_id] = f"awaiting_quantity_{volume}_{sub_type}"
                await update.message.reply_text(
                    f"✅ {persian_number(volume)} گیگ {CONFIG_NAME}\n💰 قیمت هر عدد: {format_price(get_price_for_volume(volume, 1, is_agent_user, sub_type))}\n\n🔢 تعداد مورد نیاز را وارد کنید:",
                    reply_markup=get_back_keyboard()
                )
            else:
                await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_subscription_keyboard(is_agent_user, sub_type))
        else:
            await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_main_keyboard(is_agent_user))

async def handle_quantity(update, context, user_id, state, text):
    try:
        parts = state.split("_")
        volume = int(parts[2])
        sub_type = parts[3]
        quantity = int(english_number(text.strip()))
        
        if quantity <= 0:
            await update.message.reply_text("⚠️ عدد مثبت وارد کنید", reply_markup=get_back_keyboard())
            return
        
        available = await get_available_configs_count(volume, sub_type)
        if available < quantity:
            type_name = "اکونومی" if sub_type == "economy" else "سوپر فست"
            await update.message.reply_text(f"⚠️ موجودی کافی نیست!\n📦 موجود: {persian_number(available)} عدد\n📊 درخواستی: {persian_number(quantity)} عدد", reply_markup=get_back_keyboard())
            return
        
        is_agent_user = await is_user_agent(user_id)
        total = get_price_for_volume(volume, quantity, is_agent_user, sub_type)
        type_name = "اکونومی ⭐️" if sub_type == "economy" else "سوپر فست 💎"
        plan_name = f"{CONFIG_NAME} {type_name} | {volume} گیگ | {persian_number(quantity)} عدد"
        
        user_states[user_id] = f"awaiting_coupon_{total}_{plan_name}_{volume}_{quantity}_{sub_type}"
        await update.message.reply_text(
            f"✅ {persian_number(quantity)} عدد کانفیگ {persian_number(volume)} گیگی {type_name}\n💰 مبلغ کل: {format_price(total)}\n\nدر صورت داشتن کد تخفیف وارد کنید، در غیر اینصورت روی 'ادامه' کلیک کنید:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("ادامه")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)
        )
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر وارد کنید", reply_markup=get_back_keyboard())

async def handle_coupon(update, context, user_id, state, text):
    parts = state.split("_")
    total = int(parts[2])
    plan_name = "_".join(parts[3:-3])
    volume = int(parts[-3])
    quantity = int(parts[-2])
    sub_type = parts[-1]
    
    if text == "ادامه":
        balance = await get_user_balance(user_id)
        user_states[user_id] = f"awaiting_payment_{total}_{plan_name}_{volume}_{quantity}_{sub_type}"
        await update.message.reply_text("💳 روش پرداخت را انتخاب کنید:", reply_markup=get_payment_method_keyboard(balance >= total))
        return
    
    discount, error = await validate_coupon(text.strip(), user_id)
    if error:
        await update.message.reply_text(f"{error}\nبرای ادامه روی 'ادامه' کلیک کنید:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("ادامه")]], resize_keyboard=True))
        return
    
    discounted = int(total * (1 - discount / 100))
    balance = await get_user_balance(user_id)
    user_states[user_id] = f"awaiting_payment_{discounted}_{plan_name}_{volume}_{quantity}_{sub_type}_{text.strip()}"
    await update.message.reply_text(f"✅ کد تخفیف اعمال شد! مبلغ با {persian_number(discount)}% تخفیف: {format_price(discounted)}\nروش پرداخت را انتخاب کنید:", reply_markup=get_payment_method_keyboard(balance >= discounted))

async def handle_payment(update, context, user_id, text):
    state = user_states.get(user_id)
    if not state or not state.startswith("awaiting_payment_"):
        return
    
    parts = state.split("_")
    amount = int(parts[2])
    
    # تشخیص اینکه آیا کوپن وجود دارد یا خیر
    if len(parts) >= 8 and parts[-1] not in ["card_to_card"] and not parts[-1].isdigit():
        coupon = parts[-1]
        volume = int(parts[-3])
        quantity = int(parts[-2])
        sub_type = parts[-4]
        plan_parts = parts[3:-4]
    else:
        coupon = None
        volume = int(parts[-3])
        quantity = int(parts[-2])
        sub_type = parts[-1]
        plan_parts = parts[3:-3]
    plan = "_".join(plan_parts)
    
    if text == "🏧 انتقال کارت به کارت":
        payment_id = await add_payment(user_id, amount, "buy_subscription", "card_to_card", plan, coupon)
        if payment_id:
            await add_subscription(user_id, payment_id, plan, volume, quantity, sub_type)
            await update.message.reply_text(
                f"💳 مبلغ {format_price(amount)} را به کارت زیر واریز کنید:\n\n🏦 {BANK_CARD}\n👤 {BANK_OWNER}\n\n📸 عکس فیش را ارسال کنید\n🆔 کد: {payment_id}",
                reply_markup=get_back_keyboard()
            )
            user_states[user_id] = f"awaiting_receipt_{payment_id}"
        else:
            await update.message.reply_text("⚠️ خطا در ثبت درخواست", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
            user_states.pop(user_id, None)
        return  # مهم: جلوگیری از ادامه اجرا
    
    elif text == "💳 پرداخت از موجودی":
        balance = await get_user_balance(user_id)
        if balance >= amount:
            if await subtract_balance(user_id, amount):
                payment_id = await add_payment(user_id, amount, "buy_subscription", "balance", plan, coupon)
                if payment_id:
                    await update_payment_status(payment_id, "approved")
                    await add_subscription(user_id, payment_id, plan, volume, quantity, sub_type)
                    await update.message.reply_text(f"✅ پرداخت از موجودی انجام شد! در حال ارسال کانفیگ...")
                    sub = await db_execute("SELECT id FROM subscriptions WHERE payment_id = %s", (payment_id,), fetchone=True)
                    if sub:
                        await send_multiple_configs_to_user(sub[0], user_id, volume, quantity, plan, context.bot, sub_type)
                else:
                    await add_balance(user_id, amount)
                    await update.message.reply_text("⚠️ خطا در پرداخت", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
            else:
                await update.message.reply_text("⚠️ خطا در کسر موجودی", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        else:
            await update.message.reply_text(f"❌ موجودی کافی نیست!\nموجودی: {format_price(balance)}\nمورد نیاز: {format_price(amount)}", reply_markup=get_payment_method_keyboard(False))
        user_states.pop(user_id, None)
        return
    
    elif text == "↩️ بازگشت به منو":
        is_agent_user = await is_user_agent(user_id)
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent_user))
        user_states.pop(user_id, None)
        return

async def process_receipt(update, context, user_id, payment_id):
    payment = await db_execute("SELECT user_id, amount, type, description, status FROM payments WHERE id = %s", (payment_id,), fetchone=True)
    if not payment or payment[4] != 'pending':
        await update.message.reply_text("⚠️ فیش نامعتبر", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        user_states.pop(user_id, None)
        return
    
    caption = f"💳 فیش از کاربر {user_id}\n💰 مبلغ: {format_price(payment[1])}\n📝 {payment[3]}"
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("✅ تایید", callback_data=f"approve_{payment_id}"),
         InlineKeyboardButton("❌ رد", callback_data=f"reject_{payment_id}")]
    ])
    
    if update.message.photo:
        for admin_id in ADMIN_IDS:
            await context.bot.send_photo(admin_id, update.message.photo[-1].file_id, caption=caption, reply_markup=kb)
        await update.message.reply_text("✅ فیش برای ادمین ارسال شد", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        user_states.pop(user_id, None)  # پاک کردن state بعد از ارسال فیش
    else:
        await update.message.reply_text("⚠️ لطفاً عکس فیش را ارسال کنید", reply_markup=get_back_keyboard())
        return

# ==================== سایر هندلرهای کاربر ====================
async def show_balance(update, context, user_id):
    balance = await get_user_balance(user_id)
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("💳 افزایش موجودی")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)
    await update.message.reply_text(f"💰 موجودی: {format_price(balance)}", reply_markup=keyboard)
    user_states[user_id] = "awaiting_balance_action"

async def handle_balance_action(update, context, user_id, text):
    if text == "💳 افزایش موجودی":
        await update.message.reply_text("💰 مبلغ به تومان را وارد کنید:", reply_markup=get_back_keyboard())
        user_states[user_id] = "awaiting_balance_amount"
    elif text == "↩️ بازگشت به منو":
        is_agent_user = await is_user_agent(user_id)
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent_user))
        user_states.pop(user_id, None)

async def handle_balance_amount(update, context, user_id, text):
    try:
        amount = int(english_number(text.strip()))
        if amount <= 0:
            await update.message.reply_text("⚠️ عدد مثبت وارد کنید", reply_markup=get_back_keyboard())
            return
        payment_id = await add_balance_payment(user_id, amount, "card_to_card", f"افزایش موجودی {amount} تومان")
        await update.message.reply_text(
            f"💳 مبلغ {format_price(amount)} را به کارت زیر واریز کنید:\n\n🏦 {BANK_CARD}\n👤 {BANK_OWNER}\n\n📸 عکس فیش را ارسال کنید\n🆔 کد: {payment_id}",
            reply_markup=get_back_keyboard()
        )
        user_states[user_id] = f"awaiting_balance_receipt_{payment_id}"
    except ValueError:
        await update.message.reply_text("⚠️ عدد معتبر وارد کنید", reply_markup=get_back_keyboard())

async def show_my_subscriptions(update, context, user_id):
    rows = await get_user_subscriptions(user_id)
    if not rows:
        await update.message.reply_text("📁 هیچ اشتراکی ندارید", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        return
    response = "🗂️ اشتراک‌های شما:\n\n"
    for r in rows:
        type_name = "اکونومی ⭐️" if r[5] == "economy" else "سوپر فست 💎"
        status = "✅ فعال" if r[2] == "active" else "⏳ در انتظار"
        response += f"🔹 {type_name} {r[1]} ({persian_number(r[3])} گیگ - {persian_number(r[4])} عدد)\n📊 {status}\n--------------------\n"
    await send_long_message(user_id, response, context, reply_markup=get_main_keyboard(await is_user_agent(user_id)))

async def show_connection_guide(update, context, user_id):
    await update.message.reply_text("📚 راهنمای اتصال\nلطفاً دستگاه خود را انتخاب کنید:", reply_markup=get_connection_guide_keyboard())

async def handle_guide(update, context, user_id, text):
    guides = {
        "📱 اندروید": "📱 اپ V2RayNG یا Hiddify",
        "🍏 آیفون/مک": "🍏 اپ Singbox یا V2box",
        "🖥️ ویندوز": "🪟 اپ V2rayN",
        "🐧 لینوکس": "🐧 اپ V2rayN"
    }
    if text in guides:
        await update.message.reply_text(guides[text], reply_markup=get_connection_guide_keyboard())
    elif text == "↩️ بازگشت به منو":
        is_agent_user = await is_user_agent(user_id)
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent_user))

async def handle_agent_request(update, context, user_id):
    if await is_user_agent(user_id):
        await update.message.reply_text("👑 شما نماینده هستید!", reply_markup=get_main_keyboard(True))
        return
    
    message = (
        f"📢 شرایط دریافت نمایندگی 📢\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"برای دریافت نمایندگی، لازم است مبلغ {format_price(AGENT_REGISTRATION_FEE)} تومان به موجودی حساب خود اضافه کنید.\n\n"
        f"❌ این مبلغ به طور کامل در حساب شما باقی می‌ماند.\n\n"
        f"💰 قیمت‌های ویژه نمایندگان:\n"
        f"⭐️ اکونومی هر گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY)}\n"
        f"💎 سوپر فست هر گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST)}"
    )
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("💳 پرداخت مبلغ")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)
    await update.message.reply_text(message, reply_markup=keyboard)
    user_states[user_id] = "awaiting_agent_payment"

async def handle_agent_payment(update, context, user_id, text):
    if text == "💳 پرداخت مبلغ":
        user_states[user_id] = f"awaiting_agent_method_{AGENT_REGISTRATION_FEE}"
        await update.message.reply_text(f"💰 مبلغ {format_price(AGENT_REGISTRATION_FEE)}\nروش پرداخت را انتخاب کنید:", reply_markup=get_payment_method_keyboard(False))
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        user_states.pop(user_id, None)

async def handle_agent_method(update, context, user_id, text):
    state = user_states.get(user_id)
    if not state or not state.startswith("awaiting_agent_method_"):
        return
    
    amount = int(state.split("_")[3])
    
    if text == "🏧 انتقال کارت به کارت":
        payment_id = await add_payment(user_id, amount, "agent_registration", "card_to_card", "ثبت‌نام نمایندگی")
        await update.message.reply_text(
            f"💳 مبلغ {format_price(amount)} را واریز کنید:\n🏦 {BANK_CARD}\n👤 {BANK_OWNER}\n\n📸 عکس فیش را ارسال کنید\n🆔 {payment_id}",
            reply_markup=get_back_keyboard()
        )
        user_states[user_id] = f"awaiting_agent_receipt_{payment_id}"
        return
    else:
        await update.message.reply_text("⚠️ از دکمه‌ها استفاده کنید", reply_markup=get_payment_method_keyboard(False))

# ==================== هندلرهای ادمین ====================
async def admin_callback(update, context):
    query = update.callback_query
    await query.answer()
    data = query.data
    
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("⛔ دسترسی غیرمجاز")
        return
    
    if data == "check_membership":
        await check_membership_callback(update, context)
        return
    
    if data.startswith("approve_"):
        payment_id = int(data.split("_")[1])
        payment = await db_execute("SELECT user_id, amount, type, description FROM payments WHERE id = %s", (payment_id,), fetchone=True)
        if not payment:
            await query.edit_message_text("⚠️ پرداخت یافت نشد")
            return
        
        await query.edit_message_reply_markup(reply_markup=None)
        
        await update_payment_status(payment_id, "approved")
        await query.edit_message_text(f"✅ پرداخت {payment_id} تایید شد")
        
        uid, amt, ptype, desc = payment
        
        if ptype == "buy_subscription":
            await context.bot.send_message(uid, f"✅ پرداخت شما تایید شد! کد: {payment_id}\nدر حال ارسال کانفیگ...")
            sub = await db_execute("SELECT id, volume, quantity, subscription_type FROM subscriptions WHERE payment_id = %s", (payment_id,), fetchone=True)
            if sub:
                await send_multiple_configs_to_user(sub[0], uid, sub[1], sub[2], desc, context.bot, sub[3])
        
        elif ptype == "add_balance":
            await add_balance(uid, amt)
            await context.bot.send_message(uid, f"✅ موجودی شما {format_price(amt)} افزایش یافت")
            await query.message.reply_text(f"✅ موجودی کاربر {uid} به میزان {format_price(amt)} افزایش یافت")
        
        elif ptype == "agent_registration":
            await set_user_agent(uid)
            await add_balance(uid, amt)
            await context.bot.send_message(uid, f"🎉 شما به نمایندگی ارتقا یافتید!\n💰 {format_price(amt)} به موجودی اضافه شد")
            await query.message.reply_text(f"✅ کاربر {uid} به نمایندگی ارتقا یافت و {format_price(amt)} به موجودی او اضافه شد")
    
    elif data.startswith("reject_"):
        payment_id = int(data.split("_")[1])
        payment = await db_execute("SELECT user_id FROM payments WHERE id = %s", (payment_id,), fetchone=True)
        
        await query.edit_message_reply_markup(reply_markup=None)
        
        if payment:
            await update_payment_status(payment_id, "rejected")
            await context.bot.send_message(payment[0], f"❌ پرداخت شما رد شد. کد: {payment_id}")
            await query.edit_message_text(f"❌ پرداخت {payment_id} رد شد")
        else:
            await query.edit_message_text("❌ خطا در رد پرداخت")

async def stats_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    users = await db_execute("SELECT COUNT(*) FROM users", fetchone=True)
    agents = await db_execute("SELECT COUNT(*) FROM users WHERE is_agent = TRUE", fetchone=True)
    income = await get_total_income()
    total_sold = await get_total_configs_sold()
    stats = await get_config_pool_stats()
    banned = await db_execute("SELECT COUNT(*) FROM banned_users", fetchone=True)
    status = "🟢 روشن" if await get_bot_status() else "🔴 خاموش"
    
    await update.message.reply_text(
        f"📊 آمار ربات OnePercentVPN12 📊\n━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 کاربران: {persian_number(users[0])}\n"
        f"👑 نمایندگان: {persian_number(agents[0])}\n"
        f"🚫 بن شده: {persian_number(banned[0])}\n"
        f"💰 درآمد: {format_price(income)}\n"
        f"📦 کانفیگ فروخته شده: {persian_number(total_sold)}\n"
        f"📤 کانفیگ موجود: {persian_number(stats['available'])}\n"
        f"🟢 وضعیت: {status}"
    )

async def user_info_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    users = await db_execute("SELECT user_id, username, is_agent, balance FROM users ORDER BY user_id", fetch=True)
    if not users:
        await update.message.reply_text("📂 کاربری یافت نشد")
        return
    
    response = "👥 لیست کاربران:\n━━━━━━━━━━━━━━━━━━━━\n"
    for u in users:
        response += f"🆔 {u[0]} | @{u[1] or 'نامشخص'} | {'👑 نماینده' if u[2] else '👤 عادی'} | {format_price(u[3])}\n"
    await send_long_message(update.effective_user.id, response, context, reply_markup=get_admin_main_keyboard())

async def add_config_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("⚙️ مدیریت کانفیگ:", reply_markup=get_admin_config_keyboard())
    user_states[update.effective_user.id] = "admin_config"

async def handle_admin_config(update, context, user_id, text):
    if text == "➕ اضافه کردن کانفیگ اکونومی":
        await update.message.reply_text("📊 حجم را انتخاب کنید:", reply_markup=get_volume_selection_keyboard())
        user_states[user_id] = "admin_add_economy"
    elif text == "➕ اضافه کردن کانفیگ سوپر فست":
        await update.message.reply_text("📊 حجم را انتخاب کنید:", reply_markup=get_volume_selection_keyboard())
        user_states[user_id] = "admin_add_superfast"
    elif text == "📊 مشاهده موجودی کانفیگ‌ها":
        stats = await get_config_pool_stats()
        response = f"📊 موجودی کانفیگ‌ها:\n━━━━━━━━━━━━━━━━━━━━\n"
        response += f"📦 کل: {persian_number(stats['total'])}\n✅ فروخته: {persian_number(stats['sold'])}\n📤 موجود: {persian_number(stats['available'])}\n\n"
        for v in stats['by_volume']:
            type_name = "اکونومی" if v['type'] == "economy" else "سوپر فست"
            response += f"🔹 {persian_number(v['volume'])} گیگ {type_name}: {persian_number(v['available'])} عدد موجود\n"
        await update.message.reply_text(response, reply_markup=get_admin_config_keyboard())
    elif text == "📋 لیست تمام کانفیگ‌ها":
        configs = await get_all_configs()
        if not configs:
            await update.message.reply_text("📂 کانفیگی وجود ندارد", reply_markup=get_admin_config_keyboard())
            return
        resp = "📋 لیست کانفیگ‌ها:\n\n"
        for c in configs[:30]:
            resp += f"🆔 {c['id']} | {persian_number(c['volume'])} گیگ {c['type']} | {'✅ فروخته' if c['is_sold'] else '📤 موجود'}\n"
        await send_long_message(user_id, resp, context, reply_markup=get_admin_config_keyboard())
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)

async def handle_admin_add_volume(update, context, user_id, state, text):
    volume_map = {f"{persian_number(i)} گیگ": i for i in range(1, 11)}
    if text in volume_map:
        volume = volume_map[text]
        sub_type = "economy" if "economy" in state else "superfast"
        user_states[user_id] = f"admin_config_text_{volume}_{sub_type}"
        await update.message.reply_text(f"🔐 کانفیگ‌های {text} را ارسال کنید (هر خط یک کانفیگ)", reply_markup=get_back_keyboard())
    elif text == "↩️ انصراف":
        await update.message.reply_text("⚙️ مدیریت کانفیگ:", reply_markup=get_admin_config_keyboard())
        user_states[user_id] = "admin_config"

async def handle_admin_config_text(update, context, user_id, state, text):
    parts = state.split("_")
    volume = int(parts[3])
    sub_type = parts[4]
    type_name = "اکونومی" if sub_type == "economy" else "سوپر فست"
    
    configs = parse_configs_from_text(text)
    if not configs:
        await update.message.reply_text("⚠️ کانفیگ معتبر یافت نشد", reply_markup=get_admin_config_keyboard())
        user_states[user_id] = "admin_config"
        return
    
    success, fail = await add_multiple_configs_to_pool(volume, configs, user_id, sub_type)
    await update.message.reply_text(f"✅ {persian_number(success)} کانفیگ {persian_number(volume)} گیگ {type_name} اضافه شد" + (f"\n❌ {persian_number(fail)} ناموفق" if fail else ""), reply_markup=get_admin_config_keyboard())
    user_states[user_id] = "admin_config"

async def notification_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("📢 ارسال پیام:", reply_markup=get_notification_keyboard())
    user_states[update.effective_user.id] = "admin_notification_type"

async def handle_notification_type(update, context, user_id, text):
    if text == "📢 ارسال به همه کاربران":
        user_states[user_id] = "admin_notification_all"
        await update.message.reply_text("📝 متن پیام را ارسال کنید:", reply_markup=get_back_keyboard())
    elif text == "👑 ارسال به نمایندگان":
        user_states[user_id] = "admin_notification_agents"
        await update.message.reply_text("📝 متن پیام را ارسال کنید:", reply_markup=get_back_keyboard())
    elif text == "👤 ارسال به یک نفر":
        user_states[user_id] = "admin_notification_user"
        await update.message.reply_text("🆔 آیدی کاربر را وارد کنید:", reply_markup=get_back_keyboard())
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)

async def handle_notification_user(update, context, user_id, text):
    try:
        target = int(text.strip())
        user_states[user_id] = f"admin_notification_text_{target}"
        await update.message.reply_text("📝 متن پیام را ارسال کنید:", reply_markup=get_back_keyboard())
    except:
        await update.message.reply_text("⚠️ آیدی نامعتبر", reply_markup=get_notification_keyboard())
        user_states[user_id] = "admin_notification_type"

async def handle_notification_text(update, context, user_id, state, text):
    if state == "admin_notification_all":
        users = await get_all_users()
        sent, fail = await send_notification_to_users(context, users, text)
        await update.message.reply_text(f"✅ به {persian_number(sent)} نفر ارسال شد\n❌ {persian_number(fail)} ناموفق", reply_markup=get_admin_main_keyboard())
    elif state == "admin_notification_agents":
        agents = await get_all_agents()
        sent, fail = await send_notification_to_users(context, agents, text)
        await update.message.reply_text(f"✅ به {persian_number(sent)} نماینده ارسال شد", reply_markup=get_admin_main_keyboard())
    elif state.startswith("admin_notification_text_"):
        target = int(state.split("_")[3])
        await context.bot.send_message(target, f"📢 پیام سیستم:\n\n{text}")
        await update.message.reply_text(f"✅ به کاربر {target} ارسال شد", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def coupon_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("💵 درصد تخفیف (1-100):")
    user_states[update.effective_user.id] = "admin_coupon_discount"

async def handle_coupon_discount(update, context, user_id, text):
    if text.isdigit() and 1 <= int(text) <= 100:
        discount = int(text)
        code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
        user_states[user_id] = f"admin_coupon_recipient_{code}_{discount}"
        await update.message.reply_text(f"💵 کد {code} با {discount}% تخفیف\nارسال به:", reply_markup=get_coupon_recipient_keyboard())
    else:
        await update.message.reply_text("⚠️ عدد 1 تا 100 وارد کنید", reply_markup=get_back_keyboard())

async def handle_coupon_recipient(update, context, user_id, state, text):
    parts = state.split("_")
    code = parts[3]
    discount = int(parts[4])
    
    if text == "🌎 همه کاربران":
        await create_coupon(code, discount)
        users = await get_all_users()
        sent = 0
        for u in users:
            try:
                await context.bot.send_message(u[0], f"🎉 کد تخفیف {code} با {discount}% تخفیف!")
                sent += 1
            except:
                pass
        await update.message.reply_text(f"✅ برای {persian_number(sent)} کاربر ارسال شد", reply_markup=get_admin_main_keyboard())
    elif text == "👤 یک کاربر خاص":
        user_states[user_id] = f"admin_coupon_single_{code}_{discount}"
        await update.message.reply_text("🆔 آیدی کاربر:", reply_markup=get_back_keyboard())
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)

async def handle_coupon_single(update, context, user_id, state, text):
    try:
        target = int(text.strip())
        parts = state.split("_")
        code = parts[3]
        discount = int(parts[4])
        await create_coupon(code, discount, target)
        await context.bot.send_message(target, f"🎉 کد تخفیف ویژه: {code}\n{discount}% تخفیف - 3 روز اعتبار")
        await update.message.reply_text(f"✅ برای کاربر {target} ارسال شد", reply_markup=get_admin_main_keyboard())
    except:
        await update.message.reply_text("⚠️ آیدی نامعتبر", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def search_user_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🆔 آیدی کاربر را وارد کنید:")
    user_states[update.effective_user.id] = "admin_search_user"

async def handle_search_user(update, context, user_id, text):
    try:
        target = int(text.strip())
        user = await db_execute("SELECT user_id, username, is_agent, balance FROM users WHERE user_id = %s", (target,), fetchone=True)
        if user:
            await update.message.reply_text(f"🆔 {user[0]}\n👤 @{user[1] or 'ندارد'}\n👑 {'نماینده' if user[2] else 'عادی'}\n💰 {format_price(user[3])}", reply_markup=get_admin_main_keyboard())
        else:
            await update.message.reply_text("❌ کاربر یافت نشد", reply_markup=get_admin_main_keyboard())
    except:
        await update.message.reply_text("⚠️ آیدی نامعتبر", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def remove_user_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🚫 آیدی کاربر برای بن:", reply_markup=get_back_keyboard())
    user_states[update.effective_user.id] = "admin_ban_user"

async def handle_ban_user(update, context, user_id, text):
    try:
        target = int(text.strip())
        await db_execute("DELETE FROM users WHERE user_id = %s", (target,))
        await db_execute("INSERT INTO banned_users (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (target,))
        await update.message.reply_text(f"✅ کاربر {target} بن شد", reply_markup=get_admin_main_keyboard())
        try:
            await context.bot.send_message(target, "🚫 شما توسط ادمین از ربات بن شده‌اید")
        except:
            pass
    except:
        await update.message.reply_text("⚠️ خطا", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def unban_user_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("🔓 آیدی کاربر برای رفع بن:", reply_markup=get_back_keyboard())
    user_states[update.effective_user.id] = "admin_unban_user"

async def handle_unban_user(update, context, user_id, text):
    try:
        target = int(text.strip())
        await db_execute("DELETE FROM banned_users WHERE user_id = %s", (target,))
        user_exists = await db_execute("SELECT user_id FROM users WHERE user_id = %s", (target,), fetchone=True)
        if not user_exists:
            await db_execute("INSERT INTO users (user_id, balance) VALUES (%s, 0)", (target,))
        await update.message.reply_text(f"✅ بن کاربر {target} رفع شد", reply_markup=get_admin_main_keyboard())
        try:
            await context.bot.send_message(target, "✅ بن شما رفع شد. می‌توانید مجدداً از ربات استفاده کنید.")
        except:
            pass
    except:
        await update.message.reply_text("⚠️ خطا", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def set_agent_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("👑 آیدی کاربر برای نمایندگی:")
    user_states[update.effective_user.id] = "admin_set_agent"

async def handle_set_agent(update, context, user_id, text):
    try:
        target = int(text.strip())
        current = await is_user_agent(target)
        if current:
            await db_execute("UPDATE users SET is_agent = FALSE WHERE user_id = %s", (target,))
            await update.message.reply_text(f"✅ نمایندگی کاربر {target} لغو شد", reply_markup=get_admin_main_keyboard())
        else:
            await db_execute("UPDATE users SET is_agent = TRUE WHERE user_id = %s", (target,))
            await update.message.reply_text(f"✅ کاربر {target} به نماینده ارتقا یافت", reply_markup=get_admin_main_keyboard())
    except:
        await update.message.reply_text("⚠️ خطا", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def bank_management_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("💳 مدیریت کارت:", reply_markup=get_bank_management_keyboard())
    user_states[update.effective_user.id] = "admin_bank"

async def handle_bank_management(update, context, user_id, text):
    if text == "➕ اضافه کردن کارت جدید":
        user_states[user_id] = "admin_new_card"
        await update.message.reply_text("💳 شماره کارت 16 رقمی:", reply_markup=get_back_keyboard())
    elif text == "💳 کارت‌های ذخیره شده":
        cards = await db_execute("SELECT id, card_number, owner_name FROM bank_cards", fetch=True)
        if not cards:
            await update.message.reply_text("📂 کارتی ذخیره نشده", reply_markup=get_bank_management_keyboard())
            return
        resp = "💳 لیست کارت‌ها:\n\n"
        for c in cards:
            resp += f"🆔 {c[0]} | {c[1]} | {c[2]}\n"
        await update.message.reply_text(resp, reply_markup=get_bank_management_keyboard())
    elif text == "🔄 تغییر کارت اصلی":
        cards = await db_execute("SELECT id, card_number, owner_name FROM bank_cards", fetch=True)
        if not cards:
            await update.message.reply_text("📂 کارتی وجود ندارد", reply_markup=get_bank_management_keyboard())
            return
        resp = "🆔 آیدی کارت مورد نظر:\n\n"
        for c in cards:
            resp += f"🆔 {c[0]} | {c[1]}\n"
        user_states[user_id] = "admin_set_card"
        await update.message.reply_text(resp, reply_markup=get_back_keyboard())
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)

async def handle_new_card(update, context, user_id, text):
    card = text.strip().replace(" ", "")
    if card.isdigit() and len(card) == 16:
        user_states[user_id] = f"admin_card_owner_{card}"
        await update.message.reply_text("👤 نام دارنده را وارد کنید:", reply_markup=get_back_keyboard())
    else:
        await update.message.reply_text("⚠️ شماره کارت نامعتبر", reply_markup=get_bank_management_keyboard())
        user_states[user_id] = "admin_bank"

async def handle_card_owner(update, context, user_id, state, text):
    card = state.split("_")[3]
    owner = text.strip()
    if owner:
        await db_execute("INSERT INTO bank_cards (card_number, owner_name) VALUES (%s, %s)", (card, owner))
        await update.message.reply_text(f"✅ کارت {card} اضافه شد", reply_markup=get_bank_management_keyboard())
    else:
        await update.message.reply_text("⚠️ نام نامعتبر", reply_markup=get_bank_management_keyboard())
    user_states[user_id] = "admin_bank"

async def handle_set_card(update, context, user_id, text):
    try:
        card_id = int(text.strip())
        card = await db_execute("SELECT card_number, owner_name FROM bank_cards WHERE id = %s", (card_id,), fetchone=True)
        if card:
            await db_execute("UPDATE bank_settings SET card_number = %s, owner_name = %s WHERE id = 1", (card[0], card[1]))
            global BANK_CARD, BANK_OWNER
            BANK_CARD = card[0]
            BANK_OWNER = card[1]
            await update.message.reply_text(f"✅ کارت اصلی تغییر کرد:\n🏦 {BANK_CARD}\n👤 {BANK_OWNER}", reply_markup=get_bank_management_keyboard())
        else:
            await update.message.reply_text("⚠️ کارت یافت نشد", reply_markup=get_bank_management_keyboard())
    except:
        await update.message.reply_text("⚠️ آیدی نامعتبر", reply_markup=get_bank_management_keyboard())
    user_states[user_id] = "admin_bank"

async def admin_management_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    await update.message.reply_text("⚙️ مدیریت ادمین:", reply_markup=get_admin_management_keyboard())
    user_states[update.effective_user.id] = "admin_admin"

async def handle_admin_management(update, context, user_id, text):
    if text == "➕ اضافه کردن ادمین جدید":
        user_states[user_id] = "admin_add_admin"
        await update.message.reply_text("🆔 آیدی ادمین جدید:", reply_markup=get_back_keyboard())
    elif text == "➖ حذف ادمین":
        admins = await db_execute("SELECT user_id FROM admins WHERE user_id NOT IN (6056483071, 7241184581)", fetch=True)
        if not admins:
            await update.message.reply_text("📂 ادمین قابل حذفی نیست", reply_markup=get_admin_management_keyboard())
            return
        resp = "🆔 آیدی برای حذف:\n" + "\n".join([str(a[0]) for a in admins])
        user_states[user_id] = "admin_remove_admin"
        await update.message.reply_text(resp, reply_markup=get_back_keyboard())
    elif text == "📋 لیست ادمین‌ها":
        admins = await db_execute("SELECT user_id FROM admins", fetch=True)
        resp = "👥 لیست ادمین‌ها:\n" + "\n".join([str(a[0]) for a in admins])
        await update.message.reply_text(resp, reply_markup=get_admin_management_keyboard())
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)

async def handle_add_admin(update, context, user_id, text):
    try:
        new_id = int(text.strip())
        await db_execute("INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT DO NOTHING", (new_id,))
        await update.message.reply_text(f"✅ ادمین {new_id} اضافه شد", reply_markup=get_admin_management_keyboard())
        try:
            await context.bot.send_message(new_id, "🎉 شما به عنوان ادمین ربات اضافه شدید!")
        except:
            pass
    except:
        await update.message.reply_text("⚠️ خطا", reply_markup=get_admin_management_keyboard())
    user_states.pop(user_id, None)

async def handle_remove_admin(update, context, user_id, text):
    try:
        target = int(text.strip())
        if target in ADMIN_IDS:
            await update.message.reply_text("❌ نمی‌توان ادمین اصلی را حذف کرد", reply_markup=get_admin_management_keyboard())
            return
        await db_execute("DELETE FROM admins WHERE user_id = %s", (target,))
        await update.message.reply_text(f"✅ ادمین {target} حذف شد", reply_markup=get_admin_management_keyboard())
    except:
        await update.message.reply_text("⚠️ خطا", reply_markup=get_admin_management_keyboard())
    user_states.pop(user_id, None)

async def debug_subscriptions_command(update, context):
    if not is_admin(update.effective_user.id):
        return
    pending = await get_pending_subscriptions()
    balance_pending = await get_pending_balance_payments()
    agent_pending = await get_pending_agent_payments()
    
    await update.message.reply_text(
        f"🐛 دیباگ اشتراک‌ها 🐛\n━━━━━━━━━━━━━━━━━━━━\n"
        f"📊 اشتراک در انتظار: {persian_number(len(pending))}\n"
        f"💰 افزایش موجودی: {persian_number(len(balance_pending))}\n"
        f"👑 ثبت نمایندگی: {persian_number(len(agent_pending))}"
    )

# ==================== وظیفه دوره‌ای ====================
async def periodic_pending_check():
    while True:
        await asyncio.sleep(30)
        try:
            if await get_bot_status():
                pending = await get_pending_subscriptions()
                for sub in pending:
                    await send_multiple_configs_to_user(
                        sub['subscription_id'], sub['user_id'], sub['volume'], 
                        sub['quantity'], sub['plan'], application.bot, sub['subscription_type']
                    )
        except Exception as e:
            logging.error(f"Periodic error: {e}")

# ==================== هندلر اصلی ====================
async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""
    state = user_states.get(user_id)
    
    # هندلرهای فیش (عکس) - اولویت اول
    if update.message.photo:
        if state and state.startswith("awaiting_receipt_"):
            payment_id = int(state.split("_")[2])
            await process_receipt(update, context, user_id, payment_id)
            return
        if state and state.startswith("awaiting_balance_receipt_"):
            payment_id = int(state.split("_")[3])
            await process_receipt(update, context, user_id, payment_id)
            return
        if state and state.startswith("awaiting_agent_receipt_"):
            payment_id = int(state.split("_")[3])
            await process_receipt(update, context, user_id, payment_id)
            return
    
    # هندلر بازیابی بکاپ
    if update.message.document and state == "awaiting_restore":
        await handle_restore(update, context)
        return
    
    # بازگشت به منو
    if text in ["↩️ بازگشت به منو"]:
        if is_admin(user_id):
            await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        else:
            is_agent_user = await is_user_agent(user_id)
            await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent_user))
        user_states.pop(user_id, None)
        return
    
    # ========== ابتدا وضعیت‌های کاربر را بررسی کن ==========
    # وضعیت خرید اشتراک - دریافت تعداد
    if state and state.startswith("awaiting_quantity_"):
        await handle_quantity(update, context, user_id, state, text)
        return
    
    # وضعیت خرید اشتراک - دریافت کد تخفیف
    if state and state.startswith("awaiting_coupon_"):
        await handle_coupon(update, context, user_id, state, text)
        return
    
    # وضعیت خرید اشتراک - انتخاب روش پرداخت
    if state and state.startswith("awaiting_payment_"):
        await handle_payment(update, context, user_id, text)
        return
    
    # وضعیت افزایش موجودی - انتخاب اقدام
    if state == "awaiting_balance_action":
        await handle_balance_action(update, context, user_id, text)
        return
    
    # وضعیت افزایش موجودی - وارد کردن مبلغ
    if state == "awaiting_balance_amount":
        await handle_balance_amount(update, context, user_id, text)
        return
    
    # وضعیت درخواست نمایندگی
    if state == "awaiting_agent_payment":
        await handle_agent_payment(update, context, user_id, text)
        return
    
    # وضعیت درخواست نمایندگی - انتخاب روش
    if state and state.startswith("awaiting_agent_method_"):
        await handle_agent_method(update, context, user_id, text)
        return
    
    # ========== سپس هندلرهای ادمین را بررسی کن ==========
    if is_admin(user_id):
        # دکمه‌های مستقیم ادمین
        if text == "📊 آمار":
            await stats_command(update, context)
            return
        if text == "🔌 خاموش/روشن":
            await toggle_status_command(update, context)
            return
        if text == "⚙️ مدیریت کانفیگ":
            await add_config_command(update, context)
            return
        if text == "⚙️ مدیریت ادمین":
            await admin_management_command(update, context)
            return
        if text == "💳 مدیریت کارت":
            await bank_management_command(update, context)
            return
        if text == "👥 مدیریت کاربران":
            await user_info_command(update, context)
            return
        
        # وضعیت‌های ادمین
        if state == "admin_config":
            await handle_admin_config(update, context, user_id, text)
            return
        if state in ["admin_add_economy", "admin_add_superfast"]:
            await handle_admin_add_volume(update, context, user_id, state, text)
            return
        if state and state.startswith("admin_config_text_"):
            await handle_admin_config_text(update, context, user_id, state, text)
            return
        if state == "admin_notification_type":
            await handle_notification_type(update, context, user_id, text)
            return
        if state == "admin_notification_user":
            await handle_notification_user(update, context, user_id, text)
            return
        if state in ["admin_notification_all", "admin_notification_agents"] or (state and state.startswith("admin_notification_text_")):
            await handle_notification_text(update, context, user_id, state, text)
            return
        if state == "admin_coupon_discount":
            await handle_coupon_discount(update, context, user_id, text)
            return
        if state and state.startswith("admin_coupon_recipient_"):
            await handle_coupon_recipient(update, context, user_id, state, text)
            return
        if state and state.startswith("admin_coupon_single_"):
            await handle_coupon_single(update, context, user_id, state, text)
            return
        if state == "admin_search_user":
            await handle_search_user(update, context, user_id, text)
            return
        if state == "admin_ban_user":
            await handle_ban_user(update, context, user_id, text)
            return
        if state == "admin_unban_user":
            await handle_unban_user(update, context, user_id, text)
            return
        if state == "admin_set_agent":
            await handle_set_agent(update, context, user_id, text)
            return
        if state == "admin_bank":
            await handle_bank_management(update, context, user_id, text)
            return
        if state == "admin_new_card":
            await handle_new_card(update, context, user_id, text)
            return
        if state and state.startswith("admin_card_owner_"):
            await handle_card_owner(update, context, user_id, state, text)
            return
        if state == "admin_set_card":
            await handle_set_card(update, context, user_id, text)
            return
        if state == "admin_admin":
            await handle_admin_management(update, context, user_id, text)
            return
        if state == "admin_add_admin":
            await handle_add_admin(update, context, user_id, text)
            return
        if state == "admin_remove_admin":
            await handle_remove_admin(update, context, user_id, text)
            return
    
    # ========== بررسی وضعیت ربات برای کاربران عادی ==========
    if not await get_bot_status():
        await update.message.reply_text("🔴 ربات غیرفعال است")
        return
    
    # بررسی عضویت در کانال
    if not is_admin(user_id) and not await check_user_membership(user_id):
        kb = InlineKeyboardMarkup([[
            InlineKeyboardButton("📢 عضویت", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}"),
            InlineKeyboardButton("✅ تایید", callback_data="check_membership")
        ]])
        await update.message.reply_text(f"❌ ابتدا در {CHANNEL_USERNAME} عضو شوید", reply_markup=kb)
        return
    
    # ========== منوی اصلی کاربر ==========
    if text == "🛍️ خرید اشتراک":
        await handle_buy_subscription(update, context, user_id, text)
    elif text == "💰 موجودی":
        await show_balance(update, context, user_id)
    elif text == "🆘 پشتیبانی":
        await update.message.reply_text(f"📞 پشتیبانی: {SUPPORT_USERNAME}", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
    elif text == "🗂️ اشتراک‌های من":
        await show_my_subscriptions(update, context, user_id)
    elif text == "📚 آموزش اتصال":
        await show_connection_guide(update, context, user_id)
    elif text in ["📱 اندروید", "🍏 آیفون/مک", "🖥️ ویندوز", "🐧 لینوکس"]:
        await handle_guide(update, context, user_id, text)
    elif text == "👨‍💼 درخواست نمایندگی":
        await handle_agent_request(update, context, user_id)
    elif text in ["⭐️ اشتراک اکونومی ⭐️", "💎 اشتراک سوپر فست 💎"]:
        await handle_buy_subscription(update, context, user_id, text)
    else:
        # اگر پیام نامشخص بود، پیام خطا بده
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))

# ==================== ثبت هندلرها ====================
application.add_handler(CommandHandler("start", start_with_param))
application.add_handler(CommandHandler("stats", stats_command))
application.add_handler(CommandHandler("user_info", user_info_command))
application.add_handler(CommandHandler("add_config", add_config_command))
application.add_handler(CommandHandler("backup", backup_command))
application.add_handler(CommandHandler("restore", restore_command))
application.add_handler(CommandHandler("notification", notification_command))
application.add_handler(CommandHandler("coupon", coupon_command))
application.add_handler(CommandHandler("search", search_user_command))
application.add_handler(CommandHandler("remove_user", remove_user_command))
application.add_handler(CommandHandler("unban_user", unban_user_command))
application.add_handler(CommandHandler("set_agent", set_agent_command))
application.add_handler(CommandHandler("admin", admin_management_command))
application.add_handler(CommandHandler("bank", bank_management_command))
application.add_handler(CommandHandler("shutdown", shutdown_command))
application.add_handler(CommandHandler("startup", startup_command))
application.add_handler(CommandHandler("debug", debug_subscriptions_command))
application.add_handler(CommandHandler("toggle", toggle_status_command))
application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), message_handler))
application.add_handler(CallbackQueryHandler(admin_callback))

# ==================== webhook ====================
@app.post(WEBHOOK_PATH)
async def webhook(request: Request):
    data = await request.json()
    update = Update.de_json(data, application.bot)
    await application.update_queue.put(update)
    return {"ok": True}

# ==================== lifecycle ====================
periodic_task = None

@app.on_event("startup")
async def startup_event():
    global periodic_task
    init_db_pool()
    await create_tables()
    await application.initialize()
    await application.start()
    await application.bot.set_webhook(WEBHOOK_URL)
    logging.info(f"✅ Webhook set: {WEBHOOK_URL}")
    
    scheduler.add_job(create_and_send_backup, CronTrigger(hour=23, minute=59), id="daily_backup")
    scheduler.start()
    logging.info("✅ Scheduler بکاپ راه‌اندازی شد")
    
    periodic_task = asyncio.create_task(periodic_pending_check())
    
    status_text = "روشن" if await get_bot_status() else "خاموش"
    for admin_id in ADMIN_IDS:
        try:
            await application.bot.send_message(
                admin_id, 
                f"🤖 ربات OnePercentVPN12 راه‌اندازی شد!\n"
                f"✅ عضویت اجباری: {CHANNEL_USERNAME}\n"
                f"✅ وضعیت: {status_text}\n"
                f"💰 اکونومی: {format_price(PRICE_PER_GB_ECONOMY)} هر گیگ\n"
                f"💰 سوپر فست: {format_price(PRICE_PER_GB_SUPERFAST)} هر گیگ\n"
                f"💳 کارت: {BANK_CARD}\n"
                f"👤 دارنده: {BANK_OWNER}"
            )
        except:
            pass
    logging.info("✅ Bot started successfully")

@app.on_event("shutdown")
async def shutdown_event():
    global periodic_task
    if periodic_task:
        periodic_task.cancel()
    scheduler.shutdown()
    await application.stop()
    await application.shutdown()
    close_db_pool()
    logging.info("✅ Bot shut down successfully")

if __name__ == "__main__":
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
