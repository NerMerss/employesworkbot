import os
import logging
import base64
import json
from typing import Dict, List, Optional
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import datetime
import gspread
from google.oauth2.service_account import Credentials

# Константы
MODEL, VIN, WORK, EXECUTOR = range(4)
RECENT_ITEMS_LIMIT = 5

# Списки моделей
TESLA_MODELS = ["Model 3", "Model Y", "Model S", "Model X", "Cybertruck", "Roadster", "Інше (не Tesla)"]
OTHER_MODELS = ["Rivian R1T", "Rivian R1S", "Lucid Air", "Zeekr 001", "Zeekr 007", "Інше"]

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

class GoogleSheetsManager:
    def __init__(self):
        self.credentials = self._get_credentials()
        self.spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        self.sheet_name = "ServiceRecords"
        self.client = None
        self.sheet = None
        self._connect()
    
    def _get_credentials(self):
        creds_base64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64")
        creds_json = base64.b64decode(creds_base64).decode('utf-8')
        return Credentials.from_service_account_info(json.loads(creds_json))
    
def _connect(self):
    try:
        self.client = gspread.authorize(self.credentials)
        self.sheet = self.client.open_by_key(self.spreadsheet_id).worksheet(self.sheet_name)
    except gspread.exceptions.WorksheetNotFound:
        spreadsheet = self.client.open_by_key(self.spreadsheet_id)
        self.sheet = spreadsheet.add_worksheet(title=self.sheet_name, rows=100, cols=20)
        self.sheet.append_row(["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "user_level"])
    except Exception as e:
        logger.error(f"Error connecting to Google Sheets: {e}")
        raise

    
    def get_recent_values(self, field: str, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
        try:
            col_index = ["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "user_level"].index(field) + 1
            values = self.sheet.col_values(col_index)[1:]
            return list(dict.fromkeys(reversed(values)))[:limit]
        except Exception as e:
            logger.error(f"Error getting recent values: {e}")
            return []
    
    def save_record(self, data: Dict[str, str]) -> int:
        try:
            ids = self.sheet.col_values(1)[1:]
            new_id = int(ids[-1]) + 1 if ids else 1
            
            row = [
                new_id,
                datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                data["user"],
                data["user_name"],
                data["executor"],
                data["executor_name"],
                data["model"],
                data["vin"],
                data["work"],
                data["user_level"]
            ]
            
            self.sheet.append_row(row)
            return new_id
        except Exception as e:
            logger.error(f"Error saving record: {e}")
            raise

def create_model_keyboard(models: List[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(m, callback_data=f"model_{m}")] for m in models]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

def create_vin_keyboard(vins: List[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(vin, callback_data=f"vin_{vin}")] for vin in vins]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data="vin_manual")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

def create_work_keyboard(works: List[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(w, callback_data=f"work_{w}")] for w in works]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data="work_manual")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await update.message.reply_text(
        "Виберіть дію:",
        reply_markup=ReplyKeyboardMarkup([["➕ Додати запис"]], resize_keyboard=True)
    )

async def add_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    context.user_data.clear()
    context.user_data["user"] = f"@{update.effective_user.username}"
    context.user_data["user_name"] = update.effective_user.full_name
    context.user_data["user_level"] = "worker"  # Simplified for example
    
    await update.message.reply_text(
        "Виберіть модель авто:",
        reply_markup=create_model_keyboard(TESLA_MODELS)
    )
    return MODEL

async def model_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        await query.edit_message_text("Виберіть дію:")
        return ConversationHandler.END
    
    model = query.data.replace("model_", "")
    context.user_data["model"] = model
    
    if model == "Інше (не Tesla)":
        await query.edit_message_text(
            "Виберіть модель авто:",
            reply_markup=create_model_keyboard(OTHER_MODELS)
        )
        return MODEL
    
    sheets = GoogleSheetsManager()
    vins = sheets.get_recent_values("vin")
    await query.edit_message_text(
        "Оберіть VIN:",
        reply_markup=create_vin_keyboard(vins)
    )
    return VIN

async def vin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        await query.edit_message_text(
            "Виберіть модель авто:",
            reply_markup=create_model_keyboard(TESLA_MODELS)
        )
        return MODEL
    
    if query.data == "vin_manual":
        await query.edit_message_text("Введіть VIN (6 символів):")
        return VIN
    
    vin = query.data.replace("vin_", "")
    context.user_data["vin"] = vin
    
    sheets = GoogleSheetsManager()
    works = sheets.get_recent_values("work")
    await query.edit_message_text(
        "Що було зроблено?",
        reply_markup=create_work_keyboard(works)
    )
    return WORK

async def vin_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    vin = update.message.text.strip()
    if len(vin) != 6 or not vin.isalnum():
        await update.message.reply_text("❗ VIN має містити рівно 6 символів (цифри та літери)")
        return VIN
    
    context.user_data["vin"] = vin.upper()
    
    sheets = GoogleSheetsManager()
    works = sheets.get_recent_values("work")
    await update.message.reply_text(
        "Що було зроблено?",
        reply_markup=create_work_keyboard(works)
    )
    return WORK

async def work_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        sheets = GoogleSheetsManager()
        vins = sheets.get_recent_values("vin")
        await query.edit_message_text(
            "Оберіть VIN:",
            reply_markup=create_vin_keyboard(vins)
        )
        return VIN
    
    if query.data == "work_manual":
        await query.edit_message_text("Введіть, що було зроблено:")
        return WORK
    
    work = query.data.replace("work_", "")
    context.user_data["work"] = work
    
    try:
        sheets = GoogleSheetsManager()
        record_id = sheets.save_record(context.user_data)
        
        await query.edit_message_text(
            f"✅ Запис #{record_id} збережено!\n"
            f"Модель: {context.user_data['model']}\n"
            f"VIN: {context.user_data['vin']}\n"
            f"Робота: {work}"
        )
    except Exception as e:
        logger.error(f"Помилка збереження: {e}")
        await query.edit_message_text("❌ Помилка збереження запису")
    
    return ConversationHandler.END

async def work_input(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    work = update.message.text.strip()
    context.user_data["work"] = work
    
    try:
        sheets = GoogleSheetsManager()
        record_id = sheets.save_record(context.user_data)
        
        await update.message.reply_text(
            f"✅ Запис #{record_id} збережено!\n"
            f"Модель: {context.user_data['model']}\n"
            f"VIN: {context.user_data['vin']}\n"
            f"Робота: {work}"
        )
    except Exception as e:
        logger.error(f"Помилка збереження: {e}")
        await update.message.reply_text("❌ Помилка збереження запису")
    
    return ConversationHandler.END

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    await update.message.reply_text("Дію скасовано")
    return ConversationHandler.END

def main() -> None:
    if not os.getenv("BOT_TOKEN"):
        logger.error("Встановіть BOT_TOKEN у змінних середовища!")
        return
    
    app = ApplicationBuilder().token(os.getenv("BOT_TOKEN")).build()
    
    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start),
                     MessageHandler(filters.Regex("^➕ Додати запис$"), add_record)],
        states={
            MODEL: [CallbackQueryHandler(model_handler, pattern="^model_|^back$")],
            VIN: [CallbackQueryHandler(vin_handler, pattern="^vin_|^back$"),
                  MessageHandler(filters.TEXT & ~filters.COMMAND, vin_input)],
            WORK: [CallbackQueryHandler(work_handler, pattern="^work_|^back$"),
                   MessageHandler(filters.TEXT & ~filters.COMMAND, work_input)]
        },
        fallbacks=[CommandHandler("cancel", cancel)]
    )
    
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, start))
    
    logger.info("Бот запускається...")
    app.run_polling()

if __name__ == "__main__":
    main()