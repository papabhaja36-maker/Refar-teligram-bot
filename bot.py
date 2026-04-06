import os
import asyncio
import logging
from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, KeyboardButton
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters, ConversationHandler
)
from supabase import create_client, Client

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── ENV VARS (set in Render dashboard) ───────────────────────────────────────
BOT_TOKEN   = os.environ["BOT_TOKEN"]
ADMIN_ID    = int(os.environ["ADMIN_ID"])
SUPABASE_URL = os.environ["SUPABASE_URL"]
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

# ─── Channels user must join (add your channel usernames) ─────────────────────
REQUIRED_CHANNELS = [
    "@BLACK_DEVIL_z_x",
    "@SNYPER_DEVIL",
    "@PAGEL_ZONE",
    "@pagel_D2",
]

REFER_AMOUNT   = 0.50
WITHDRAW_MIN   = 10.00
WITHDRAW_MAX   = 5000.00

# ConversationHandler states
ASK_AMOUNT, ASK_UPI = range(2)

# ─── Supabase client ──────────────────────────────────────────────────────────
supabase: Client = create_client(SUPABASE_URL, SUPABASE_KEY)

# ══════════════════════════════════════════════════════════════════════════════
# HELPERS
# ══════════════════════════════════════════════════════════════════════════════

def get_or_create_user(user_id: int, username: str, full_name: str, referred_by: int = None):
    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    if res.data:
        return res.data[0], False  # existing user
    data = {"user_id": user_id, "username": username, "full_name": full_name}
    if referred_by:
        data["referred_by"] = referred_by
    supabase.table("users").insert(data).execute()
    return supabase.table("users").select("*").eq("user_id", user_id).execute().data[0], True


def get_user(user_id: int):
    res = supabase.table("users").select("*").eq("user_id", user_id).execute()
    return res.data[0] if res.data else None


def credit_referrer(referrer_id: int, new_user_id: int):
    """Credit ₹0.50 to referrer, only once per referred user."""
    already = supabase.table("referrals")\
        .select("id").eq("referred_id", new_user_id).execute()
    if already.data:
        return False  # already credited
    # Credit
    supabase.table("referrals").insert({
        "referrer_id": referrer_id,
        "referred_id": new_user_id,
        "amount_earned": REFER_AMOUNT
    }).execute()
    # Update balance
    user = get_user(referrer_id)
    if user:
        new_bal = float(user["balance"]) + REFER_AMOUNT
        supabase.table("users").update({"balance": new_bal})\
            .eq("user_id", referrer_id).execute()
    return True


async def check_membership(bot, user_id: int) -> bool:
    for ch in REQUIRED_CHANNELS:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ("left", "kicked", "banned"):
                return False
        except Exception:
            return False
    return True


def join_keyboard():
    buttons = [[InlineKeyboardButton(f"Join {ch}", url=f"https://t.me/{ch.lstrip('@')}")] for ch in REQUIRED_CHANNELS]
    buttons.append([InlineKeyboardButton("✅ Maine Join Kar Liya", callback_data="check_joined")])
    return InlineKeyboardMarkup(buttons)


def main_menu():
    return ReplyKeyboardMarkup(
        [
            [KeyboardButton("🔗 Refer"), KeyboardButton("📋 Refer List Check")],
            [KeyboardButton("💸 Withdraw"), KeyboardButton("💰 Check Balance")],
        ],
        resize_keyboard=True
    )

# ══════════════════════════════════════════════════════════════════════════════
# /start
# ══════════════════════════════════════════════════════════════════════════════

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user    = update.effective_user
    args    = context.args
    ref_id  = int(args[0]) if args and args[0].isdigit() else None

    db_user, is_new = get_or_create_user(
        user.id, user.username or "", user.full_name or "", referred_by=ref_id
    )

    # Check channels
    joined = await check_membership(context.bot, user.id)
    if not joined:
        await update.message.reply_text(
            "👋 Welcome!\n\n"
            "Bot use karne ke liye pehle neeche diye 4 channels join karo 👇",
            reply_markup=join_keyboard()
        )
        return

    # New user — credit referrer
    if is_new and ref_id and ref_id != user.id:
        credited = credit_referrer(ref_id, user.id)
        if credited:
            try:
                await context.bot.send_message(
                    ref_id,
                    f"🎉 Aapke refer se ek naya user join hua!\n"
                    f"Aapke account mein ₹{REFER_AMOUNT:.2f} add ho gaye! 💰"
                )
            except Exception:
                pass

    await update.message.reply_text(
        f"✅ Welcome, {user.first_name}!\n\n"
        "Neeche se option choose karo 👇",
        reply_markup=main_menu()
    )

# ══════════════════════════════════════════════════════════════════════════════
# Check joined callback
# ══════════════════════════════════════════════════════════════════════════════

async def check_joined_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user = query.from_user

    joined = await check_membership(context.bot, user.id)
    if not joined:
        await query.edit_message_text(
            "❌ Aapne abhi tak saare channels join nahi kiye.\nPehle join karo, phir try karo.",
            reply_markup=join_keyboard()
        )
        return

    # Make sure user is in DB
    get_or_create_user(user.id, user.username or "", user.full_name or "")
    await query.edit_message_text("✅ Aapne saare channels join kar liye! Bot use kar sakte ho.")
    await context.bot.send_message(user.id, "👇 Menu se option choose karo:", reply_markup=main_menu())

# ══════════════════════════════════════════════════════════════════════════════
# MENU HANDLERS
# ══════════════════════════════════════════════════════════════════════════════

async def guard_membership(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Returns True if member, else sends join message."""
    joined = await check_membership(context.bot, update.effective_user.id)
    if not joined:
        await update.message.reply_text(
            "❌ Aapne channel(s) unjoin kar diya!\n"
            "Bot use karne ke liye pehle channels mein wapas join karo 👇",
            reply_markup=join_keyboard()
        )
    return joined


async def handle_refer(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_membership(update, context):
        return
    user = update.effective_user
    link = f"https://t.me/{(await context.bot.get_me()).username}?start={user.id}"
    await update.message.reply_text(
        f"🔗 Aapka Refer Link:\n{link}\n\n"
        f"Har refer par ₹{REFER_AMOUNT:.2f} milega!\n"
        "Jitna chahe refer karo, koi limit nahi! 😊"
    )


async def handle_refer_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_membership(update, context):
        return
    user_id = update.effective_user.id
    rows = supabase.table("referrals")\
        .select("referred_id, amount_earned, created_at")\
        .eq("referrer_id", user_id).execute().data

    if not rows:
        await update.message.reply_text("📋 Aapne abhi tak kisi ko refer nahi kiya.")
        return

    text = f"📋 *Aapki Refer List* ({len(rows)} users)\n\n"
    for i, r in enumerate(rows, 1):
        uid   = r["referred_id"]
        amt   = r["amount_earned"]
        date  = r["created_at"][:10]
        u     = get_user(uid)
        name  = u["full_name"] if u else str(uid)
        text += f"{i}. {name} — ₹{amt:.2f} — {date}\n"

    await update.message.reply_text(text, parse_mode="Markdown")


async def handle_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_membership(update, context):
        return
    user_id = update.effective_user.id
    u = get_user(user_id)
    bal = float(u["balance"]) if u else 0.0
    await update.message.reply_text(f"💰 Aapka Balance: ₹{bal:.2f}")

# ══════════════════════════════════════════════════════════════════════════════
# WITHDRAW CONVERSATION
# ══════════════════════════════════════════════════════════════════════════════

async def handle_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not await guard_membership(update, context):
        return ConversationHandler.END
    u = get_user(update.effective_user.id)
    bal = float(u["balance"]) if u else 0.0
    if bal < WITHDRAW_MIN:
        await update.message.reply_text(
            f"❌ Aapka balance ₹{bal:.2f} hai.\n"
            f"Minimum ₹{WITHDRAW_MIN:.0f} chahiye withdraw ke liye."
        )
        return ConversationHandler.END
    await update.message.reply_text(
        f"💸 *Withdraw Request*\n\n"
        f"Aapka Balance: ₹{bal:.2f}\n"
        f"Kitna withdraw karna chahte ho? (Min ₹{WITHDRAW_MIN:.0f} – Max ₹{WITHDRAW_MAX:.0f})\n\n"
        "Amount type karo:",
        parse_mode="Markdown"
    )
    return ASK_AMOUNT


async def ask_amount(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        amount = float(text)
    except ValueError:
        await update.message.reply_text("❌ Galat amount. Sirf number type karo.")
        return ASK_AMOUNT

    if amount < WITHDRAW_MIN or amount > WITHDRAW_MAX:
        await update.message.reply_text(
            f"❌ Amount ₹{WITHDRAW_MIN:.0f} se ₹{WITHDRAW_MAX:.0f} ke beech hona chahiye."
        )
        return ASK_AMOUNT

    u = get_user(update.effective_user.id)
    if float(u["balance"]) < amount:
        await update.message.reply_text("❌ Itna balance nahi hai aapke paas.")
        return ConversationHandler.END

    context.user_data["withdraw_amount"] = amount
    await update.message.reply_text("✅ Ab apna UPI ID type karo:")
    return ASK_UPI


async def ask_upi(update: Update, context: ContextTypes.DEFAULT_TYPE):
    upi_id = update.message.text.strip()
    amount = context.user_data.get("withdraw_amount")
    user_id = update.effective_user.id

    # Deduct balance
    u = get_user(user_id)
    new_bal = float(u["balance"]) - amount
    supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()

    # Create request
    res = supabase.table("withdrawals").insert({
        "user_id": user_id,
        "amount": amount,
        "upi_id": upi_id,
        "status": "pending"
    }).execute()
    req_id = res.data[0]["id"]

    await update.message.reply_text(
        f"✅ Withdraw request submit ho gayi!\n"
        f"Amount: ₹{amount:.2f}\n"
        f"UPI: {upi_id}\n\n"
        "Admin jald approve karega. 🙏"
    )

    # Notify admin
    u_info = get_user(user_id)
    name = u_info["full_name"] if u_info else str(user_id)
    kb = InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✅ Approve", callback_data=f"wd_approve_{req_id}"),
            InlineKeyboardButton("❌ Cancel & Refund", callback_data=f"wd_cancel_{req_id}"),
        ]
    ])
    await context.bot.send_message(
        ADMIN_ID,
        f"🆕 *Withdraw Request #{req_id}*\n\n"
        f"👤 User: {name} (`{user_id}`)\n"
        f"💰 Amount: ₹{amount:.2f}\n"
        f"📲 UPI: `{upi_id}`",
        parse_mode="Markdown",
        reply_markup=kb
    )
    return ConversationHandler.END


async def cancel_withdraw(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("❌ Withdraw cancel kar diya.")
    return ConversationHandler.END

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN: Approve / Cancel withdraw
# ══════════════════════════════════════════════════════════════════════════════

async def admin_withdraw_action(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    if query.from_user.id != ADMIN_ID:
        await query.answer("❌ Aap admin nahi ho!", show_alert=True)
        return

    data   = query.data                    # wd_approve_5 / wd_cancel_5
    parts  = data.split("_")
    action = parts[1]
    req_id = int(parts[2])

    row = supabase.table("withdrawals").select("*").eq("id", req_id).execute().data
    if not row:
        await query.edit_message_text("❌ Request nahi mili.")
        return
    row = row[0]

    if row["status"] != "pending":
        await query.edit_message_text(f"⚠️ Is request ka status already '{row['status']}' hai.")
        return

    user_id = row["user_id"]
    amount  = float(row["amount"])

    if action == "approve":
        supabase.table("withdrawals").update({"status": "approved"}).eq("id", req_id).execute()
        await context.bot.send_message(
            user_id,
            f"✅ *Aapka Withdraw Successful!*\n\n"
            f"Amount: ₹{amount:.2f} aapke UPI par bhej diya gaya. 🎉",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"✅ Request #{req_id} approve kar diya gaya.")

    elif action == "cancel":
        # Refund
        u = get_user(user_id)
        new_bal = float(u["balance"]) + amount
        supabase.table("users").update({"balance": new_bal}).eq("user_id", user_id).execute()
        supabase.table("withdrawals").update({"status": "cancelled"}).eq("id", req_id).execute()
        await context.bot.send_message(
            user_id,
            f"❌ *Aapka Withdraw Cancel Ho Gaya.*\n\n"
            f"Amount: ₹{amount:.2f} aapke balance mein wapas add kar diya gaya.",
            parse_mode="Markdown"
        )
        await query.edit_message_text(f"❌ Request #{req_id} cancel + refund kar diya gaya.")

# ══════════════════════════════════════════════════════════════════════════════
# ADMIN COMMANDS
# ══════════════════════════════════════════════════════════════════════════════

async def admin_panel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id != ADMIN_ID:
        return
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📋 Pending Withdrawals", callback_data="admin_pending")],
        [InlineKeyboardButton("👥 User List", callback_data="admin_users")],
    ])
    await update.message.reply_text("🛠 *Admin Panel*", parse_mode="Markdown", reply_markup=kb)


async def admin_callbacks(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    if query.from_user.id != ADMIN_ID:
        return

    if query.data == "admin_pending":
        rows = supabase.table("withdrawals").select("*").eq("status", "pending").execute().data
        if not rows:
            await query.edit_message_text("✅ Koi pending withdrawal nahi hai.")
            return
        for r in rows:
            u = get_user(r["user_id"])
            name = u["full_name"] if u else str(r["user_id"])
            kb = InlineKeyboardMarkup([[
                InlineKeyboardButton("✅ Approve", callback_data=f"wd_approve_{r['id']}"),
                InlineKeyboardButton("❌ Cancel & Refund", callback_data=f"wd_cancel_{r['id']}"),
            ]])
            await context.bot.send_message(
                ADMIN_ID,
                f"🆕 *Withdraw Request #{r['id']}*\n"
                f"👤 {name} (`{r['user_id']}`)\n"
                f"💰 ₹{float(r['amount']):.2f}\n"
                f"📲 UPI: `{r['upi_id']}`",
                parse_mode="Markdown",
                reply_markup=kb
            )
        await query.edit_message_text(f"📋 {len(rows)} pending withdrawal(s) bheje gaye.")

    elif query.data == "admin_users":
        rows = supabase.table("users").select("*").execute().data
        if not rows:
            await query.edit_message_text("Koi user nahi hai abhi.")
            return
        text = f"👥 *Total Users: {len(rows)}*\n\n"
        for u in rows[:30]:  # show max 30
            refs = supabase.table("referrals").select("id").eq("referrer_id", u["user_id"]).execute().data
            text += f"• {u['full_name']} (`{u['user_id']}`) | Refs: {len(refs)} | ₹{float(u['balance']):.2f}\n"
        await query.edit_message_text(text, parse_mode="Markdown")

# ══════════════════════════════════════════════════════════════════════════════
# TEXT ROUTER
# ══════════════════════════════════════════════════════════════════════════════

async def text_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    if text == "🔗 Refer":
        await handle_refer(update, context)
    elif text == "📋 Refer List Check":
        await handle_refer_list(update, context)
    elif text == "💰 Check Balance":
        await handle_balance(update, context)

# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    app = Application.builder().token(BOT_TOKEN).build()

    # Withdraw conversation
    withdraw_conv = ConversationHandler(
        entry_points=[MessageHandler(filters.Regex("^💸 Withdraw$"), handle_withdraw)],
        states={
            ASK_AMOUNT: [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_amount)],
            ASK_UPI:    [MessageHandler(filters.TEXT & ~filters.COMMAND, ask_upi)],
        },
        fallbacks=[CommandHandler("cancel", cancel_withdraw)],
    )

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("admin", admin_panel))
    app.add_handler(withdraw_conv)
    app.add_handler(CallbackQueryHandler(check_joined_callback, pattern="^check_joined$"))
    app.add_handler(CallbackQueryHandler(admin_withdraw_action, pattern="^wd_(approve|cancel)_\\d+$"))
    app.add_handler(CallbackQueryHandler(admin_callbacks, pattern="^admin_"))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, text_router))

    logger.info("Bot start ho gaya!")
    app.run_polling()


if __name__ == "__main__":
    main()
