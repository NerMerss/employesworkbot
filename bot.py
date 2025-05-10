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
MODEL, VIN, WORK = range(3)
CSV_FILE = "records.csv"
RECENT_ITEMS_LIMIT = 5
ADMIN_USERNAMES = {u.strip() for u in os.getenv("ADMIN_USERNAMES", "").split(",") if u.strip()}

# Налаштування логування
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# Клавіатури
ADMIN_MENU_MARKUP = ReplyKeyboardMarkup(
    [
        ["➕ Додати запис"],
        ["🗑 Видалити записи", "📤 Експорт даних"],
        ["🔙 Головне меню"]
    ],
    resize_keyboard=True
)

DELETE_MENU_MARKUP = ReplyKeyboardMarkup(
    [
        ["❌ Видалити ВСЕ"],
        ["🔢 Видалити за ID"],
        ["🔙 Назад"]
    ],
    resize_keyboard=True
)

CONFIRM_MARKUP = ReplyKeyboardMarkup(
    [
        ["✅ Так", "❌ Ні"],
        ["🔙 Назад"]
    ],
    resize_keyboard=True
)

class CSVManager:
    """Клас для роботи з CSV файлом"""
    HEADERS = ["id", "timestamp", "user", "model", "vin", "work"]
    
    @staticmethod
    def ensure_file_exists():
        """Створює CSV файл з заголовками, якщо він не існує"""
        if not os.path.exists(CSV_FILE):
            with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
                csv.writer(f).writerow(CSVManager.HEADERS)
    
    @staticmethod
    def get_recent_values(field: str, limit: int = RECENT_ITEMS_LIMIT) -> List[str]:
        """Отримує останні унікальні значення для вказаного поля"""
        values = []
        seen: Set[str] = set()
        
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
    def save_record(user_data: Dict[str, str], username: str, work_text: str) -> int:
        """Зберігає новий запис і повертає його ID"""
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
    def delete_records(ids_to_remove: Optional[Set[str]] = None) -> bool:
        """Видаляє записи за ID або всі записи"""
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

def create_keyboard(items: List[str], prefix: str) -> InlineKeyboardMarkup:
    """Створює інлайн-клавіатуру з варіантами"""
    buttons = [
        [InlineKeyboardButton(item, callback_data=f"{prefix}:{item}")]
        for item in items
    ]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data=f"{prefix}:manual")])
    return InlineKeyboardMarkup(buttons)

def is_admin(update: Update) -> bool:
    """Перевіряє, чи є користувач адміністратором"""
    if not update.effective_user:
        return False
    username = update.effective_user.username
    return f"@{username}" in ADMIN_USERNAMES if username else False

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Початок взаємодії з ботом"""
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
    """Показує меню адміністратора"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас немає прав адміністратора")
        return
    
    await update.message.reply_text(
        "Меню адміністратора:",
        reply_markup=ADMIN_MENU_MARKUP
    )

async def admin_add_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Починає процес додавання запису для адміністратора"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас немає прав адміністратора")
        return
    
    models = CSVManager.get_recent_values("model")
    await update.message.reply_text(
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
    work_text = update.message.text.strip()
    await save_and_confirm(update, context, work_text)
    return ConversationHandler.END

async def save_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, work_text: str) -> None:
    """Зберігає запис і підтверджує"""
    username = update.effective_user.full_name
    record_id = CSVManager.save_record(context.user_data, username, work_text)
    
    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("➕ Додати ще", callback_data="restart")]
    ])
    
    if update.callback_query:
        await update.callback_query.edit_message_text(
            f"✅ Запис збережено (ID: {record_id})\nЩо було зроблено: {work_text}",
            reply_markup=keyboard
        )
    else:
        await update.message.reply_text(
            f"✅ Запис збережено (ID: {record_id})\nЩо було зроблено: {work_text}",
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
    models = CSVManager.get_recent_values("model")
    await context.bot.send_message(
        chat_id=query.message.chat_id,
        text="Виберіть модель авто або введіть вручну:",
        reply_markup=create_keyboard(models, "model")
    )
    return MODEL

async def show_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Показує меню видалення"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас немає прав адміністратора")
        return
    
    await update.message.reply_text(
        "Оберіть тип видалення:",
        reply_markup=DELETE_MENU_MARKUP
    )

async def ask_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запитує підтвердження для видалення всіх записів"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас немає прав адміністратора")
        return
    
    await update.message.reply_text(
        "❗ Ви впевнені, що хочете видалити ВСІ записи?",
        reply_markup=CONFIRM_MARKUP
    )
    context.user_data["delete_type"] = "all"

async def ask_ids_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Запитує ID записів для видалення"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас немає прав адміністратора")
        return
    
    await update.message.reply_text(
        "Введіть ID записів для видалення (наприклад: 1, 2-5, 7):",
        reply_markup=ReplyKeyboardRemove()
    )
    context.user_data["delete_type"] = "selected"

async def execute_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Виконує видалення записів"""
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас немає прав адміністратора")
        return
    
    delete_type = context.user_data.get("delete_type")
    
    if delete_type == "all":
        if update.message.text == "✅ Так":
            success = CSVManager.delete_records()
            msg = "🗑 Всі записи видалено!" if success else "❌ Помилка при видаленні"
        else:
            msg = "❌ Видалення скасовано"
    elif delete_type == "selected":
        try:
            ids_to_remove = parse_ids(update.message.text)
            success = CSVManager.delete_records(ids_to_remove)
            msg = f"🗑 Видалено записи: {', '.join(sorted(ids_to_remove))}" if success else "❌ Помилка при видаленні"
        except ValueError:
            msg = "❗ Невірний формат ID. Спробуйте ще раз."
            await update.message.reply_text(msg)
            return
    
    await update.message.reply_text(
        msg,
        reply_markup=ADMIN_MENU_MARKUP
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
    if not is_admin(update):
        await update.message.reply_text("⛔ У вас немає прав адміністратора")
        return
    
    if not os.path.exists(CSV_FILE):
        await update.message.reply_text("❌ Файл даних не знайдено")
        return
    
    await update.message.reply_document(
        document=open(CSV_FILE, 'rb'),
        filename='car_records.csv'
    )

async def handle_admin_commands(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Обробляє команди адміністратора"""
    text = update.message.text
    
    if text == "➕ Додати запис":
        await admin_add_record(update, context)
    elif text == "🗑 Видалити записи":
        await show_delete_menu(update, context)
    elif text == "📤 Експорт даних":
        await export_data(update, context)
    elif text == "🔙 Головне меню":
        await update.message.reply_text(
            "Головне меню",
            reply_markup=ReplyKeyboardRemove()
        )
    elif text == "❌ Видалити ВСЕ":
        await ask_delete_confirmation(update, context)
    elif text == "🔢 Видалити за ID":
        await ask_ids_to_delete(update, context)
    elif text == "🔙 Назад":
        await show_admin_menu(update, context)
    elif text in ["✅ Так", "❌ Ні"]:
        await execute_deletion(update, context)
    elif "delete_type" in context.user_data:
        await execute_deletion(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    """Скасовує поточну бесіду"""
    await update.message.reply_text(
        "❌ Дію скасовано",
        reply_markup=ReplyKeyboardRemove()
    )
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
            MessageHandler(filters.Regex("^➕ Додати запис$"), admin_add_record),
            CallbackQueryHandler(restart_conversation, pattern="^restart$")
        ],
        states={
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
    app.add_handler(CommandHandler("admin", show_admin_menu))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_commands))
    
    logger.info("Бот запущений...")
    app.run_polling()

if __name__ == '__main__':
    main()