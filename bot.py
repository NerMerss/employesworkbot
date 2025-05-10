import os
import csv
import logging
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
import datetime

# Constants
MODEL, VIN, WORK = range(3)
CSV_FILE = "records.csv"
RECENT_ITEMS_LIMIT = 5
ADMIN_USERNAMES = {f"@{u.strip()}" for u in os.getenv("ADMIN_USERNAMES", "").split(",") if u.strip()}

# Configure logging
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Keyboard Markups
ADMIN_MENU_MARKUP = ReplyKeyboardMarkup(
    [
        ["➕ Добавить запись"],
        ["🗑 Очистить записи", "📤 Экспорт"],
        ["🔙 Главное меню"]
    ],
    resize_keyboard=True
)

CLEAR_MENU_MARKUP = ReplyKeyboardMarkup(
    [
        ["❌ Очистить ВСЁ"],
        ["🔢 Очистить по ID"],
        ["🔙 Назад"]
    ],
    resize_keyboard=True
)

CONFIRM_MARKUP = ReplyKeyboardMarkup(
    [
        ["✅ Да", "❌ Нет"],
        ["🔙 Назад"]
    ],
    resize_keyboard=True
)

class CSVManager:
    """Handles all CSV operations"""
    HEADERS = ["id", "timestamp", "user", "model", "vin", "work"]
    
    @staticmethod
    def ensure_file_exists():
        """Create CSV file with headers if not exists"""
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(CSVManager.HEADERS)
    
    @staticmethod
    def get_recent_values(field: str, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
        """Get unique recent values for a specific field"""
        values = []
        seen: Set[str] = set()
        
        try:
            with open(CSV_FILE, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                for row in reversed(list(reader)):  # Read from newest to oldest
                    if len(values) >= limit:
                        break
                    val = row.get(field, "").strip()
                    if val and val not in seen:
                        seen.add(val)
                        values.append(val)
        except FileNotFoundError:
            logger.warning("CSV file not found while getting recent values")
        
        return values
    
    @staticmethod
    def save_record(user_data: Dict[str, str], username: str, work_text: str) -> int:
        """Save new record and return its ID"""
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
                user_data["model"],
                user_data["vin"],
                work_text
            ])
        
        return next_id
    
    @staticmethod
    def export_records() -> Optional[str]:
        """Return path to CSV file if exists"""
        return CSV_FILE if os.path.exists(CSV_FILE) else None
    
    @staticmethod
    def clear_records(ids_to_remove: Optional[Set[str]] = None) -> bool:
        """Clear all or specific records"""
        try:
            with open(CSV_FILE, 'r', newline='', encoding='utf-8') as f:
                rows = list(csv.reader(f))
            
            if not rows:
                return False
            
            header, data = rows[0], rows[1:]
            
            if ids_to_remove:
                new_data = [row for row in data if row[0] not in ids_to_remove]
            else:
                new_data = []
            
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(new_data)
            
            return True
        except Exception as e:
            logger.error(f"Error clearing records: {e}")
            return False

def create_keyboard(items: List[str], prefix: str) -> InlineKeyboardMarkup:
    """Create inline keyboard with items and manual option"""
    buttons = [
        [InlineKeyboardButton(item, callback_data=f"{prefix}:{item}")]
        for item in items
    ]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data=f"{prefix}:manual")])
    return InlineKeyboardMarkup(buttons)

def is_admin(update: Update) -> bool:
    """Check if user is admin"""
    username = f"@{update.effective_user.username}"
    return username in ADMIN_USERNAMES

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start conversation and ask for model"""
    if is_admin(update):
        await show_admin_menu(update, context)
        return ConversationHandler.END
    
    models = CSVManager.get_recent_values("model")
    await update.message.reply_text(
        "Виберіть модель авто або введіть вручну:",
        reply_markup=create_keyboard(models, "model")
    )
    return MODEL

async def show_admin_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show admin menu"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас нет прав администратора")
        return
    
    await update.message.reply_text(
        "Админ-меню:",
        reply_markup=ADMIN_MENU_MARKUP
    )

async def admin_add_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Start adding record from admin menu"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас нет прав администратора")
        return
    
    models = CSVManager.get_recent_values("model")
    await update.message.reply_text(
        "Виберіть модель авто або введіть вручну:",
        reply_markup=create_keyboard(models, "model")
    )
    return MODEL

async def admin_clear_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Show clear options menu"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас нет прав администратора")
        return
    
    await update.message.reply_text(
        "Выберите тип очистки:",
        reply_markup=CLEAR_MENU_MARKUP
    )

async def ask_clear_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask confirmation for full clear"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас нет прав администратора")
        return
    
    await update.message.reply_text(
        "❗ Вы уверены, что хотите удалить ВСЕ записи?",
        reply_markup=CONFIRM_MARKUP
    )
    context.user_data["clear_type"] = "full"

async def ask_ids_to_clear(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Ask for IDs to clear"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас нет прав администратора")
        return
    
    await update.message.reply_text(
        "Введите ID записей для удаления:\n"
        "Примеры:\n"
        "• 1 (удалить одну запись)\n"
        "• 1-5 (удалить диапазон)\n"
        "• 1,3,5 (удалить несколько)\n"
        "• 1-3,5,7-9 (комбинация)",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data["clear_type"] = "partial"

def parse_complex_ids(id_str: str) -> Set[str]:
    """Parse complex ID patterns like '1-3,5,7-9'"""
    ids = set()
    parts = id_str.split(",")
    
    for part in parts:
        part = part.strip()
        if "-" in part:
            start, end = map(int, part.split("-"))
            ids.update(str(i) for i in range(start, end + 1))
        elif part.isdigit():
            ids.add(part)
    
    return ids

async def execute_clearing(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Execute clearing based on user choice"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас нет прав администратора")
        return
    
    clear_type = context.user_data.get("clear_type")
    
    if clear_type == "full":
        if update.message.text == "✅ Да":
            success = CSVManager.clear_records()
            msg = "🗑 Все записи удалены!" if success else "❌ Ошибка при удалении"
        else:
            msg = "❌ Удаление отменено"
    elif clear_type == "partial":
        try:
            ids_to_remove = parse_complex_ids(update.message.text)
            success = CSVManager.clear_records(ids_to_remove)
            msg = f"🗑 Удалены записи: {', '.join(sorted(ids_to_remove))}" if success else "❌ Ошибка при удалении"
        except ValueError:
            msg = "❗ Неверный формат ID. Попробуйте еще раз."
            await update.message.reply_text(msg)
            return
    
    await update.message.reply_text(
        msg,
        reply_markup=ADMIN_MENU_MARKUP
    )
    context.user_data.pop("clear_type", None)

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Handle admin menu commands"""
    text = update.message.text
    
    if text == "➕ Добавить запись":
        await admin_add_record(update, context)
    elif text == "🗑 Очистить записи":
        await admin_clear_options(update, context)
    elif text == "📤 Экспорт":
        await export_csv(update, context)
    elif text == "🔙 Главное меню":
        await update.message.reply_text(
            "Главное меню",
            reply_markup=ReplyKeyboardRemove()
        )
    elif text == "❌ Очистить ВСЁ":
        await ask_clear_confirmation(update, context)
    elif text == "🔢 Очистить по ID":
        await ask_ids_to_clear(update, context)
    elif text == "🔙 Назад":
        await show_admin_menu(update, context)
    elif text in ["✅ Да", "❌ Нет"]:
        await execute_clearing(update, context)
    elif "clear_type" in context.user_data:
        await execute_clearing(update, context)

async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export CSV file (admin only)"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас нет прав администратора")
        return
    
    if csv_path := CSVManager.export_records():
        await update.message.reply_document(
            document=open(csv_path, "rb"),
            filename="records.csv"
        )
    else:
        await update.message.reply_text("❌ Файл данных не найден")

# ... (остальные функции обработчиков остаются без изменений)

def main() -> None:
    """Start the bot"""
    if not (token := os.getenv("BOT_TOKEN")):
        logger.error("BOT_TOKEN environment variable not set!")
        return
    
    CSVManager.ensure_file_exists()
    
    app = ApplicationBuilder().token(token).build()
    
    # Conversation handler
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^➕ Добавить запись$"), admin_add_record)
        ],
        states={
            MODEL: [
                CallbackQueryHandler(handle_model, pattern="^model:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, 
                    lambda u, c: handle_manual_input(u, c, "model")),
            ],
            VIN: [
                CallbackQueryHandler(handle_vin, pattern="^vin:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, 
                    lambda u, c: handle_manual_input(u, c, "vin")),
            ],
            WORK: [
                CallbackQueryHandler(handle_work, pattern="^work:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, 
                    lambda u, c: handle_manual_input(u, c, "work")),
            ]
        },
        fallbacks=[CommandHandler("cancel", 
            lambda u, c: u.message.reply_text("❌ Скасовано.") or ConversationHandler.END)],
        allow_reentry=True
    )
    
    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("admin", show_admin_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_commands))
    app.add_handler(CallbackQueryHandler(restart_conversation, pattern="^restart$"))
    
    logger.info("Starting bot...")
    app.run_polling()

if __name__ == '__main__':
    main()