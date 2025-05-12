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

# Константи
MODEL, VIN, WORK, DESCRIPTION, UPLOAD_CSV = range(5)
CSV_FILE = "/data/records.csv"
RECENT_ITEMS_LIMIT = 5
MAX_WORK_LENGTH = 64  # Максимальна довжина основного опису роботи в байтах

# Списки моделей
TESLA_MODELS = ["Model 3", "Model Y", "Model S", "Model X", "Cybertruck", "Roadster", "Інше (не Tesla)"]
OTHER_MODELS = ["Rivian R1T", "Rivian R1S", "Lucid Air", "Zeekr 001", "Zeekr 007", "Інше"]

# Список спеціальних команд
SPECIAL_COMMANDS = [
    "➕ Додати запис", "📤 Завантажити дані", "📥 Завантажити таблицю",
    "🔙 Назад", "✅ Так", "❌ Ні", "⏩ Пропустити"
]

def parse_user_list(env_var: str) -> dict:
    """Парсить список користувачів у форматі { '@username': 'Ім'я Прізвище' }"""
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

# Рівні доступу
OWNERS = parse_user_list("OWNERS")
MANAGERS = parse_user_list("MANAGERS")
WORKERS = parse_user_list("WORKERS")

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Клавіатури
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
            logger.warning("Файл CSV не знайдено")
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

async def work_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір робіт - ВИПРАВЛЕНА ВЕРСІЯ"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        return await back_to_menu(update, context)
    
    work_text = query.data.split(":")[1]
    if work_text == "manual":
        await query.edit_message_text(
            "Введіть, що було зроблено (макс. 64 символи):",
            reply_markup=None
        )
        return WORK
    
    # Перевіряємо довжину тексту роботи
    if len(work_text.encode('utf-8')) > MAX_WORK_LENGTH:
        works = CSVManager.get_recent_values("work", 6)
        keyboard = create_keyboard(works, "work")
        await query.edit_message_text(
            f"❗ Опис роботи занадто довгий (макс. {MAX_WORK_LENGTH} байт). Спробуйте ще раз:",
            reply_markup=keyboard
        )
        return WORK
    
    context.user_data["work"] = work_text
    
    # Відправляємо нове повідомлення замість редагування старого
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Бажаєте додати додатковий опис?",
        reply_markup=DESCRIPTION_MARKUP
    )
    return DESCRIPTION

async def handle_csv_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє завантажений CSV файл - ВИПРАВЛЕНА ВЕРСІЯ"""
    if update.message.text and update.message.text.strip() == "🔙 Назад":
        return await back_to_menu(update, context)
    
    if not update.message.document:
        await update.message.reply_text(
            "Будь ласка, надішліть CSV файл або натисніть '🔙 Назад'",
            reply_markup=UPLOAD_MARKUP
        )
        return UPLOAD_CSV
    
    try:
        # Завантажуємо файл у тимчасову директорію
        file = await context.bot.get_file(update.message.document.file_id)
        temp_file_path = f"{tempfile.gettempdir()}/{update.message.document.file_id}.csv"
        await file.download_to_drive(temp_file_path)
        
        # Намагаємось замінити дані
        if CSVManager.replace_data(temp_file_path):
            await update.message.reply_text("✅ Дані успішно оновлено!", reply_markup=OWNER_MENU)
        else:
            await update.message.reply_text(
                "❌ Помилка: файл має неправильний формат. Перевірте структуру.",
                reply_markup=OWNER_MENU
            )
        
        # Видаляємо тимчасовий файл
        try:
            os.unlink(temp_file_path)
        except Exception as e:
            logger.error(f"Помилка видалення тимчасового файлу: {e}")
    
    except Exception as e:
        logger.error(f"Помилка обробки CSV файлу: {e}")
        await update.message.reply_text(
            "❌ Помилка при обробці файлу. Спробуйте ще раз.",
            reply_markup=OWNER_MENU
        )
    
    return ConversationHandler.END

async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логує помилки та повідомляє користувача - ВИПРАВЛЕНА ВЕРСІЯ"""
    logger.error("Exception while handling an update:", exc_info=context.error)
    
    # Визначаємо, чи є повідомлення для відповіді
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

def main() -> None:
    """Запускає бота"""
    if not (token := os.getenv("BOT_TOKEN")):
        logger.error("Не встановлено змінну BOT_TOKEN!")
        return
    
    CSVManager.ensure_file_exists()
    
    app = ApplicationBuilder().token(token).build()
    
    # Додаємо обробник помилок
    app.add_error_handler(error_handler)
    
    # Основний обробник бесіди
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
    
    logger.info("Бот запущений...")
    app.run_polling()

if __name__ == '__main__':
    main()