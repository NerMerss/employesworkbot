
#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import base64
import json
import logging
import datetime
import io

import gspread
from google.oauth2.service_account import Credentials

from telegram import (
    Update,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup
)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    MessageHandler,
    CallbackQueryHandler,
    ConversationHandler,
    ContextTypes,
    filters
)

# --- Логування ---
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# --- Google Sheets setup ---
SCOPES = ["https://www.googleapis.com/auth/spreadsheets"]
B64_CRED = os.getenv("GOOGLE_SHEETS_CREDENTIALS_BASE64", "")
info = json.loads(base64.b64decode(B64_CRED))
creds = Credentials.from_service_account_info(info, scopes=SCOPES)
gc = gspread.authorize(creds)
SPREADSHEET_ID = os.getenv("GOOGLE_SHEETS_SPREADSHEET_ID")
sh = gc.open_by_key(SPREADSHEET_ID)
worksheet = sh.sheet1  # або інший аркуш за назвою

# --- Константи та меню ---
MODEL, VIN, WORK, EXECUTOR = range(4)
RECENT_ITEMS_LIMIT = 5

SPECIAL_COMMANDS = [
    "➕ Додати запис", "🗑 Видалити записи", "📤 Експорт даних",
    "❌ Видалити ВСЕ", "🔢 Видалити за ID", "🔙 Назад",
    "✅ Так", "❌ Ні"
]

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
    [["✅ Так", "❌ Ні"], ["🔙 Назад"]],
    resize_keyboard=True
)

# --- Парсинг користувачів із ENV ---
def parse_user_list(env_var: str) -> dict:
    users = {}
    for item in os.getenv(env_var, "").split(","):
        if not item.strip():
            continue
        parts = item.strip().split(" ", 1)
        if len(parts) >= 2:
            username = parts[0] if parts[0].startswith("@") else f"@{parts[0]}"
            users[username.lower()] = parts[1]
    return users

OWNERS = parse_user_list("OWNERS")
MANAGERS = parse_user_list("MANAGERS")
WORKERS = parse_user_list("WORKERS")

# --- Google Sheets manager ---
class SheetManager:
    HEADERS = [
        "id", "timestamp", "user", "user_name",
        "executor", "executor_name",
        "model", "vin", "work", "user_level"
    ]

    @staticmethod
    def get_recent_values(field: str, limit: int = RECENT_ITEMS_LIMIT) -> list:
        records = worksheet.get_all_records()
        seen, vals = set(), []
        for row in reversed(records):
            val = str(row.get(field, "")).strip()
            if val and val not in seen:
                seen.add(val)
                vals.append(val)
            if len(vals) >= limit:
                break
        return vals

    @staticmethod
    def save_record(user_data: dict, username: str, user_name: str, user_level: str) -> int:
        all_rows = worksheet.get_all_values()
        next_id = len(all_rows)  # row count includes header
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        row = [
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
        ]
        worksheet.append_row(row, value_input_option="USER_ENTERED")
        return next_id

    @staticmethod
    def delete_all_records():
        worksheet.clear()
        worksheet.append_row(SheetManager.HEADERS)

    @staticmethod
    def delete_selected_records(ids_to_remove: set):
        records = worksheet.get_all_records()
        filtered = [r for r in records if str(r.get("id")) not in ids_to_remove]
        worksheet.clear()
        worksheet.append_row(SheetManager.HEADERS)
        for r in filtered:
            worksheet.append_row([r.get(h, "") for h in SheetManager.HEADERS], value_input_option="USER_ENTERED")

    @staticmethod
    def export_csv() -> io.BytesIO:
        values = worksheet.get_all_values()
        buf = io.StringIO()
        writer = csv.writer(buf)
        for row in values:
            writer.writerow(row)
        bytes_buf = io.BytesIO(buf.getvalue().encode('utf-8'))
        bytes_buf.seek(0)
        return bytes_buf

# --- Допоміжні функції ---
def get_user_level(username: str) -> str:
    uname = username.lower().strip()
    if not uname.startswith("@"): uname = f"@{uname}"
    if uname in OWNERS: return "owner"
    if uname in MANAGERS: return "manager"
    if uname in WORKERS: return "worker"
    return None

def create_keyboard(items: list, prefix: str) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(i, callback_data=f"{prefix}:{i}")] for i in items]
    buttons.append([InlineKeyboardButton("Ввести вручну", callback_data=f"{prefix}:manual")])
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

def create_model_keyboard(models: list) -> InlineKeyboardMarkup:
    buttons = [[InlineKeyboardButton(m, callback_data=f"model:{m}")] for m in models]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    return InlineKeyboardMarkup(buttons)

def parse_ids(id_str: str) -> list:
    ids = []
    parts = [p.strip() for p in id_str.split(",") if p.strip()]
    for part in parts:
        if "-" in part:
            try:
                start, end = map(int, part.split("-"))
                ids.extend(str(i) for i in range(start, end+1))
            except ValueError:
                pass
        elif part.isdigit():
            ids.append(part)
    return ids

# --- Handlers ---
async def back_to_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query = update.callback_query
    if query:
        await query.answer()
        try: await query.delete_message()
        except: pass
    username = f"@{update.effective_user.username}"
    lvl = get_user_level(username)
    if lvl == "owner": await update.effective_message.reply_text("Меню власника:", reply_markup=OWNER_MENU)
    elif lvl == "manager": await update.effective_message.reply_text("Меню керівника:", reply_markup=MANAGER_MENU)
    else: await update.effective_message.reply_text("Меню працівника:", reply_markup=WORKER_MENU)
    context.user_data.clear()
    return ConversationHandler.END

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username = f"@{update.effective_user.username}"
    lvl = get_user_level(username)
    if not lvl:
        await update.message.reply_text("⛔ У вас немає доступу до цього бота")
        return
    if lvl == "owner": kb=OWNER_MENU
    elif lvl=="manager": kb=MANAGER_MENU
    else: kb=WORKER_MENU
    await update.message.reply_text(f"Меню {lvl}:", reply_markup=kb)

async def add_record(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    username = f"@{update.effective_user.username}"
    lvl = get_user_level(username)
    name = OWNERS.get(username) or MANAGERS.get(username) or WORKERS.get(username) or update.effective_user.full_name
    if not lvl:
        await update.message.reply_text("⛔ У вас немає доступу")
        return ConversationHandler.END
    context.user_data.update({"user_level":lvl, "user_name":name})
    if lvl == "worker":
        context.user_data.update({"executor":username, "executor_name":name})
        await update.message.reply_text("Виберіть модель авто:", reply_markup=create_model_keyboard(TESLA_MODELS))
        return MODEL
    # owner or manager
    executors = {**OWNERS, **MANAGERS, **WORKERS} if lvl=="owner" else {username:name, **WORKERS}
    buttons=[[InlineKeyboardButton((f"Я ({name})" if i==username else u_name), callback_data=f"executor:{i}:{u_name}")] if lvl=="manager" else [InlineKeyboardButton(u_name, callback_data=f"executor:{i}:{u_name}")] for i,u_name in executors.items()]
    buttons.append([InlineKeyboardButton("🔙 Назад", callback_data="back")])
    await update.message.reply_text("Оберіть виконавця:", reply_markup=InlineKeyboardMarkup(buttons))
    return EXECUTOR

async def executor_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer()
    if query.data=="back": return await back_to_menu(update, context)
    _, user_id, name = query.data.split(":",2)
    context.user_data.update({"executor":user_id, "executor_name":name})
    await query.edit_message_text("Виберіть модель авто:", reply_markup=create_model_keyboard(TESLA_MODELS))
    return MODEL

async def model_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer()
    if query.data=="back": return await back_to_menu(update, context)
    sel=query.data.split(":",1)[1]; context.user_data["model"]=sel
    if sel=="Інше (не Tesla)":
        await query.edit_message_text("Виберіть модель авто:", reply_markup=create_model_keyboard(OTHER_MODELS))
        return MODEL
    vins=SheetManager.get_recent_values("vin")
    await query.edit_message_text("Оберіть VIN або введіть вручну:", reply_markup=create_keyboard(vins, "vin"))
    return VIN

async def model_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text=update.message.text.strip()
    if text in SPECIAL_COMMANDS: return await handle_text_messages(update, context)
    context.user_data["model"] = text if text in TESLA_MODELS+OTHER_MODELS else f"Інше: {text}"
    vins=SheetManager.get_recent_values("vin")
    await update.message.reply_text("Оберіть VIN або введіть вручну:", reply_markup=create_keyboard(vins, "vin"))
    return VIN

async def vin_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer()
    if query.data=="back": return await back_to_menu(update, context)
    sel=query.data.split(":",1)[1]
    if sel=="manual":
        await query.edit_message_text("Введіть останні 6 символів VIN:")
        return VIN
    context.user_data["vin"]=sel
    await query.edit_message_text(f"VIN: {sel}")
    return await show_work_options(update, context)

async def vin_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text=update.message.text.strip()
    if text in SPECIAL_COMMANDS: return await handle_text_messages(update, context)
    if len(text)!=6 or not text.isalnum():
        await update.message.reply_text("❗ Введіть рівно 6 символів VIN.")
        return VIN
    context.user_data["vin"]=text.upper()
    return await show_work_options(update, context)

async def show_work_options(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    works=SheetManager.get_recent_values("work", RECENT_ITEMS_LIMIT)
    kb=create_keyboard(works, "work")
    if update.callback_query:
        await update.callback_query.edit_message_text("Що було зроблено?", reply_markup=kb)
    else:
        await update.message.reply_text("Що було зроблено?", reply_markup=kb)
    return WORK

async def work_selected(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    query=update.callback_query; await query.answer()
    if query.data=="back": return await back_to_menu(update, context)
    work_text=query.data.split(":",1)[1]
    if work_text=="manual":
        await query.edit_message_text("Введіть, що було зроблено:")
        return WORK
    return await save_and_confirm(update, context, work_text)

async def work_manual(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    text=update.message.text.strip()
    if text in SPECIAL_COMMANDS: return await handle_text_messages(update, context)
    return await save_and_confirm(update, context, text)

async def save_and_confirm(update: Update, context: ContextTypes.DEFAULT_TYPE, work_text: str) -> int:
    username=f"@{update.effective_user.username}"
    user_name=context.user_data["user_name"]
    user_level=context.user_data["user_level"]
    context.user_data["work"]=work_text
    record_id=SheetManager.save_record(context.user_data, username, user_name, user_level)
    kb=InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Назад", callback_data="back")]])
    msg=(f"✅ Запис #{record_id} збережено\n"
         f"Виконавець: {context.user_data['executor_name']}\n"
         f"Модель: {context.user_data['model']}\n"
         f"VIN: {context.user_data['vin']}\n"
         f"Робота: {work_text}")
    if update.callback_query:
        await update.callback_query.edit_message_text(msg, reply_markup=kb)
    else:
        await update.message.reply_text(msg, reply_markup=kb)
    return ConversationHandler.END

async def show_delete_menu(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username=f"@{update.effective_user.username}"
    if get_user_level(username)!="owner":
        await update.message.reply_text("⛔ У вас немає прав для цієї дії")
        return
    await update.message.reply_text("Оберіть тип видалення:", reply_markup=DELETE_MENU)

async def ask_delete_confirmation(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username=f"@{update.effective_user.username}"
    if get_user_level(username)!="owner": return
    await update.message.reply_text("❗ Ви впевнені, що хочете видалити ВСІ записи?", reply_markup=CONFIRM_MARKUP)
    context.user_data['delete_type']='all'

async def ask_ids_to_delete(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username=f"@{update.effective_user.username}"
    if get_user_level(username)!="owner": return
    records=worksheet.get_all_records()
    if not records:
        await update.message.reply_text("ℹ Немає записів для видалення", reply_markup=OWNER_MENU)
        return
    last10=records[-10:]
    msg="Доступні записи (останні 10):\n"+"\n".join(f"ID: {r['id']}, Модель: {r['model']}, VIN: {r['vin']}" for r in last10)
    msg+="\n\nВведіть ID для видалення (наприклад: 1, 2-5):"
    await update.message.reply_text(msg, reply_markup=ReplyKeyboardMarkup([["🔙 Назад"]], resize_keyboard=True))
    context.user_data['delete_type']='selected'

async def execute_deletion(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username=f"@{update.effective_user.username}"
    if get_user_level(username)!="owner": return
    text=update.message.text.strip()
    if text=="🔙 Назад":
        await update.message.reply_text("Меню власника:", reply_markup=OWNER_MENU)
        context.user_data.pop('delete_type',None)
        return
    dt=context.user_data.get('delete_type')
    if dt=='all':
        if text=='✅ Так': SheetManager.delete_all_records(); await update.message.reply_text("🗑 Всі записи видалено!", reply_markup=OWNER_MENU)
        else: await update.message.reply_text("❌ Видалення скасовано", reply_markup=OWNER_MENU)
    elif dt=='selected':
        ids=parse_ids(text)
        if not ids: await update.message.reply_text("❗ Неправильний формат ID", reply_markup=OWNER_MENU); return
        SheetManager.delete_selected_records(set(ids))
        await update.message.reply_text(f"🗑 Видалено {len(ids)} записів. ID: {', '.join(ids)}", reply_markup=OWNER_MENU)
    context.user_data.pop('delete_type',None)

async def export_data(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username=f"@{update.effective_user.username}"
    if get_user_level(username)!="owner": return
    buf=SheetManager.export_csv()
    await update.message.reply_document(document=buf, filename='service_records.csv')

async def handle_text_messages(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    username=f"@{update.effective_user.username}"
    lvl=get_user_level(username)
    if not lvl: await update.message.reply_text("⛔ У вас немає доступу до цього бота"); return
    text=update.message.text.strip()
    if text in SPECIAL_COMMANDS:
        if text=="➕ Додати запис": await add_record(update, context)
        elif text=="🗑 Видалити записи": await show_delete_menu(update, context)
        elif text=="📤 Експорт даних": await export_data(update, context)
        elif text=="❌ Видалити ВСЕ": await ask_delete_confirmation(update, context)
        elif text=="🔢 Видалити за ID": await ask_ids_to_delete(update, context)
        elif text=="🔙 Назад": await back_to_menu(update, context)
        return
    state=context.user_data.get('state')
    if state==MODEL: await model_manual(update, context)
    elif state==VIN: await vin_manual(update, context)
    elif state==WORK: await work_manual(update, context)
    else: await update.message.reply_text("Оберіть дію з меню")

async def cancel(update: Update, context: ContextTypes.DEFAULT_TYPE) -> int:
    return await back_to_menu(update, context)

# --- Основний запуск ---
def main() -> None:
    token=os.getenv("BOT_TOKEN")
    if not token:
        logger.error("Не встановлено BOT_TOKEN")
        return
    app=ApplicationBuilder().token(token).build()

    conv=ConversationHandler(
        entry_points=[
            CommandHandler("start", start),
            MessageHandler(filters.Regex("^➕ Додати запис$"), add_record),
            CallbackQueryHandler(back_to_menu, pattern="^back$")
        ],
        states={
            EXECUTOR:[CallbackQueryHandler(executor_selected, pattern="^executor:")],
            MODEL:   [CallbackQueryHandler(model_selected, pattern="^model:"), MessageHandler(filters.TEXT & ~filters.COMMAND, model_manual)],
            VIN:     [CallbackQueryHandler(vin_selected, pattern="^vin:"),    MessageHandler(filters.TEXT & ~filters.COMMAND, vin_manual)],
            WORK:    [CallbackQueryHandler(work_selected, pattern="^work:"), MessageHandler(filters.TEXT & ~filters.COMMAND, work_manual)]
        },
        fallbacks=[CommandHandler("cancel", cancel)],
        allow_reentry=True
    )

    app.add_handler(conv)
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text_messages))

    logger.info("Бот запущений")
    app.run_polling()

if __name__ == "__main__":
    main()
