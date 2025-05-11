```python
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import base64
import json
import logging
import datetime

import gspread
from google.oauth2.service_account import Credentials

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# --- Логування ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Google Sheets setup ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
B64_CRED = os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64", "")
info = json.loads(base64.b64decode(B64_CRED))
creds = Credentials.from_service_account_info(info, scopes=SCOPES)
gc = gspread.authorize(creds)
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
sh = gc.open_by_key(SPREADSHEET_ID)
worksheet = sh.sheet1

# --- Константи ---
EXECUTOR, MODEL, VIN, WORK = range(4)

# --- Парсинг користувачів із ENV ---
def parse_user_list(env_var: str) -> dict:
    users = {}
    for item in os.getenv(env_var, "").split(","):
        if not item.strip(): continue
        parts = item.strip().split(" ", 1)
        if len(parts) >= 2:
            username = parts[0] if parts[0].startswith("@") else f"@{parts[0]}"
            users[username.lower()] = parts[1]
    return users

OWNERS = parse_user_list("OWNERS")
MANAGERS = parse_user_list("MANAGERS")
WORKERS = parse_user_list("WORKERS")

# --- Google Sheets Manager ---
class SheetManager:
    HEADERS = ["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "user_level"]

    @staticmethod
    def get_recent_values(field, limit=5):
        records = worksheet.get_all_records()
        seen, vals = set(), []
        for row in reversed(records):
            val = str(row.get(field, "")).strip()
            if val and val not in seen:
                seen.add(val)
                vals.append(val)
            if len(vals) >= limit: break
        return vals

    @staticmethod
    def save_record(data, username, user_name, user_level):
        next_id = len(worksheet.get_all_values())
        row = [
            next_id,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            username,
            user_name,
            data["executor"],
            data["executor_name"],
            data["model"],
            data["vin"],
            data["work"],
            user_level
        ]
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        return next_id

# --- Handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text("Натисніть ➕ Додати запис")

async def add_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    executors = {**OWNERS, **MANAGERS, **WORKERS}
    buttons = [[InlineKeyboardButton(name, callback_data=f"executor:{username}:{name}")] for username, name in executors.items()]
    await update.message.reply_text("Оберіть виконавця:", reply_markup=InlineKeyboardMarkup(buttons))
    return EXECUTOR

async def executor_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    _, user_id, name = query.data.split(":", 2)
    context.user_data.update({"executor": user_id, "executor_name": name})
    await query.edit_message_text("Введіть модель авто:")
    return MODEL

async def model_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["model"] = update.message.text
    await update.message.reply_text("Введіть останні 6 символів VIN:")
    return VIN

async def vin_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["vin"] = update.message.text
    await update.message.reply_text("Опишіть виконану роботу:")
    return WORK

async def work_entered(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data["work"] = update.message.text
    username = f"@{update.effective_user.username}"
    user_name = update.effective_user.full_name
    record_id = SheetManager.save_record(context.user_data, username, user_name, "worker")
    await update.message.reply_text(f"✅ Запис #{record_id} збережено")
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("❌ Операцію скасовано")
    return ConversationHandler.END

# --- Main ---
def main():
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()

    conv_handler = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("➕ Додати запис"), add_record)],
        states={
            EXECUTOR: [CallbackQueryHandler(executor_selected, pattern="^executor:")],
            MODEL: [MessageHandler(filters.TEXT, model_entered)],
            VIN: [MessageHandler(filters.TEXT, vin_entered)],
            WORK: [MessageHandler(filters.TEXT, work_entered)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(conv_handler)

    app.run_polling()

if __name__ == "__main__":
    main()
```
