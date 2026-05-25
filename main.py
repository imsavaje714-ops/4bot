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
# نوع اشتراک: "economy" (اکونومی) و "superfast" (سوپر فست)
PRICE_PER_GB_ECONOMY = 169000      # قیمت هر گیگ اکونومی برای کاربر عادی
PRICE_PER_GB_SUPERFAST = 229000    # قیمت هر گیگ سوپر فست برای کاربر عادی

# قیمت‌های ویژه نمایندگان
AGENT_PRICE_PER_GB_ECONOMY = 153000     # قیمت هر گیگ اکونومی برای نماینده
AGENT_PRICE_PER_GB_SUPERFAST = 212000   # قیمت هر گیگ سوپر فست برای نماینده

# مبلغ نمایندگی
AGENT_REGISTRATION_FEE = 4000000

CONFIG_NAME = "کانفیگ"
AVAILABLE_VOLUMES = list(range(1, 11))  # 1 تا 10 گیگ
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
    english_digits = {'۰': '0', '۱': '1
