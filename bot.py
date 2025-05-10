import os
import csv
import datetime
import re
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

MODEL, VIN, WORK = range(3)
CSV_FILE = "records.csv"
ADMIN_USERNAMES = os.getenv("ADMIN_USERNAMES", "").split(",")

if not os.path.exists(CSV_FILE):
    with open(CSV_FILE, mode='w', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow(["id", "timestamp", "user", "model", "vin", "work"])

def get_recent_values(field, limit=5):
    seen, values = set(), []
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        for row in list(csv.DictReader(f))[::-1]:
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
    buttons = [["➕ Додати запис"]]
    if is_admin:
        buttons.append(["📁 Експорт", "🗑 Очистити"])
    await update.message.reply_text("📋 Оберіть дію:", reply_markup=ReplyKeyboardMarkup(buttons, resize_keyboard=True))

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    models = get_recent_values("model")
    keyboard = [[InlineKeyboardButton(m, callback_data=f"model:{m}")] for m in models]
    keyboard.append([InlineKeyboardButton("Ввести вручну", callback_data="model:manual")])
    await update.message.reply_text("Виберіть модель авто або введіть вручну:", reply_markup=InlineKeyboardMarkup(keyboard))
    return MODEL

async def model_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    selected = update.callback_query.data.split(":")[1]
    if selected == "manual":
        await update.callback_query.edit_message_text("Введіть модель авто:")
        return MODEL
    context.user_data["model"] = selected
    vins = get_recent_values("vin")
    keyboard = [[InlineKeyboardButton(v, callback_data=f"vin:{v}")] for v in vins]
    keyboard.append([InlineKeyboardButton("Ввести вручну", callback_data="vin:manual")])
    await update.callback_query.edit_message_text("Оберіть VIN або введіть вручну:", reply_markup=InlineKeyboardMarkup(keyboard))
    return VIN

async def model_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["model"] = update.message.text.strip()
    return await ask_vin(update, context)

async def ask_vin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vins = get_recent_values("vin")
    keyboard = [[InlineKeyboardButton(v, callback_data=f"vin:{v}")] for v in vins]
    keyboard.append([InlineKeyboardButton("Ввести вручну", callback_data="vin:manual")])
    await update.message.reply_text("Оберіть VIN або введіть вручну:", reply_markup=InlineKeyboardMarkup(keyboard))
    return VIN

async def vin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    selected = update.callback_query.data.split(":")[1]
    if selected == "manual":
        await update.callback_query.edit_message_text("Введіть останні 6 символів VIN:")
        return VIN
    context.user_data["vin"] = selected
    return await show_work_options(update, context)

async def vin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vin = update.message.text.strip().upper()
    if len(vin) != 6 or not vin.isalnum():
        await update.message.reply_text("❗ Введіть рівно 6 символів VIN.")
        return VIN
    context.user_data["vin"] = vin
    return await show_work_options(update, context)

async def show_work_options(update: Update, context: ContextTypes.DEFAULT_TYPE):
    works = get_recent_values("work")
    keyboard = [[InlineKeyboardButton(w, callback_data=f"work:{w}")] for w in works]
    keyboard.append([InlineKeyboardButton("Інше (ввести вручну)", callback_data="work:manual")])
    if update.message:
        await update.message.reply_text("Що було зроблено?", reply_markup=InlineKeyboardMarkup(keyboard))
    else:
        await update.callback_query.message.reply_text("Що було зроблено?", reply_markup=InlineKeyboardMarkup(keyboard))
    return WORK

async def work_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.callback_query.answer()
    selected = update.callback_query.data.split(":")[1]
    if selected == "manual":
        await update.callback_query.edit_message_text("Введіть, що було зроблено:")
        return WORK
    await save_record(update.callback_query.from_user.full_name, context, selected)
    await update.callback_query.edit_message_text(f"✅ Записано: {selected}")
    await send_main_menu(update, context)
    return ConversationHandler.END

async def work_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await save_record(update.message.from_user.full_name, context, update.message.text.strip())
    await update.message.reply_text("✅ Записано. Дякуємо!")
    await send_main_menu(update, context)
    return ConversationHandler.END

async def save_record(user, context, work):
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        next_id = len(list(csv.reader(f)))
    with open(CSV_FILE, 'a', newline='', encoding='utf-8') as f:
        csv.writer(f).writerow([
            str(next_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            user, context.user_data["model"], context.user_data["vin"], work
        ])

async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if f"@{update.effective_user.username}" not in ADMIN_USERNAMES:
        await update.message.reply_text("⛔ У вас немає доступу до експорту.")
        return
    await update.message.reply_document(document=open(CSV_FILE, "rb"), filename="records.csv")

async def clear_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if f"@{update.effective_user.username}" not in ADMIN_USERNAMES:
        await update.message.reply_text("⛔ У вас немає прав для очищення бази.")
        return
    context.user_data["awaiting_clear_input"] = True
    await update.message.reply_text("✏️ Введіть номери записів для видалення. Наприклад: `1`, `2-4`, `5,7`, `1-2,4-6`", parse_mode="Markdown")

async def handle_partial_clear_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.user_data.get("awaiting_clear_input"):
        return
    text = update.message.text.strip()
    ids = set()
    for part in text.split(","):
        part = part.strip()
        if re.fullmatch(r"\d+", part):
            ids.add(part)
        elif re.fullmatch(r"\d+-\d+", part):
            start, end = map(int, part.split("-"))
            ids.update(str(i) for i in range(start, end + 1))
    context.user_data.pop("awaiting_clear_input", None)
    if not ids:
        await update.message.reply_text("❗ Неправильний формат. Спробуйте ще раз.")
        return
    with open(CSV_FILE, newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
    header, data = rows[0], rows[1:]
    remaining = [row for row in data if row[0] not in ids]
    with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
        writer = csv.writer(f)
        writer.writerow(header)
        writer.writerows(remaining)
    await update.message.reply_text(f"🗑 Видалено записи: {', '.join(sorted(ids))}")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Скасовано.")
    return ConversationHandler.END

if __name__ == '__main__':
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[CommandHandler("start", start)],
        states={
            MODEL: [CallbackQueryHandler(model_selected, pattern="^model:"), MessageHandler(filters.TEXT & ~filters.COMMAND, model_manual)],
            VIN: [CallbackQueryHandler(vin_selected, pattern="^vin:"), MessageHandler(filters.TEXT & ~filters.COMMAND, vin_manual)],
            WORK: [CallbackQueryHandler(work_selected, pattern="^work:"), MessageHandler(filters.TEXT & ~filters.COMMAND, work_manual)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    app.add_handler(conv_handler)
    app.add_handler(CommandHandler("menu", send_main_menu))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^➕ Додати запис$"), start))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^📁 Експорт$"), export_csv))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^🗑 Очистити$"), clear_csv))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_partial_clear_input))
    app.run_polling()
