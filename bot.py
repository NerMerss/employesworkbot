import os
import logging
import base64
import json
from typing import Dict, List, Optional
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
import gspread
from google.oauth2.service_account import Credentials

# Константи
MODEL, VIN, WORK, EXECUTOR = range(4)
RECENT_ITEMS_LIMIT = 5

# Списки моделей
TESLA_MODELS = ["Model 3", "Model Y", "Model S", "Model X", "Cybertruck", "Roadster", "Інше (не Tesla)"]
OTHER_MODELS = ["Rivian R1T", "Rivian R1S", "Lucid Air", "Zeekr 001", "Zeekr 007", "Інше"]

# Список спеціальних команд
SPECIAL_COMMANDS = [
    "➕ Додати запис", "🔙 Назад"
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
    [["➕ Додати запис"]],
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

class GoogleSheetsManager:
    HEADERS = ["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "user_level"]
    
    def __init__(self):
        self.credentials = self._get_credentials()
        self.spreadsheet_id = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
        self.sheet_name = "ServiceRecords"
        self.client = None
        self.sheet = None
        self._connect()
    
    def _get_credentials(self):
        """Отримує облікові дані з base64"""
        creds_base64 = os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64")
        if not creds_base64:
            raise ValueError("GOOGLE_SHEETS_CREDENTIALS_BASE64 не встановлено")
        
        creds_json = base64.b64decode(creds_base64).decode('utf-8')
        return Credentials.from_service_account_info(json.loads(creds_json))
    
    def _connect(self):
        """Підключається до Google Sheets"""
        try:
            self.client = gspread.authorize(self.credentials)
            self.sheet = self.client.open_by_key(self.spreadsheet_id).worksheet(self.sheet_name)
            
            # Перевіряємо наявність заголовків
            if not self.sheet.get_values('A1:J1'):
                self.sheet.append_row(self.HEADERS)
        except Exception as e:
            logger.error(f"Помилка підключення до Google Sheets: {e}")
            raise
    
    def get_recent_values(self, field: str, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
        """Отримує останні значення для певного поля"""
        try:
            col_index = self.HEADERS.index(field) + 1  # Google Sheets починає з 1
            values = self.sheet.col_values(col_index)[1:]  # Пропускаємо заголовок
            
            # Видаляємо дублікати та порожні значення
            seen = set()
            unique_values = []
            for val in reversed(values):
                if val and val not in seen:
                    seen.add(val)
                    unique_values.append(val)
                    if len(unique_values) >= limit:
                        break
            
            return unique_values
        except Exception as e:
            logger.error(f"Помилка при отриманні значень: {e}")
            return []
    
    def save_record(self, user_data: Dict[str, str], username: str, user_name: str, user_level: str) -> int:
        """Зберігає запис у таблицю"""
        try:
            # Отримуємо останній ID
            last_id = 0
            ids = self.sheet.col_values(1)[1:]  # Пропускаємо заголовок
            if ids:
                last_id = int(ids[-1]) if ids[-1].isdigit() else 0
            
            new_id = last_id + 1
            timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            
            # Формуємо рядок для додавання
            row = [
                new_id,
                timestamp,
                username,
                user_name,
                user_data["executor"],
                user_data["executor_name"],
                user_data["model"],
                user_data["vin"],
                user_data["work"],
                user_level
            ]
            
            self.sheet.append_row(row)
            return new_id
        except Exception as e:
            logger.error(f"Помилка при збереженні запису: {e}")
            raise

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
    
    if user_level == "owner":
        executors = {**OWNERS, **MANAGERS, **WORKERS}
    else:  # manager
        executors = {username: user_name}
        executors.update(WORKERS)
    
    buttons = []
    for user_id, name in executors.items():
        buttons.append([InlineKeyboardButton(
            name,
            callback_data=f"executor:{user_id}:{name}"
        )])
    
    if user_level == "manager":
        buttons.insert(0, [InlineKeyboardButton(
            f"Я ({user_name})",
            callback_data=f"executor:{username}:{user_name}"
        )])
    
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    
    await update.message.reply_text(
        "Оберіть виконавця:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EXECUTOR

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
    
    sheets_manager = GoogleSheetsManager()
    vins = sheets_manager.get_recent_values("vin")
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
    
    sheets_manager = GoogleSheetsManager()
    vins = sheets_manager.get_recent_values("vin")
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
    sheets_manager = GoogleSheetsManager()
    works = sheets_manager.get_recent_values("work", 6)
    keyboard = create_keyboard(works, "work")
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            "Що було зроблено?",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            "Що було зроблено?",
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
        await query.edit_message_text("Введіть, що було зроблено:")
        return WORK
    
    await save_and_confirm(update, context, work_text)
    return ConversationHandler.END

async def work_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє ручний ввід робіт"""
    text = update.message.text.strip()
    
    if text in SPECIAL_COMMANDS:
        return await handle_text_messages(update, context)
    
    await save_and_confirm(update, context, text)
    return ConversationHandler.END

async def save_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, work_text: str) -> None:
    """Зберігає запис і підтверджує"""
    username = f"@{update.effective_user.username}"
    user_name = context.user_data["user_name"]
    user_level = context.user_data["user_level"]
    
    context.user_data["work"] = work_text
    
    try:
        sheets_manager = GoogleSheetsManager()
        record_id = sheets_manager.save_record(context.user_data, username, user_name, user_level)
        
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("🔙 Назад", callback_data="back")]
        ])
        
        if update.callback_query:
            await update.callback_query.edit_message_text(
                f"✅ Запис #{record_id} збережено\n"
                f"Виконавець: {context.user_data['executor_name']}\n"
                f"Модель: {context.user_data['model']}\n"
                f"VIN: {context.user_data['vin']}\n"
                f"Робота: {work_text}",
                reply_markup=keyboard
            )
        else:
            await update.message.reply_text(
                f"✅ Запис #{record_id} збережено\n"
                f"Виконавець: {context.user_data['executor_name']}\n"
                f"Модель: {context.user_data['model']}\n"
                f"VIN: {context.user_data['vin']}\n"
                f"Робота: {work_text}",
                reply_markup=keyboard
            )
    except Exception as e:
        logger.error(f"Помилка при збереженні запису: {e}")
        await update.effective_message.reply_text(
            "❌ Помилка при збереженні запису. Спробуйте ще раз.",
            reply_markup=ReplyKeyboardRemove()
        )

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
    else:
        await update.message.reply_text("Оберіть дію з меню")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Скасовує поточну бесіду"""
    return await back_to_menu(update, context)

def main() -> None:
    """Запускає бота"""
    if not (token := os.getenv("BOT_TOKEN")):
        logger.error("Не встановлено змінну BOT_TOKEN!")
        return
    
    if not os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64"):
        logger.error("Не встановлено GOOGLE_SHEETS_CREDENTIALS_BASE64!")
        return
    
    if not os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID"):
        logger.error("Не встановлено GOOGLE_SHEETS_SPREADSHEET_ID!")
        return
    
    app = ApplicationBuilder().token(token).build()
    
    # Основний обробник бесіди
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^➕ Додати запис$"), add_record),
            CallbackQueryHandler(back_to_menu, pattern="^back$")
        ],
        states={
            EXECUTOR: [
                CallbackQueryHandler(executor_selected, pattern="^executor:"),
            ],
            MODEL: [
                CallbackQueryHandler(model_selected, pattern="^model:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, model_manual),
            ],
            VIN: [
                CallbackQueryHandler(vin_selected, pattern="^vin:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, vin_manual),
            ],
            WORK: [
                CallbackQueryHandler(work_selected, pattern="^work:"),
                MessageHandler(filters.TEXT & ~filters.COMMAND, work_manual),
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