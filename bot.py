import os
import csv
import logging
from typing import Dict, List, Optional
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
    Document
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import datetime
import tempfile

# Constants
MODEL, VIN, WORK, DESCRIPTION, UPLOAD_CSV = range(5)
CSV_FILE = "/data/records.csv"
RECENT_ITEMS_LIMIT = 5
MAX_WORK_LENGTH = 64  # Maximum length of work description in bytes

# Model lists
TESLA_MODELS = ["Model 3", "Model Y", "Model S", "Model X", "Cybertruck", "Roadster", "Інше (не Tesla)"]
OTHER_MODELS = ["Rivian R1T", "Rivian R1S", "Lucid Air", "Zeekr 001", "Zeekr 007", "Інше"]

# Special commands
SPECIAL_COMMANDS = [
    "➕ Додати запис", "📤 Завантажити дані", "📥 Завантажити таблицю",
    "🔙 Назад", "✅ Так", "❌ Ні", "⏩ Пропустити"
]

def parse_user_list(env_var: str) -> dict:
    """Parse user list in format {'@username': 'Name Surname'}"""
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

# Access levels
OWNERS = parse_user_list("OWNERS")
MANAGERS = parse_user_list("MANAGERS")
WORKERS = parse_user_list("WORKERS")

# Logging setup
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Keyboards
OWNER_MENU = ReplyKeyboardMarkup(
    [["➕ Додати запис"], ["📤 Завантажити дані", "📥 Завантажити таблицю"]],
    resize_keyboard=True
)

MANAGER_MENU = ReplyKeyboardMarkup(
    [["➕ Додати запис"]],
    resize_keyboard=True
)

WORKER_MENU = ReplyKeyboardMarkup(
    [["➕ Додати запис"]],
    resize_keyboard=True
)

DESCRIPTION_MARKUP = ReplyKeyboardMarkup(
    [["⏩ Пропустити"], ["🔙 Назад"]],
    resize_keyboard=True
)

UPLOAD_MARKUP = ReplyKeyboardMarkup(
    [["🔙 Назад"]],
    resize_keyboard=True
)

class CSVManager:
    HEADERS = ["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "description", "user_level"]
    
    @staticmethod
    def ensure_file_exists():
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(CSVManager.HEADERS)
    
    @staticmethod
    def get_recent_values(field: str, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
        values = []
        seen = set()
        try:
            with open(CSV_FILE, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reversed(list(reader)):
                    if len(values) >= limit:
                        break
                    val = row.get(field, "").strip()
                    if val and val not in seen:
                        seen.add(val)
                        values.append(val)
        except FileNotFoundError:
            logger.warning("CSV file not found")
        return values
    
    @staticmethod
    def save_record(user_data: Dict[str, str], username: str, user_name: str, user_level: str) -> int:
        CSVManager.ensure_file_exists()
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        
        with open(CSV_FILE, 'r+', newline='', encoding='utf-8') as f:
            rows = list(csv.reader(f))
            next_id = int(rows[-1][0]) + 1 if len(rows) > 1 else 1
            writer = csv.writer(f)
            writer.writerow([
                next_id,
                timestamp,
                username,
                user_name,
                user_data["executor"],
                user_data["executor_name"],
                user_data["model"],
                user_data["vin"],
                user_data["work"],
                user_data.get("description", ""),
                user_level
            ])
        return next_id
    
    @staticmethod
    def replace_data(new_data_path: str) -> bool:
        try:
            # Validate the new file
            with open(new_data_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or set(reader.fieldnames) != set(CSVManager.HEADERS):
                    return False
                
                # Make a backup
                backup_path = f"{CSV_FILE}.bak"
                if os.path.exists(CSV_FILE):
                    os.replace(CSV_FILE, backup_path)
                
                # Replace the file
                os.replace(new_data_path, CSV_FILE)
                return True
        except Exception as e:
            logger.error(f"Error replacing CSV file: {e}")
            return False

def get_user_level(username: str) -> Optional[str]:
    """Get user access level"""
    username = username.lower().strip()
    if not username.startswith("@"):
        username = f"@{username}"
        
    if username in {k.lower(): v for k, v in OWNERS.items()}:
        return "owner"
    elif username in {k.lower(): v for k, v in MANAGERS.items()}:
        return "manager"
    elif username in {k.lower(): v for k, v in WORKERS.items()}:
        return "worker"
    return None

def create_keyboard(items: List[str], prefix: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(item, callback_data=f"{prefix}:{item}")] for item in items]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data=f"{prefix}:manual")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

def create_model_keyboard(models: List[str]) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(model, callback_data=f"model:{model}")] for model in models]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Start interaction with the bot"""
    username = f"@{update.effective_user.username}"
    user_level = get_user_level(username)
    
    if not user_level:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота")
        return
    
    if user_level == "owner":
        await update.message.reply_text("Меню власника:", reply_markup=OWNER_MENU)
    elif user_level == "manager":
        await update.message.reply_text("Меню керівника:", reply_markup=MANAGER_MENU)
    else:
        await update.message.reply_text("Меню працівника:", reply_markup=WORKER_MENU)

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Return to main menu"""
    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.delete_message()
        except Exception as e:
            logger.error(f"Failed to delete message: {e}")
    
    username = f"@{update.effective_user.username}"
    user_level = get_user_level(username)
    
    if user_level == "owner":
        await update.effective_message.reply_text("Меню власника:", reply_markup=OWNER_MENU)
    elif user_level == "manager":
        await update.effective_message.reply_text("Меню керівника:", reply_markup=MANAGER_MENU)
    else:
        await update.effective_message.reply_text("Меню працівника:", reply_markup=WORKER_MENU)
    
    context.user_data.clear()
    return ConversationHandler.END

# [Previous functions like add_record, executor_selected, model_selected, etc. would go here]

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Log errors and notify user"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    if update and isinstance(update, Update):
        if update.callback_query:
            chat_id = update.callback_query.message.chat_id
        elif update.message:
            chat_id = update.message.chat_id
        else:
            return
            
        await context.bot.send_message(
            chat_id=chat_id,
            text="❌ Сталася помилка. Спробуйте ще раз або зверніться до адміністратора."
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Cancel current conversation"""
    return await back_to_menu(update, context)

def main() -> None:
    """Run the bot"""
    if not (token := os.getenv("BOT_TOKEN")):
        logger.error("BOT_TOKEN environment variable not set!")
        return
    
    CSVManager.ensure_file_exists()
    
    app = ApplicationBuilder().token(token).build()
    
    # Add error handler
    app.add_error_handler(error_handler)
    
    # Main conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^➕ Додати запис$"), add_record),
            CallbackQueryHandler(back_to_menu, pattern="^back$")
        ],
        states={
            MODEL: [
                CallbackQueryHandler(model_selected, pattern="^model:"),
                CallbackQueryHandler(executor_selected, pattern="^executor:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, model_manual),
            ],
            VIN: [
                CallbackQueryHandler(vin_selected, pattern="^vin:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, vin_manual),
            ],
            WORK: [
                CallbackQueryHandler(work_selected, pattern="^work:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, work_manual),
            ],
            DESCRIPTION: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_description),
            ],
            UPLOAD_CSV: [
                MessageHandler(filters.TEXT | filters.Document.CSV, handle_csv_upload),
            ]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )
    
    app.add_handler(conv_handler)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))
    
    logger.info("Bot starting...")
    app.run_polling()

if __name__ == '__main__':
    main()