import os
import psycopg2
import logging
import http.server
import socketserver
import threading
import requests
import time
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler
from dotenv import load_dotenv
load_dotenv()
# Enable logging
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s", level=logging.INFO
)
logger = logging.getLogger(__name__)

# Constants
TELEGRAM_CHANNEL1_ID = os.getenv('TELEGRAM_CHANNEL1_ID')
TELEGRAM_CHANNEL2_ID = os.getenv('TELEGRAM_CHANNEL2_ID')
TELEGRAM_CHANNEL1_URL = os.getenv('TELEGRAM_CHANNEL1_URL')
TELEGRAM_CHANNEL2_URL = os.getenv('TELEGRAM_CHANNEL2_URL')
DATABASE_URL = os.getenv('DATABASE_URL')
WHATSAPP_LINK = os.getenv('WHATSAPP_LINK')  
ADMIN_IDS = [7502333334, 5991907369, 7692366281] 
REFERRAL_REWARD = 60 
MIN_WITHDRAWAL = 500  

def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Database setup
def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 10,
        account_number TEXT,
        referrer_id BIGINT,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        whatsapp_clicked INTEGER DEFAULT 0
    )
    ''')
    
    # Create subscriptions table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS subscriptions (
        user_id BIGINT PRIMARY KEY,
        channel1_joined BIGINT DEFAULT 0,
        channel2_joined BIGINT DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    # Create withdrawals table
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS withdrawals (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )
    ''')
    
    conn.commit()
    conn.close()

# Check if user is subscribed to required channels
async def check_joined(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check database for subscription status
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT channel1_joined, channel2_joined FROM subscriptions WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result or result[0] == 0 or result[1] == 0:
        # User hasn't joined all channels, check current status
        try:
            # Check first channel
            member1 = await context.bot.get_chat_member(chat_id=TELEGRAM_CHANNEL1_ID, user_id=user_id)
            channel1_joined = member1.status in ['member', 'administrator', 'creator']
            
            # Check second channel
            member2 = await context.bot.get_chat_member(chat_id=TELEGRAM_CHANNEL2_ID, user_id=user_id)
            channel2_joined = member2.status in ['member', 'administrator', 'creator']
            
            # Update database
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute('''
            INSERT INTO subscriptions (user_id, channel1_joined, channel2_joined)
            VALUES (%s, %s, %s)
            ON CONFLICT (user_id) 
            DO UPDATE SET 
                channel1_joined = EXCLUDED.channel1_joined,
                channel2_joined = EXCLUDED.channel2_joined
            ''', (user_id, int(channel1_joined), int(channel2_joined)))

            conn.commit()
            conn.close()
            
            if not channel1_joined or not channel2_joined:
                # User hasn't joined all channels
                keyboard = [
                    [InlineKeyboardButton("🔗 Join Channel 1", url=f"{TELEGRAM_CHANNEL1_URL}")],
                    [InlineKeyboardButton("🔗 Join Channel 2", url=f"{TELEGRAM_CHANNEL2_URL}")],
                    [InlineKeyboardButton("🔗 Join WhatsApp Group", url=WHATSAPP_LINK, callback_data="whatsapp_clicked")],
                    [InlineKeyboardButton("✅ Check My Subscription", callback_data="check_subscription")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.effective_message.reply_text(
                    "You need to join our channels and WhatsApp group to use this bot:",
                    reply_markup=reply_markup
                )
                return False
            
            # Check WhatsApp click status
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT whatsapp_clicked FROM users WHERE user_id = %s", (user_id,))
            whatsapp_result = cursor.fetchone()
            conn.close()
            
            if not whatsapp_result or whatsapp_result[0] == 0:
                keyboard = [
                    [InlineKeyboardButton("Join WhatsApp Group", url=WHATSAPP_LINK, callback_data="whatsapp_clicked")],
                    [InlineKeyboardButton("✅ I've Joined WhatsApp", callback_data="whatsapp_confirmed")]
                ]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.effective_message.reply_text(
                    "Please join our WhatsApp group to continue:",
                    reply_markup=reply_markup
                )
                return False
            
            return True
            
        except Exception as e:
            logger.error(f"Error checking subscription: {e}")
            await update.effective_message.reply_text("An error occurred. Please try again later.")
            return False
    
    # Check WhatsApp click status
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT whatsapp_clicked FROM users WHERE user_id = %s", (user_id,))
    cursor.execute("SELECT referrer_id FROM users WHERE user_id = %s", (user_id,))
    whatsapp_result = cursor.fetchone()
    referrer_result = cursor.fetchone()
    referrer_id = referrer_result[0] if referrer_result else None
    conn.close()
    
    if not whatsapp_result or whatsapp_result[0] == 0:
        keyboard = [
            [InlineKeyboardButton("Join WhatsApp Group", url=WHATSAPP_LINK, callback_data="whatsapp_clicked")],
            [InlineKeyboardButton("✅ I've Joined WhatsApp", callback_data="whatsapp_confirmed")]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.effective_message.reply_text(
            "Please join our WhatsApp group to continue:",
            reply_markup=reply_markup
        )
        return False
    
    if referrer_id:
        await reward_referrer(referrer_id, context)
    
    return True

# Decorator for checking subscription
def subscription_required(func):
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE, *args, **kwargs):
        if await check_joined(update, context):
            return await func(update, context, *args, **kwargs)
        return ConversationHandler.END
    return wrapper

# Start command handler
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username
    first_name = user.first_name
    
    # Check if user exists in database
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    existing_user = cursor.fetchone()
    
    # Get referrer from deep link if available
    referrer_id = None
    if context.args and context.args[0].isdigit():
        referrer_id = int(context.args[0])
        # Make sure referrer exists and is not the same as user
        if referrer_id == user_id:
            referrer_id = None
        else:
            cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
            if not cursor.fetchone():
                referrer_id = None
    
    if not existing_user:
        # New user, add to database
        cursor.execute('''
        INSERT INTO users (user_id, username, first_name, referrer_id)
        VALUES (%s, %s, %s, %s)
        ''', (user_id, username, first_name, referrer_id))
        conn.commit()
    
    conn.close()
    
    # Check if user has joined required channels
    if not await check_joined(update, context):
        return
    
    # If user was referred and this is their first time, reward referrer
    if not existing_user and referrer_id:
        await reward_referrer(referrer_id, context)
    
    # Show main menu
    await show_main_menu(update, context)

# Reward referrer
async def reward_referrer(referrer_id, context):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get referred user's info
    cursor.execute("SELECT username, first_name FROM users WHERE referrer_id = %s ORDER BY joined_date DESC LIMIT 1", (referrer_id,))
    referred_user = cursor.fetchone()
    referred_name = f"@{referred_user[0]}" if referred_user[0] else referred_user[1]
    
    # Update referrer's balance with REFERRAL_REWARD
    cursor.execute('''
    UPDATE users 
    SET balance = balance + %s 
    WHERE user_id = %s
    ''', (REFERRAL_REWARD, referrer_id))
    
    # Get updated balance
    cursor.execute("SELECT balance FROM users WHERE user_id = %s", (referrer_id,))
    new_balance = cursor.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    # Send enhanced notification to referrer
    try:
        await context.bot.send_message(
            chat_id=referrer_id,
            text=f"🎉 You referred {referred_name}!\n\n"
                 f"✅ Earned: ₦{REFERRAL_REWARD}\n"
                 f"💰 New Balance: ₦{new_balance}"
        )
    except Exception as e:
        logger.error(f"Failed to notify referrer: {e}")


# Show main menu
async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    keyboard = [
        ['💰 Balance', '👥 Refer & Earn'],
        ['💸 Withdraw', '⚙️ Settings'],
        ['🏆 Top Earners', '📞 Help & Ads']  
    ]
    reply_markup = ReplyKeyboardMarkup(keyboard, resize_keyboard=True)
    
    await update.effective_message.reply_text(
        "Welcome to EarnHive! 🐝\n\n"
        "Earn rewards by referring friends and completing tasks.\n"
        "Use the menu below to navigate:",
        reply_markup=reply_markup
    )

@subscription_required
async def show_top_earners(update: Update, context: ContextTypes.DEFAULT_TYPE):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get top 10 users by referral count
    cursor.execute('''
    SELECT u.first_name, COUNT(r.referrer_id) as referral_count
    FROM users u
    LEFT JOIN users r ON u.user_id = r.referrer_id
    GROUP BY u.user_id, u.first_name
    ORDER BY referral_count DESC
    LIMIT 10
    ''')
    
    top_users = cursor.fetchall()
    conn.close()
    
    # Create leaderboard message
    message = "🏆 *Top 10 Referrers*\n\n"
    for index, (name, count) in enumerate(top_users, 1):
        earnings = count * REFERRAL_REWARD
        message += f"{index}. {name}\n"
        message += f"   • Referrals: {count}\n"
        message += f"   • Earned: ₦{earnings:,.2f}\n\n"
    
    await update.message.reply_text(
        message,
        parse_mode="Markdown"
    )
# Handle menu selections
@subscription_required
async def handle_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    
    if text == '💰 Balance':
        await show_balance(update, context)
    elif text == '👥 Refer & Earn':
        await show_referral(update, context)
    elif text == '💸 Withdraw':
        await show_withdrawal(update, context)
    elif text == '⚙️ Settings':
        await show_settings(update, context)
    elif text == '🏆 Top Earners':
        await show_top_earners(update, context)
    elif text == '📞 Help & Ads':
        keyboard =  [[InlineKeyboardButton("Contact Us", url='https://t.me/spinnsisnbot?text=Hello')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('For help and Advertisements booking, click the button below to contact us 👇', reply_markup=reply_markup)
    else:
        pass

# Show user balance
@subscription_required
async def show_balance(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if result:
        balance = result[0]
        await update.message.reply_text(
            f"💰 Your current balance: ₦{balance:.2f}\n\n"
            f"Earn ₦{REFERRAL_REWARD} for each friend you refer!"
        )
    else:
        await update.message.reply_text("Error retrieving your balance. Please try again.")

# Show referral information
@subscription_required
async def show_referral(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    bot_username = context.bot.username
    
    # Create referral link
    referral_link = f"https://t.me/{bot_username}?start={user_id}"
    
    # Get referral stats
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users WHERE referrer_id = %s", (user_id,))
    referral_count = cursor.fetchone()[0]
    conn.close()
    
    await update.message.reply_text(
        f"👥 *Refer & Earn*\n\n"
        f"Earn ₦{REFERRAL_REWARD} for each friend you refer!\n\n"
        f"Your referral link:\n`{referral_link}`\n\n"
        f"Total referrals: {referral_count}\n"
        f"Earnings from referrals: ₦{referral_count * REFERRAL_REWARD}",
        parse_mode="Markdown"
    )

# Show withdrawal menu
@subscription_required
async def show_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Check if user has set account number
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT account_number, balance FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    if not result or not result[0]:
        await update.message.reply_text(
            "⚠️ You need to set your account number before withdrawing.\n\n"
            "Go to ⚙️ Settings to set your account number."
        )
        return
    
    account_number = result[0]
    balance = result[1]
    
    # Create numeric keyboard for withdrawal amounts
    keyboard = [
        [InlineKeyboardButton("₦500", callback_data="withdraw_500"),
         InlineKeyboardButton("₦1000", callback_data="withdraw_1000")],
        [InlineKeyboardButton("₦2000", callback_data="withdraw_2000"),
         InlineKeyboardButton("₦5000", callback_data="withdraw_5000")],
        [InlineKeyboardButton("Custom Amount", callback_data="withdraw_custom")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"💸 *Withdrawal*\n\n"
        f"Your balance: ₦{balance:.2f}\n"
        f"Account number:\n {account_number}\n\n"
        f"Select withdrawal amount:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Handle withdrawal callback
async def handle_withdrawal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith("withdraw_"):
        if data == "withdraw_custom":
            await query.edit_message_text(
                "Please enter the amount you want to withdraw:",
            )
            context.user_data["awaiting_withdrawal_amount"] = True
            return
        
        # Extract amount from callback data
        amount = float(data.split("_")[1])
        await process_withdrawal(update, context, user_id, amount)

async def check_referral_subscriptions(user_id, context):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Get all referrals for this user
    cursor.execute("""
    SELECT u.user_id, u.first_name, u.username, s.channel1_joined, s.channel2_joined 
    FROM users u 
    LEFT JOIN subscriptions s ON u.user_id = s.user_id 
    WHERE u.referrer_id = %s
    """, (user_id,))
    
    referrals = cursor.fetchall()
    conn.close()
    
    if not referrals:
        return True, []
    
    unsubscribed = []
    for ref in referrals:
        ref_id, first_name, username, ch1, ch2 = ref
        if not ch1 or not ch2:
            if username:
                unsubscribed.append(f"<a href='https://t.me/{username}'>{first_name}</a>")
            elif ref_id:
                unsubscribed.append(f"<a href='tg://user?id={ref_id}'>{first_name}</a>")
            else:
                unsubscribed.append(first_name)

    unsubscribed_percentage = (len(unsubscribed) / len(referrals)) * 100
    
    if unsubscribed_percentage > 80:
        unsubscribed_list = [f"<a href='tg://user?id={uid}'>{name}</a>" for uid, name in unsubscribed]
        message = (
            "❌ 80% of the people you referred are not subscribed to the channels!\n\n"
            "List of your referrals not subscribed:\n"
            f"{chr(10).join(unsubscribed_list)}\n\n"
            f"Please remind them to join:\n"
            f"Channel 1: {TELEGRAM_CHANNEL1_URL}\n"
            f"Channel 2: {TELEGRAM_CHANNEL2_URL}\n"
            f"Whatsapp Group: {WHATSAPP_LINK}\n"

        )
        return False, message
    
    return True, []

# Process withdrawal request
async def process_withdrawal(update: Update, context: ContextTypes.DEFAULT_TYPE, user_id, amount):
    
    
    # Check if user has sufficient balance
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT balance, account_number FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    
    if not result:
        await update.callback_query.edit_message_text("Error retrieving your account information.")
        conn.close()
        return
    
    check_passed, message = await check_referral_subscriptions(user_id, context)
    if not check_passed:
        await update.callback_query.edit_message_text(
            message,
            parse_mode="HTML",
            disable_web_page_preview=True
        )
        return

    balance = result[0]
    account_number = result[1]
    
    if amount < MIN_WITHDRAWAL:
        await update.callback_query.edit_message_text(
            f"⚠️ Minimum withdrawal amount is ₦{MIN_WITHDRAWAL}.\n\n"
            f"Your requested amount: ₦{amount:.2f}"
        )
        return
    
    if balance < amount:
        await update.callback_query.edit_message_text(
            f"⚠️ Insufficient balance.\n\n"
            f"Your balance: ₦{balance:.2f}\n"
            f"Requested amount: ₦{amount:.2f}"
        )
        conn.close()
        return
    
    
    # Create withdrawal request
    cursor.execute('''
    INSERT INTO withdrawals (user_id, amount)
    VALUES (%s, %s)
    ''', (user_id, amount))
    
    # Update user balance
    cursor.execute('''
    UPDATE users SET balance = balance - %s WHERE user_id = %s
    ''', (amount, user_id))
    
    conn.commit()
    conn.close()
    
    # Notify user
    await update.callback_query.edit_message_text(
        f"✅ Withdrawal request submitted!\n\n"
        f"Amount: ₦{amount:.2f}\n"
        f"Account: {account_number}\n\n"
        f"Your request is being processed. You will be notified once completed."
    )
    
    # Notify admins
    user = update.effective_user
    admin_message = (
        f"🔔 <b>New Withdrawal Request</b>\n\n"
        f"User: {user.first_name} (@{user.username})\n"
        f"User ID: <code>{user_id}</code>\n"
        f"Amount: ₦{amount:.2f}\n"
        f"Account: {account_number}\n\n"
        f"Use <code>/approve_{user_id}_{int(amount)}</code> to approve or <code>/reject_{user_id}_{int(amount)}</code> to reject."
    )

    
    for admin_id in ADMIN_IDS:
        try:
            await context.bot.send_message(
                chat_id=admin_id,
                text=admin_message,
                parse_mode="html"
            )
        except Exception as e:
            logger.error(f"Failed to notify admin {admin_id}: {e}")

# Handle custom withdrawal amount
async def handle_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "awaiting_withdrawal_amount" in context.user_data and context.user_data["awaiting_withdrawal_amount"]:
        try:
            amount = float(update.message.text)
            if amount <= 0:
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text("Please enter a valid amount greater than 0.",
                                                reply_markup=reply_markup)
                return
            
            user_id = update.effective_user.id
            
            # Process the withdrawal
            conn = get_db_connection()
            cursor = conn.cursor()
            cursor.execute("SELECT balance, account_number FROM users WHERE user_id = %s", (user_id,))
            result = cursor.fetchone()
            
            
            if not result:
                await update.message.reply_text("Error retrieving your account information.")
                conn.close()
                return

            check_passed, message = await check_referral_subscriptions(user_id, context)
            if not check_passed:
                await update.callback_query.edit_message_text(
                    message,
                    parse_mode="HTML",
                    disable_web_page_preview=True
                )
                return
            
            balance = result[0]
            account_number = result[1]
            
            if balance < amount:
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.message.reply_text(
                    f"⚠️ Insufficient balance.\n\n"
                    f"Your balance: ₦{balance:.2f}\n"
                    f"Requested amount: ₦{amount:.2f}",
                    reply_markup=reply_markup
                )
                conn.close()
                return
        
            if amount < MIN_WITHDRAWAL:
                keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
                reply_markup = InlineKeyboardMarkup(keyboard)
                await update.callback_query.edit_message_text(
                    f"⚠️ Minimum withdrawal amount is ₦{MIN_WITHDRAWAL}.\n\n"
                    f"Your requested amount: ₦{amount:.2f}",
                    reply_markup=reply_markup
                )
                return

            
            # Create withdrawal request
            cursor.execute('''
            INSERT INTO withdrawals (user_id, amount)
            VALUES (%s, %s)
            ''', (user_id, amount))
            
            # Update user balance
            cursor.execute('''
            UPDATE users SET balance = balance - %s WHERE user_id = %s
            ''', (amount, user_id))
            
            conn.commit()
            conn.close()
            
            # Notify user
            await update.message.reply_text(
                f"✅ Withdrawal request submitted!\n\n"
                f"Amount: ₦{amount:.2f}\n"
                f"Account: {account_number}\n\n"
                f"Your request is being processed. You will be notified once completed."
            )
            
            # Notify admins
            user = update.effective_user
            admin_message = (
                f"🔔 <b>New Withdrawal Request</b>\n\n"
                f"User: {user.first_name} (@{user.username})\n"
                f"User ID: <code>{user_id}</code>\n"
                f"Amount: ₦{amount:.2f}\n"
                f"Account: {account_number}\n\n"
                f"Use: \n<code>/approve_{user_id}_{int(amount)}</code> \nto approve or\n <code>/reject_{user_id}_{int(amount)}</code>\n to reject."
            )
            
            for admin_id in ADMIN_IDS:
                try:
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_message,
                        parse_mode="html"
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
            
            # Reset the awaiting flag
            context.user_data["awaiting_withdrawal_amount"] = False
            
        except ValueError:
            keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
            await update.message.reply_text("Please enter a valid number.", reply_markup=InlineKeyboardMarkup(keyboard))
        
        return
    
    # If not awaiting withdrawal amount, handle as regular menu selection
    await handle_menu(update, context)

# Show settings menu
@subscription_required
async def show_settings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Get current account number
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT account_number FROM users WHERE user_id = %s", (user_id,))
    result = cursor.fetchone()
    conn.close()
    
    account_number = result[0] if result and result[0] else "Not set"
    
    keyboard = [
        [InlineKeyboardButton("Set Account Number", callback_data="set_account")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"⚙️ *Settings*\n\n"
        f"Account Number: {account_number}\n\n"
        f"Use the button below to update your settings:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Handle settings callback
async def handle_settings_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    
    if query.data == "set_account":
        keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel")]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await query.edit_message_text(
            "Please enter your account number:",
            reply_markup=reply_markup
        )
        context.user_data["awaiting_account_number"] = True

# Handle account number input
async def handle_account_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "awaiting_account_number" in context.user_data and context.user_data["awaiting_account_number"]:
        account_number = update.message.text
        user_id = update.effective_user.id
        
        # Update account number in database
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE users SET account_number = %s WHERE user_id = %s
        ''', (account_number, user_id))
        conn.commit()
        conn.close()
        
        await update.message.reply_text(
            f"✅ Account number updated successfully!\n\n"
            f"Your account number:\n {account_number}"
        )
        
        # Reset the awaiting flag
        context.user_data["awaiting_account_number"] = False
        return
    
    # If not awaiting account number, handle as regular text input
    await handle_text_input(update, context)

# Handle WhatsApp confirmation
async def handle_callback_query(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    
    # In handle_callback_query function:
    if query.data == "whatsapp_clicked":
        user_id = update.effective_user.id
        print(f"User  ID {user_id} has clicked the WhatsApp button")
        # Update WhatsApp clicked status
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute('''
        UPDATE users SET whatsapp_clicked = 1 WHERE user_id = %s
        ''', (user_id,))
        conn.commit()
        conn.close()
        print(f"User  ID {user_id} has clicked the WhatsApp button and updated the database.")
    elif query.data == "whatsapp_confirmed":
        user_id = update.effective_user.id  # Added this line
        
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Get referrer_id for this user
        cursor.execute("SELECT referrer_id FROM users WHERE user_id = %s", (user_id,))
        referrer_result = cursor.fetchone()
        referrer_id = referrer_result[0] if referrer_result else None
        
        # Update WhatsApp status
        cursor.execute('''
        UPDATE users SET whatsapp_clicked = 1 WHERE user_id = %s
        ''', (user_id,))
        conn.commit()
        conn.close()

        if referrer_id:
            await reward_referrer(referrer_id, context)

        await query.edit_message_text("✅ WhatsApp subscription confirmed!")
        await show_main_menu(update, context)

    elif query.data == "check_subscription":
        await query.message.delete()
        if await check_joined(update, context):
            await query.edit_message_text("✅ All subscriptions confirmed! You can now use the bot.")
            # Show main menu after confirmation
            await show_main_menu(update, context)    
    # Handle withdrawal and settings callbacks
    elif query.data.startswith("withdraw_"):
        await handle_withdrawal_callback(update, context)
    elif query.data.startswith("set_"):
        await handle_settings_callback(update, context)
    elif query.data == "cancel":
        await query.message.delete()
        context.user_data.clear()
        context.user_data["awaiting_withdrawal_amount"] = False
        context.user_data["awaiting_account_number"] = False

# Admin commands
async def handle_admin_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    query = update.callback_query
    # Check if user is admin
    if user_id not in ADMIN_IDS:
        return
    
    text = update.message.text
    
    if text.startswith("/approve_"):
        # Format: /approve_user_id_amount
        parts = text.split("_")
        if len(parts) == 3:
            try:
                target_user_id = int(parts[1])
                amount = int(parts[2])
                
                # Update withdrawal status
                conn = get_db_connection()
                cursor = conn.cursor()
                cursor.execute('''
                UPDATE withdrawals 
                SET status = 'approved' 
                WHERE user_id = %s AND amount = %s AND status = 'pending'
                ''', (target_user_id, amount))
                
                if cursor.rowcount > 0:
                    conn.commit()
                    
                    # Notify user
                    try:
                        await context.bot.send_message(
                            chat_id=target_user_id,
                            text=f"✅ Your withdrawal request of ₦{amount} has been approved!"
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user {target_user_id}: {e}")
                    
                    await update.message.reply_text(f"Withdrawal for user {target_user_id} approved.")
                else:
                    await update.message.reply_text("No pending withdrawal found with these details.")
                
                conn.close()
                
            except (ValueError, IndexError):
                await update.message.reply_text("Invalid command format. Use /approve_user_id_amount")
    
    elif text.startswith("/reject_"):
        # Format: /reject_user_id_amount
        parts = text.split("_")
        if len(parts) == 3:
            try:
                target_user_id = int(parts[1])
                amount = int(parts[2])
                
                # Update withdrawal status and refund balance
                conn = get_db_connection()
                cursor = conn.cursor()
                
                # First update the withdrawal status
                cursor.execute('''
                UPDATE withdrawals 
                SET status = 'rejected' 
                WHERE user_id = %s AND amount = %s AND status = 'pending'
                ''', (target_user_id, amount))
                
                if cursor.rowcount > 0:
                    # Refund the balance
                    cursor.execute('''
                    UPDATE users 
                    SET balance = balance + %s 
                    WHERE user_id = %s
                    ''', (amount, target_user_id))
                    
                    conn.commit()
                    
                    # Notify user
                    try:
                        await context.bot.send_message(
                            chat_id=target_user_id,
                            text=f"ℹ️ Your withdrawal request of ₦{amount} has been rejected. The amount has been refunded to your balance."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify user {target_user_id}: {e}")
                    
                    await update.message.reply_text(f"Withdrawal for user {target_user_id} rejected and refunded.")
                else:
                    await update.message.reply_text("No pending withdrawal found with these details.")
                
                conn.close()
                
            except (ValueError, IndexError):
                await update.message.reply_text("Invalid command format. Use /reject_user_id_amount")
    
async def reset_db(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Only allow admins to reset
    if user_id not in ADMIN_IDS:
        return
        
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Drop all tables
    cursor.execute('''
    DROP TABLE IF EXISTS withdrawals;
    DROP TABLE IF EXISTS subscriptions;
    DROP TABLE IF EXISTS users;
    ''')
    
    conn.commit()
    conn.close()
    
    # Recreate tables
    setup_database()
    
    await update.message.reply_text("Database has been reset successfully!")


BROADCAST = 1

async def broadcast_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        return
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total_users = cursor.fetchone()[0]
    conn.close()

    keyboard = [[InlineKeyboardButton("❌ Cancel", callback_data="cancel_broadcast")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"📊 Total users: {total_users}\n\n"
        "✍️ Send your broadcast message:",
        reply_markup=reply_markup
    )
    
    return BROADCAST

async def handle_broadcast_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    message = update.message.text
    success = 0
    failed = 0
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users")
    users = cursor.fetchall()
    conn.close()
    
    progress_msg = await update.message.reply_text("📤 Broadcasting message...")
    
    for user in users:
        try:
            await context.bot.send_message(
                chat_id=user[0],
                text=message,
                parse_mode="HTML"
            )
            success += 1
        except Exception as e:
            failed += 1
            logger.error(f"Failed to send broadcast to {user[0]}: {e}")
    
    await progress_msg.edit_text(
        f"✅ Broadcast completed!\n\n"
        f"📨 Sent: {success}\n"
        f"❌ Failed: {failed}"
    )
    
    return ConversationHandler.END

async def cancel_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    await query.edit_message_text("🚫 Broadcast cancelled")
    return ConversationHandler.END

# Main function
def main():
    # Setup database
    setup_database()
    
    # Get bot token from environment variable
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        logger.error("No token provided!")
        return
    
    # Create application
    application = Application.builder().token(token).build()
    
    # Add handlers
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("reset", reset_db))
    
    # Add broadcast handler
    broadcast_handler = ConversationHandler(
        entry_points=[CommandHandler('broadcast', broadcast_command)],
        states={
            BROADCAST: [MessageHandler(filters.TEXT & ~filters.COMMAND, handle_broadcast_message)]
        },
        fallbacks=[CallbackQueryHandler(cancel_broadcast, pattern='^cancel_broadcast$')]
    )
    application.add_handler(broadcast_handler)
    
    application.add_handler(CallbackQueryHandler(handle_callback_query))
    
    # Admin commands
    application.add_handler(MessageHandler(
        filters.Regex(r"^/approve_\d+_\d+$") | filters.Regex(r"^/reject_\d+_\d+$"),
        handle_admin_command
    ))
    
    # Handle account number input
    application.add_handler(MessageHandler(
        filters.TEXT & ~filters.COMMAND,
        handle_account_input
    ))
    
    # Start the bot
    application.run_polling()

def ping_server():
    app_url = os.getenv('RENDER_EXTERNAL_URL', 'http://localhost:5000')
    while True:
        try:
            response = requests.get(app_url)
            print(f"Ping successful: {response.status_code}")
        except Exception as e:
            print(f"Ping failed: {e}")
        time.sleep(300)  # 5 minutes


class CustomHandler(http.server.SimpleHTTPRequestHandler):  
    def do_GET(self):  
        self.send_response(200)  
        self.send_header("Content-type", "text/html")  
        self.end_headers()  

        self.wfile.write(b"<!doctype html><html><head><title>Server Status</title></head>")  
        self.wfile.write(b"<body><h1>Bot is running...</h1></body></html>")  

def run_web_server():  
    port = int(os.environ.get('PORT', 5000))  
    handler = CustomHandler  
    with socketserver.TCPServer(("", port), handler) as httpd:  
        print(f"Forwarder is running >> Serving at port {port}")  
        httpd.serve_forever()  

if __name__ == "__main__":
    server_thread = threading.Thread(target=run_web_server)
    ping_thread = threading.Thread(target=ping_server)

    server_thread.start()
    ping_thread.start()
    main()
