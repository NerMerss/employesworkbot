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

# Константи
MODEL, VIN, WORK, EXECUTOR = range(4)
CSV_FILE = "records.csv"
RECENT_ITEMS_LIMIT = 5

def parse_user_list(env_var: str) -> dict:
    """Парсить список користувачів у форматі { '@username': 'Ім'я Прізвище' }"""
    users = {}
    for item in os.getenv(env_var, "").split(","):
        if not item.strip():
            continue
        parts = item.strip().split(" ", 1)  # Розділяємо тільки по першому пробілу
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
    [["➕ Додати запис"], ["🗑 Видалити записи", "📤 Експорт даних"]],
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

DELETE_MENU = ReplyKeyboardMarkup(
    [["❌ Видалити ВСЕ"], ["🔢 Видалити за ID"], ["🔙 Назад"]],
    resize_keyboard=True
)

CONFIRM_MARKUP = ReplyKeyboardMarkup(
    [["✅ Так", "❌ Ні"]],
    resize_keyboard=True
)

class CSVManager:
    HEADERS = ["id", "timestamp", "user", "user_name", "executor", "executor_name", "model", "vin", "work", "user_level"]
    
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
                user_level
            ])
        return next_id
    
    @staticmethod
    def delete_records(ids_to_remove: Optional[Set[str]] = None) -> bool:
        try:
            with open(CSV_FILE, 'r', newline='', encoding='utf-8') as f:
                rows = list(csv.reader(f))
            
            if not rows:
                return False
            
            header, data = rows[0], rows[1:]
            new_data = [row for row in data if not ids_to_remove or row[0] not in ids_to_remove]
            
            with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow(header)
                writer.writerows(new_data)
            return True
        except Exception as e:
            logger.error(f"Помилка при видаленні: {e}")
            return False

def get_user_level(username: str) -> Optional[str]:
    """Повертає рівень доступу користувача"""
    username = f"@{username}" if not username.startswith("@") else username
    if username in OWNERS:
        return "owner"
    elif username in MANAGERS:
        return "manager"
    elif username in WORKERS:
        return "worker"
    return None

def create_keyboard(items: List[str], prefix: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(item, callback_data=f"{prefix}:{item}")] for item in items]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data=f"{prefix}:manual")])
    return InlineKeyboardMarkup(buttons)

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
    
    # Для працівників одразу встановлюємо себе як виконавця
    if user_level == "worker":
        context.user_data["executor"] = username
        context.user_data["executor_name"] = user_name
        models = CSVManager.get_recent_values("model")
        await update.message.reply_text(
            "Виберіть модель авто або введіть вручну:",
            reply_markup=create_keyboard(models, "model")
        )
        return MODEL
    
    # Для власників та керівників формуємо список виконавців
    if user_level == "owner":
        executors = {**OWNERS, **MANAGERS, **WORKERS}
    else:  # manager
        executors = {username: user_name}
        executors.update(WORKERS)
    
    # Створюємо кнопки з іменами
    buttons = []
    for user_id, name in executors.items():
        buttons.append([InlineKeyboardButton(
            f"{user_id} {name}",
            callback_data=f"executor:{user_id}:{name}"
        )])
    
    await update.message.reply_text(
        "Оберіть виконавця:",
        reply_markup=InlineKeyboardMarkup(buttons)
    )
    return EXECUTOR

async def executor_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір виконавця"""
    query = update.callback_query
    await query.answer()
    
    _, user_id, name = query.data.split(":", 2)
    context.user_data["executor"] = user_id
    context.user_data["executor_name"] = name
    
    models = CSVManager.get_recent_values("model")
    await query.edit_message_text(
        "Виберіть модель авто або введіть вручну:",
        reply_markup=create_keyboard(models, "model")
    )
    return MODEL

async def model_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір моделі"""
    query = update.callback_query
    await query.answer()
    
    selected = query.data.split(":")[1]
    if selected == "manual":
        await query.edit_message_text("Введіть модель авто:")
        return MODEL
    
    context.user_data["model"] = selected
    vins = CSVManager.get_recent_values("vin")
    await query.edit_message_text(
        "Оберіть VIN або введіть вручну:",
        reply_markup=create_keyboard(vins, "vin")
    )
    return VIN

async def model_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє ручний ввід моделі"""
    if update.message.text in ["🗑 Видалити записи", "📤 Експорт даних"]:
        return await handle_text_messages(update, context)
    
    context.user_data["model"] = update.message.text.strip()
    vins = CSVManager.get_recent_values("vin")
    await update.message.reply_text(
        "Оберіть VIN або введіть вручну:",
        reply_markup=create_keyboard(vins, "vin")
    )
    return VIN

async def vin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє вибір VIN"""
    query = update.callback_query
    await query.answer()
    
    selected = query.data.split(":")[1]
    if selected == "manual":
        await query.edit_message_text("Введіть останні 6 символів VIN:")
        return VIN
    
    context.user_data["vin"] = selected
    await query.edit_message_text(f"VIN: {selected}")
    return await show_work_options(update, context)

async def vin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє ручний ввід VIN"""
    if update.message.text in ["🗑 Видалити записи", "📤 Експорт даних"]:
        return await handle_text_messages(update, context)
    
    vin_input = update.message.text.strip()
    if len(vin_input) != 6 or not vin_input.isalnum():
        await update.message.reply_text("❗ Введіть рівно 6 символів VIN.")
        return VIN
    context.user_data["vin"] = vin_input.upper()
    return await show_work_options(update, context)

async def show_work_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Показує варіанти робіт"""
    works = CSVManager.get_recent_values("work", 6)
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
    
    work_text = query.data.split(":")[1]
    if work_text == "manual":
        await query.edit_message_text("Введіть, що було зроблено:")
        return WORK
    
    await save_and_confirm(update, context, work_text)
    return ConversationHandler.END

async def work_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє ручний ввід робіт"""
    if update.message.text in ["🗑 Видалити записи", "📤 Експорт даних"]:
        return await handle_text_messages(update, context)
    
    work_text = update.message.text.strip()
    await save_and_confirm(update, context, work_text)
    return ConversationHandler.END

async def save_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, work_text: str) -> None:
    """Зберігає запис і підтверджує"""
    username = f"@{update.effective_user.username}"
    user_name = context.user_data["user_name"]
    user_level = context.user_data["user_level"]
    
    context.user_data["work"] = work_text
    record_id = CSVManager.save_record(context.user_data, username, user_name, user_level)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати ще", callback_data="restart")]
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

async def restart_conversation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Обробляє натискання кнопки 'Додати ще'"""
    query = update.callback_query
    await query.answer()
    
    # Очищаємо попередні дані
    context.user_data.clear()
    
    # Видаляємо попереднє повідомлення
    try:
        await query.delete_message()
    except Exception as e:
        logger.error(f"Не вдалося видалити повідомлення: {e}")
    
    # Починаємо нову бесіду
    return await add_record(update, context)

async def show_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує меню видалення"""
    username = f"@{update.effective_user.username}"
    if get_user_level(username) != "owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return
    
    await update.message.reply_text(
        "Оберіть тип видалення:",
        reply_markup=DELETE_MENU
    )

async def ask_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запитує підтвердження для видалення всіх записів"""
    username = f"@{update.effective_user.username}"
    if get_user_level(username) != "owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return
    
    await update.message.reply_text(
        "❗ Ви впевнені, що хочете видалити ВСІ записи?",
        reply_markup=CONFIRM_MARKUP
    )
    context.user_data["delete_type"] = "all"

async def ask_ids_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запитує ID записів для видалення"""
    username = f"@{update.effective_user.username}"
    if get_user_level(username) != "owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return
    
    await update.message.reply_text(
        "Введіть ID записів для видалення (наприклад: 1, 2-5, 7):",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data["delete_type"] = "selected"

async def execute_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Виконує видалення записів"""
    username = f"@{update.effective_user.username}"
    if get_user_level(username) != "owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return
    
    delete_type = context.user_data.get("delete_type")
    
    if delete_type == "all":
        if update.message.text == "✅ Так":
            success = CSVManager.delete_records()
            msg = "🗑 Всі записи видалено!" if success else "❌ Помилка при видаленні"
            await update.message.reply_text(msg, reply_markup=OWNER_MENU)
        else:
            await update.message.reply_text("❌ Видалення скасовано", reply_markup=OWNER_MENU)
    elif delete_type == "selected":
        try:
            ids_to_remove = parse_ids(update.message.text)
            success = CSVManager.delete_records(ids_to_remove)
            msg = f"🗑 Видалено записи: {', '.join(sorted(ids_to_remove))}" if success else "❌ Помилка при видаленні"
            await update.message.reply_text(msg, reply_markup=OWNER_MENU)
        except ValueError:
            await update.message.reply_text(
                "❗ Невірний формат ID. Спробуйте ще раз.",
                reply_markup=OWNER_MENU
            )
    
    context.user_data.pop("delete_type", None)

def parse_ids(id_str: str) -> Set[str]:
    """Розбирає рядок з ID на множину"""
    ids = set()
    parts = [p.strip() for p in id_str.split(",") if p.strip()]
    
    for part in parts:
        if "-" in part:
            start, end = map(int, part.split("-"))
            ids.update(str(i) for i in range(start, end + 1))
        else:
            ids.add(part)
    return ids

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Експортує дані у CSV"""
    username = f"@{update.effective_user.username}"
    if get_user_level(username) != "owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return
    
    if not os.path.exists(CSV_FILE):
        await update.message.reply_text("❌ Файл даних не знайдено")
        return
    
    await update.message.reply_document(
        document=open(CSV_FILE, 'rb'),
        filename='service_records.csv'
    )

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє текстові повідомлення"""
    username = f"@{update.effective_user.username}"
    user_level = get_user_level(username)
    
    if not user_level:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота")
        return
    
    text = update.message.text
    
    if text == "➕ Додати запис":
        await add_record(update, context)
    elif text == "🗑 Видалити записи" and user_level == "owner":
        await show_delete_menu(update, context)
    elif text == "📤 Експорт даних" and user_level == "owner":
        await export_data(update, context)
    elif text == "❌ Видалити ВСЕ" and user_level == "owner":
        await ask_delete_confirmation(update, context)
    elif text == "🔢 Видалити за ID" and user_level == "owner":
        await ask_ids_to_delete(update, context)
    elif text in ["✅ Так", "❌ Ні"] and user_level == "owner":
        await execute_deletion(update, context)
    elif "delete_type" in context.user_data and user_level == "owner":
        await execute_deletion(update, context)
    else:
        # Перевіряємо, чи це частина бесіди
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
    username = f"@{update.effective_user.username}"
    user_level = get_user_level(username)
    
    if not user_level:
        await update.message.reply_text("⛔ У вас немає доступу")
        return ConversationHandler.END
    
    if user_level == "owner":
        await update.message.reply_text("❌ Дію скасовано", reply_markup=OWNER_MENU)
    elif user_level == "manager":
        await update.message.reply_text("❌ Дію скасовано", reply_markup=MANAGER_MENU)
    else:
        await update.message.reply_text("❌ Дію скасовано", reply_markup=WORKER_MENU)
    
    context.user_data.clear()
    return ConversationHandler.END

def main() -> None:
    """Запускає бота"""
    if not (token := os.getenv("BOT_TOKEN")):
        logger.error("Не встановлено змінну BOT_TOKEN!")
        return
    
    CSVManager.ensure_file_exists()
    
    app = ApplicationBuilder().token(token).build()
    
    # Основний обробник бесіди
    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^➕ Додати запис$"), add_record),
            CallbackQueryHandler(restart_conversation, pattern="^restart$")
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