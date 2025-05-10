import os
import csv
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import datetime

MODEL, VIN, WORK = range(3)
CSV_FILE = "records.csv"
ADMIN_USERNAMES = os.getenv("ADMIN_USERNAMES", "").split(",")  # список Telegram username админов

# Убедимся, что CSV существует с заголовками
if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["id", "timestamp", "user", "model", "vin", "work"])

def get_recent_values(field, limit=5):
    values = []
    seen = set()
    if not os.path.exists(CSV_FILE):
        return []
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        reader = csv.DictReader(f)
        rows = list(reader)[::-1]  # Сначала последние
        for row in rows:
            val = row.get(field)
            if val and val not in seen:
                seen.add(val)
                values.append(val)
                if len(values) >= limit:
                    break
    return values

async def send_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    is_admin = f"@{username}" in ADMIN_USERNAMES

    reply_keyboard = [["➕ Додати запис"]]
    if is_admin:
        reply_keyboard.append(["📁 Експорт", "🗑 Очистити"])

    if update.message:
        await update.message.reply_text("📋 Оберіть дію:", reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True))
    elif update.callback_query:
        await update.callback_query.message.reply_text("📋 Оберіть дію:", reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True))

    return
    username = update.effective_user.username
    is_admin = f"@{username}" in ADMIN_USERNAMES

    reply_keyboard = [["➕ Додати запис"]]
    if is_admin:
        reply_keyboard.append(["📁 Експорт", "🗑 Очистити"])

    await update.message.reply_text(
        "📋 Оберіть дію:",
        reply_markup=ReplyKeyboardMarkup(reply_keyboard, resize_keyboard=True)
    )
    username = update.effective_user.username
    is_admin = f"@{username}" in ADMIN_USERNAMES

    keyboard = [
        [InlineKeyboardButton("➕ Додати запис", callback_data="restart")],
    ]
    if is_admin:
        keyboard.append([InlineKeyboardButton("📁 Експорт", callback_data="menu_export")])
        keyboard.append([InlineKeyboardButton("🗑 Очистити", callback_data="menu_clear")])

    await update.message.reply_text("📋 Меню:", reply_markup=InlineKeyboardMarkup(keyboard))



    models = get_recent_values("model")
    keyboard = [[InlineKeyboardButton(model, callback_data=f"model:{model}")] for model in models]
    keyboard.append([InlineKeyboardButton("Ввести вручну", callback_data="model:manual")])

    if update.message:
        await update.message.reply_text("Виберіть модель авто або введіть вручну:", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.message.reply_text("Виберіть модель авто або введіть вручну:", reply_markup=InlineKeyboardMarkup(keyboard))
    return MODEL

async def model_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = query.data.split("model:")[1]
    if selected == "manual":
        await query.edit_message_text("Введіть модель авто:")
        return MODEL
    context.user_data["model"] = selected

    vins = get_recent_values("vin", 5)
    keyboard = [[InlineKeyboardButton(vin, callback_data=f"vin:{vin}")] for vin in vins]
    keyboard.append([InlineKeyboardButton("Ввести вручну", callback_data="vin:manual")])
    await query.edit_message_text("Оберіть VIN або введіть вручну:", reply_markup=InlineKeyboardMarkup(keyboard))
    return VIN

async def model_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["model"] = update.message.text.strip()
    return await ask_vin(update, context)

async def ask_vin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vins = get_recent_values("vin", 5)
    keyboard = [[InlineKeyboardButton(vin, callback_data=f"vin:{vin}")] for vin in vins]
    keyboard.append([InlineKeyboardButton("Ввести вручну", callback_data="vin:manual")])
    await update.message.reply_text("Оберіть VIN або введіть вручну:", reply_markup=InlineKeyboardMarkup(keyboard))
    return VIN

async def vin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = query.data.split("vin:")[1]
    if selected == "manual":
        await query.edit_message_text("Введіть останні 6 символів VIN:")
        return VIN
    context.user_data["vin"] = selected
    await query.edit_message_text(f"VIN: {selected}")
    return await show_work_options(update, context)

async def vin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vin_input = update.message.text.strip()
    if len(vin_input) != 6 or not vin_input.isalnum():
        await update.message.reply_text("❗ Введіть рівно 6 символів VIN.")
        return VIN
    context.user_data["vin"] = vin_input.upper()
    return await show_work_options(update, context)

async def show_work_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    works = get_recent_values("work", 6)
    keyboard = [[InlineKeyboardButton(work, callback_data=f"work:{work}")] for work in works]
    keyboard.append([InlineKeyboardButton("Інше (ввести вручну)", callback_data="work:manual")])
    if update.message:
        await update.message.reply_text("Що було зроблено?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.message.reply_text("Що було зроблено?", reply_markup=InlineKeyboardMarkup(keyboard))
    return WORK

async def work_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    selected = query.data.split("work:")[1]
    if selected == "manual":
        await query.edit_message_text("Введіть, що було зроблено:")
        return WORK
    await save_record(query.from_user.full_name, context, selected)
    keyboard = [[InlineKeyboardButton("➕ Додати ще", callback_data="restart")]]
    await query.edit_message_text(f"✅ Записано: {selected}", reply_markup=InlineKeyboardMarkup(keyboard))
    await send_main_menu(update, context)
    await send_main_menu(update, context)
    return ConversationHandler.END

async def work_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    work_text = update.message.text.strip()
    await save_record(update.message.from_user.full_name, context, work_text)
    keyboard = [[InlineKeyboardButton("➕ Додати ще", callback_data="restart")]]
    await update.message.reply_text("✅ Записано. Дякуємо!", reply_markup=InlineKeyboardMarkup(keyboard))
    await send_main_menu(update, context)
    return ConversationHandler.END

async def save_record(user, context, work_text):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        existing_rows = list(csv.reader(f))
    next_id = len(existing_rows) if existing_rows else 1
    row = [str(next_id), timestamp, user, context.user_data["model"], context.user_data["vin"], work_text]
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(row)

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.callback_query:
        await update.callback_query.answer()
        message = update.callback_query.message
        fake_update = Update(update.update_id, message=message)
        return await start(fake_update, context)
    elif update.message:
        return await start(update, context)
    elif update.callback_query:
        return await start(update.callback_query, context)
    elif update.message:
        return await start(update, context)
        await update.callback_query.answer()
    return await start(update, context)

async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if f"@{username}" not in ADMIN_USERNAMES:
        await update.message.reply_text("⛔ У вас немає доступу до експорту.")
        return
    if not os.path.exists(CSV_FILE):
        await update.message.reply_text("❌ CSV файл не знайдено.")
        return
    await update.message.reply_document(document=open(CSV_FILE, "rb"), filename="records.csv")

async def clear_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if f"@{username}" not in ADMIN_USERNAMES:
        await update.message.reply_text("⛔ У вас немає прав для очищення бази.")
        return

    keyboard = [
        ["🧹 Очистити все"],
        ["🗂 Очистити певні записи"],
        ["⬅ Повернутися до меню"]
    ]
    from telegram import ReplyKeyboardMarkup
    await update.message.reply_text(
        "🔧 Оберіть варіант очищення:",
        reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    )
    return
    if len(args) > 1:
        try:
            arg = args[1]
            if "-" in arg:
                start_id, end_id = map(int, arg.split("-"))
                ids_to_remove = set(str(i) for i in range(start_id, end_id + 1))
            else:
                ids_to_remove = {str(int(arg))}
        except ValueError:
            await update.message.reply_text("❗ Неправильний формат. Використовуйте /clear або /clear 12 або /clear 5-8")
            return

        with open(CSV_FILE, newline='', encoding='utf-8') as f:
            rows = list(csv.reader(f))
        header, data = rows[0], rows[1:]
        new_data = [row for row in data if row[0] not in ids_to_remove]
        keyboard = [[InlineKeyboardButton("✅ Так, видалити ці записи", callback_data=f"confirm_partial_clear:{','.join(sorted(ids_to_remove))}")]]
        await update.message.reply_text(
            f"🔸 Ви вибрали для видалення записи: {', '.join(sorted(ids_to_remove))}. Підтвердити?",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )
        return
        return

    keyboard = [[InlineKeyboardButton("Так, очистити ВСЕ", callback_data="confirm_clear")]]
    await update.message.reply_text(
        "❗ Ви впевнені, що хочете видалити ВСІ записи?",
        reply_markup=InlineKeyboardMarkup(keyboard)
    )
    await update.message.reply_text(
        "Якщо хочете видалити певний запис або проміжок — напишіть номер у форматі \"1\" або \"1-20\" нижче повідомленням."
    )


async def confirm_clear_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if f"@{username}" not in ADMIN_USERNAMES:
        await update.callback_query.answer("⛔ Немає доступу.", show_alert=True)
        return
    await update.callback_query.answer()
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(["timestamp", "user", "model", "vin", "work"])
    await update.callback_query.edit_message_text("🗑 Усі записи видалено.")
    await context.bot.delete_message(chat_id=update.effective_chat.id, message_id=update.callback_query.message.message_id, delay=5)


async def confirm_partial_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    username = update.effective_user.username
    if f"@{username}" not in ADMIN_USERNAMES:
        await update.callback_query.answer("⛔ Немає доступу.", show_alert=True)
        return
    await update.callback_query.answer()
    ids_to_remove = update.callback_query.data.split(":")[1].split(",")
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    new_data = [row for row in data if row[0] not in ids_to_remove]
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(new_data)
    await update.callback_query.edit_message_text(f"🗑 Видалено записи: {', '.join(ids_to_remove)}")


async def handle_menu_buttons(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    username = update.effective_user.username
    is_admin = f"@{username}" in ADMIN_USERNAMES

    if query.data == "menu_export" and is_admin:
        if not os.path.exists(CSV_FILE):
            await query.edit_message_text("❌ CSV файл не знайдено.")
        else:
            await context.bot.send_document(chat_id=update.effective_chat.id, document=open(CSV_FILE, "rb"), filename="records.csv")

    elif query.data == "menu_clear" and is_admin:
        keyboard = [[InlineKeyboardButton("Так, очистити ВСЕ", callback_data="confirm_clear")]]
        await query.edit_message_text("❗ Ви впевнені, що хочете видалити ВСІ записи?", reply_markup=InlineKeyboardMarkup(keyboard))


async def confirm_clear_prompt(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [[InlineKeyboardButton("✅ Так, очистити", callback_data="confirm_clear")]]
    await update.message.reply_text("❗ Ви впевнені, що хочете видалити ВСІ записи?", reply_markup=InlineKeyboardMarkup(keyboard))


async def prompt_partial_clear(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
    "✏️ Введіть номери записів, які потрібно видалити. Наприклад: `1`, `2-4`, `1,3`, `1-2,5-6`",
    parse_mode="Markdown"
)

async def handle_partial_clear_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_clear_input"):
        return
    text = update.message.text.strip()
    import re
    ids = set()
    for part in text.split(","):
        part = part.strip()
        if re.fullmatch(r"\d+", part):
            ids.add(part)
        elif re.fullmatch(r"\d+-\d+", part):
            start, end = map(int, part.split("-"))
            ids.update(str(i) for i in range(start, end + 1))
    if not ids:
        await update.message.reply_text("❗ Неправильний формат. Спробуйте ще раз.")
        return
    context.user_data.pop("awaiting_clear_input", None)
    confirm_text = f"🔸 Ви вибрали для видалення записи: {', '.join(sorted(ids))}. Підтвердити?"
    keyboard = [[InlineKeyboardButton("✅ Так, видалити ці записи", callback_data=f"confirm_partial_clear:{','.join(sorted(ids))}")]]
    await update.message.reply_text(confirm_text, reply_markup=InlineKeyboardMarkup(keyboard))


async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Скасовано.")
    return ConversationHandler.END

if __name__ == '__main__':
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", send_main_menu),
            CallbackQueryHandler(model_selected, pattern="^model:")
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
    app.add_handler(CallbackQueryHandler(restart, pattern="^restart$"))
    app.add_handler(CommandHandler("menu", send_main_menu))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^➕ Додати запис$"), restart))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📁 Експорт$"), export_csv))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🗑 Очистити$"), clear_csv))
    app.add_handler(CallbackQueryHandler(handle_menu_buttons, pattern="^menu_"))
    app.add_handler(CommandHandler("export", export_csv))
    app.add_handler(CommandHandler("clear", clear_csv))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🧹 Очистити все$"), confirm_clear_prompt))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🗂 Очистити певні записи$"), prompt_partial_clear))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^⬅ Повернутися до меню$"), cancel))
    app.add_handler(CallbackQueryHandler(confirm_clear_csv, pattern="^confirm_clear$"))
    app.add_handler(CallbackQueryHandler(confirm_partial_clear, pattern="^confirm_partial_clear:"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_partial_clear_input))
    app.run_polling()
