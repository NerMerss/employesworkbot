import os
import csv
import logging
import base64
import json
from typing import Dict, List, Optional
from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import datetime
import tempfile
import gspread
from oauth2client.service_account import ServiceAccountCredentials

# Константи
MODEL, VIN, WORK, DESCRIPTION, UPLOAD_CSV = range(5)
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

class GoogleSheetsManager:
    HEADERS = ["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "description", "user_level"]
    
    @staticmethod
    def get_client():
        """Initialize gspread client using base64-encoded credentials."""
        try:
            # Decode base64 credentials
            credentials_json = base64.b64decode(os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64")).decode('utf-8')
            credentials_dict = json.loads(credentials_json)
            
            # Set up credentials
            scope-dotenv.scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
            credentials = ServiceAccountCredentials.from_json_keyfile_dict(credentials_dict, scope)
            
            # Authorize and return gspread client
            return gspread.authorize(credentials)
        except Exception as e:
            logger.error(f"Error initializing Google Sheets client: {e}")
            raise
    
    @staticmethod
    def ensure_sheet_exists():
        """Ensure the spreadsheet and worksheet exist with correct headers."""
        try:
            client = GoogleSheetsManager.get_client()
            spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
            spreadsheet = client.open_by_key(spreadsheet_id)
            
            # Try to access the first worksheet or create it
            try:
                worksheet = spreadsheet.sheet1
            except gspread.exceptions.WorksheetNotFound:
                worksheet = spreadsheet.add_worksheet(title="Sheet1", rows=100, cols=len(GoogleSheetsManager.HEADERS))
            
            # Check if headers exist, if not, set them
            if not worksheet.row_values(1):
                worksheet.append_row(GoogleSheetsManager.HEADERS)
        except Exception as e:
            logger.error(f"Error ensuring sheet exists: {e}")
            raise
    
    @staticmethod
    def get_recent_values(field: str, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
        """Retrieve recent unique values for a given field."""
        try:
            client = GoogleSheetsManager.get_client()
            spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
            worksheet = client.open_by_key(spreadsheet_id).sheet1
            
            # Get all values
            all_values = worksheet.get_all_records()
            values = []
            seen = set()
            
            # Iterate in reverse to get most recent first
            for row in reversed(all_values):
                if len(values) >= limit:
                    break
                val = str(row.get(field, "")).strip()
                if val and val not in seen:
                    seen.add(val)
                    values.append(val)
            return values
        except Exception as e:
            logger.error(f"Error retrieving recent values: {e}")
            return []
    
    @staticmethod
    def save_record(user_data: Dict[str, str], username: str, user_name: str, user_level: str) -> int:
        """Save a new record to Google Sheets and return the record ID."""
        try:
            GoogleSheetsManager.ensure_sheet_exists()
            client = GoogleSheetsManager.get_client()
            spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
            worksheet = client.open_by_key(spreadsheet_id).sheet1
            
            # Get the last ID
            all_values = worksheet.get_all_values()
            next_id = int(all_values[-1][0]) + 1 if len(all_values) > 1 and all_values[-1][0].isdigit() else 1
            
            # Prepare the record
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            record = [
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
            ]
            
            # Append the record
            worksheet.append_row(record)
            return next_id
        except Exception as e:
            logger.error(f"Error saving record to Google Sheets: {e}")
            raise
    
    @staticmethod
    def replace_data(new_data_path: str) -> bool:
        """Replace all data in the Google Sheet with data from a CSV file."""
        try:
            client = GoogleSheetsManager.get_client()
            spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
            worksheet = client.open_by_key(spreadsheet_id).sheet1
            
            # Validate the new CSV file
            with open(new_data_path, newline='', encoding='utf-8') as f:
                reader = csv.DictReader(f)
                if not reader.fieldnames or set(reader.fieldnames) != set(GoogleSheetsManager.HEADERS):
                    logger.error("Invalid CSV headers")
                    return False
                
                # Clear existing data
                worksheet.clear()
                
                # Write headers
                worksheet.append_row(GoogleSheetsManager.HEADERS)
                
                # Write new data
                for row in reader:
                    worksheet.append_row([
                        row["id"],
                        row["timestamp"],
                        row["user"],
                        row["user_name"],
                        row["executor"],
                        row["executor_name"],
                        row["model"],
                        row["vin"],
                        row["work"],
                        row["description"],
                        row["user_level"]
                    ])
            return True
        except Exception as e:
            logger.error(f"Error replacing Google Sheets data: {e}")
            return False

def get_user_level(username: str) -> Optional[str]:
    """Повертає рівень доступу користувача"""
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

async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Повертає до головного меню"""
    query = update.callback_query
    if query:
        await query.answer()
        try:
            await query.delete_message()
        except Exception as e:
            logger.error(f"Не вдалося видалити повідомлення: {e}")
    
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

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Початок взаємодії з ботом"""
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

async def add_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Починає процес додавання запису"""
    username = f"@{update.effective_user.username}"
    user_level = get_user_level(username)
    user_name = OWNERS.get(username) or MANAGERS.get(username) or WORKERS.get(username) or update.effective_user.full_name
    
    if not user_level:
        await update.message.reply_text("⛔ У вас немає доступу")
        return ConversationHandler.END
    
    context.user_data["user_level"] = user_level
    context.user_data["user_name"] = user_name
    
    if user_level == "worker":
        context.user_data["executor"] = username
        context.user_data["executor_name"] = user_name
        await update.message.reply_text(
            "Виберіть модель авто:",
            reply_markup=create_model_keyboard(TESLA_MODELS)
        )
        return MODEL
    
    # Для власників і менеджерів показуємо вибір виконавця
    if user_level == "owner":
        executors = {**MANAGERS, **WORKERS}  # Власники бачать менеджерів і працівників
    else:  # manager
        executors = WORKERS  # Менеджери бачать тільки працівників
    
    buttons = []
    # Додаємо себе для менеджера
    if user_level == "manager":
        buttons.append([InlineKeyboardButton(
            f"Я ({user_name})",
            callback_data=f"executor:{username}:{user_name}"
        )])
    
    # Додаємо інших виконавців
    for user_id, name in executors.items():
        buttons.append([InlineKeyboardButton(
            name,
            callback_data=f"executor:{user_id}:{name}"
        )])
    
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    
    await update.message.reply_text(
        "Оберіть виконавця:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return MODEL

async def executor_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір виконавця"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        return await back_to_menu(update, context)
    
    _, user_id, name = query.data.split(":", 2)
    context.user_data["executor"] = user_id
    context.user_data["executor_name"] = name
    
    await query.edit_message_text(
        "Виберіть модель авто:",
        reply_markup=create_model_keyboard(TESLA_MODELS)
    )
    return MODEL

async def model_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір моделі"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        return await back_to_menu(update, context)
    
    selected = query.data.split(":")[1]
    context.user_data["model"] = selected
    
    if selected == "Інше (не Tesla)":
        await query.edit_message_text(
            "Виберіть модель авто:",
            reply_markup=create_model_keyboard(OTHER_MODELS)
        )
        return MODEL
    
    vins = GoogleSheetsManager.get_recent_values("vin")
    await query.edit_message_text(
        "Оберіть VIN або введіть вручну:",
        reply_markup=create_keyboard(vins, "vin")
    )
    return VIN

async def model_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє ручний ввід моделі"""
    text = update.message.text.strip()
    
    if text in SPECIAL_COMMANDS:
        return await handle_text_messages(update, context)
    
    if text in TESLA_MODELS + OTHER_MODELS:
        context.user_data["model"] = text
    else:
        context.user_data["model"] = f"Інше: {text}"
    
    vins = GoogleSheetsManager.get_recent_values("vin")
    await update.message.reply_text(
        "Оберіть VIN або введіть вручну:",
        reply_markup=create_keyboard(vins, "vin")
    )
    return VIN

async def vin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір VIN"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        return await back_to_menu(update, context)
    
    selected = query.data.split(":")[1]
    if selected == "manual":
        await query.edit_message_text("Введіть останні 6 символів VIN:")
        return VIN
    
    context.user_data["vin"] = selected
    await query.edit_message_text(f"VIN: {selected}")
    return await show_work_options(update, context)

async def vin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє ручний ввід VIN"""
    text = update.message.text.strip()
    
    if text in SPECIAL_COMMANDS:
        return await handle_text_messages(update, context)
    
    if len(text) != 6 or not text.isalnum():
        await update.message.reply_text("❗ Введіть рівно 6 символів VIN.")
        return VIN
    
    context.user_data["vin"] = text.upper()
    return await show_work_options(update, context)

async def show_work_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показує варіанти робіт"""
    works = GoogleSheetsManager.get_recent_values("work", 6)
    keyboard = create_keyboard(works, "work")
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                "Що було зроблено? (макс. 64 символи)",
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await update.callback_query.message.reply_text(
                "Що було зроблено? (макс. 64 символи)",
                reply_markup=keyboard
            )
    else:
        await update.message.reply_text(
            "Що було зроблено? (макс. 64 символи)",
            reply_markup=keyboard
        )
    return WORK

async def work_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір робіт"""
    query = update.callback_query
    await query.answer()
    
    if query.data == "back":
        return await back_to_menu(update, context)
    
    work_text = query.data.split(":")[1]
    if work_text == "manual":
        try:
            await query.edit_message_text(
                "Введіть, що було зроблено (макс. 64 символи):",
                reply_markup=ReplyKeyboardRemove()
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await query.message.reply_text(
                "Введіть, що було зроблено (макс. 64 символи):",
                reply_markup=ReplyKeyboardRemove()
            )
        return WORK
    
    # Перевіряємо довжину тексту роботи
    if len(work_text.encode('utf-8')) > MAX_WORK_LENGTH:
        await query.edit_message_text(
            f"❗ Опис роботи занадто довгий (макс. {MAX_WORK_LENGTH} байт). Спробуйте ще раз:",
            reply_markup=create_keyboard(GoogleSheetsManager.get_recent_values("work", 6), "work")
        )
        return WORK
    
    context.user_data["work"] = work_text
    await ask_for_description(update, context)
    return DESCRIPTION

async def work_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє ручний ввід робіт"""
    text = update.message.text.strip()
    
    if text in SPECIAL_COMMANDS:
        return await handle_text_messages(update, context)
    
    # Перевіряємо довжину тексту роботи
    if len(text.encode('utf-8')) > MAX_WORK_LENGTH:
        await update.message.reply_text(
            f"❗ Опис роботи занадто довгий (макс. {MAX_WORK_LENGTH} байт). Спробуйте ще раз:",
            reply_markup=create_keyboard(GoogleSheetsManager.get_recent_values("work", 6), "work")
        )
        return WORK
    
    context.user_data["work"] = text
    await ask_for_description(update, context)
    return DESCRIPTION

async def ask_for_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запитує додатковий опис"""
    message_text = "Бажаєте додати додатковий опис?"
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                message_text,
                reply_markup=DESCRIPTION_MARKUP
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await update.callback_query.message.reply_text(
                message_text,
                reply_markup=DESCRIPTION_MARKUP
            )
    else:
        await update.message.reply_text(
            message_text,
            reply_markup=DESCRIPTION_MARKUP
        )

async def handle_description(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє додатковий опис"""
    text = update.message.text.strip()
    
    if text in SPECIAL_COMMANDS:
        if text == "⏩ Пропустити":
            context.user_data["description"] = ""
            return await save_and_confirm(update, context)
        elif text == "🔙 Назад":
            return await show_work_options(update, context)
        return DESCRIPTION
    
    context.user_data["description"] = text
    return await save_and_confirm(update, context)

async def save_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Зберігає запис і підтверджує"""
    username = f"@{update.effective_user.username}"
    user_name = context.user_data["user_name"]
    user_level = context.user_data["user_level"]
    
    record_id = GoogleSheetsManager.save_record(context.user_data, username, user_name, user_level)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔙 Назад", callback_data="back")]
    ])
    
    message_text = (
        f"✅ Запис #{record_id} збережено\n"
        f"Виконавець: {context.user_data['executor_name']}\n"
        f"Модель: {context.user_data['model']}\n"
        f"VIN: {context.user_data['vin']}\n"
        f"Робота: {context.user_data['work']}"
    )
    
    if context.user_data.get("description"):
        message_text += f"\nДодатковий опис: {context.user_data['description']}"
    
    if update.callback_query:
        try:
            await update.callback_query.edit_message_text(
                message_text,
                reply_markup=keyboard
            )
        except Exception as e:
            logger.error(f"Error editing message: {e}")
            await update.callback_query.message.reply_text(
                message_text,
                reply_markup=keyboard
            )
    else:
        await update.message.reply_text(
            message_text,
            reply_markup=keyboard
        )
    
    return ConversationHandler.END

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Export data from Google Sheets as a CSV file."""
    username = f"@{update.effective_user.username}"
    if get_user_level(username) != "owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return
    
    try:
        client = GoogleSheetsManager.get_client()
        spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        worksheet = client.open_by_key(spreadsheet_id).sheet1
        
        # Get all values
        all_values = worksheet.get_all_values()
        if not all_values:
            await update.message.reply_text("❌ Дані відсутні")
            return
        
        # Create a temporary CSV file
        temp_file_path = os.path.join(tempfile.gettempdir(), "service_records.csv")
        with open(temp_file_path, mode='w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerows(all_values)
        
        # Send the file
        await update.message.reply_document(
            document=open(temp_file_path, 'rb'),
            filename='service_records.csv'
        )
        
        # Clean up
        os.unlink(temp_file_path)
    except Exception as e:
        logger.error(f"Error exporting data: {e}")
        await update.message.reply_text("❌ Помилка при експорті даних")

async def upload_csv_start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Починає процес завантаження CSV файлу"""
    username = f"@{update.effective_user.username}"
    if get_user_level(username) != "owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return ConversationHandler.END
    
    await update.message.reply_text(
        "Будь ласка, надішліть CSV файл для завантаження. "
        "Файл повинен мати такі стовпці:\n" +
        ", ".join(GoogleSheetsManager.HEADERS),
        reply_markup=UPLOAD_MARKUP
    )
    return UPLOAD_CSV

async def handle_csv_upload(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє завантажений CSV файл"""
    if update.message.text and update.message.text.strip() == "🔙 Назад":
        return await back_to_menu(update, context)
    
    if not update.message.document or not update.message.document.file_name.lower().endswith('.csv'):
        await update.message.reply_text(
            "Будь ласка, надішліть CSV файл (розширення .csv) або натисніть '🔙 Назад'",
            reply_markup=UPLOAD_MARKUP
        )
        return UPLOAD_CSV
    
    try:
        # Завантажуємо файл у тимчасову директорію
        file = await context.bot.get_file(update.message.document.file_id)
        temp_file_path = os.path.join(tempfile.gettempdir(), update.message.document.file_name)
        await file.download_to_drive(temp_file_path)
        
        # Намагаємось замінити дані
        if GoogleSheetsManager.replace_data(temp_file_path):
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

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє текстові повідомлення"""
    username = f"@{update.effective_user.username}"
    user_level = get_user_level(username)
    
    if not user_level:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота")
        return
    
    text = update.message.text.strip()
    
    if text in SPECIAL_COMMANDS:
        if text == "➕ Додати запис":
            await add_record(update, context)
        elif text == "📤 Завантажити дані" and user_level == "owner":
            await export_data(update, context)
        elif text == "📥 Завантажити таблицю" and user_level == "owner":
            await upload_csv_start(update, context)
        elif text == "🔙 Назад":
            await back_to_menu(update, context)
        return
    
    current_state = await context.application.persistence.get_conversation(update.effective_chat.id)
    if current_state:
        if current_state.get('state') == MODEL:
            await model_manual(update, context)
        elif current_state.get('state') == VIN:
            await vin_manual(update, context)
        elif current_state.get('state') == WORK:
            await work_manual(update, context)
        elif current_state.get('state') == DESCRIPTION:
            await handle_description(update, context)
        elif current_state.get('state') == UPLOAD_CSV:
            await handle_csv_upload(update, context)
    else:
        await update.message.reply_text("Оберіть дію з меню")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Логує помилки та повідомляє користувача"""
    logger.error(msg="Exception while handling an update:", exc_info=context.error)
    
    if update and update.effective_message:
        await update.effective_message.reply_text(
            "❌ Сталася помилка. Спробуйте ще раз або зверніться до адміністратора."
        )

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Скасовує поточну бесіду"""
    return await back_to_menu(update, context)

def main() -> None:
    """Запускає бота"""
    if not (token := os.getenv("BOT_TOKEN")):
        logger.error("Не встановлено змінну BOT_TOKEN!")
        return
    
    GoogleSheetsManager.ensure_sheet_exists()
    
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
                MessageHandler(filters.TEXT | filters.Document.ALL, handle_csv_upload),
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