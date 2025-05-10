import os
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, MessageHandler,
    CallbackQueryHandler, ConversationHandler, ContextTypes, filters
)
import sqlite3
import datetime

MODEL, VIN, WORK = range(3)

conn = sqlite3.connect('service_log.db', check_same_thread=False)
cursor = conn.cursor()
cursor.execute('''
CREATE TABLE IF NOT EXISTS records (
    timestamp TEXT,
    user TEXT,
    model TEXT,
    vin TEXT,
    work TEXT
)
''')
conn.commit()

def get_recent_values(field, limit=5):
    cursor.execute(f"""
        SELECT {field}
        FROM records
        WHERE {field} IS NOT NULL
        GROUP BY {field}
        ORDER BY MAX(timestamp) DESC
        LIMIT ?
    """, (limit,))
    return [row[0] for row in cursor.fetchall()]

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
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
    return ConversationHandler.END

async def work_manual(update: Update, context: ContextTypes.DEFAULT_TYPE):
    work_text = update.message.text.strip()
    await save_record(update.message.from_user.full_name, context, work_text)
    keyboard = [[InlineKeyboardButton("➕ Додати ще", callback_data="restart")]]
    await update.message.reply_text("✅ Записано. Дякуємо!", reply_markup=InlineKeyboardMarkup(keyboard))
    return ConversationHandler.END

async def save_record(user, context, work_text):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    cursor.execute(
        "INSERT INTO records VALUES (?, ?, ?, ?, ?)",
        (
            timestamp,
            user,
            context.user_data["model"],
            context.user_data["vin"],
            work_text
        )
    )
    conn.commit()

async def restart(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    return await start(update, context)

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Скасовано.")
    return ConversationHandler.END

if __name__ == '__main__':
    BOT_TOKEN = os.getenv("BOT_TOKEN")
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    conv_handler = ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
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
    app.run_polling()
