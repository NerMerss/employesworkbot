# Telegram-бот для сервісу, збереження у Google Таблицю

import os
import csv
import logging
import base64
import json
import datetime
from typing import Dict, List, Optional, Set
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import gspread
from google.oauth2.service_account import Credentials

# Константи
MODEL, VIN, WORK, EXECUTOR = range(4)
SPREADSHEET_NAME = "ServiceRecords"
RECENT_ITEMS_LIMIT = 5

TESLA_MODELS = ["Model 3", "Model Y", "Model S", "Model X", "Cybertruck", "Roadster", "Інше (не Tesla)"]
OTHER_MODELS = ["Rivian R1T", "Rivian R1S", "Lucid Air", "Zeekr 001", "Zeekr 007", "Інше"]
SPECIAL_COMMANDS = ["➕ Додати запис", "🗑 Видалити записи", "📤 Експорт даних", "❌ Видалити ВСЕ", "🔢 Видалити за ID", "🔙 Назад", "✅ Так", "❌ Ні"]

# Користувачі

def parse_user_list(env_var: str) -> dict:
    users = {}
    for item in os.getenv(env_var, "").split(","):
        if not item.strip():
            continue
        parts = item.strip().split(" ", 1)
        if len(parts) >= 2:
            username = parts[0] if parts[0].startswith("@") else f"@{parts[0]}"
            name = parts[1]
            users[username] = name
    return users

OWNERS = parse_user_list("OWNERS")
MANAGERS = parse_user_list("MANAGERS")
WORKERS = parse_user_list("WORKERS")

# Логування
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Меню
OWNER_MENU = ReplyKeyboardMarkup([[
    "➕ Додати запис"], ["🗑 Видалити записи", "📤 Експорт даних"]], resize_keyboard=True)
MANAGER_MENU = ReplyKeyboardMarkup([["➕ Додати запис"]], resize_keyboard=True)
WORKER_MENU = ReplyKeyboardMarkup([["➕ Додати запис"]], resize_keyboard=True)
DELETE_MENU = ReplyKeyboardMarkup([["❌ Видалити ВСЕ"], ["🔢 Видалити за ID"], ["🔙 Назад"]], resize_keyboard=True)
CONFIRM_MARKUP = ReplyKeyboardMarkup([["✅ Так", "❌ Ні"], ["🔙 Назад"]], resize_keyboard=True)

# Менеджер таблиці
class GoogleSheetManager:
    HEADERS = ["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "user_level"]

    def __init__(self, spreadsheet_name: str):
        creds_b64 = os.getenv("GOOGLE_SHEET_CREDENTIALS_BASE64")
        if not creds_b64:
            raise Exception("GOOGLE_SHEET_CREDENTIALS_BASE64 is not set")
        creds_dict = json.loads(base64.b64decode(creds_b64))
        creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
        self.sheet = gspread.authorize(creds).open(spreadsheet_name).sheet1
        self.ensure_headers()

    def ensure_headers(self):
        if self.sheet.row_values(1) != self.HEADERS:
            self.sheet.clear()
            self.sheet.insert_row(self.HEADERS, index=1)

    def append_record(self, data: Dict[str, str], username: str, user_name: str, user_level: str) -> int:
        rows = self.sheet.get_all_values()
        next_id = int(rows[-1][0]) + 1 if len(rows) > 1 else 1
        now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        self.sheet.append_row([
            next_id, now, username, user_name,
            data["executor"], data["executor_name"],
            data["model"], data["vin"], data["work"], user_level
        ])
        return next_id

    def get_recent_values(self, field: str, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
        records = self.sheet.get_all_records()
        seen, result = set(), []
        for row in reversed(records):
            val = row.get(field, "").strip()
            if val and val not in seen:
                seen.add(val)
                result.append(val)
            if len(result) >= limit:
                break
        return result

    def delete_all(self):
        self.sheet.resize(rows=1)

    def delete_by_ids(self, ids: Set[str]) -> int:
        all_rows = self.sheet.get_all_values()
        header, data = all_rows[0], all_rows[1:]
        filtered = [row for row in data if row[0] not in ids]
        self.sheet.clear()
        self.sheet.insert_row(header, index=1)
        for row in filtered:
            self.sheet.append_row(row)
        return len(data) - len(filtered)

sheet_manager = GoogleSheetManager(SPREADSHEET_NAME)

# Далі підключається логіка: start, add_record, видалення, експорт, handler
# (Ця частина буде додана наступним кроком)
