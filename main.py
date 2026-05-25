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
from fastapi import FastAPI, Request, HTTPException
from telegram import (
    Update, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, BotCommand
)
from telegram.ext import (
    Application, CommandHandler, ContextTypes, MessageHandler, filters, CallbackQueryHandler
)
import psycopg2
from psycopg2 import pool

# ==================== تنظیمات زمانبندی بکاپ ====================
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
import pytz

# ---------- تنظیمات اولیه ----------
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_USERNAME = "@mottasel1333"
ADMIN_IDS = [6056483071, 7241184581]
SUPPORT_USERNAME = "@Amireerfani"

# تنظیمات کارت بانکی (پیش‌فرض)
BANK_CARD = "6219861847420634"
BANK_OWNER = "عرفانی نیا"

# قیمت‌ها (قیمت‌های جدید با تفکیک نوع اشتراک)
PRICE_PER_GB_ECONOMY = 169000
PRICE_PER_GB_SUPERFAST = 229000

# قیمت‌های ویژه نمایندگان
AGENT_PRICE_PER_GB_ECONOMY = 153000
AGENT_PRICE_PER_GB_SUPERFAST = 212000

# مبلغ نمایندگی
AGENT_REGISTRATION_FEE = 4000000

CONFIG_NAME = "کانفیگ"
AVAILABLE_VOLUMES = list(range(1, 11))
AVAILABLE_SUBSCRIPTION_TYPES = ["economy", "superfast"]

RENDER_BASE_URL = os.getenv("RENDER_EXTERNAL_URL") or os.getenv("RAILWAY_STATIC_URL") or "https://OnePercentVPN12.railway.app"
WEBHOOK_PATH = f"/webhook/{TOKEN}"
WEBHOOK_URL = f"{RENDER_BASE_URL}{WEBHOOK_PATH}"

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("OnePercentVPN12_bot.log", encoding="utf-8") if os.path.exists("/tmp") else logging.StreamHandler()
    ]
)

app = FastAPI()

# ---------- وضعیت ربات ----------
bot_is_active = True

# ---------- توابع کمکی ----------
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
        else:
            return volume * quantity * PRICE_PER_GB_SUPERFAST
    else:
        if is_agent:
            return volume * quantity * AGENT_PRICE_PER_GB_ECONOMY
        else:
            return volume * quantity * PRICE_PER_GB_ECONOMY

def get_display_text_for_volume(volume: int, is_agent: bool = False, subscription_type: str = "economy") -> str:
    price = get_price_for_volume(volume, 1, is_agent, subscription_type)
    
    if subscription_type == "economy":
        type_name = "اکونومی ⭐️"
    else:
        type_name = "سوپر فست 💎"
    
    if is_agent:
        return f"{persian_number(volume)} گیگ {type_name} | {format_price(price)} | نماینده"
    else:
        return f"{persian_number(volume)} گیگ {type_name} | {format_price(price)}"

def get_subscription_type_keyboard():
    keyboard = [
        [KeyboardButton("⭐️ اشتراک اکونومی ⭐️")],
        [KeyboardButton("💎 اشتراک سوپر فست 💎")],
        [KeyboardButton("↩️ بازگشت به منو")]
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

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

# ---------- توابع مدیریت ادمین و کارت ----------
async def add_admin(new_admin_id: int) -> bool:
    global ADMIN_IDS
    if new_admin_id not in ADMIN_IDS:
        ADMIN_IDS.append(new_admin_id)
        try:
            await db_execute(
                "INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (new_admin_id,)
            )
        except:
            pass
        return True
    return False

async def remove_admin(admin_id: int) -> bool:
    global ADMIN_IDS
    if admin_id in [6056483071, 7241184581]:
        return False
    if admin_id in ADMIN_IDS:
        ADMIN_IDS.remove(admin_id)
        try:
            await db_execute("DELETE FROM admins WHERE user_id = %s", (admin_id,))
        except:
            pass
        return True
    return False

async def load_admins_from_db():
    global ADMIN_IDS
    try:
        rows = await db_execute("SELECT user_id FROM admins", fetch=True)
        for row in rows:
            if row[0] not in ADMIN_IDS:
                ADMIN_IDS.append(row[0])
    except:
        pass

async def update_bank_card(card_number: str, owner_name: str) -> bool:
    global BANK_CARD, BANK_OWNER
    try:
        await db_execute(
            "INSERT INTO bank_settings (id, card_number, owner_name) VALUES (1, %s, %s) ON CONFLICT (id) DO UPDATE SET card_number = EXCLUDED.card_number, owner_name = EXCLUDED.owner_name",
            (card_number, owner_name)
        )
        BANK_CARD = card_number
        BANK_OWNER = owner_name
        return True
    except Exception as e:
        logging.error(f"Error updating bank card: {e}")
        return False

async def add_bank_card(card_number: str, owner_name: str) -> bool:
    try:
        await db_execute(
            "INSERT INTO bank_cards (card_number, owner_name) VALUES (%s, %s)",
            (card_number, owner_name)
        )
        return True
    except Exception as e:
        logging.error(f"Error adding bank card: {e}")
        return False

async def get_all_bank_cards() -> List[Dict]:
    try:
        rows = await db_execute(
            "SELECT id, card_number, owner_name, is_active, created_at FROM bank_cards ORDER BY id DESC",
            fetch=True
        )
        cards = []
        for row in rows:
            cards.append({
                "id": row[0],
                "card_number": row[1],
                "owner_name": row[2],
                "is_active": row[3],
                "created_at": row[4]
            })
        return cards
    except Exception as e:
        logging.error(f"Error getting bank cards: {e}")
        return []

async def set_active_card(card_id: int) -> bool:
    global BANK_CARD, BANK_OWNER
    try:
        card = await db_execute(
            "SELECT card_number, owner_name FROM bank_cards WHERE id = %s",
            (card_id,), fetchone=True
        )
        if card:
            BANK_CARD = card[0]
            BANK_OWNER = card[1]
            await db_execute(
                "UPDATE bank_settings SET card_number = %s, owner_name = %s WHERE id = 1",
                (BANK_CARD, BANK_OWNER)
            )
            return True
        return False
    except Exception as e:
        logging.error(f"Error setting active card: {e}")
        return False

async def load_bank_settings():
    global BANK_CARD, BANK_OWNER
    try:
        row = await db_execute("SELECT card_number, owner_name FROM bank_settings WHERE id = 1", fetchone=True)
        if row:
            BANK_CARD = row[0]
            BANK_OWNER = row[1]
    except:
        pass

# ---------- endpoint سلامت ----------
@app.get("/")
async def health_check():
    return {"status": "up", "message": "OnePercentVPN12 Bot is running!", "timestamp": datetime.now().isoformat()}

@app.get("/health")
async def health():
    try:
        await db_execute("SELECT 1", fetchone=True)
        return {"status": "healthy", "database": "connected", "bot": "running", "timestamp": datetime.now().isoformat()}
    except Exception as e:
        return {"status": "unhealthy", "database": "disconnected", "error": str(e), "timestamp": datetime.now().isoformat()}

@app.get("/ping")
async def ping():
    return {"pong": True, "timestamp": datetime.now().isoformat()}

# ---------- مدیریت application ----------
application = Application.builder().token(TOKEN).build()

# ---------- PostgreSQL connection pool ----------
DATABASE_URL = os.getenv("DATABASE_URL")
db_pool: pool.ThreadedConnectionPool = None

def init_db_pool():
    global db_pool
    if not DATABASE_URL:
        raise RuntimeError("DATABASE_URL environment variable is not set.")
    try:
        db_pool = psycopg2.pool.ThreadedConnectionPool(minconn=1, maxconn=10, dsn=DATABASE_URL, sslmode='require')
        logging.info("Database pool initialized successfully")
    except Exception as e:
        logging.error(f"Failed to initialize database pool: {e}")
        raise

def close_db_pool():
    global db_pool
    if db_pool:
        db_pool.closeall()
        db_pool = None
        logging.info("Database pool closed")

def _db_execute_sync(query, params=(), fetch=False, fetchone=False, returning=False):
    conn = None
    cur = None
    try:
        conn = db_pool.getconn()
        cur = conn.cursor()
        cur.execute(query, params)
        result = None
        if returning:
            result = cur.fetchone()[0] if cur.rowcount > 0 else None
        elif fetchone:
            result = cur.fetchone()
        elif fetch:
            result = cur.fetchall()
        if not query.strip().lower().startswith("select"):
            conn.commit()
        return result
    except Exception as e:
        logging.error(f"Database error: {e}")
        if conn:
            conn.rollback()
        raise
    finally:
        if cur:
            cur.close()
        if conn:
            db_pool.putconn(conn)

async def db_execute(query, params=(), fetch=False, fetchone=False, returning=False):
    try:
        return await asyncio.to_thread(_db_execute_sync, query, params, fetch, fetchone, returning)
    except Exception as e:
        logging.error(f"Async database error: {e}")
        raise

# ---------- ساخت جداول ----------
CREATE_BOT_STATUS_SQL = """
CREATE TABLE IF NOT EXISTS bot_status (
    id INTEGER PRIMARY KEY DEFAULT 1,
    is_active BOOLEAN DEFAULT TRUE
)
"""

CREATE_USERS_SQL = """
CREATE TABLE IF NOT EXISTS users (
    user_id BIGINT PRIMARY KEY,
    username TEXT,
    balance BIGINT DEFAULT 0,
    invited_by BIGINT,
    phone TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    is_agent BOOLEAN DEFAULT FALSE,
    is_new_user BOOLEAN DEFAULT TRUE,
    is_member BOOLEAN DEFAULT FALSE
)
"""

CREATE_PAYMENTS_SQL = """
CREATE TABLE IF NOT EXISTS payments (
    id SERIAL PRIMARY KEY,
    user_id BIGINT,
    amount BIGINT,
    status TEXT,
    type TEXT,
    payment_method TEXT,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_SUBSCRIPTIONS_SQL = """
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
"""

CREATE_COUPONS_SQL = """
CREATE TABLE IF NOT EXISTS coupons (
    code TEXT PRIMARY KEY,
    discount_percent INTEGER,
    user_id BIGINT,
    is_used BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expiry_date TIMESTAMP GENERATED ALWAYS AS (created_at + INTERVAL '3 days') STORED
)
"""

CREATE_CONFIG_POOL_SQL = """
CREATE TABLE IF NOT EXISTS config_pool (
    id SERIAL PRIMARY KEY,
    volume INTEGER NOT NULL,
    config_text TEXT NOT NULL,
    is_sold BOOLEAN DEFAULT FALSE,
    sold_to_user BIGINT,
    sold_at TIMESTAMP,
    created_by BIGINT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    subscription_type TEXT DEFAULT 'economy'
)
"""

CREATE_ADMINS_SQL = """
CREATE TABLE IF NOT EXISTS admins (
    user_id BIGINT PRIMARY KEY,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_BANK_SETTINGS_SQL = """
CREATE TABLE IF NOT EXISTS bank_settings (
    id INTEGER PRIMARY KEY DEFAULT 1,
    card_number TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_BANK_CARDS_SQL = """
CREATE TABLE IF NOT EXISTS bank_cards (
    id SERIAL PRIMARY KEY,
    card_number TEXT NOT NULL,
    owner_name TEXT NOT NULL,
    is_active BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

CREATE_BANNED_USERS_SQL = """
CREATE TABLE IF NOT EXISTS banned_users (
    user_id BIGINT PRIMARY KEY,
    banned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
)
"""

MIGRATE_SUBSCRIPTIONS_SQL = """
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='is_new_user') THEN
        ALTER TABLE users ADD COLUMN is_new_user BOOLEAN DEFAULT TRUE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='users' AND column_name='is_member') THEN
        ALTER TABLE users ADD COLUMN is_member BOOLEAN DEFAULT FALSE;
    END IF;
    UPDATE users SET is_new_user = FALSE WHERE is_new_user IS NULL;
    UPDATE users SET is_member = FALSE WHERE is_member IS NULL;
END $$;

ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS start_date TIMESTAMP;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS duration_days INTEGER;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS volume INTEGER;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS quantity INTEGER DEFAULT 1;
ALTER TABLE subscriptions ADD COLUMN IF NOT EXISTS subscription_type TEXT DEFAULT 'economy';
ALTER TABLE users ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE users ADD COLUMN IF NOT EXISTS is_agent BOOLEAN DEFAULT FALSE;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP;
ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_method TEXT;
ALTER TABLE config_pool ADD COLUMN IF NOT EXISTS subscription_type TEXT DEFAULT 'economy';

UPDATE subscriptions SET start_date = COALESCE(start_date, CURRENT_TIMESTAMP), duration_days = 30
WHERE start_date IS NULL OR duration_days IS NULL;
"""

async def create_tables():
    try:
        await db_execute(CREATE_BOT_STATUS_SQL)
        await db_execute(CREATE_USERS_SQL)
        await db_execute(CREATE_PAYMENTS_SQL)
        await db_execute(CREATE_SUBSCRIPTIONS_SQL)
        await db_execute(CREATE_COUPONS_SQL)
        await db_execute(CREATE_CONFIG_POOL_SQL)
        await db_execute(CREATE_ADMINS_SQL)
        await db_execute(CREATE_BANK_SETTINGS_SQL)
        await db_execute(CREATE_BANK_CARDS_SQL)
        await db_execute(CREATE_BANNED_USERS_SQL)
        await db_execute(MIGRATE_SUBSCRIPTIONS_SQL)
        
        status = await db_execute("SELECT is_active FROM bot_status WHERE id = 1", fetchone=True)
        if not status:
            await db_execute("INSERT INTO bot_status (id, is_active) VALUES (1, TRUE)")
            global bot_is_active
            bot_is_active = True
        else:
            bot_is_active = status[0]
        
        await load_admins_from_db()
        await load_bank_settings()
        
        for admin_id in [6056483071, 7241184581]:
            await db_execute(
                "INSERT INTO admins (user_id) VALUES (%s) ON CONFLICT (user_id) DO NOTHING",
                (admin_id,)
            )
        
        await db_execute(
            "INSERT INTO bank_settings (id, card_number, owner_name) VALUES (1, %s, %s) ON CONFLICT (id) DO NOTHING",
            (BANK_CARD, BANK_OWNER)
        )
            
        logging.info("Database tables created successfully")
    except Exception as e:
        logging.error(f"Error creating tables: {e}")

# ---------- توابع مدیریت وضعیت ربات ----------
async def set_bot_status(is_active: bool):
    global bot_is_active
    bot_is_active = is_active
    await db_execute("UPDATE bot_status SET is_active = %s WHERE id = 1", (is_active,))

async def get_bot_status() -> bool:
    global bot_is_active
    return bot_is_active

async def is_bot_available_for_user(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    return await get_bot_status()

# ---------- وضعیت کاربر ----------
user_states = {}

def generate_coupon_code(length=8):
    return ''.join(random.choices(string.ascii_uppercase + string.digits, k=length))

# ---------- کیبوردها ----------
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

def get_subscription_keyboard(is_agent: bool = False, subscription_type: str = "economy"):
    keyboard = []
    for volume in AVAILABLE_VOLUMES:
        display_text = get_display_text_for_volume(volume, is_agent, subscription_type)
        keyboard.append([KeyboardButton(display_text)])
    keyboard.append([KeyboardButton("↩️ بازگشت به منو")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_payment_method_keyboard(has_balance: bool = False):
    keyboard = [[KeyboardButton("🏧 انتقال کارت به کارت")]]
    if has_balance:
        keyboard.append([KeyboardButton("💳 پرداخت از موجودی")])
    keyboard.append([KeyboardButton("↩️ بازگشت به منو")])
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_connection_guide_keyboard():
    keyboard = [[KeyboardButton("📱 اندروید")], [KeyboardButton("🍏 آیفون/مک")], [KeyboardButton("🖥️ ویندوز")], [KeyboardButton("🐧 لینوکس")], [KeyboardButton("↩️ بازگشت به منو")]]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

def get_coupon_recipient_keyboard():
    return ReplyKeyboardMarkup([[KeyboardButton("🌎 همه کاربران")], [KeyboardButton("👤 یک کاربر خاص")], [KeyboardButton("🎲 درصد مشخصی از کاربران")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)

def get_admin_main_keyboard():
    keyboard = [
        [KeyboardButton("🛍️ خرید اشتراک")],
        [KeyboardButton("💰 موجودی")],
        [KeyboardButton("🆘 پشتیبانی")],
        [KeyboardButton("🗂️ اشتراک‌های من"), KeyboardButton("📚 آموزش اتصال")],
        [KeyboardButton("👨‍💼 درخواست نمایندگی")],
        [KeyboardButton("⚙️ مدیریت ادمین"), KeyboardButton("💳 مدیریت کارت")],
        [KeyboardButton("👥 مدیریت کاربران"), KeyboardButton("⚙️ مدیریت کانفیگ")]
    ]
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

def get_user_management_keyboard():
    keyboard = [
        [KeyboardButton("📊 مشاهده اطلاعات کاربر")],
        [KeyboardButton("➕ افزایش/کاهش موجودی")],
        [KeyboardButton("👑 اعطای/عزل نمایندگی")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    return ReplyKeyboardMarkup(keyboard, resize_keyboard=True)

# ---------- توابع کمکی ----------
async def send_long_message(chat_id, text, context, reply_markup=None, parse_mode=None):
    max_len = 4000
    if len(text) <= max_len:
        await context.bot.send_message(chat_id=chat_id, text=text, reply_markup=reply_markup, parse_mode=parse_mode)
        return
    messages = []
    current = ""
    for line in text.split("\n"):
        if len(current) + len(line) + 1 > max_len:
            messages.append(current)
            current = line + "\n"
        else:
            current += line + "\n"
    if current:
        messages.append(current)
    for i, msg in enumerate(messages):
        await context.bot.send_message(chat_id=chat_id, text=msg, reply_markup=reply_markup if i == len(messages)-1 else None, parse_mode=parse_mode)

def parse_configs_from_text(text: str) -> List[str]:
    lines = text.strip().split('\n')
    configs = []
    for line in lines:
        line = line.strip()
        if line and (line.startswith('http://') or line.startswith('https://') or line.startswith('vless://') or line.startswith('vmess://') or line.startswith('trojan://') or line.startswith('ss://')):
            configs.append(line)
    return configs

def extract_volume_and_type_from_display_text(text: str) -> Tuple[Optional[int], Optional[str]]:
    """استخراج حجم و نوع اشتراک از متن دکمه"""
    # فرمت: "۱ گیگ اکونومی ⭐️ | ۱۶۹,۰۰۰ تومان" یا "۱ گیگ سوپر فست 💎 | ۲۲۹,۰۰۰ تومان"
    for volume in range(1, 11):
        volume_text = f"{persian_number(volume)} گیگ"
        if text.startswith(volume_text):
            if "اکونومی" in text:
                return volume, "economy"
            elif "سوپر فست" in text:
                return volume, "superfast"
    return None, None

# ---------- توابع DB ----------
async def check_user_membership(user_id: int) -> bool:
    try:
        member = await application.bot.get_chat_member(CHANNEL_USERNAME, user_id)
        is_member = member.status in ["member", "administrator", "creator"]
        await db_execute("UPDATE users SET is_member = %s WHERE user_id = %s", (is_member, user_id))
        return is_member
    except Exception as e:
        logging.error(f"Error checking membership for user {user_id}: {e}")
        await db_execute("UPDATE users SET is_member = FALSE WHERE user_id = %s", (user_id,))
        return False

async def ensure_user(user_id, username, invited_by=None):
    try:
        row = await db_execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,), fetchone=True)
        if not row:
            await db_execute("INSERT INTO users (user_id, username, invited_by, is_agent, is_new_user, is_member, balance) VALUES (%s, %s, %s, FALSE, TRUE, FALSE, 0)", (user_id, username, invited_by))
            if invited_by and invited_by != user_id:
                await add_balance(invited_by, 15000)
        else:
            await db_execute("UPDATE users SET is_new_user = FALSE WHERE user_id = %s", (user_id,))
    except Exception as e:
        logging.error(f"Error ensuring user: {e}")

async def get_user_balance(user_id):
    try:
        row = await db_execute("SELECT balance FROM users WHERE user_id = %s", (user_id,), fetchone=True)
        return row[0] if row else 0
    except:
        return 0

async def add_balance(user_id, amount):
    try:
        await db_execute("UPDATE users SET balance = COALESCE(balance,0) + %s WHERE user_id = %s", (amount, user_id))
    except Exception as e:
        logging.error(f"Error adding balance: {e}")

async def subtract_balance(user_id, amount):
    try:
        current = await get_user_balance(user_id)
        if current >= amount:
            await db_execute("UPDATE users SET balance = COALESCE(balance,0) - %s WHERE user_id = %s", (amount, user_id))
            return True
        return False
    except:
        return False

async def is_user_agent(user_id):
    try:
        row = await db_execute("SELECT is_agent FROM users WHERE user_id = %s", (user_id,), fetchone=True)
        return row[0] if row and row[0] is not None else False
    except:
        return False

async def set_user_agent(user_id):
    try:
        await db_execute("UPDATE users SET is_agent = TRUE WHERE user_id = %s", (user_id,))
    except:
        pass

async def unset_user_agent(user_id):
    try:
        await db_execute("UPDATE users SET is_agent = FALSE WHERE user_id = %s", (user_id,))
    except:
        pass

async def add_payment(user_id, amount, ptype, payment_method, description="", coupon_code=None):
    try:
        query = "INSERT INTO payments (user_id, amount, status, type, payment_method, description) VALUES (%s, %s, 'pending', %s, %s, %s) RETURNING id"
        new_id = await db_execute(query, (user_id, amount, ptype, payment_method, description), returning=True)
        if coupon_code:
            await mark_coupon_used(coupon_code)
        return int(new_id) if new_id is not None else None
    except:
        return None

async def add_balance_payment(user_id, amount, payment_method, description=""):
    try:
        query = "INSERT INTO payments (user_id, amount, status, type, payment_method, description) VALUES (%s, %s, 'pending', 'add_balance', %s, %s) RETURNING id"
        new_id = await db_execute(query, (user_id, amount, payment_method, description), returning=True)
        return int(new_id) if new_id is not None else None
    except:
        return None

async def add_subscription(user_id, payment_id, plan, volume, quantity, subscription_type):
    try:
        await db_execute("INSERT INTO subscriptions (user_id, payment_id, plan, status, start_date, duration_days, volume, quantity, subscription_type) VALUES (%s, %s, %s, 'pending', CURRENT_TIMESTAMP, 30, %s, %s, %s)", (user_id, payment_id, plan, volume, quantity, subscription_type))
    except Exception as e:
        logging.error(f"Error adding subscription: {e}")

async def update_subscription_config(subscription_id, config):
    try:
        await db_execute("UPDATE subscriptions SET config = %s, status = 'active' WHERE id = %s", (config, subscription_id))
    except:
        pass

async def update_payment_status(payment_id, status):
    try:
        await db_execute("UPDATE payments SET status = %s WHERE id = %s", (status, payment_id))
    except:
        pass

async def get_user_subscriptions(user_id):
    try:
        rows = await db_execute("SELECT id, plan, config, status, payment_id, start_date, duration_days, volume, quantity, subscription_type FROM subscriptions WHERE user_id = %s ORDER BY status DESC, start_date DESC", (user_id,), fetch=True)
        current_time = datetime.now()
        subs = []
        for row in rows:
            sub_id, plan, config, status, payment_id, start_date, duration_days, volume, quantity, subscription_type = row
            start_date = start_date or current_time
            duration_days = duration_days or 30
            if status == "active":
                end_date = start_date + timedelta(days=duration_days)
                if current_time > end_date:
                    await db_execute("UPDATE subscriptions SET status = 'inactive' WHERE id = %s", (sub_id,))
                    status = "inactive"
            subs.append({'id': sub_id, 'plan': plan, 'config': config, 'status': status, 'payment_id': payment_id, 'start_date': start_date, 'duration_days': duration_days, 'volume': volume, 'quantity': quantity, 'subscription_type': subscription_type, 'end_date': start_date + timedelta(days=duration_days)})
        return subs
    except:
        return []

async def create_coupon(code, discount_percent, user_id=None):
    try:
        await db_execute("INSERT INTO coupons (code, discount_percent, user_id, is_used) VALUES (%s, %s, %s, FALSE)", (code, discount_percent, user_id))
    except:
        pass

async def validate_coupon(code, user_id):
    try:
        row = await db_execute("SELECT discount_percent, user_id, is_used, expiry_date FROM coupons WHERE code = %s", (code,), fetchone=True)
        if not row:
            return None, "❌ کد تخفیف معتبر نمی‌باشد."
        discount_percent, coupon_user_id, is_used, expiry_date = row
        if is_used:
            return None, "❌ این کد قبلاً استفاده شده است."
        if datetime.now() > expiry_date:
            return None, "❌ این کد منقضی شده است."
        if coupon_user_id is not None and coupon_user_id != user_id:
            return None, "❌ این کد متعلق به شما نیست."
        if await is_user_agent(user_id):
            return None, "⚠️ نمایندگان گرامی نمی‌توانند از کد تخفیف استفاده نمایند."
        return discount_percent, None
    except:
        return None, "❌ خطا در بررسی کد تخفیف."

async def mark_coupon_used(code):
    try:
        await db_execute("UPDATE coupons SET is_used = TRUE WHERE code = %s", (code,))
    except:
        pass

async def clear_all_database():
    try:
        await db_execute("DELETE FROM config_pool")
        await db_execute("DELETE FROM coupons")
        await db_execute("DELETE FROM subscriptions")
        await db_execute("DELETE FROM payments")
        await db_execute("DELETE FROM users")
        return True
    except Exception as e:
        logging.error(f"Error clearing database: {e}")
        return False

async def remove_user_from_db(user_id):
    try:
        await db_execute("DELETE FROM coupons WHERE user_id = %s", (user_id,))
        await db_execute("DELETE FROM subscriptions WHERE user_id = %s", (user_id,))
        await db_execute("DELETE FROM payments WHERE user_id = %s", (user_id,))
        await db_execute("DELETE FROM users WHERE user_id = %s", (user_id,))
        return True
    except:
        return False

async def ban_user_from_bot(user_id: int) -> bool:
    try:
        await remove_user_from_db(user_id)
        await db_execute(
            "INSERT INTO banned_users (user_id, banned_at) VALUES (%s, CURRENT_TIMESTAMP) ON CONFLICT (user_id) DO NOTHING",
            (user_id,)
        )
        return True
    except:
        return False

async def unban_user_from_bot(user_id: int) -> bool:
    try:
        await db_execute("DELETE FROM banned_users WHERE user_id = %s", (user_id,))
        
        user_exists = await db_execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,), fetchone=True)
        
        if not user_exists:
            await db_execute(
                "INSERT INTO users (user_id, username, balance, is_agent, is_new_user, is_member) VALUES (%s, NULL, 0, FALSE, TRUE, FALSE)",
                (user_id,)
            )
        
        return True
    except Exception as e:
        logging.error(f"Error unbanning user {user_id}: {e}")
        return False

async def is_user_banned(user_id: int) -> bool:
    try:
        row = await db_execute("SELECT user_id FROM banned_users WHERE user_id = %s", (user_id,), fetchone=True)
        return row is not None
    except:
        return False

async def send_notification_to_users(context, user_ids, notification_text):
    sent = 0
    failed = 0
    for user_id in user_ids:
        try:
            await context.bot.send_message(chat_id=user_id[0], text=f"📢 پیام سیستم:\n\n{notification_text}")
            sent += 1
        except Exception as e:
            logging.error(f"Failed to send to {user_id[0]}: {e}")
            failed += 1
    return sent, failed

async def get_all_users() -> List[Tuple]:
    try:
        return await db_execute("SELECT user_id FROM users", fetch=True)
    except:
        return []

async def get_all_agents() -> List[Tuple]:
    try:
        return await db_execute("SELECT user_id FROM users WHERE is_agent = TRUE", fetch=True)
    except:
        return []

async def get_total_income() -> int:
    try:
        row = await db_execute("SELECT SUM(amount) FROM payments WHERE status = 'approved'", fetchone=True)
        return row[0] if row and row[0] else 0
    except:
        return 0

async def get_total_configs_sold() -> int:
    try:
        row = await db_execute("SELECT COUNT(*) FROM config_pool WHERE is_sold = TRUE", fetch=True)
        return row[0] if row else 0
    except:
        return 0

# ---------- توابع مدیریت کانفیگ ----------
async def add_config_to_pool(volume: int, config_text: str, admin_id: int, subscription_type: str = "economy") -> bool:
    try:
        await db_execute(
            "INSERT INTO config_pool (volume, config_text, created_by, is_sold, subscription_type) VALUES (%s, %s, %s, FALSE, %s)",
            (volume, config_text, admin_id, subscription_type)
        )
        return True
    except Exception as e:
        logging.error(f"Error adding config to pool: {e}")
        return False

async def add_multiple_configs_to_pool(volume: int, configs_text: List[str], admin_id: int, subscription_type: str = "economy") -> Tuple[int, int]:
    success_count = 0
    fail_count = 0
    for config_text in configs_text:
        if await add_config_to_pool(volume, config_text, admin_id, subscription_type):
            success_count += 1
        else:
            fail_count += 1
    return success_count, fail_count

async def get_available_configs_count(volume: int, subscription_type: str = "economy") -> int:
    try:
        row = await db_execute(
            "SELECT COUNT(*) FROM config_pool WHERE volume = %s AND is_sold = FALSE AND subscription_type = %s",
            (volume, subscription_type), fetchone=True
        )
        return row[0] if row else 0
    except Exception as e:
        logging.error(f"Error getting available configs count: {e}")
        return 0

async def get_available_configs(volume: int, quantity: int, subscription_type: str = "economy") -> Optional[List[Dict]]:
    try:
        rows = await db_execute(
            "SELECT id, config_text FROM config_pool WHERE volume = %s AND is_sold = FALSE AND subscription_type = %s ORDER BY id LIMIT %s",
            (volume, subscription_type, quantity), fetch=True
        )
        if rows and len(rows) >= quantity:
            return [{"id": row[0], "config_text": row[1]} for row in rows]
        return None
    except Exception as e:
        logging.error(f"Error getting available configs: {e}")
        return None

async def mark_configs_as_sold(config_ids: List[int], user_id: int) -> bool:
    try:
        for config_id in config_ids:
            await db_execute(
                "UPDATE config_pool SET is_sold = TRUE, sold_to_user = %s, sold_at = CURRENT_TIMESTAMP WHERE id = %s",
                (user_id, config_id)
            )
        return True
    except Exception as e:
        logging.error(f"Error marking configs as sold: {e}")
        return False

async def get_config_pool_stats() -> Dict:
    try:
        total = await db_execute("SELECT COUNT(*) FROM config_pool", fetchone=True)
        sold = await db_execute("SELECT COUNT(*) FROM config_pool WHERE is_sold = TRUE", fetchone=True)
        available = await db_execute("SELECT COUNT(*) FROM config_pool WHERE is_sold = FALSE", fetchone=True)
        
        volume_stats = await db_execute(
            "SELECT volume, subscription_type, COUNT(*) as total, SUM(CASE WHEN is_sold THEN 1 ELSE 0 END) as sold FROM config_pool GROUP BY volume, subscription_type ORDER BY volume, subscription_type",
            fetch=True
        )
        
        stats_by_volume = []
        for row in volume_stats:
            volume, sub_type, total_count, sold_count = row
            type_name = "اکونومی" if sub_type == "economy" else "سوپر فست"
            stats_by_volume.append({
                "volume": volume,
                "subscription_type": sub_type,
                "type_name": type_name,
                "total": total_count,
                "sold": sold_count,
                "available": total_count - sold_count
            })
        
        return {
            "total": total[0] if total else 0,
            "sold": sold[0] if sold else 0,
            "available": available[0] if available else 0,
            "by_volume": stats_by_volume
        }
    except Exception as e:
        logging.error(f"Error getting config pool stats: {e}")
        return {"total": 0, "sold": 0, "available": 0, "by_volume": []}

async def get_all_configs() -> List[Dict]:
    try:
        rows = await db_execute(
            "SELECT id, volume, config_text, is_sold, sold_to_user, created_by, created_at, sold_at, subscription_type FROM config_pool ORDER BY created_at DESC",
            fetch=True
        )
        configs = []
        for row in rows:
            type_name = "اکونومی" if row[8] == "economy" else "سوپر فست"
            configs.append({
                "id": row[0],
                "volume": row[1],
                "config_text": row[2][:100] + "..." if len(row[2]) > 100 else row[2],
                "is_sold": row[3],
                "sold_to_user": row[4],
                "created_by": row[5],
                "created_at": row[6],
                "sold_at": row[7],
                "subscription_type": row[8],
                "type_name": type_name
            })
        return configs
    except Exception as e:
        logging.error(f"Error getting all configs: {e}")
        return []

async def get_pending_subscriptions() -> List[Dict]:
    try:
        rows = await db_execute(
            "SELECT s.id, s.user_id, s.volume, s.plan, s.quantity, s.subscription_type, p.id as payment_id FROM subscriptions s JOIN payments p ON s.payment_id = p.id WHERE s.status = 'pending' AND p.status = 'approved'",
            fetch=True
        )
        pending = []
        for row in rows:
            pending.append({
                "subscription_id": row[0],
                "user_id": row[1],
                "volume": row[2],
                "plan": row[3],
                "quantity": row[4],
                "subscription_type": row[5],
                "payment_id": row[6]
            })
        return pending
    except Exception as e:
        logging.error(f"Error getting pending subscriptions: {e}")
        return []

async def get_pending_balance_payments() -> List[Dict]:
    try:
        rows = await db_execute(
            "SELECT id, user_id, amount, description FROM payments WHERE type = 'add_balance' AND status = 'pending'",
            fetch=True
        )
        pending = []
        for row in rows:
            pending.append({
                "payment_id": row[0],
                "user_id": row[1],
                "amount": row[2],
                "description": row[3]
            })
        return pending
    except Exception as e:
        logging.error(f"Error getting pending balance payments: {e}")
        return []

async def get_pending_agent_payments() -> List[Dict]:
    try:
        rows = await db_execute(
            "SELECT id, user_id, amount, description FROM payments WHERE type = 'agent_registration' AND status = 'pending'",
            fetch=True
        )
        pending = []
        for row in rows:
            pending.append({
                "payment_id": row[0],
                "user_id": row[1],
                "amount": row[2],
                "description": row[3]
            })
        return pending
    except Exception as e:
        logging.error(f"Error getting pending agent payments: {e}")
        return []

# ==================== توابع بکاپ ====================

scheduler = AsyncIOScheduler(timezone=pytz.timezone('Asia/Tehran'))

async def backup_config_pool_only() -> Dict:
    try:
        configs = await db_execute(
            "SELECT id, volume, config_text, is_sold, created_by, created_at, subscription_type FROM config_pool WHERE is_sold = FALSE ORDER BY id",
            fetch=True
        )
        
        backup_data = {
            "backup_date": datetime.now().isoformat(),
            "backup_type": "config_pool_only",
            "config_pool": {
                "total": len(configs),
                "items": [
                    {
                        "id": row[0],
                        "volume": row[1],
                        "config_text": row[2],
                        "is_sold": row[3],
                        "created_by": row[4],
                        "created_at": str(row[5]) if row[5] else None,
                        "subscription_type": row[6]
                    }
                    for row in configs
                ]
            }
        }
        
        return backup_data
    except Exception as e:
        logging.error(f"Config backup error: {e}")
        return None

async def send_backup_to_admins(backup_file_path: str, backup_type: str = "daily"):
    if not os.path.exists(backup_file_path):
        logging.error(f"فایل بکاپ وجود ندارد: {backup_file_path}")
        return False
    
    file_size = os.path.getsize(backup_file_path)
    tehran_time = datetime.now(pytz.timezone('Asia/Tehran')).strftime('%Y-%m-%d %H:%M:%S')
    
    caption = (
        f"📦 *بکاپ {backup_type}*\n"
        f"📅 تاریخ: `{tehran_time}`\n"
        f"📊 حجم: `{file_size / 1024:.2f} KB`"
    )
    
    success_count = 0
    for admin_id in ADMIN_IDS:
        try:
            with open(backup_file_path, 'rb') as backup_file:
                await application.bot.send_document(
                    chat_id=admin_id,
                    document=backup_file,
                    caption=caption,
                    parse_mode="Markdown"
                )
            success_count += 1
            logging.info(f"بکاپ به ادمین {admin_id} ارسال شد")
        except Exception as e:
            logging.error(f"خطا در ارسال بکاپ به ادمین {admin_id}: {e}")
    
    return success_count > 0

async def create_and_send_backup():
    try:
        tehran_now = datetime.now(pytz.timezone('Asia/Tehran'))
        logging.info(f"🕐 شروع تسک بکاپ روزانه در {tehran_now}")
        
        backup_data = await backup_config_pool_only()
        
        if not backup_data:
            error_msg = "❌ خطا در تهیه بکاپ روزانه!"
            logging.error(error_msg)
            for admin_id in ADMIN_IDS:
                try:
                    await application.bot.send_message(chat_id=admin_id, text=error_msg)
                except:
                    pass
            return
        
        backup_json = json.dumps(backup_data, ensure_ascii=False, indent=2)
        
        total_configs = backup_data['config_pool']['total']
        
        volumes = {}
        for item in backup_data['config_pool']['items']:
            vol = item['volume']
            sub_type = item.get('subscription_type', 'economy')
            type_name = "اکونومی" if sub_type == "economy" else "سوپر فست"
            key = f"{vol}_{sub_type}"
            if key not in volumes:
                volumes[key] = {"count": 0, "volume": vol, "type_name": type_name}
            volumes[key]["count"] += 1
        
        volume_text = "\n".join([f"🔹 {persian_number(v['volume'])} گیگ {v['type_name']}: {persian_number(v['count'])} عدد" for v in volumes.values()])
        
        temp_file = f"/tmp/config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(temp_file, 'w', encoding='utf-8') as f:
            f.write(backup_json)
        
        for admin_id in ADMIN_IDS:
            try:
                with open(temp_file, 'rb') as f:
                    await application.bot.send_document(
                        chat_id=admin_id,
                        document=f,
                        caption=f"📦 *بکاپ خودکار استخر کانفیگ‌ها*\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"📅 تاریخ: `{tehran_now.strftime('%Y-%m-%d %H:%M:%S')}`\n"
                                f"📊 کانفیگ‌های موجود: {persian_number(total_configs)} عدد\n"
                                f"{volume_text}\n"
                                f"━━━━━━━━━━━━━━━━━━━━\n"
                                f"✅ بکاپ خودکار شبانه",
                        parse_mode="Markdown"
                    )
                logging.info(f"بکاپ روزانه به ادمین {admin_id} ارسال شد")
            except Exception as e:
                logging.error(f"خطا در ارسال بکاپ به ادمین {admin_id}: {e}")
        
        os.remove(temp_file)
        logging.info(f"✅ بکاپ روزانه با موفقیت انجام شد - {persian_number(total_configs)} کانفیگ")
        
    except Exception as e:
        error_msg = f"❌ خطا در بکاپ روزانه:\n{str(e)}"
        logging.error(error_msg)
        for admin_id in ADMIN_IDS:
            try:
                await application.bot.send_message(chat_id=admin_id, text=error_msg)
            except:
                pass

async def start_backup_scheduler():
    scheduler.add_job(
        create_and_send_backup,
        trigger=CronTrigger(hour=23, minute=59),
        id="daily_backup",
        name="بکاپ روزانه",
        replace_existing=True
    )
    scheduler.start()
    logging.info("✅ Scheduler بکاپ راه‌اندازی شد - هر شب ساعت ۲۳:۵۹ بکاپ گرفته می‌شود")

async def backup_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context, None):
        return
    
    await update.message.reply_text("📦 در حال تهیه بکاپ از استخر کانفیگ‌ها...")
    
    backup_data = await backup_config_pool_only()
    
    if not backup_data:
        await update.message.reply_text("❌ خطا در تهیه بکاپ!")
        return
    
    backup_json = json.dumps(backup_data, ensure_ascii=False, indent=2)
    
    total_configs = backup_data['config_pool']['total']
    
    volumes = {}
    for item in backup_data['config_pool']['items']:
        vol = item['volume']
        sub_type = item.get('subscription_type', 'economy')
        type_name = "اکونومی" if sub_type == "economy" else "سوپر فست"
        key = f"{vol}_{sub_type}"
        if key not in volumes:
            volumes[key] = {"count": 0, "volume": vol, "type_name": type_name}
        volumes[key]["count"] += 1
    
    volume_text = "\n".join([f"🔹 {persian_number(v['volume'])} گیگ {v['type_name']}: {persian_number(v['count'])} عدد" for v in volumes.values()])
    
    if len(backup_json) > 4000:
        file_io = io.BytesIO(backup_json.encode('utf-8'))
        file_io.name = f"config_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        
        await context.bot.send_document(
            chat_id=update.effective_user.id,
            document=file_io,
            caption=f"📦 بکاپ استخر کانفیگ‌ها\n"
                    f"📅 تاریخ: {datetime.now().strftime('%Y/%m/%d %H:%M:%S')}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"📊 کانفیگ‌های موجود: {persian_number(total_configs)} عدد\n"
                    f"{volume_text}\n"
                    f"━━━━━━━━━━━━━━━━━━━━\n"
                    f"⚠️ این فایل فقط کانفیگ‌های فروخته نشده را شامل می‌شود."
        )
    else:
        await update.message.reply_text(
            f"📦 **بکاپ استخر کانفیگ‌ها** 📦\n━━━━━━━━━━━━━━━━━━━━\n"
            f"📊 کانفیگ‌های موجود: {persian_number(total_configs)} عدد\n"
            f"{volume_text}\n━━━━━━━━━━━━━━━━━━━━\n"
            f"```json\n{backup_json[:3500]}\n```",
            parse_mode="Markdown"
        )
    
    await update.message.reply_text("✅ بکاپ با موفقیت تهیه شد!")

# ---------- توابع مدیریت کانفیگ و غیره ----------
async def send_multiple_configs_to_user(subscription_id: int, user_id: int, volume: int, quantity: int, plan: str, bot, subscription_type: str = "economy") -> bool:
    existing_config = await db_execute(
        "SELECT config FROM subscriptions WHERE id = %s AND config IS NOT NULL AND status = 'active'",
        (subscription_id,), fetchone=True
    )
    if existing_config and existing_config[0]:
        logging.info(f"Subscription {subscription_id} already has config, skipping duplicate send")
        return True
    
    configs = await get_available_configs(volume, quantity, subscription_type)
    
    if configs and len(configs) == quantity:
        configs_text = "\n\n".join([cfg['config_text'] for cfg in configs])
        config_ids = [cfg['id'] for cfg in configs]
        
        await update_subscription_config(subscription_id, configs_text)
        await mark_configs_as_sold(config_ids, user_id)
        
        type_name = "اکونومی ⭐️" if subscription_type == "economy" else "سوپر فست 💎"
        message = f"✅ اشتراک {type_name} {plan} شما فعال شد!\n\n"
        message += f"📦 تعداد: {persian_number(quantity)} عدد کانفیگ {persian_number(volume)} گیگی\n\n"
        message += f"🔐 کانفیگ‌های شما:\n```\n{configs_text}\n```"
        
        await bot.send_message(user_id, message, parse_mode="Markdown")
        
        for admin_id in ADMIN_IDS:
            try:
                if user_id not in ADMIN_IDS:
                    await bot.send_message(
                        admin_id,
                        f"✅ {persian_number(quantity)} عدد کانفیگ {persian_number(volume)} گیگ {type_name} برای کاربر {user_id} ارسال شد."
                    )
            except:
                pass
        return True
    else:
        available_count = await get_available_configs_count(volume, subscription_type)
        type_name = "اکونومی" if subscription_type == "economy" else "سوپر فست"
        if user_id not in ADMIN_IDS:
            for admin_id in ADMIN_IDS:
                try:
                    await bot.send_message(
                        admin_id,
                        f"⚠️ کاربر {user_id} درخواست {persian_number(quantity)} عدد کانفیگ {persian_number(volume)} گیگ {type_name} دارد اما فقط {persian_number(available_count)} عدد موجود است!"
                    )
                except:
                    pass
        return False

# ---------- وظیفه دوره‌ای ----------
async def periodic_pending_check(bot):
    processed_in_cycle = set()
    
    while True:
        try:
            await asyncio.sleep(30)
            if await get_bot_status():
                pending_subs = await get_pending_subscriptions()
                for sub in pending_subs:
                    sub_id = sub['subscription_id']
                    if sub_id in processed_in_cycle:
                        continue
                    processed_in_cycle.add(sub_id)
                    await send_multiple_configs_to_user(
                        sub['subscription_id'], 
                        sub['user_id'], 
                        sub['volume'], 
                        sub['quantity'], 
                        sub['plan'], 
                        bot,
                        sub['subscription_type']
                    )
            
            processed_in_cycle.clear()
            
        except Exception as e:
            logging.error(f"Error in periodic check: {e}")

# ---------- دستورات ادمین ----------
async def set_bot_commands():
    try:
        public_commands = [BotCommand(command="/start", description="شروع ربات")]
        await application.bot.set_my_commands(public_commands)
        
        admin_commands = [
            BotCommand(command="/start", description="شروع ربات"),
            BotCommand(command="/stats", description="آمار ربات"),
            BotCommand(command="/user_info", description="اطلاعات کاربران"),
            BotCommand(command="/coupon", description="ساخت کد تخفیف"),
            BotCommand(command="/notification", description="ارسال پیام همگانی"),
            BotCommand(command="/add_config", description="مدیریت کانفیگ‌ها"),
            BotCommand(command="/backup", description="تهیه پشتیبان از کانفیگ‌ها"),
            BotCommand(command="/restore", description="بازیابی پشتیبان"),
            BotCommand(command="/remove_user", description="حذف و بن کاربر"),
            BotCommand(command="/unban_user", description="رفع بن کاربر"),
            BotCommand(command="/cleardb", description="پاکسازی دیتابیس"),
            BotCommand(command="/debug_subscriptions", description="بررسی اشتراک‌ها"),
            BotCommand(command="/shutdown", description="خاموش کردن ربات"),
            BotCommand(command="/startup", description="روشن کردن ربات"),
            BotCommand(command="/set_agent", description="مدیریت نمایندگان"),
            BotCommand(command="/admin", description="مدیریت ادمین‌ها"),
            BotCommand(command="/bank", description="مدیریت کارت بانکی"),
            BotCommand(command="/search", description="جستجوی کاربر")
        ]
        
        for admin_id in ADMIN_IDS:
            try:
                await application.bot.set_my_commands(admin_commands, scope={"type": "chat", "chat_id": admin_id})
                logging.info(f"Admin commands set for admin {admin_id}")
            except Exception as e:
                logging.error(f"Could not set admin commands for {admin_id}: {e}")
    except Exception as e:
        logging.error(f"Error setting bot commands: {e}")

async def admin_only(update, context, next_handler):
    user_id = update.effective_user.id
    if not is_admin(user_id):
        if update.message:
            await update.message.reply_text("⛔ شما دسترسی به این دستور ندارید.")
        elif update.callback_query:
            await update.callback_query.answer("⛔ شما دسترسی به این بخش ندارید.", show_alert=True)
        return False
    return True

async def stats_command(update, context):
    if not await admin_only(update, context, None):
        return
    total_users = await db_execute("SELECT COUNT(*) FROM users", fetchone=True)
    agents = await db_execute("SELECT COUNT(*) FROM users WHERE is_agent = TRUE", fetchone=True)
    total_income = await get_total_income()
    total_configs_sold = await get_total_configs_sold()
    config_stats = await get_config_pool_stats()
    banned = await db_execute("SELECT COUNT(*) FROM banned_users", fetchone=True)
    
    eco_available = sum([s['available'] for s in config_stats['by_volume'] if s['subscription_type'] == 'economy'])
    super_available = sum([s['available'] for s in config_stats['by_volume'] if s['subscription_type'] == 'superfast'])
    
    await update.message.reply_text(
        f"📊 آمار ربات OnePercentVPN12 📊\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"👥 کل کاربران: {persian_number(total_users[0]) if total_users else '۰'} نفر\n"
        f"👑 نمایندگان: {persian_number(agents[0]) if agents else '۰'} نفر\n"
        f"🚫 کاربران بن شده: {persian_number(banned[0]) if banned else '۰'} نفر\n"
        f"💰 مجموع درآمد: {format_price(total_income)}\n"
        f"📦 کانفیگ‌های فروخته شده: {persian_number(total_configs_sold)} عدد\n"
        f"📤 کانفیگ‌های موجود اکونومی: {persian_number(eco_available)} عدد\n"
        f"📤 کانفیگ‌های موجود سوپر فست: {persian_number(super_available)} عدد\n"
        f"🟢 وضعیت ربات: {'روشن' if await get_bot_status() else 'خاموش'}\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )

async def user_info_command(update, context):
    if not await admin_only(update, context, None):
        return
    users = await db_execute("SELECT user_id, username, is_agent, balance, created_at FROM users ORDER BY created_at DESC", fetch=True)
    if not users:
        await update.message.reply_text("📂 کاربری یافت نشد.")
        return
    
    response = "👥 📊 لیست کامل کاربران 📊 👥\n━━━━━━━━━━━━━━━━━━━━\n"
    count = 0
    for u in users:
        uid, uname, agent, balance, created_at = u
        agent_mark = "👑 نماینده" if agent else "👤 معمولی"
        response += f"🆔 {uid} | @{uname if uname else 'نامشخص'}\n"
        response += f"💰 موجودی: {format_price(balance)}\n"
        response += f"📊 وضعیت: {agent_mark}\n"
        response += f"📅 تاریخ: {created_at.strftime('%Y/%m/%d') if created_at else 'نامشخص'}\n"
        response += "━━━━━━━━━━━━━━━━━━━━\n"
        count += 1
        if len(response) > 3500 or count % 20 == 0:
            await send_long_message(update.effective_user.id, response, context)
            response = "━━━━━━━━━━━━━━━━━━━━\n"
    
    if response and response != "━━━━━━━━━━━━━━━━━━━━\n":
        await send_long_message(update.effective_user.id, response, context)

async def remove_user_command(update, context):
    if not await admin_only(update, context, None):
        return
    await update.message.reply_text(
        "🚫 **حذف و بن کاربر** 🚫\n━━━━━━━━━━━━━━━━━━━━\n"
        "🆔 آیدی عددی کاربر مورد نظر برای بن کردن را وارد کنید:\n\n"
        "⚠️ توجه: کاربر بن شده دیگر نمی‌تواند از ربات استفاده کند.",
        reply_markup=get_back_keyboard()
    )
    user_states[update.effective_user.id] = "awaiting_ban_user_id"

async def unban_user_command(update, context):
    if not await admin_only(update, context, None):
        return
    
    await update.message.reply_text(
        "🔓 **رفع بن کاربر** 🔓\n━━━━━━━━━━━━━━━━━━━━\n"
        "🆔 آیدی عددی کاربر مورد نظر برای رفع بن را وارد کنید:\n\n"
        "⚠️ توجه: پس از رفع بن، کاربر می‌تواند دوباره از ربات استفاده کند.",
        reply_markup=get_back_keyboard()
    )
    user_states[update.effective_user.id] = "awaiting_unban_user_id"

async def handle_remove_user(update, context, user_id, text):
    try:
        target_id = int(text.strip())
        
        user_data = await db_execute("SELECT user_id, username FROM users WHERE user_id = %s", (target_id,), fetchone=True)
        if not user_data:
            await update.message.reply_text(f"❌ کاربر با آیدی {target_id} در دیتابیس یافت نشد.", reply_markup=get_admin_main_keyboard())
            user_states.pop(user_id, None)
            return
        
        success = await ban_user_from_bot(target_id)
        if success:
            await update.message.reply_text(
                f"✅ کاربر با آیدی {target_id} با موفقیت بن شد.\n\n"
                f"👤 یوزرنیم: @{user_data[1] if user_data[1] else 'ندارد'}\n"
                f"🚫 این کاربر دیگر نمی‌تواند از ربات استفاده کند.",
                reply_markup=get_admin_main_keyboard()
            )
            try:
                await context.bot.send_message(
                    target_id,
                    "🚫 شما توسط ادمین از ربات OnePercentVPN12 بن شده‌اید و دیگر نمی‌توانید از خدمات استفاده کنید."
                )
            except:
                pass
        else:
            await update.message.reply_text("❌ خطا در بن کردن کاربر.", reply_markup=get_admin_main_keyboard())
    except ValueError:
        await update.message.reply_text("⚠️ آیدی نامعتبر. لطفاً یک عدد وارد کنید.", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def handle_unban_user(update, context, user_id, text):
    try:
        target_id = int(text.strip())
        
        is_banned = await is_user_banned(target_id)
        
        if not is_banned:
            await update.message.reply_text(
                f"ℹ️ کاربر با آیدی {target_id} در لیست بن شده‌ها وجود ندارد.\n\n"
                f"این کاربر قبلاً رفع بن شده است یا هرگز بن نبوده است.",
                reply_markup=get_admin_main_keyboard()
            )
            user_states.pop(user_id, None)
            return
        
        success = await unban_user_from_bot(target_id)
        
        if success:
            await update.message.reply_text(
                f"✅ کاربر با آیدی {target_id} با موفقیت رفع بن شد.\n\n"
                f"🔓 این کاربر مجدداً می‌تواند از ربات استفاده کند.",
                reply_markup=get_admin_main_keyboard()
            )
            try:
                await context.bot.send_message(
                    target_id,
                    "✅ بن شما توسط ادمین رفع شد.\n\n"
                    "🎉 می‌توانید مجدداً از ربات OnePercentVPN12 استفاده کنید.\n"
                    "لطفاً با دستور /start مجدداً شروع کنید."
                )
            except Exception as e:
                logging.error(f"Could not send unban message to user {target_id}: {e}")
        else:
            await update.message.reply_text("❌ خطا در رفع بن کاربر.", reply_markup=get_admin_main_keyboard())
            
    except ValueError:
        await update.message.reply_text("⚠️ آیدی نامعتبر. لطفاً یک عدد وارد کنید.", reply_markup=get_admin_main_keyboard())
    
    user_states.pop(user_id, None)

async def notification_command(update, context):
    if not await admin_only(update, context, None):
        return
    await update.message.reply_text(
        "📢 **ارسال پیام همگانی** 📢\n━━━━━━━━━━━━━━━━━━━━\n"
        "لطفاً نوع ارسال را انتخاب کنید:",
        reply_markup=get_notification_keyboard(),
        parse_mode="Markdown"
    )
    user_states[update.effective_user.id] = "awaiting_notification_type"

async def handle_notification_type(update, context, user_id, text):
    if text == "📢 ارسال به همه کاربران":
        user_states[user_id] = "awaiting_notification_text_all"
        await update.message.reply_text(
            "📢 متن پیام خود را ارسال کنید:\n\n"
            "⚠️ توجه: پیام برای **همه کاربران** ارسال خواهد شد.",
            reply_markup=get_back_keyboard()
        )
    elif text == "👑 ارسال به نمایندگان":
        user_states[user_id] = "awaiting_notification_text_agents"
        await update.message.reply_text(
            "📢 متن پیام خود را ارسال کنید:\n\n"
            "⚠️ توجه: پیام برای **نمایندگان** ارسال خواهد شد.",
            reply_markup=get_back_keyboard()
        )
    elif text == "👤 ارسال به یک نفر":
        user_states[user_id] = "awaiting_notification_target_user"
        await update.message.reply_text(
            "🆔 آیدی عددی کاربر را وارد کنید:",
            reply_markup=get_back_keyboard()
        )
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)
    else:
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_notification_keyboard())

async def handle_notification_target_user(update, context, user_id, text):
    try:
        target_id = int(text.strip())
        user_data = await db_execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,), fetchone=True)
        if not user_data:
            await update.message.reply_text(f"❌ کاربر با آیدی {target_id} یافت نشد.", reply_markup=get_notification_keyboard())
            user_states.pop(user_id, None)
            return
        user_states[user_id] = f"awaiting_notification_text_single_{target_id}"
        await update.message.reply_text("📢 متن پیام خود را ارسال کنید:", reply_markup=get_back_keyboard())
    except ValueError:
        await update.message.reply_text("⚠️ آیدی نامعتبر. لطفاً یک عدد وارد کنید.", reply_markup=get_notification_keyboard())
        user_states.pop(user_id, None)

async def handle_notification_text(update, context, user_id, state, text):
    try:
        if state == "awaiting_notification_text_all":
            users = await get_all_users()
            user_type = "همه کاربران"
            user_count = len(users)
        elif state == "awaiting_notification_text_agents":
            users = await get_all_agents()
            user_type = "نمایندگان"
            user_count = len(users)
        elif state.startswith("awaiting_notification_text_single_"):
            target_id = int(state.split("_")[-1])
            users = [(target_id,)]
            user_type = f"کاربر {target_id}"
            user_count = 1
        else:
            await update.message.reply_text("⚠️ خطا در پردازش درخواست.", reply_markup=get_admin_main_keyboard())
            user_states.pop(user_id, None)
            return
        
        if user_count == 0:
            await update.message.reply_text(f"⚠️ هیچ {user_type}ی برای ارسال پیام وجود ندارد.", reply_markup=get_admin_main_keyboard())
            user_states.pop(user_id, None)
            return
        
        await update.message.reply_text(f"📢 در حال ارسال پیام به {persian_number(user_count)} {user_type}...", reply_markup=get_admin_main_keyboard())
        
        sent, failed = await send_notification_to_users(context, users, text)
        
        await update.message.reply_text(
            f"✅ نتیجه ارسال پیام:\n"
            f"━━━━━━━━━━━━━━━━━━━━\n"
            f"📨 ارسال شده: {persian_number(sent)}\n"
            f"❌ ناموفق: {persian_number(failed)}\n"
            f"👥 مخاطبان: {user_type}\n"
            f"━━━━━━━━━━━━━━━━━━━━",
            reply_markup=get_admin_main_keyboard()
        )
    except Exception as e:
        logging.error(f"Error in handle_notification_text: {e}")
        await update.message.reply_text("⚠️ خطا در ارسال پیام.", reply_markup=get_admin_main_keyboard())
    finally:
        user_states.pop(user_id, None)

async def debug_subscriptions_command(update, context):
    if not await admin_only(update, context, None):
        return
    pending = await get_pending_subscriptions()
    balance_pending = await get_pending_balance_payments()
    agent_pending = await get_pending_agent_payments()
    
    response = f"🐛 دیباگ اشتراک‌ها 🐛\n━━━━━━━━━━━━━━━━━━━━\n"
    response += f"📊 اشتراک‌های در انتظار: {persian_number(len(pending))}\n"
    response += f"💰 افزایش موجودی در انتظار: {persian_number(len(balance_pending))}\n"
    response += f"👑 ثبت‌نام نمایندگی در انتظار: {persian_number(len(agent_pending))}\n"
    response += "━━━━━━━━━━━━━━━━━━━━\n\n"
    
    if pending:
        response += "📋 لیست اشتراک‌های در انتظار:\n"
        for p in pending:
            type_name = "اکونومی" if p['subscription_type'] == "economy" else "سوپر فست"
            response += f"🆔 {p['subscription_id']} | کاربر {p['user_id']} | {type_name} | {p['volume']} گیگ x {p['quantity']}\n"
    else:
        response += "✅ هیچ اشتراک در انتظاری وجود ندارد."
    
    await send_long_message(update.effective_user.id, response, context)

async def set_agent_command(update, context):
    if not await admin_only(update, context, None):
        return
    await update.message.reply_text(
        "👑 مدیریت نمایندگان 👑\n━━━━━━━━━━━━━━━━━━━━\n"
        "🆔 آیدی عددی کاربر را وارد کنید:",
        reply_markup=get_back_keyboard()
    )
    user_states[update.effective_user.id] = "awaiting_set_agent_user_id"

async def handle_set_agent(update, context, user_id, text):
    try:
        target_id = int(text.strip())
        user_data = await db_execute("SELECT user_id, is_agent FROM users WHERE user_id = %s", (target_id,), fetchone=True)
        if not user_data:
            await update.message.reply_text(f"❌ کاربر با آیدی {target_id} یافت نشد.", reply_markup=get_admin_main_keyboard())
            user_states.pop(user_id, None)
            return
        
        is_agent = user_data[1]
        if is_agent:
            await unset_user_agent(target_id)
            await update.message.reply_text(f"✅ نمایندگی کاربر {target_id} لغو شد.", reply_markup=get_admin_main_keyboard())
        else:
            await set_user_agent(target_id)
            await update.message.reply_text(f"✅ کاربر {target_id} به نماینده ارتقا یافت.", reply_markup=get_admin_main_keyboard())
    except ValueError:
        await update.message.reply_text("⚠️ آیدی نامعتبر. لطفاً یک عدد وارد کنید.", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def search_user_command(update, context):
    if not await admin_only(update, context, None):
        return
    
    keyboard = [
        [KeyboardButton("🔢 دریافت با آیدی عددی")],
        [KeyboardButton("👤 دریافت با یوزرنیم")],
        [KeyboardButton("↩️ بازگشت به منو")]
    ]
    await update.message.reply_text(
        "🔍 جستجوی کاربر\n\nلطفاً روش جستجو را انتخاب کنید:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    user_states[update.effective_user.id] = "awaiting_search_method"

async def handle_search_method(update, context, user_id, text):
    if text == "🔢 دریافت با آیدی عددی":
        await update.message.reply_text("🆔 آیدی عددی کاربر را وارد کنید:", reply_markup=get_back_keyboard())
        user_states[user_id] = "awaiting_search_by_id"
    elif text == "👤 دریافت با یوزرنیم":
        await update.message.reply_text("👤 یوزرنیم کاربر را وارد کنید (بدون @):", reply_markup=get_back_keyboard())
        user_states[user_id] = "awaiting_search_by_username"
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)
    else:
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=ReplyKeyboardMarkup([
            [KeyboardButton("🔢 دریافت با آیدی عددی")],
            [KeyboardButton("👤 دریافت با یوزرنیم")],
            [KeyboardButton("↩️ بازگشت به منو")]
        ], resize_keyboard=True))

async def handle_search_by_id(update, context, user_id, text):
    try:
        target_id = int(text.strip())
        user_data = await db_execute(
            "SELECT user_id, username, is_agent, balance, created_at, invited_by FROM users WHERE user_id = %s",
            (target_id,), fetchone=True
        )
        if not user_data:
            await update.message.reply_text(f"❌ کاربر با آیدی {target_id} یافت نشد.", reply_markup=get_admin_main_keyboard())
        else:
            uid, uname, agent, balance, created_at, invited_by = user_data
            agent_mark = "👑 نماینده" if agent else "👤 معمولی"
            response = f"🔍 اطلاعات کاربر 🔍\n━━━━━━━━━━━━━━━━━━━━\n"
            response += f"🆔 آیدی عددی: {uid}\n"
            response += f"👤 یوزرنیم: @{uname if uname else 'ندارد'}\n"
            response += f"📊 وضعیت: {agent_mark}\n"
            response += f"💰 موجودی: {format_price(balance)}\n"
            response += f"📅 تاریخ عضویت: {created_at.strftime('%Y/%m/%d - %H:%M') if created_at else 'نامشخص'}\n"
            if invited_by:
                response += f"🔗 دعوت شده توسط: {invited_by}\n"
            response += "━━━━━━━━━━━━━━━━━━━━"
            await update.message.reply_text(response, reply_markup=get_admin_main_keyboard())
    except ValueError:
        await update.message.reply_text("⚠️ آیدی نامعتبر. لطفاً یک عدد وارد کنید.", reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def handle_search_by_username(update, context, user_id, text):
    username = text.strip().replace("@", "")
    user_data = await db_execute(
        "SELECT user_id, username, is_agent, balance, created_at, invited_by FROM users WHERE username ILIKE %s",
        (f"%{username}%",), fetchone=True
    )
    if not user_data:
        await update.message.reply_text(f"❌ کاربر با یوزرنیم {username} یافت نشد.", reply_markup=get_admin_main_keyboard())
    else:
        uid, uname, agent, balance, created_at, invited_by = user_data
        agent_mark = "👑 نماینده" if agent else "👤 معمولی"
        response = f"🔍 اطلاعات کاربر 🔍\n━━━━━━━━━━━━━━━━━━━━\n"
        response += f"🆔 آیدی عددی: {uid}\n"
        response += f"👤 یوزرنیم: @{uname if uname else 'ندارد'}\n"
        response += f"📊 وضعیت: {agent_mark}\n"
        response += f"💰 موجودی: {format_price(balance)}\n"
        response += f"📅 تاریخ عضویت: {created_at.strftime('%Y/%m/%d - %H:%M') if created_at else 'نامشخص'}\n"
        if invited_by:
            response += f"🔗 دعوت شده توسط: {invited_by}\n"
        response += "━━━━━━━━━━━━━━━━━━━━"
        await update.message.reply_text(response, reply_markup=get_admin_main_keyboard())
    user_states.pop(user_id, None)

async def coupon_command(update, context):
    if not await admin_only(update, context, None):
        return
    await update.message.reply_text("💵 درصد تخفیف را وارد نمایید (مثال: ۲۰):")
    user_states[update.effective_user.id] = "awaiting_coupon_discount"

async def add_config_command(update, context):
    if not await admin_only(update, context, None):
        return
    await update.message.reply_text("⚙️ پنل مدیریت کانفیگ‌ها:", reply_markup=get_admin_config_keyboard())
    user_states[update.effective_user.id] = "awaiting_admin_config_action"

async def shutdown_command(update, context):
    if not await admin_only(update, context, None):
        return
    if not await get_bot_status():
        await update.message.reply_text("🔴 ربات در حال حاضر خاموش است.")
        return
    await set_bot_status(False)
    await update.message.reply_text("🔴 ربات برای کاربران عادی خاموش شد.")

async def startup_command(update, context):
    if not await admin_only(update, context, None):
        return
    if await get_bot_status():
        await update.message.reply_text("🟢 ربات در حال حاضر روشن است.")
        return
    await set_bot_status(True)
    await update.message.reply_text("🟢 ربات برای کاربران عادی روشن شد.")

async def admin_management_command(update, context):
    if not await admin_only(update, context, None):
        return
    await update.message.reply_text("⚙️ پنل مدیریت ادمین‌ها:", reply_markup=get_admin_management_keyboard())
    user_states[update.effective_user.id] = "awaiting_admin_management_action"

async def bank_management_command(update, context):
    if not await admin_only(update, context, None):
        return
    await update.message.reply_text("💳 پنل مدیریت کارت بانکی:", reply_markup=get_bank_management_keyboard())
    user_states[update.effective_user.id] = "awaiting_bank_management_action"

async def handle_admin_management(update, context, user_id, text):
    if text == "➕ اضافه کردن ادمین جدید":
        await update.message.reply_text("🆔 آیدی عددی کاربر جدید را وارد کنید:")
        user_states[user_id] = "awaiting_new_admin_id"
    elif text == "➖ حذف ادمین":
        admins_list = "\n".join([f"🆔 {aid}" for aid in ADMIN_IDS if aid not in [6056483071, 7241184581]])
        if not admins_list:
            await update.message.reply_text("📂 هیچ ادمین قابل حذفی وجود ندارد.", reply_markup=get_admin_management_keyboard())
            return
        await update.message.reply_text(f"🆔 آیدی ادمین مورد نظر برای حذف را وارد کنید:\n\n{admins_list}")
        user_states[user_id] = "awaiting_remove_admin_id"
    elif text == "📋 لیست ادمین‌ها":
        admins_list = "\n".join([f"🆔 {aid}" for aid in ADMIN_IDS])
        await update.message.reply_text(f"👥 لیست ادمین‌ها:\n\n{admins_list}\n\n🔒 ادمین‌های اولیه قابل حذف نیستند.", reply_markup=get_admin_management_keyboard())
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)
    else:
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_admin_management_keyboard())

async def handle_add_new_admin(update, context, user_id, text):
    try:
        new_admin_id = int(text)
        if new_admin_id in ADMIN_IDS:
            await update.message.reply_text("⚠️ این کاربر قبلاً ادمین است.", reply_markup=get_admin_management_keyboard())
        else:
            success = await add_admin(new_admin_id)
            if success:
                await update.message.reply_text(f"✅ کاربر {new_admin_id} با موفقیت به ادمین‌ها اضافه شد.", reply_markup=get_admin_management_keyboard())
                try:
                    await context.bot.send_message(
                        new_admin_id,
                        "🎉 شما به عنوان ادمین ربات OnePercentVPN12 اضافه شدید!\nاکنون به تمام دستورات مدیریتی دسترسی دارید."
                    )
                except:
                    pass
            else:
                await update.message.reply_text("❌ خطا در اضافه کردن ادمین.", reply_markup=get_admin_management_keyboard())
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک آیدی عددی معتبر وارد کنید.", reply_markup=get_admin_management_keyboard())
    user_states.pop(user_id, None)

async def handle_remove_admin(update, context, user_id, text):
    try:
        target_id = int(text)
        if target_id in [6056483071, 7241184581]:
            await update.message.reply_text("⚠️ حذف ادمین‌های اولیه امکان‌پذیر نیست.", reply_markup=get_admin_management_keyboard())
        elif target_id not in ADMIN_IDS:
            await update.message.reply_text("⚠️ این کاربر ادمین نیست.", reply_markup=get_admin_management_keyboard())
        else:
            success = await remove_admin(target_id)
            if success:
                await update.message.reply_text(f"✅ ادمین {target_id} با موفقیت حذف شد.", reply_markup=get_admin_management_keyboard())
            else:
                await update.message.reply_text("❌ خطا در حذف ادمین.", reply_markup=get_admin_management_keyboard())
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک آیدی عددی معتبر وارد کنید.", reply_markup=get_admin_management_keyboard())
    user_states.pop(user_id, None)

async def handle_bank_management(update, context, user_id, text):
    if text == "➕ اضافه کردن کارت جدید":
        await update.message.reply_text("💳 شماره کارت جدید را ارسال کنید:\n(۱۶ رقم)", reply_markup=get_back_keyboard())
        user_states[user_id] = "awaiting_new_card_number"
    elif text == "💳 کارت‌های ذخیره شده":
        cards = await get_all_bank_cards()
        if not cards:
            await update.message.reply_text("📂 هیچ کارتی ذخیره نشده است.", reply_markup=get_bank_management_keyboard())
            return
        response = "💳 لیست کارت‌های ذخیره شده:\n\n"
        for card in cards:
            active_mark = "⭐️ کارت اصلی ⭐️\n" if card['card_number'] == BANK_CARD else ""
            response += f"{active_mark}🆔 {card['id']}\n🏦 شماره کارت: {card['card_number']}\n👤 دارنده: {card['owner_name']}\n────────────────\n"
        await send_long_message(user_id, response, context, reply_markup=get_bank_management_keyboard())
    elif text == "🔄 تغییر کارت اصلی":
        cards = await get_all_bank_cards()
        if not cards:
            await update.message.reply_text("📂 هیچ کارتی برای تنظیم به عنوان کارت اصلی وجود ندارد.\nلطفاً ابتدا کارت اضافه کنید.", reply_markup=get_bank_management_keyboard())
            return
        response = "💳 کارت‌های موجود برای تنظیم به عنوان کارت اصلی:\n\n"
        for card in cards:
            response += f"🆔 {card['id']} | {card['card_number']} | {card['owner_name']}\n"
        response += "\n🆔 آیدی کارت مورد نظر را وارد کنید:"
        await update.message.reply_text(response, reply_markup=get_back_keyboard())
        user_states[user_id] = "awaiting_set_active_card"
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)
    else:
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_bank_management_keyboard())

async def handle_new_card_number(update, context, user_id, text):
    card_number = text.strip().replace(" ", "")
    if not card_number.isdigit() or len(card_number) != 16:
        await update.message.reply_text("⚠️ شماره کارت نامعتبر است. لطفاً یک شماره ۱۶ رقمی ارسال کنید:", reply_markup=get_back_keyboard())
        return
    user_states[user_id] = f"awaiting_card_owner_{card_number}"
    await update.message.reply_text("👤 لطفاً نام دارنده حساب را وارد کنید:", reply_markup=get_back_keyboard())

async def handle_card_owner(update, context, user_id, state, text):
    card_number = state.split("_")[3]
    owner_name = text.strip()
    
    if not owner_name:
        await update.message.reply_text("⚠️ لطفاً نام معتبری وارد کنید:", reply_markup=get_back_keyboard())
        return
    
    user_states[user_id] = f"awaiting_card_confirm_{card_number}_{owner_name}"
    
    kb = ReplyKeyboardMarkup([[KeyboardButton("✅ بله، تایید")], [KeyboardButton("❌ انصراف")]], resize_keyboard=True)
    await update.message.reply_text(
        f"📋 اطلاعات کارت جدید:\n\n"
        f"🏦 شماره کارت: {card_number}\n"
        f"👤 نام دارنده: {owner_name}\n\n"
        f"⚠️ آیا از ذخیره این کارت اطمینان دارید؟",
        reply_markup=kb
    )

async def handle_card_confirm(update, context, user_id, state, text):
    if text == "✅ بله، تایید":
        parts = state.split("_")
        card_number = parts[3]
        owner_name = parts[4]
        
        success = await add_bank_card(card_number, owner_name)
        if success:
            await update.message.reply_text("✅ کارت جدید با موفقیت ذخیره شد.", reply_markup=get_bank_management_keyboard())
        else:
            await update.message.reply_text("❌ خطا در ذخیره کارت.", reply_markup=get_bank_management_keyboard())
    else:
        await update.message.reply_text("❌ عملیات ذخیره کارت لغو شد.", reply_markup=get_bank_management_keyboard())
    
    user_states.pop(user_id, None)

async def handle_set_active_card(update, context, user_id, text):
    try:
        card_id = int(text)
        cards = await get_all_bank_cards()
        card_exists = any(card['id'] == card_id for card in cards)
        
        if not card_exists:
            await update.message.reply_text("⚠️ کارت مورد نظر یافت نشد.", reply_markup=get_bank_management_keyboard())
            user_states.pop(user_id, None)
            return
        
        success = await set_active_card(card_id)
        if success:
            await update.message.reply_text(
                f"✅ کارت اصلی با موفقیت تغییر کرد.\n\n"
                f"🏦 شماره کارت جدید: {BANK_CARD}\n"
                f"👤 نام دارنده: {BANK_OWNER}",
                reply_markup=get_bank_management_keyboard()
            )
        else:
            await update.message.reply_text("❌ خطا در تغییر کارت اصلی.", reply_markup=get_bank_management_keyboard())
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک آیدی عددی معتبر وارد کنید.", reply_markup=get_bank_management_keyboard())
    
    user_states.pop(user_id, None)

async def handle_admin_config_action(update, context, user_id, text):
    if text == "➕ اضافه کردن کانفیگ اکونومی":
        await update.message.reply_text("📊 حجم کانفیگ اکونومی را انتخاب کنید:", reply_markup=get_volume_selection_keyboard())
        user_states[user_id] = "awaiting_config_volume_selection_economy"
    elif text == "➕ اضافه کردن کانفیگ سوپر فست":
        await update.message.reply_text("📊 حجم کانفیگ سوپر فست را انتخاب کنید:", reply_markup=get_volume_selection_keyboard())
        user_states[user_id] = "awaiting_config_volume_selection_superfast"
    elif text == "📊 مشاهده موجودی کانفیگ‌ها":
        stats = await get_config_pool_stats()
        response = f"📊 آمار استخر کانفیگ‌ها\n\n"
        response += f"📦 مجموع کانفیگ‌ها: {persian_number(stats['total'])}\n"
        response += f"✅ فروخته شده: {persian_number(stats['sold'])}\n"
        response += f"📤 موجود: {persian_number(stats['available'])}\n\n"
        response += f"📈 موجودی به تفکیک حجم و نوع:\n"
        for vol_stat in stats['by_volume']:
            response += f"🔹 {persian_number(vol_stat['volume'])} گیگ {vol_stat['type_name']}: {persian_number(vol_stat['available'])} عدد موجود / {persian_number(vol_stat['sold'])} عدد فروخته شده\n"
        await send_long_message(user_id, response, context)
        await update.message.reply_text("⚙️ پنل مدیریت کانفیگ‌ها:", reply_markup=get_admin_config_keyboard())
    elif text == "📋 لیست تمام کانفیگ‌ها":
        configs = await get_all_configs()
        if not configs:
            await update.message.reply_text("📂 هیچ کانفیگی در استخر وجود ندارد.", reply_markup=get_admin_config_keyboard())
            return
        response = f"📋 لیست تمام کانفیگ‌ها (مجموع: {persian_number(len(configs))})\n\n"
        for cfg in configs:
            status = "✅ فروخته شده" if cfg['is_sold'] else "📤 موجود"
            sold_to = f" به کاربر {cfg['sold_to_user']}" if cfg['sold_to_user'] else ""
            response += f"🆔 {cfg['id']} | {persian_number(cfg['volume'])} گیگ {cfg['type_name']} | {status}{sold_to}\n"
            response += f"🔐 کانفیگ: {cfg['config_text'][:50]}...\n"
            response += "────────────────\n"
            if len(response) > 3500:
                await send_long_message(user_id, response, context)
                response = ""
        if response:
            await send_long_message(user_id, response, context)
        await update.message.reply_text("⚙️ پنل مدیریت کانفیگ‌ها:", reply_markup=get_admin_config_keyboard())
    elif text == "↩️ بازگشت به منو":
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)
    else:
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_admin_config_keyboard())

async def handle_config_volume_selection(update, context, user_id, state, text):
    volume_map = {}
    for i in range(1, 11):
        volume_map[f"{persian_number(i)} گیگ"] = i
    
    if text in volume_map:
        volume = volume_map[text]
        if "economy" in state:
            subscription_type = "economy"
            type_name = "اکونومی"
        else:
            subscription_type = "superfast"
            type_name = "سوپر فست"
        user_states[user_id] = f"awaiting_config_text_{volume}_{subscription_type}"
        await update.message.reply_text(f"🔐 لطفاً کانفیگ(های) {text} {type_name} را ارسال کنید.\n(هر کانفیگ در یک خط جداگانه)", reply_markup=get_back_keyboard())
    elif text == "↩️ انصراف":
        await update.message.reply_text("⚙️ پنل مدیریت کانفیگ‌ها:", reply_markup=get_admin_config_keyboard())
        user_states.pop(user_id, None)
    else:
        await update.message.reply_text("⚠️ لطفاً یکی از گزینه‌های حجم را انتخاب کنید.", reply_markup=get_volume_selection_keyboard())

async def handle_config_text(update, context, user_id, state, text):
    try:
        parts = state.split("_")
        volume = int(parts[3])
        subscription_type = parts[4]
        type_name = "اکونومی" if subscription_type == "economy" else "سوپر فست"
        
        config_text = update.message.text
        if not config_text:
            await update.message.reply_text("⚠️ لطفاً کانفیگ را به صورت متن ارسال کنید:", reply_markup=get_back_keyboard())
            return
        
        configs = parse_configs_from_text(config_text)
        if not configs:
            await update.message.reply_text("⚠️ هیچ کانفیگ معتبری یافت نشد.", reply_markup=get_back_keyboard())
            return
        
        success_count, fail_count = await add_multiple_configs_to_pool(volume, configs, user_id, subscription_type)
        
        if success_count > 0:
            await update.message.reply_text(
                f"✅ {persian_number(success_count)} کانفیگ {persian_number(volume)} گیگ {type_name} با موفقیت به استخر اضافه شد.\n"
                f"{'❌ ' + persian_number(fail_count) + ' کانفیگ ناموفق' if fail_count > 0 else ''}",
                reply_markup=get_admin_config_keyboard()
            )
        else:
            await update.message.reply_text("⚠️ خطا در ذخیره کانفیگ‌ها.", reply_markup=get_admin_config_keyboard())
        user_states.pop(user_id, None)
    except Exception as e:
        logging.error(f"Error in handle_config_text: {e}")
        await update.message.reply_text("⚠️ خطا در پردازش کانفیگ.", reply_markup=get_admin_config_keyboard())
        user_states.pop(user_id, None)

async def handle_coupon_recipient(update, context, user_id, state, text):
    parts = state.split("_")
    coupon_code = parts[3]
    discount_percent = int(parts[4])
    if text == "🌎 همه کاربران":
        await create_coupon(coupon_code, discount_percent)
        users = await db_execute("SELECT user_id FROM users", fetch=True)
        sent = 0
        for u in users:
            try:
                await context.bot.send_message(u[0], f"🎉 کد تخفیف ویژه {coupon_code} با {persian_number(discount_percent)}% تخفیف!")
                sent += 1
            except:
                pass
        await update.message.reply_text(f"✅ کد تخفیف برای {persian_number(sent)} کاربر ارسال شد.", reply_markup=get_admin_main_keyboard())
        user_states.pop(user_id, None)
    elif text == "👤 یک کاربر خاص":
        user_states[user_id] = f"awaiting_single_coupon_user_{coupon_code}_{discount_percent}"
        await update.message.reply_text("🆔 آیدی کاربر را وارد کنید:", reply_markup=get_back_keyboard())
    else:
        await update.message.reply_text("⚠️ گزینه نامعتبر.", reply_markup=get_coupon_recipient_keyboard())

async def handle_single_coupon_user(update, context, user_id, state, text):
    parts = state.split("_")
    coupon_code = parts[4]
    discount_percent = int(parts[5])
    
    try:
        target_id = int(text.strip())
        
        user_exists = await db_execute("SELECT user_id FROM users WHERE user_id = %s", (target_id,), fetchone=True)
        if not user_exists:
            await update.message.reply_text(f"❌ کاربر با آیدی {target_id} یافت نشد.", reply_markup=get_coupon_recipient_keyboard())
            user_states.pop(user_id, None)
            return
        
        await create_coupon(coupon_code, discount_percent, target_id)
        
        await context.bot.send_message(
            target_id,
            f"🎉 یک کد تخفیف ویژه برای شما ایجاد شده است!\n\n"
            f"🔑 کد تخفیف: `{coupon_code}`\n"
            f"💯 درصد تخفیف: {persian_number(discount_percent)}%\n"
            f"⏰ اعتبار: 3 روز\n\n"
            f"از این کد در مرحله پرداخت استفاده کنید.",
            parse_mode="Markdown"
        )
        
        await update.message.reply_text(
            f"✅ کد تخفیف {coupon_code} با {persian_number(discount_percent)}% تخفیف برای کاربر {target_id} ارسال شد.",
            reply_markup=get_admin_main_keyboard()
        )
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک آیدی عددی معتبر وارد کنید.", reply_markup=get_coupon_recipient_keyboard())
    
    user_states.pop(user_id, None)

# ---------- عضویت اجباری ----------
MEMBERSHIP_REQUIRED_MESSAGE = f"""❌ دسترسی غیرمجاز!

برای استفاده از ربات، ابتدا باید در کانال زیر عضو شوید:

👉 {CHANNEL_USERNAME}

پس از عضویت، روی دکمه «✅ تایید عضویت» کلیک کنید."""

async def send_membership_required(message_obj):
    kb = InlineKeyboardMarkup([[
        InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}"),
        InlineKeyboardButton("✅ تایید عضویت", callback_data="check_membership")
    ]])
    await message_obj.reply_text(MEMBERSHIP_REQUIRED_MESSAGE, reply_markup=kb)

async def require_membership(update, context, user_id) -> bool:
    if is_admin(user_id):
        return True
    
    if await is_user_banned(user_id):
        await update.message.reply_text("🚫 شما توسط ادمین از ربات بن شده‌اید و دیگر نمی‌توانید از خدمات استفاده کنید.")
        return False
    
    is_member = await check_user_membership(user_id)
    
    if not is_member:
        await send_membership_required(update.message)
        return False
    
    return True

# ---------- هندلرهای اصلی ----------
async def start(update, context):
    user = update.effective_user
    
    if await is_user_banned(user.id) and not is_admin(user.id):
        await update.message.reply_text("🚫 شما توسط ادمین از ربات بن شده‌اید و دیگر نمی‌توانید از خدمات استفاده کنید.")
        return
    
    if is_admin(user.id):
        invited_by = context.user_data.get("invited_by")
        await ensure_user(user.id, user.username or "", invited_by)
        await update.message.reply_text(
            "🌐 به ربات OnePercentVPN12 خوش آمدید!\n\n✅ شما به عنوان ادمین به تمام امکانات دسترسی دارید.",
            reply_markup=get_admin_main_keyboard()
        )
        user_states.pop(user.id, None)
        return
    
    if not await is_bot_available_for_user(user.id):
        await update.message.reply_text("🔴 ربات در حال حاضر برای کاربران عادی غیرفعال است.")
        return
    
    if not await require_membership(update, context, user.id):
        return
    
    invited_by = context.user_data.get("invited_by")
    await ensure_user(user.id, user.username or "", invited_by)
    is_agent = await is_user_agent(user.id)
    await update.message.reply_text("🌐 به ربات OnePercentVPN12 خوش آمدید!", reply_markup=get_main_keyboard(is_agent))
    user_states.pop(user.id, None)

async def start_with_param(update, context):
    args = context.args
    if args and len(args) > 0:
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
    
    if await is_user_banned(user.id) and not is_admin(user.id):
        await query.edit_message_text("🚫 شما توسط ادمین از ربات بن شده‌اید.")
        return
    
    is_member = await check_user_membership(user.id)
    
    if is_member:
        invited_by = context.user_data.get("invited_by")
        await ensure_user(user.id, user.username or "", invited_by)
        await query.edit_message_text("✅ عضویت شما تأیید شد!\n🌐 به ربات OnePercentVPN12 خوش آمدید!")
        
        if is_admin(user.id):
            await query.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        else:
            is_agent = await is_user_agent(user.id)
            await query.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent))
        user_states.pop(user.id, None)
    else:
        await query.edit_message_text(
            "❌ شما هنوز در کانال عضو نشده‌اید.\n\n"
            f"لطفاً ابتدا در {CHANNEL_USERNAME} عضو شوید، سپس روی دکمه «✅ تایید عضویت» کلیک کنید.",
            reply_markup=InlineKeyboardMarkup([[
                InlineKeyboardButton("📢 عضویت در کانال", url=f"https://t.me/{CHANNEL_USERNAME.replace('@','')}"),
                InlineKeyboardButton("✅ تایید عضویت", callback_data="check_membership")
            ]])
        )

async def show_balance(update, context, user_id):
    if not await require_membership(update, context, user_id):
        return
    
    balance = await get_user_balance(user_id)
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("💳 افزایش موجودی")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)
    await update.message.reply_text(
        f"💰 موجودی حساب شما 💰\n━━━━━━━━━━━━━━━━━━━━\n"
        f"💵 موجودی فعلی: {format_price(balance)}\n━━━━━━━━━━━━━━━━━━━━\n\n"
        f"برای افزایش موجودی روی دکمه زیر کلیک کنید:",
        reply_markup=keyboard
    )
    user_states[user_id] = "awaiting_balance_action"

async def handle_balance_action(update, context, user_id, text):
    if text == "💳 افزایش موجودی":
        await update.message.reply_text(
            "💰 افزایش موجودی 💰\n━━━━━━━━━━━━━━━━━━━━\n"
            "مبلغ مورد نظر را به تومان وارد کنید:\n\nمثال: 100000",
            reply_markup=get_back_keyboard()
        )
        user_states[user_id] = "awaiting_balance_amount"
    elif text == "↩️ بازگشت به منو":
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent))
        user_states.pop(user_id, None)
    else:
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_main_keyboard(is_agent))

async def handle_balance_amount(update, context, user_id, text):
    try:
        amount = int(english_number(text.strip()))
        if amount <= 0:
            await update.message.reply_text("⚠️ لطفاً یک عدد مثبت وارد کنید.", reply_markup=get_back_keyboard())
            return
        
        payment_id = await add_balance_payment(user_id, amount, "card_to_card", f"افزایش موجودی - {amount} تومان")
        if payment_id:
            await update.message.reply_text(
                f"💳 لطفاً مبلغ {format_price(amount)} را به کارت زیر واریز کنید:\n\n"
                f"🏦 شماره کارت: {BANK_CARD}\n"
                f"👤 به نام: {BANK_OWNER}\n\n"
                f"📸 سپس فیش واریز را به صورت عکس ارسال نمایید\n\n"
                f"🆔 کد پیگیری: {payment_id}",
                reply_markup=get_back_keyboard()
            )
            user_states[user_id] = f"awaiting_balance_receipt_{payment_id}"
        else:
            await update.message.reply_text("⚠️ خطا در ثبت درخواست.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
            user_states.pop(user_id, None)
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک عدد معتبر وارد کنید.", reply_markup=get_back_keyboard())

async def handle_subscription_type(update, context, user_id, text):
    if text == "⭐️ اشتراک اکونومی ⭐️":
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("💳 پلن اکونومی مورد نظر را انتخاب کنید:", reply_markup=get_subscription_keyboard(is_agent, "economy"))
        user_states[user_id] = "awaiting_subscription_type_economy"
    elif text == "💎 اشتراک سوپر فست 💎":
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("💳 پلن سوپر فست مورد نظر را انتخاب کنید:", reply_markup=get_subscription_keyboard(is_agent, "superfast"))
        user_states[user_id] = "awaiting_subscription_type_superfast"
    elif text == "↩️ بازگشت به منو":
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent))
        user_states.pop(user_id, None)
    else:
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_main_keyboard(is_agent))

async def handle_subscription_plan(update, context, user_id, text, subscription_type):
    selected_volume, selected_type = extract_volume_and_type_from_display_text(text)
    
    if selected_volume and selected_type == subscription_type:
        volume = selected_volume
        is_agent = await is_user_agent(user_id)
        price = get_price_for_volume(volume, 1, is_agent, subscription_type)
        
        type_name = "اکونومی ⭐️" if subscription_type == "economy" else "سوپر فست 💎"
        
        await update.message.reply_text(
            f"✅ {persian_number(volume)} گیگ {CONFIG_NAME} {type_name}\n"
            f"💰 قیمت هر عدد: {format_price(price)}\n\n"
            f"🔢 تعداد مورد نیاز خود را به عدد وارد کنید:",
            reply_markup=get_back_keyboard()
        )
        
        user_states[user_id] = f"awaiting_quantity_{volume}_{subscription_type}"
    else:
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_subscription_keyboard(is_agent, subscription_type))

async def handle_quantity_input(update, context, user_id, state, text):
    try:
        parts = state.split("_")
        volume = int(parts[2])
        subscription_type = parts[3]
        quantity = int(english_number(text.strip()))
        
        if quantity <= 0:
            await update.message.reply_text("⚠️ لطفاً یک عدد مثبت وارد کنید.", reply_markup=get_back_keyboard())
            return
        
        available_count = await get_available_configs_count(volume, subscription_type)
        
        if available_count < quantity:
            type_name = "اکونومی" if subscription_type == "economy" else "سوپر فست"
            await update.message.reply_text(
                f"⚠️ موجودی کافی نیست!\n\n"
                f"📦 تعداد موجود {persian_number(volume)} گیگ {type_name}: {persian_number(available_count)} عدد\n"
                f"📊 تعداد درخواستی شما: {persian_number(quantity)} عدد\n\n"
                f"لطفاً تعداد کمتر یا مساوی موجودی وارد کنید:",
                reply_markup=get_back_keyboard()
            )
            return
        
        is_agent = await is_user_agent(user_id)
        total_amount = get_price_for_volume(volume, quantity, is_agent, subscription_type)
        type_name = "اکونومی ⭐️" if subscription_type == "economy" else "سوپر فست 💎"
        plan_name = f"{CONFIG_NAME} {type_name} | {volume} گیگ | {persian_number(quantity)} عدد"
        
        await update.message.reply_text(
            f"✅ {persian_number(quantity)} عدد کانفیگ {persian_number(volume)} گیگی {type_name}\n"
            f"💰 مبلغ کل: {format_price(total_amount)}\n\n"
            f"در صورت داشتن کد تخفیف، آن را وارد کنید، در غیر اینصورت روی 'ادامه' کلیک کنید:",
            reply_markup=ReplyKeyboardMarkup([[KeyboardButton("ادامه")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)
        )
        
        user_states[user_id] = f"awaiting_coupon_code_{total_amount}_{plan_name}_{volume}_{quantity}_{subscription_type}"
    except ValueError:
        await update.message.reply_text("⚠️ لطفاً یک عدد معتبر وارد کنید.", reply_markup=get_back_keyboard())

async def handle_coupon_code(update, context, user_id, state, text):
    parts = state.split("_")
    if len(parts) < 7:
        await update.message.reply_text("⚠️ خطا در پردازش درخواست.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        user_states.pop(user_id, None)
        return
    
    amount = int(parts[3])
    volume = int(parts[-3])
    quantity = int(parts[-2])
    subscription_type = parts[-1]
    plan_parts = parts[4:-3]
    plan = "_".join(plan_parts)
    
    if text == "ادامه":
        balance = await get_user_balance(user_id)
        has_balance = balance >= amount
        user_states[user_id] = f"awaiting_payment_method_{amount}_{plan}_{volume}_{quantity}_{subscription_type}"
        await update.message.reply_text("💳 روش پرداخت را انتخاب کنید:", reply_markup=get_payment_method_keyboard(has_balance))
        return
    
    discount_percent, error = await validate_coupon(text.strip(), user_id)
    if error:
        await update.message.reply_text(f"{error}\nبرای ادامه روی 'ادامه' کلیک کنید:", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("ادامه")]], resize_keyboard=True))
        return
    
    discounted_amount = int(amount * (1 - discount_percent / 100))
    balance = await get_user_balance(user_id)
    has_balance = balance >= discounted_amount
    user_states[user_id] = f"awaiting_payment_method_{discounted_amount}_{plan}_{volume}_{quantity}_{subscription_type}_{text.strip()}"
    await update.message.reply_text(f"✅ کد تخفیف اعمال شد! مبلغ با {persian_number(discount_percent)}% تخفیف: {format_price(discounted_amount)}\nروش پرداخت را انتخاب کنید:", reply_markup=get_payment_method_keyboard(has_balance))

async def handle_payment_method(update, context, user_id, text):
    state = user_states.get(user_id)
    if not state or not state.startswith("awaiting_payment_method_"):
        return
    
    try:
        parts = state.split("_")
        
        if len(parts) < 8:
            await update.message.reply_text("⚠️ خطا در پردازش درخواست.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
            user_states.pop(user_id, None)
            return
        
        amount = int(parts[3])
        
        if len(parts) >= 9 and parts[-1] and parts[-1] not in ["card_to_card"] and not parts[-1].isdigit():
            coupon_code = parts[-1]
            volume = int(parts[-3])
            quantity = int(parts[-2])
            subscription_type = parts[-4]
            plan_parts = parts[4:-4]
            plan = "_".join(plan_parts)
        else:
            coupon_code = None
            volume = int(parts[-3])
            quantity = int(parts[-2])
            subscription_type = parts[-1]
            plan_parts = parts[4:-3]
            plan = "_".join(plan_parts)
        
        if text == "🏧 انتقال کارت به کارت":
            payment_id = await add_payment(user_id, amount, "buy_subscription", "card_to_card", description=plan, coupon_code=coupon_code)
            if payment_id:
                await add_subscription(user_id, payment_id, plan, volume, quantity, subscription_type)
                await update.message.reply_text(
                    f"💳 لطفاً مبلغ {format_price(amount)} را به کارت زیر واریز کنید:\n\n"
                    f"🏦 شماره کارت: {BANK_CARD}\n"
                    f"👤 به نام: {BANK_OWNER}\n\n"
                    f"📸 سپس فیش واریز را به صورت عکس ارسال نمایید\n\n"
                    f"🆔 کد پیگیری: {payment_id}",
                    reply_markup=get_back_keyboard()
                )
                user_states[user_id] = f"awaiting_subscription_receipt_{payment_id}"
            else:
                await update.message.reply_text("⚠️ خطا در ثبت درخواست.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
                user_states.pop(user_id, None)
        elif text == "💳 پرداخت از موجودی":
            balance = await get_user_balance(user_id)
            if balance >= amount:
                success = await subtract_balance(user_id, amount)
                if success:
                    payment_id = await add_payment(user_id, amount, "buy_subscription", "balance", description=plan, coupon_code=coupon_code)
                    if payment_id:
                        await update_payment_status(payment_id, "approved")
                        await add_subscription(user_id, payment_id, plan, volume, quantity, subscription_type)
                        await update.message.reply_text(f"✅ پرداخت با موفقیت از موجودی شما انجام شد.\n💰 مبلغ {format_price(amount)} از موجودی شما کسر گردید.\n🆔 کد پیگیری: {payment_id}\n\nدر حال ارسال کانفیگ‌ها...")
                        
                        sub = await db_execute("SELECT id FROM subscriptions WHERE payment_id = %s", (payment_id,), fetchone=True)
                        if sub:
                            await send_multiple_configs_to_user(sub[0], user_id, volume, quantity, plan, context.bot, subscription_type)
                    else:
                        await add_balance(user_id, amount)
                        await update.message.reply_text("⚠️ خطا در ثبت پرداخت. مبلغ به موجودی شما بازگردانده شد.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
                else:
                    await update.message.reply_text("⚠️ خطا در کسر موجودی.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
            else:
                await update.message.reply_text(f"❌ موجودی شما کافی نیست!\n💰 موجودی فعلی: {format_price(balance)}\n💰 مبلغ مورد نیاز: {format_price(amount)}\n\nلطفاً روش دیگری را انتخاب کنید:", reply_markup=get_payment_method_keyboard(False))
                return
            user_states.pop(user_id, None)
        else:
            is_agent = await is_user_agent(user_id)
            await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_main_keyboard(is_agent))
    except Exception as e:
        logging.error(f"Error in payment method: {e}")
        await update.message.reply_text("⚠️ خطا در پردازش درخواست.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        user_states.pop(user_id, None)

async def process_payment_receipt(update, context, user_id, payment_id, receipt_type):
    try:
        payment = await db_execute("SELECT user_id, amount, type, description, status FROM payments WHERE id = %s", (payment_id,), fetchone=True)
        if not payment:
            await update.message.reply_text("⚠️ درخواست پرداخت یافت نشد.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
            return
        
        uid, amount, ptype, description, status = payment
        
        if status != 'pending':
            await update.message.reply_text("⚠️ این فیش قبلاً تایید یا رد شده است.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
            user_states.pop(user_id, None)
            return
        
        caption = f"💳 فیش پرداختی از کاربر {user_id}:\n💰 مبلغ: {format_price(amount)}\n📝 نوع: {description}"
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("✅ تایید", callback_data=f"approve_payment_{payment_id}"),
             InlineKeyboardButton("❌ رد", callback_data=f"reject_payment_{payment_id}")]
        ])
        
        if update.message.photo:
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_photo(chat_id=admin_id, photo=update.message.photo[-1].file_id, caption=caption, reply_markup=kb)
                except:
                    pass
            await update.message.reply_text("✅ فیش برای ادمین ارسال شد.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        elif update.message.document:
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_document(chat_id=admin_id, document=update.message.document.file_id, caption=caption, reply_markup=kb)
                except:
                    pass
            await update.message.reply_text("✅ فیش برای ادمین ارسال شد.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))
        else:
            await update.message.reply_text("⚠️ لطفاً فیش را به صورت عکس ارسال کنید.", reply_markup=get_back_keyboard())
            return
        user_states.pop(user_id, None)
    except Exception as e:
        logging.error(f"Error processing receipt: {e}")
        await update.message.reply_text("⚠️ خطا در ارسال فیش.", reply_markup=get_main_keyboard(await is_user_agent(user_id)))

async def handle_agent_registration(update, context, user_id):
    if not await require_membership(update, context, user_id):
        return
    
    is_agent = await is_user_agent(user_id)
    if is_agent:
        await update.message.reply_text(
            "👑 شما در حال حاضر نماینده هستید!\n\n"
            f"💰 قیمت‌های ویژه نمایندگان:\n"
            f"⭐️ اکونومی ۱ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY)}\n"
            f"⭐️ اکونومی ۲ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 2)}\n"
            f"⭐️ اکونومی ۳ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 3)}\n"
            f"⭐️ اکونومی ۴ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 4)}\n"
            f"⭐️ اکونومی ۵ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 5)}\n"
            f"⭐️ اکونومی ۶ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 6)}\n"
            f"⭐️ اکونومی ۷ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 7)}\n"
            f"⭐️ اکونومی ۸ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 8)}\n"
            f"⭐️ اکونومی ۹ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 9)}\n"
            f"⭐️ اکونومی ۱۰ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 10)}\n\n"
            f"💎 سوپر فست ۱ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST)}\n"
            f"💎 سوپر فست ۲ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 2)}\n"
            f"💎 سوپر فست ۳ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 3)}\n"
            f"💎 سوپر فست ۴ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 4)}\n"
            f"💎 سوپر فست ۵ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 5)}\n"
            f"💎 سوپر فست ۶ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 6)}\n"
            f"💎 سوپر فست ۷ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 7)}\n"
            f"💎 سوپر فست ۸ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 8)}\n"
            f"💎 سوپر فست ۹ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 9)}\n"
            f"💎 سوپر فست ۱۰ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 10)}",
            reply_markup=get_main_keyboard(True)
        )
        return
    
    message = (
        "📢 شرایط دریافت نمایندگی 📢\n"
        "━━━━━━━━━━━━━━━━━━━━\n\n"
        "برای دریافت نمایندگی، لازم است مبلغ ۴,۰۰۰,۰۰۰ تومان به موجودی حساب خود اضافه کنید تا حساب شما به سطح نمایندگی ارتقا یابد.\n\n"
        "❌ توجه: این مبلغ صرفاً جهت احراز شرایط نمایندگی است و به‌طور کامل در حساب شما باقی می‌ماند. هیچ هزینه‌ای بابت تبدیل حساب به نمایندگی کسر نخواهد شد و کل موجودی قابل استفاده است.\n\n"
        "💰 قیمت‌ها پس از دریافت نمایندگی:\n"
        "━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐️ اکونومی ۱ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY)}\n"
        f"⭐️ اکونومی ۲ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 2)}\n"
        f"⭐️ اکونومی ۳ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 3)}\n"
        f"⭐️ اکونومی ۴ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 4)}\n"
        f"⭐️ اکونومی ۵ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 5)}\n"
        f"⭐️ اکونومی ۶ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 6)}\n"
        f"⭐️ اکونومی ۷ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 7)}\n"
        f"⭐️ اکونومی ۸ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 8)}\n"
        f"⭐️ اکونومی ۹ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 9)}\n"
        f"⭐️ اکونومی ۱۰ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY * 10)}\n\n"
        f"💎 سوپر فست ۱ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST)}\n"
        f"💎 سوپر فست ۲ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 2)}\n"
        f"💎 سوپر فست ۳ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 3)}\n"
        f"💎 سوپر فست ۴ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 4)}\n"
        f"💎 سوپر فست ۵ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 5)}\n"
        f"💎 سوپر فست ۶ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 6)}\n"
        f"💎 سوپر فست ۷ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 7)}\n"
        f"💎 سوپر فست ۸ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 8)}\n"
        f"💎 سوپر فست ۹ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 9)}\n"
        f"💎 سوپر فست ۱۰ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST * 10)}\n"
        "━━━━━━━━━━━━━━━━━━━━"
    )
    
    keyboard = ReplyKeyboardMarkup([[KeyboardButton("💳 پرداخت مبلغ")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True)
    await update.message.reply_text(message, reply_markup=keyboard)
    user_states[user_id] = "awaiting_agent_registration_payment"

async def handle_agent_registration_payment(update, context, user_id, text):
    if text == "💳 پرداخت مبلغ":
        await update.message.reply_text(
            f"💰 مبلغ {format_price(AGENT_REGISTRATION_FEE)} برای ثبت‌نام نمایندگی\n━━━━━━━━━━━━━━━━━━━━\n"
            "لطفاً روش پرداخت را انتخاب کنید:",
            reply_markup=get_payment_method_keyboard(False)
        )
        user_states[user_id] = f"awaiting_agent_payment_method_{AGENT_REGISTRATION_FEE}"
    elif text == "↩️ بازگشت به منو":
        is_agent = await is_user_agent(user_id)
        await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent))
        user_states.pop(user_id, None)
    else:
        await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=ReplyKeyboardMarkup([[KeyboardButton("💳 پرداخت مبلغ")], [KeyboardButton("↩️ بازگشت به منو")]], resize_keyboard=True))

async def handle_agent_payment_method(update, context, user_id, text):
    state = user_states.get(user_id)
    if not state or not state.startswith("awaiting_agent_payment_method_"):
        return
    
    try:
        parts = state.split("_")
        if len(parts) < 5:
            await update.message.reply_text("⚠️ خطا در پردازش درخواست.", reply_markup=get_main_keyboard(False))
            user_states.pop(user_id, None)
            return
        
        amount = int(parts[4])
        
        if text == "🏧 انتقال کارت به کارت":
            payment_id = await add_payment(user_id, amount, "agent_registration", "card_to_card", "ثبت‌نام نمایندگی")
            if payment_id:
                await update.message.reply_text(
                    f"💳 لطفاً مبلغ {format_price(amount)} را به کارت زیر واریز کنید:\n\n"
                    f"🏦 شماره کارت: {BANK_CARD}\n"
                    f"👤 به نام: {BANK_OWNER}\n\n"
                    f"📸 سپس فیش واریز را به صورت عکس ارسال نمایید\n\n"
                    f"🆔 کد پیگیری: {payment_id}",
                    reply_markup=get_back_keyboard()
                )
                user_states[user_id] = f"awaiting_agent_receipt_{payment_id}"
            else:
                await update.message.reply_text("⚠️ خطا در ثبت درخواست.", reply_markup=get_main_keyboard(False))
                user_states.pop(user_id, None)
        elif text == "💳 پرداخت از موجودی":
            balance = await get_user_balance(user_id)
            if balance >= amount:
                success = await subtract_balance(user_id, amount)
                if success:
                    await set_user_agent(user_id)
                    await update.message.reply_text(
                        f"✅ تبریک! شما به نمایندگی ارتقا یافتید!\n\n"
                        f"💰 مبلغ {format_price(amount)} از موجودی شما کسر شد.\n"
                        f"💎 از این پس می‌توانید از قیمت‌های ویژه نمایندگان استفاده کنید.",
                        reply_markup=get_main_keyboard(True)
                    )
                    for admin_id in ADMIN_IDS:
                        try:
                            await context.bot.send_message(
                                admin_id,
                                f"👑 کاربر {user_id} با پرداخت از موجودی ({format_price(amount)}) به نمایندگی ارتقا یافت."
                            )
                        except:
                            pass
                else:
                    await update.message.reply_text("⚠️ خطا در انجام تراکنش.", reply_markup=get_main_keyboard(False))
            else:
                await update.message.reply_text(
                    f"❌ موجودی شما کافی نیست!\n💰 موجودی فعلی: {format_price(balance)}\n💰 مبلغ مورد نیاز: {format_price(amount)}\n\n"
                    f"لطفاً ابتدا موجودی خود را افزایش دهید.",
                    reply_markup=get_main_keyboard(False)
                )
            user_states.pop(user_id, None)
        else:
            await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_payment_method_keyboard(False))
    except Exception as e:
        logging.error(f"Error in agent payment method: {e}")
        await update.message.reply_text("⚠️ خطا در پردازش درخواست.", reply_markup=get_main_keyboard(False))
        user_states.pop(user_id, None)

async def admin_callback_handler(update, context):
    query = update.callback_query
    await query.answer()
    
    data = query.data
    
    if data == "check_membership":
        await check_membership_callback(update, context)
        return
    
    if not is_admin(update.effective_user.id):
        await query.edit_message_text("⛔ دسترسی غیرمجاز.")
        return
    
    try:
        if data.startswith("approve_payment_"):
            payment_id = int(data.split("_")[2])
            
            payment = await db_execute("SELECT user_id, amount, type, description, status FROM payments WHERE id = %s", (payment_id,), fetchone=True)
            if not payment:
                await query.edit_message_text("⚠️ درخواست پرداخت یافت نشد.")
                return
            
            uid, amt, ptype, desc, status = payment
            
            if status != 'pending':
                await query.edit_message_text(f"⚠️ این پرداخت قبلاً { 'تایید' if status == 'approved' else 'رد' } شده است.")
                await query.edit_message_reply_markup(reply_markup=None)
                return
            
            await update_payment_status(payment_id, "approved")
            
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("✅ پرداخت تایید شد.")
            
            if ptype == "buy_subscription":
                await context.bot.send_message(uid, f"✅ پرداخت شما تایید شد. کد پیگیری: {payment_id}")
                sub = await db_execute("SELECT id, volume, plan, quantity, subscription_type, config FROM subscriptions WHERE payment_id = %s", (payment_id,), fetchone=True)
                if sub:
                    subscription_id, volume, plan, quantity, subscription_type, existing_config = sub
                    if existing_config:
                        await query.message.reply_text(f"⚠️ این اشتراک قبلاً کانفیگ خود را دریافت کرده است.")
                    else:
                        await send_multiple_configs_to_user(subscription_id, uid, volume, quantity, plan, context.bot, subscription_type)
            elif ptype == "add_balance":
                await add_balance(uid, amt)
                await context.bot.send_message(uid, f"✅ درخواست افزایش موجودی شما تایید شد!\n💰 مبلغ {format_price(amt)} به حساب شما اضافه شد.\n🆔 کد پیگیری: {payment_id}")
                await query.message.reply_text(f"✅ مبلغ {format_price(amt)} به موجودی کاربر {uid} اضافه شد.")
            elif ptype == "agent_registration":
                await set_user_agent(uid)
                await add_balance(uid, amt)
                await context.bot.send_message(
                    uid,
                    f"🎉 تبریک! شما به نمایندگی ارتقا یافتید!\n\n"
                    f"💰 مبلغ {format_price(amt)} به موجودی شما اضافه شد و قابل استفاده است.\n"
                    f"💎 از این پس می‌توانید از قیمت‌های ویژه نمایندگان استفاده کنید.\n\n"
                    f"⭐️ قیمت‌های ویژه شما:\n"
                    f"اکونومی ۱ تا ۱۰ گیگ — {format_price(AGENT_PRICE_PER_GB_ECONOMY)} هر گیگ\n"
                    f"💎 سوپر فست ۱ تا ۱۰ گیگ — {format_price(AGENT_PRICE_PER_GB_SUPERFAST)} هر گیگ"
                )
                await query.message.reply_text(f"✅ کاربر {uid} به نمایندگی ارتقا یافت و مبلغ {format_price(amt)} به موجودی او اضافه شد.")
                    
        elif data.startswith("reject_payment_"):
            payment_id = int(data.split("_")[2])
            
            payment = await db_execute("SELECT user_id, status FROM payments WHERE id = %s", (payment_id,), fetchone=True)
            if not payment:
                await query.edit_message_text("⚠️ درخواست پرداخت یافت نشد.")
                return
            
            uid, status = payment
            
            if status != 'pending':
                await query.edit_message_text(f"⚠️ این پرداخت قبلاً { 'تایید' if status == 'approved' else 'رد' } شده است.")
                await query.edit_message_reply_markup(reply_markup=None)
                return
            
            await update_payment_status(payment_id, "rejected")
            
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("❌ پرداخت رد شد.")
            
            if uid:
                await context.bot.send_message(uid, "❌ متأسفانه پرداخت شما تایید نشد. لطفاً مجدداً تلاش کنید.")
    except Exception as e:
        logging.error(f"Error in callback: {e}")
        try:
            await query.edit_message_reply_markup(reply_markup=None)
            await query.message.reply_text("⚠️ خطا در پردازش درخواست.")
        except:
            pass

async def handle_normal_commands(update, context, user_id, text):
    if not await is_bot_available_for_user(user_id):
        await update.message.reply_text("🔴 ربات در حال حاضر برای کاربران عادی غیرفعال است.")
        return
    
    if not await require_membership(update, context, user_id):
        return
    
    is_agent = await is_user_agent(user_id)
    
    if text == "🛍️ خرید اشتراک":
        await update.message.reply_text("💳 نوع اشتراک خود را انتخاب کنید:", reply_markup=get_subscription_type_keyboard())
    elif text in ["⭐️ اشتراک اکونومی ⭐️", "💎 اشتراک سوپر فست 💎"]:
        await handle_subscription_type(update, context, user_id, text)
    elif text == "💰 موجودی":
        await show_balance(update, context, user_id)
    elif text == "🆘 پشتیبانی":
        await update.message.reply_text(f"📞 پشتیبانی: {SUPPORT_USERNAME}", reply_markup=get_main_keyboard(is_agent))
    elif text == "🗂️ اشتراک‌های من":
        subs = await get_user_subscriptions(user_id)
        if not subs:
            await update.message.reply_text("📁 شما هیچ اشتراک فعالی ندارید.", reply_markup=get_main_keyboard(is_agent))
            return
        response = "🗂️ اشتراک‌های شما:\n\n"
        for s in subs:
            type_name = "اکونومی ⭐️" if s['subscription_type'] == "economy" else "سوپر فست 💎"
            response += f"🔹 {type_name} {s['plan']} ({persian_number(s['volume'])} گیگ - تعداد: {persian_number(s['quantity'])} عدد)\n📊 وضعیت: {'✅ فعال' if s['status'] == 'active' else '⏳ در انتظار تایید'}\n"
            if s['status'] == 'active' and s['config']:
                response += f"🔐 کانفیگ:\n```\n{s['config']}\n```\n"
            response += "--------------------\n"
            if len(response) > 3500:
                await send_long_message(user_id, response, context, parse_mode="Markdown")
                response = ""
        if response:
            await send_long_message(user_id, response, context, parse_mode="Markdown")
    elif text == "📚 آموزش اتصال":
        await update.message.reply_text("📚 راهنمای اتصال\nلطفاً دستگاه خود را انتخاب کنید:", reply_markup=get_connection_guide_keyboard())
    elif text in ["📱 اندروید", "🍏 آیفون/مک", "🖥️ ویندوز", "🐧 لینوکس"]:
        guides = {"📱 اندروید": "📱 آموزش اندروید:\nاستفاده از اپلیکیشن V2RayNG یا Hiddify", "🍏 آیفون/مک": "🍏 آموزش iOS/Mac:\nاستفاده از اپلیکیشن Singbox یا V2box", "🖥️ ویندوز": "🪟 آموزش ویندوز:\nاستفاده از اپلیکیشن V2rayN", "🐧 لینوکس": "🐧 آموزش لینوکس:\nاستفاده از اپلیکیشن V2rayN"}
        await update.message.reply_text(guides[text], reply_markup=get_connection_guide_keyboard())
    elif text == "👨‍💼 درخواست نمایندگی":
        await handle_agent_registration(update, context, user_id)
    else:
        # بررسی دکمه‌های خرید اشتراک
        volume, sub_type = extract_volume_and_type_from_display_text(text)
        if volume and sub_type:
            await handle_subscription_plan(update, context, user_id, text, sub_type)
        else:
            await update.message.reply_text("⚠️ لطفاً از دکمه‌های منو استفاده کنید.", reply_markup=get_main_keyboard(is_agent))

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not update.effective_user:
        return
    
    user_id = update.effective_user.id
    text = update.message.text if update.message.text else ""
    state = user_states.get(user_id)
    
    if update.message.document and state == "awaiting_restore_file":
        await handle_restore_file(update, context)
        return
    
    if text in ["بازگشت به منو", "↩️ بازگشت به منو"]:
        if is_admin(user_id):
            await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_admin_main_keyboard())
        else:
            is_agent = await is_user_agent(user_id)
            await update.message.reply_text("🌐 منوی اصلی:", reply_markup=get_main_keyboard(is_agent))
        user_states.pop(user_id, None)
        return
    
    # هندلرهای ادمین
    if is_admin(user_id):
        if state == "awaiting_notification_type":
            await handle_notification_type(update, context, user_id, text)
            return
        if state == "awaiting_notification_target_user":
            await handle_notification_target_user(update, context, user_id, text)
            return
        if state in ["awaiting_notification_text_all", "awaiting_notification_text_agents"] or (state and state.startswith("awaiting_notification_text_single_")):
            await handle_notification_text(update, context, user_id, state, text)
            return
        if state == "awaiting_ban_user_id":
            await handle_remove_user(update, context, user_id, text)
            return
        if state == "awaiting_unban_user_id":
            await handle_unban_user(update, context, user_id, text)
            return
        if state == "awaiting_admin_config_action":
            await handle_admin_config_action(update, context, user_id, text)
            return
        if state == "awaiting_config_volume_selection_economy" or state == "awaiting_config_volume_selection_superfast":
            await handle_config_volume_selection(update, context, user_id, state, text)
            return
        if state and state.startswith("awaiting_config_text_"):
            await handle_config_text(update, context, user_id, state, text)
            return
        if state == "awaiting_admin_management_action":
            await handle_admin_management(update, context, user_id, text)
            return
        if state == "awaiting_new_admin_id":
            await handle_add_new_admin(update, context, user_id, text)
            return
        if state == "awaiting_remove_admin_id":
            await handle_remove_admin(update, context, user_id, text)
            return
        if state == "awaiting_bank_management_action":
            await handle_bank_management(update, context, user_id, text)
            return
        if state == "awaiting_new_card_number":
            await handle_new_card_number(update, context, user_id, text)
            return
        if state and state.startswith("awaiting_card_owner_"):
            await handle_card_owner(update, context, user_id, state, text)
            return
        if state and state.startswith("awaiting_card_confirm_"):
            await handle_card_confirm(update, context, user_id, state, text)
            return
        if state == "awaiting_set_active_card":
            await handle_set_active_card(update, context, user_id, text)
            return
        if state == "awaiting_coupon_discount":
            if text.isdigit():
                discount = int(text)
                if 1 <= discount <= 100:
                    code = generate_coupon_code()
                    user_states[user_id] = f"awaiting_coupon_recipient_{code}_{discount}"
                    await update.message.reply_text(f"💵 کد تخفیف {code} با {persian_number(discount)}% تخفیف ساخته شد.\nاین کد برای چه کسانی ارسال شود؟", reply_markup=get_coupon_recipient_keyboard())
                else:
                    await update.message.reply_text("⚠️ درصد تخفیف باید بین 1 تا 100 باشد.", reply_markup=get_back_keyboard())
            else:
                await update.message.reply_text("⚠️ لطفاً یک عدد وارد کنید.", reply_markup=get_back_keyboard())
            return
        if state and state.startswith("awaiting_coupon_recipient_"):
            await handle_coupon_recipient(update, context, user_id, state, text)
            return
        if state and state.startswith("awaiting_single_coupon_user_"):
            await handle_single_coupon_user(update, context, user_id, state, text)
            return
        if state == "awaiting_search_method":
            await handle_search_method(update, context, user_id, text)
            return
        if state == "awaiting_search_by_id":
            await handle_search_by_id(update, context, user_id, text)
            return
        if state == "awaiting_search_by_username":
            await handle_search_by_username(update, context, user_id, text)
            return
        if state == "awaiting_set_agent_user_id":
            await handle_set_agent(update, context, user_id, text)
            return
        if text == "⚙️ مدیریت ادمین":
            await admin_management_command(update, context)
            return
        if text == "💳 مدیریت کارت":
            await bank_management_command(update, context)
            return
        if text == "⚙️ مدیریت کانفیگ":
            await add_config_command(update, context)
            return
        if text == "👥 مدیریت کاربران":
            await user_info_command(update, context)
            return
    
    # هندلرهای عادی کاربران
    if not await is_bot_available_for_user(user_id):
        if text not in ["بازگشت به منو", "↩️ بازگشت به منو"]:
            await update.message.reply_text("🔴 ربات در حال حاضر برای کاربران عادی غیرفعال است.")
        return
    
    if state and state.startswith("awaiting_subscription_receipt_"):
        payment_id = int(state.split("_")[-1])
        await process_payment_receipt(update, context, user_id, payment_id, "خرید اشتراک")
        user_states.pop(user_id, None)
        return
    
    if state and state.startswith("awaiting_balance_receipt_"):
        payment_id = int(state.split("_")[-1])
        await process_payment_receipt(update, context, user_id, payment_id, "افزایش موجودی")
        user_states.pop(user_id, None)
        return
    
    if state and state.startswith("awaiting_agent_receipt_"):
        payment_id = int(state.split("_")[-1])
        await process_payment_receipt(update, context, user_id, payment_id, "ثبت‌نام نمایندگی")
        user_states.pop(user_id, None)
        return
    
    if state == "awaiting_balance_action":
        await handle_balance_action(update, context, user_id, text)
        return
    
    if state == "awaiting_balance_amount":
        await handle_balance_amount(update, context, user_id, text)
        return
    
    if state == "awaiting_agent_registration_payment":
        await handle_agent_registration_payment(update, context, user_id, text)
        return
    
    if state and state.startswith("awaiting_agent_payment_method_"):
        await handle_agent_payment_method(update, context, user_id, text)
        return
    
    if state and state.startswith("awaiting_coupon_code_"):
        await handle_coupon_code(update, context, user_id, state, text)
        return
    
    if state and state.startswith("awaiting_payment_method_"):
        await handle_payment_method(update, context, user_id, text)
        return
    
    if state and state.startswith("awaiting_subscription_type_"):
        subscription_type = state.split("_")[2]
        await handle_subscription_plan(update, context, user_id, text, subscription_type)
        return
    
    if state and state.startswith("awaiting_quantity_"):
        await handle_quantity_input(update, context, user_id, state, text)
        return
    
    await handle_normal_commands(update, context, user_id, text)

async def restore_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await admin_only(update, context, None):
        return
    
    await update.message.reply_text(
        "⚠️ **بازیابی اطلاعات** ⚠️\n━━━━━━━━━━━━━━━━━━━━\n"
        "⚠️ توجه: این عملیات **همه کانفیگ‌های موجود** را حذف و با کانفیگ‌های بکاپ جایگزین می‌کند.\n\n"
        "لطفاً فایل JSON بکاپ را ارسال کنید:",
        reply_markup=get_back_keyboard()
    )
    user_states[update.effective_user.id] = "awaiting_restore_file"

async def handle_restore_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    if not is_admin(user_id):
        return
    
    if not update.message.document:
        await update.message.reply_text("❌ لطفاً فایل JSON بکاپ را ارسال کنید.")
        return
    
    file = await update.message.document.get_file()
    file_content = await file.download_as_bytearray()
    
    try:
        backup_data = json.loads(file_content.decode('utf-8'))
        
        if 'config_pool' not in backup_data:
            await update.message.reply_text("❌ فایل بکاپ معتبر نیست. فرمت صحیح ندارد.")
            user_states.pop(user_id, None)
            return
        
        configs_list = backup_data['config_pool'].get('items', [])
        
        if not configs_list:
            await update.message.reply_text("⚠️ هیچ کانفیگی در فایل بکاپ یافت نشد.")
            user_states.pop(user_id, None)
            return
        
        await update.message.reply_text(f"🔄 در حال بازیابی {persian_number(len(configs_list))} کانفیگ...")
        
        await db_execute("DELETE FROM config_pool")
        
        success_count = 0
        for cfg in configs_list:
            try:
                sub_type = cfg.get('subscription_type', 'economy')
                await db_execute(
                    "INSERT INTO config_pool (id, volume, config_text, is_sold, created_by, created_at, subscription_type) VALUES (%s, %s, %s, FALSE, %s, %s, %s) ON CONFLICT (id) DO NOTHING",
                    (cfg['id'], cfg['volume'], cfg['config_text'], cfg.get('created_by', 1), cfg['created_at'], sub_type)
                )
                success_count += 1
            except:
                pass
        
        await update.message.reply_text(
            f"✅ عملیات بازیابی کامل شد!\n\n"
            f"📊 کانفیگ‌های بازیابی شده: {persian_number(success_count)} عدد\n"
            f"📅 تاریخ بکاپ: {backup_data.get('backup_date', 'نامشخص')}",
            reply_markup=get_admin_main_keyboard()
        )
        
    except json.JSONDecodeError:
        await update.message.reply_text("❌ فایل ارسالی JSON معتبر نیست.")
    except Exception as e:
        logging.error(f"Restore file error: {e}")
        await update.message.reply_text(f"❌ خطا در بازیابی: {str(e)}")
    
    user_states.pop(user_id, None)

# ---------- ثبت هندلرها ----------
application.add_handler(CommandHandler("start", start_with_param))
application.add_handler(CommandHandler("stats", stats_command))
application.add_handler(CommandHandler("user_info", user_info_command))
application.add_handler(CommandHandler("remove_user", remove_user_command))
application.add_handler(CommandHandler("unban_user", unban_user_command))
application.add_handler(CommandHandler("notification", notification_command))
application.add_handler(CommandHandler("search", search_user_command))
application.add_handler(CommandHandler("debug_subscriptions", debug_subscriptions_command))
application.add_handler(CommandHandler("set_agent", set_agent_command))
application.add_handler(CommandHandler("coupon", coupon_command))
application.add_handler(CommandHandler("add_config", add_config_command))
application.add_handler(CommandHandler("backup", backup_command))
application.add_handler(CommandHandler("restore", restore_command))
application.add_handler(CommandHandler("shutdown", shutdown_command))
application.add_handler(CommandHandler("startup", startup_command))
application.add_handler(CommandHandler("admin", admin_management_command))
application.add_handler(CommandHandler("bank", bank_management_command))
application.add_handler(MessageHandler(filters.ALL & (~filters.COMMAND), message_handler))
application.add_handler(CallbackQueryHandler(admin_callback_handler))

@app.post(WEBHOOK_PATH)
async def telegram_webhook(request: Request):
    try:
        data = await request.json()
        update = Update.de_json(data, application.bot)
        await application.update_queue.put(update)
        return {"ok": True}
    except Exception as e:
        logging.error(f"Error in webhook: {e}")
        return {"ok": False, "error": str(e)}

periodic_task = None

@app.on_event("startup")
async def on_startup():
    global periodic_task
    try:
        init_db_pool()
        await create_tables()
        await application.initialize()
        await application.start()
        await application.bot.set_webhook(url=WEBHOOK_URL)
        logging.info(f"✅ Webhook set: {WEBHOOK_URL}")
        await set_bot_commands()
        
        await start_backup_scheduler()
        
        periodic_task = asyncio.create_task(periodic_pending_check(application.bot))
        
        status_text = "روشن" if bot_is_active else "خاموش"
        for admin_id in ADMIN_IDS:
            try:
                await application.bot.send_message(
                    chat_id=admin_id, 
                    text=f"🤖 ربات OnePercentVPN12 با موفقیت راه‌اندازی شد!\n✅ عضویت اجباری در کانال {CHANNEL_USERNAME} فعال است.\n✅ وضعیت ربات: {status_text}\n🎉 قیمت‌ها:\n⭐️ اکونومی هر گیگ: {format_price(PRICE_PER_GB_ECONOMY)}\n💎 سوپر فست هر گیگ: {format_price(PRICE_PER_GB_SUPERFAST)}\n💳 شماره کارت فعال: {BANK_CARD}\n👤 نام دارنده: {BANK_OWNER}\n━━━━━━━━━━━━━━━━━━━━\n📦 بکاپ خودکار استخر کانفیگ‌ها هر شب ساعت ۲۳:۵۹ ارسال می‌شود."
                )
            except:
                pass
        logging.info("✅ Bot started successfully")
    except Exception as e:
        logging.error(f"Startup error: {e}")

@app.on_event("shutdown")
async def on_shutdown():
    global periodic_task
    try:
        if periodic_task:
            periodic_task.cancel()
        scheduler.shutdown()
        await application.stop()
        await application.shutdown()
        close_db_pool()
        logging.info("✅ Bot shut down successfully")
    except Exception as e:
        logging.error(f"Shutdown error: {e}")

if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")
