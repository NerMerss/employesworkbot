import os
import csv
import logging
import datetime
from telegram import Update, InlineKeyboardMarkup, InlineKeyboardButton, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)

MODEL, VIN, WORK = range(3)
CSV_FILE = "/data/records.csv"
RECENT_ITEMS_LIMIT = 5

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def ensure_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, 'w', newline='', encoding='utf-8') as f:
            csv.writer(f).writerow(["id", "timestamp", "model", "vin", "work"])

def get_recent(field):
    try:
        with open(CSV_FILE, newline='', encoding='utf-8') as f:
            return list({row[field] for row in csv.DictReader(f) if row[field]})[-RECENT_ITEMS_LIMIT:]
    except FileNotFoundError:
        return []

def save_record(model, vin, work):
    ensure_csv()
    with open(CSV_FILE, 'a+', newline='', encoding='utf-8') as f:
        rows = list(csv.reader(f))
        new_id = int(rows[-1][0]) + 1 if len(rows) > 1 else 1
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        csv.writer(f).writerow([new_id, timestamp, model, vin, work])
    return new_id

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [["➕ Додати запис"], ["📤 Експорт CSV", "📥 Завантажити CSV"]]
    await update.message.reply_text("Оберіть дію:", reply_markup=ReplyKeyboardMarkup(keyboard, resize_keyboard=True))

async def add_record(update: Update, context: ContextTypes.DEFAULT_TYPE):
    models = ["Model 3", "Model Y", "Model S", "Model X", "Cybertruck", "Інше"]
    buttons = [[InlineKeyboardButton(m, callback_data=f"model:{m}")] for m in models]
    await update.message.reply_text("Виберіть модель:", reply_markup=InlineKeyboardMarkup(buttons))
    return MODEL

async def select_model(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    context.user_data['model'] = query.data.split(":")[1]

    recent_vins = get_recent('vin')
    buttons = [[InlineKeyboardButton(v, callback_data=f"vin:{v}")] for v in recent_vins]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data="vin:manual")])

    await query.edit_message_text("Оберіть VIN або введіть вручну:", reply_markup=InlineKeyboardMarkup(buttons))
    return VIN

async def select_vin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    vin = query.data.split(":")[1]

    if vin == "manual":
        await query.edit_message_text("Введіть VIN (6 символів):")
        return VIN

    context.user_data['vin'] = vin
    recent_works = get_recent('work')
    buttons = [[InlineKeyboardButton(w, callback_data=f"work:{w}")] for w in recent_works]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data="work:manual")])

    await query.edit_message_text("Оберіть роботу:", reply_markup=InlineKeyboardMarkup(buttons))
    return WORK

async def manual_vin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    vin = update.message.text.strip()
    if len(vin) != 6:
        await update.message.reply_text("VIN повинен бути 6 символів.")
        return VIN
    context.user_data['vin'] = vin.upper()

    recent_works = get_recent('work')
    buttons = [[InlineKeyboardButton(w, callback_data=f"work:{w}")] for w in recent_works]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data="work:manual")])

    await update.message.reply_text("Оберіть роботу:", reply_markup=InlineKeyboardMarkup(buttons))
    return WORK

async def select_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    work = query.data.split(":")[1]

    if work == "manual":
        await query.edit_message_text("Опишіть роботу:")
        return WORK

    return await save_and_finish(update, context, work)

async def manual_work(update: Update, context: ContextTypes.DEFAULT_TYPE):
    work = update.message.text.strip()
    return await save_and_finish(update, context, work)

async def save_and_finish(update, context, work):
    record_id = save_record(context.user_data['model'], context.user_data['vin'], work)
    await update.effective_message.reply_text(f"✅ Запис #{record_id} збережено.")
    return ConversationHandler.END

async def export_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    ensure_csv()
    await update.message.reply_document(open(CSV_FILE, 'rb'))

async def upload_csv(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Надішліть CSV-файл:")

async def handle_csv_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    document = update.message.document
    if document.mime_type != 'text/csv':
        await update.message.reply_text("Це не CSV-файл.")
        return

    await document.get_file().download_to_drive(CSV_FILE)
    await update.message.reply_text("✅ CSV-файл оновлено.")

def main():
    token = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(token).build()

    conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("➕ Додати запис"), add_record)],
        states={
            MODEL: [CallbackQueryHandler(select_model, pattern="^model:")],
            VIN: [
                CallbackQueryHandler(select_vin, pattern="^vin:"),
                MessageHandler(filters.TEXT, manual_vin)
            ],
            WORK: [
                CallbackQueryHandler(select_work, pattern="^work:"),
                MessageHandler(filters.TEXT, manual_work)
            ]
        },
        fallbacks=[CommandHandler('start', start)],
        allow_reentry=True
    )

    app.add_handler(CommandHandler('start', start))
    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.Regex("📤 Експорт CSV"), export_csv))
    app.add_handler(MessageHandler(filters.Regex("📥 Завантажити CSV"), upload_csv))
    app.add_handler(MessageHandler(filters.Document.CSV, handle_csv_upload))

    app.run_polling()

if __name__ == '__main__':
    main()
