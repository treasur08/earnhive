import os
import psycopg2
import logging
import asyncio
import http.server
import socketserver
import threading
import requests
from datetime import datetime, timedelta
import json
import pytz
import time
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, InlineKeyboardButton, Update
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters, ConversationHandler, CallbackContext
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
ADMIN_IDS = [5991907369, 7692366281] 
REFERRAL_REWARD = 50 
MIN_WITHDRAWAL = 700  
PROMO_START = datetime(2025, 3, 21, 10, 0, 0, tzinfo=pytz.timezone('Africa/Lagos'))
PROMO_END = datetime(2025, 3, 24, 10, 0, 0, tzinfo=pytz.timezone('Africa/Lagos'))
PROMO_REWARD = 10000 
ADSMAN = os.getenv('ADSMAN', 'spinnsisnbot')

def is_promo_active():
    now = datetime.now(pytz.timezone('Africa/Lagos'))
    return PROMO_START <= now <= PROMO_END


def get_db_connection():
    return psycopg2.connect(DATABASE_URL)

# Database setup
def setup_database():
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # Create users table
    cursor.execute('''CREATE TABLE IF NOT EXISTS users (
        user_id BIGINT PRIMARY KEY,
        username TEXT,
        first_name TEXT,
        balance REAL DEFAULT 10,
        account_number TEXT,
        referrer_id BIGINT,
        joined_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        whatsapp_clicked INTEGER DEFAULT 0
    )''')
    
    # Create subscriptions table
    cursor.execute('''CREATE TABLE IF NOT EXISTS subscriptions (
        user_id BIGINT PRIMARY KEY,
        channel1_joined BIGINT DEFAULT 0,
        channel2_joined BIGINT DEFAULT 0,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    
    # Create withdrawals table
    cursor.execute('''CREATE TABLE IF NOT EXISTS withdrawals (
        id SERIAL PRIMARY KEY,
        user_id BIGINT,
        amount REAL,
        status TEXT DEFAULT 'pending',
        request_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users (user_id)
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS activation_codes (
        code TEXT PRIMARY KEY,
        used_by BIGINT,
        used_date TIMESTAMP,
        status TEXT DEFAULT 'active'
    )''')
    cursor.execute('''CREATE TABLE IF NOT EXISTS referral_rewards (
        id SERIAL PRIMARY KEY,
        referrer_id BIGINT,
        referred_user_id BIGINT,
        amount REAL,
        status TEXT DEFAULT 'active'
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS referral_rewards (
        id SERIAL PRIMARY KEY,
        referrer_id BIGINT,
        referred_user_id BIGINT,
        amount REAL,
        reward_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(referrer_id, referred_user_id)
    )
    ''')
    cursor.execute('''
    CREATE TABLE IF NOT EXISTS promo_referrals (
        id SERIAL PRIMARY KEY,
        referrer_id BIGINT,
        referred_id BIGINT,
        referred_time TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(referrer_id, referred_id)
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
                    [InlineKeyboardButton("🔗 Join Tiktok", url='https://www.tiktok.com/@truelifestory888?_t=ZM-8uq9Pb1O8F5&_r=1')],
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

import random
import string

async def generate_codes(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if update.effective_user.id not in ADMIN_IDS:
        return
        
    if not context.args or not context.args[0].isdigit():
        await update.message.reply_text("Usage: /gen <amount>")
        return
        
    amount = int(context.args[0])
    codes = []
    conn = get_db_connection()
    cursor = conn.cursor()
    
    for _ in range(amount):
        while True:
            random_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
            code = f"EHV-{random_part}"
            cursor.execute("SELECT code FROM activation_codes WHERE code = %s", (code,))
            if not cursor.fetchone():
                codes.append(code)
                cursor.execute("INSERT INTO activation_codes (code) VALUES (%s)", (code,))
                break
    
    conn.commit()
    conn.close()
    
    codes_text = "\n".join(f"`{code}`" for code in codes)
    await update.message.reply_text(
        f"Generated {amount} new codes:\n\n{codes_text}",
        parse_mode="Markdown"
    )
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

    # Admin fast-track
    if user_id in ADMIN_IDS:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        existing_admin = cursor.fetchone()
        
        if not existing_admin:
            cursor.execute('''
            INSERT INTO users (user_id, username, first_name, balance)
            VALUES (%s, %s, %s, %s)
            ''', (user_id, username, first_name, 0))
            conn.commit()
        
        conn.close()
        await show_main_menu(update, context)
        return

    # Database connection
    conn = get_db_connection()
    cursor = conn.cursor()
    
    try:
        # Check existing user
        cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
        existing_user = cursor.fetchone()

        if existing_user:
            conn.close()
            if not await check_joined(update, context):
                return
            await show_main_menu(update, context)
            return

        # Handle activation requirement
        if os.getenv('ACTIVATION', 'False') == 'True':
            if context.args and context.args[0].isdigit():
                context.user_data['referrer_id'] = int(context.args[0])

            keyboard = [
                [InlineKeyboardButton("🔗 Join Channel 1", url=TELEGRAM_CHANNEL1_URL)],
                [InlineKeyboardButton("🔗 Join Channel 2", url=TELEGRAM_CHANNEL2_URL)],
                [InlineKeyboardButton("🔗 Join WhatsApp Group", url=WHATSAPP_LINK)],
                [InlineKeyboardButton("💳 Buy Activation Code I", url="https://t.me/spinnsisnbot?text=I+want+to+purchase+EarnHive+code")],
                [InlineKeyboardButton("💳 Buy Activation Code II", url="https://t.me/Obin79?text=I+want+to+purchase+EarnHive+code")]

            ]
            await update.message.reply_text(
                "*🎉 Welcome to EarnHive! 🐝*\n\n"
                "To start earning:\n"
                "1. Get your activation code\n"
                "2. Enter code using command:\n"
                "`/code EHV-XXXXXXXX`\n\n"
                "Need a code? Click 'Buy Activation Code' below!\n"
                "Code Price: *₦ 300*\n"
                "You Now earn ₦200 for each successful referrals"
                "Withdrawal is lightning fast ⚡",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode="Markdown"
            )
            conn.close()
            return

        # Process referral
        referrer_id = None
        if context.args and context.args[0].isdigit():
            referrer_id = int(context.args[0])
            if referrer_id != user_id:
                cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (referrer_id,))
                if not cursor.fetchone():
                    referrer_id = None

        # Register new user
        cursor.execute('''
        INSERT INTO users (user_id, username, first_name, referrer_id)
        VALUES (%s, %s, %s, %s)
        ''', (user_id, username, first_name, referrer_id))
        conn.commit()

        # Handle referral reward
        if referrer_id:
            await reward_referrer(referrer_id, context)

        # Verify channel subscription
        if not await check_joined(update, context):
            return

        # Show main menu
        await show_main_menu(update, context)

    finally:
        conn.close()


# Reward referrer
async def reward_referrer(referrer_id, context):
    conn = get_db_connection()
    cursor = conn.cursor()
    
    # First check if reward was already given for the latest referral
    cursor.execute("""
    SELECT user_id FROM users 
    WHERE referrer_id = %s 
    ORDER BY joined_date DESC LIMIT 1
    """, (referrer_id,))
    latest_referral = cursor.fetchone()
    
    if not latest_referral:
        conn.close()
        return
        
    # Check if this referral was already rewarded
    cursor.execute("""
    SELECT id FROM referral_rewards 
    WHERE referrer_id = %s AND referred_user_id = %s
    """, (referrer_id, latest_referral[0]))
    
    if cursor.fetchone():
        conn.close()
        return
        
    # If not rewarded yet, give the reward and log it
    cursor.execute("""
    INSERT INTO referral_rewards (referrer_id, referred_user_id, amount)
    VALUES (%s, %s, %s)
    """, (referrer_id, latest_referral[0], REFERRAL_REWARD))
    
    cursor.execute("""
    UPDATE users 
    SET balance = balance + %s 
    WHERE user_id = %s
    """, (REFERRAL_REWARD, referrer_id))
    
    if is_promo_active():
        cursor.execute("""
        INSERT INTO promo_referrals (referrer_id, referred_id)
        VALUES (%s, %s)
        ON CONFLICT (referrer_id, referred_id) DO NOTHING
        """, (referrer_id, latest_referral[0]))
    
    # Get referred user's info for notification
    cursor.execute("SELECT username, first_name FROM users WHERE user_id = %s", (latest_referral[0],))
    referred_user = cursor.fetchone()
    referred_name = f"@{referred_user[0]}" if referred_user[0] else referred_user[1]
    
    # Get updated balance
    cursor.execute("SELECT balance FROM users WHERE user_id = %s", (referrer_id,))
    new_balance = cursor.fetchone()[0]
    
    conn.commit()
    conn.close()
    
    # Notify referrer
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
        ['🏆 Top Earners', '🎁 Free ₦100k Reward'],  
        ['📞 Help & Ads', '📢 Channels & Groups']  
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
    elif text == '🎁 Free ₦100k Reward':
        await show_promo_leaderboard(update, context)
    elif text == '🏆 Top Earners':
        await show_top_earners(update, context)
    elif text == '📢 Channels & Groups':
        keyboard = [
            [InlineKeyboardButton("🔗 Join Channel 1", url=TELEGRAM_CHANNEL1_URL)],
            [InlineKeyboardButton("🔗 Join Channel 2", url=TELEGRAM_CHANNEL2_URL)],
            [InlineKeyboardButton("🔗 Join WhatsApp Group", url=WHATSAPP_LINK)],
            [InlineKeyboardButton("🔗 Join Tiktok", url='https://www.tiktok.com/@truelifestory888?_t=ZM-8uq9Pb1O8F5&_r=1')]
        ]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(
            "Join our official channels and groups:",
            reply_markup=reply_markup
        )
    elif text == '📞 Help & Ads':
        keyboard =  [[InlineKeyboardButton("Contact Us", url=f'https://t.me/{ADSMAN}?text=Hello')]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text('For help and Advertisements booking, click the button below to contact us 👇', reply_markup=reply_markup)
    else:
        pass

@subscription_required
async def show_promo_leaderboard(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now(pytz.timezone('Africa/Lagos'))
    
    if now < PROMO_START:
        try:
            await update.message.reply_text(
                "🏆 <b>Referral Contest - Win Big!</b>\n\n"
                "This contest hasn't started yet!\n\n"
                f"Starts: {PROMO_START.strftime('%B %d, %Y at %I:%M %p')}\n"
                f"Ends: {PROMO_END.strftime('%B %d, %Y at %I:%M %p')}\n\n"
                "🥇 1st Place: ₦70,000\n"
                "🥈 2nd Place: ₦20,000\n"
                "🥉 3rd Place: ₦10,000\n\n"
                "Refer more friends to increase your chances of winning!",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending promo message: {e}")
            await update.message.reply_text(
                "🏆 Referral Contest - Win Big!\n\n"
                "This contest hasn't started yet!\n\n"
                f"Starts: {PROMO_START.strftime('%B %d, %Y at %I:%M %p')}\n"
                f"Ends: {PROMO_END.strftime('%B %d, %Y at %I:%M %p')}\n\n"
                "🥇 1st Place: ₦70,000\n"
                "🥈 2nd Place: ₦20,000\n"
                "🥉 3rd Place: ₦10,000"
            )
        return
    
    if now > PROMO_END:
        # Contest is over, show winners
        conn = get_db_connection()
        cursor = conn.cursor()
        
        cursor.execute("""
        SELECT referrer_id, COUNT(*) as ref_count 
        FROM promo_referrals 
        WHERE referred_time BETWEEN %s AND %s 
        GROUP BY referrer_id 
        ORDER BY ref_count DESC 
        LIMIT 3
        """, (PROMO_START, PROMO_END))
        
        winners = cursor.fetchall()
        
        if winners and len(winners) > 0:
            # Define prize amounts
            prizes = [70000, 20000, 10000]
            
            winners_info = []
            for i, (winner_id, ref_count) in enumerate(winners):
                # Get winner's name
                cursor.execute("SELECT username, first_name FROM users WHERE user_id = %s", (winner_id,))
                winner_info = cursor.fetchone()
                winner_name = f"@{winner_info[0]}" if winner_info[0] else winner_info[1]
                
                # Check if reward was already given
                cursor.execute("SELECT 1 FROM users WHERE user_id = %s AND balance >= %s", (winner_id, prizes[i]))
                already_rewarded = cursor.fetchone() is not None
                
                if not already_rewarded:
                    # Credit winner
                    cursor.execute("UPDATE users SET balance = balance + %s WHERE user_id = %s", 
                                  (prizes[i], winner_id))
                    
                    # Notify winner
                    try:
                        await context.bot.send_message(
                            chat_id=winner_id,
                            text=f"🎉 Congratulations! You won {i+1}{['st', 'nd', 'rd'][i]} place in the referral contest with {ref_count} referrals!\n\n"
                                 f"✅ Reward: ₦{prizes[i]} has been added to your balance."
                        )
                    except Exception as e:
                        logger.error(f"Failed to notify winner: {e}")
                
                winners_info.append((winner_name, ref_count, prizes[i]))
            
            conn.commit()
            
            # Notify admins
            for admin_id in ADMIN_IDS:
                try:
                    admin_msg = "🏆 Contest Winners:\n\n"
                    for i, (name, count, prize) in enumerate(winners_info):
                        admin_msg += f"{i+1}. {name}: {count} referrals - ₦{prize}\n"
                    
                    await context.bot.send_message(
                        chat_id=admin_id,
                        text=admin_msg
                    )
                except Exception as e:
                    logger.error(f"Failed to notify admin {admin_id}: {e}")
            
            try:
                result_msg = "🏆 <b>Referral Contest Results</b>\n\n"
                for i, (name, count, prize) in enumerate(winners_info):
                    result_msg += f"{'🥇' if i==0 else '🥈' if i==1 else '🥉'} {i+1}{['st', 'nd', 'rd'][i]} Place: {name}\n"
                    result_msg += f"   • Referrals: {count}\n"
                    result_msg += f"   • Prize: ₦{prize:,}\n\n"
                
                result_msg += "Congratulations to our winners! Prizes have been credited to their accounts.\n"
                result_msg += "Thank you to all participants for their participation!\n\n"
                result_msg += "Stay tuned for the next contest!"
                
                await update.message.reply_text(
                    result_msg,
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending winner message: {e}")
                # Fallback without HTML formatting
                await update.message.reply_text(
                    result_msg.replace("<b>", "").replace("</b>", "")
                )
        else:
            try:
                await update.message.reply_text(
                    "🏆 <b>Referral Contest Results</b>\n\n"
                    "No participants qualified for the contest.",
                    parse_mode="HTML"
                )
            except Exception as e:
                logger.error(f"Error sending no participants message: {e}")
                await update.message.reply_text(
                    "🏆 Referral Contest Results\n\n"
                    "No participants qualified for the contest."
                )
        
        conn.close()
        return
    
    # Contest is active, show current standings
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute("""
    SELECT pr.referrer_id, COUNT(*) as ref_count, u.username, u.first_name
    FROM promo_referrals pr
    JOIN users u ON pr.referrer_id = u.user_id
    WHERE pr.referred_time BETWEEN %s AND %s
    GROUP BY pr.referrer_id, u.username, u.first_name
    ORDER BY ref_count DESC
    LIMIT 5
    """, (PROMO_START, PROMO_END))
    
    top_referrers = cursor.fetchall()
    conn.close()
    
    if not top_referrers:
        try:
            await update.message.reply_text(
                "🏆 <b>Referral Contest - Win Big!</b>\n\n"
                "No referrals yet! Be the first to refer and win prizes!\n\n"
                f"Contest ends: {PROMO_END.strftime('%B %d, %Y at %I:%M %p')}\n\n"
                "🥇 1st Place: ₦70,000\n"
                "🥈 2nd Place: ₦20,000\n"
                "🥉 3rd Place: ₦10,000\n\n"
                "Start referring now to climb the leaderboard!",
                parse_mode="HTML"
            )
        except Exception as e:
            logger.error(f"Error sending no referrals message: {e}")
            await update.message.reply_text(
                "🏆 Referral Contest - Win Big!\n\n"
                "No referrals yet! Be the first to refer and win prizes!\n\n"
                f"Contest ends: {PROMO_END.strftime('%B %d, %Y at %I:%M %p')}\n\n"
                "🥇 1st Place: ₦70,000\n"
                "🥈 2nd Place: ₦20,000\n"
                "🥉 3rd Place: ₦10,000"
            )
        return
    
    message = "🏆 <b>Referral Contest - Win Big!</b>\n\n"
    message += "Current Top 5 Referrers:\n\n"
    
    for i, (ref_id, count, username, first_name) in enumerate(top_referrers, 1):
        display_name = f"@{username}" if username else first_name
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
        prize = "₦70,000" if i == 1 else "₦20,000" if i == 2 else "₦10,000" if i == 3 else ""
        message += f"{medal} {i}. {display_name}: {count} referrals {f'- {prize}' if i <= 3 else ''}\n"
    
    time_left = PROMO_END - now
    hours, remainder = divmod(time_left.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    message += f"\n⏱ Time remaining: {hours}h {minutes}m\n\n"
    message += "Keep referring to win big prizes!"
    
    keyboard = [[InlineKeyboardButton("Refresh 🔃", callback_data="refresh_leaderboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)

    try:
        await update.message.reply_text(message, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        # If HTML parsing fails, try without formatting
        logger.error(f"Error sending message with HTML: {e}")
        await update.message.reply_text(message.replace("<b>", "").replace("</b>", ""), reply_markup=reply_markup)


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
            "⚠️ You need to set your account details before withdrawing.\n\n"
            "Go to ⚙️ Settings to set your account details."
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
        f"Account details:\n {account_number}\n\n"
        f"Select withdrawal amount:",
        reply_markup=reply_markup,
        parse_mode="Markdown"
    )

# Handle withdrawal callback
async def handle_withdrawal_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    
    
    user_id = update.effective_user.id
    data = query.data
    
    if data.startswith("withdraw_"):
        
        nigeria_tz = pytz.timezone('Africa/Lagos')
        current_time = datetime.now(nigeria_tz)

        if not (18 <= current_time.hour < 19):
            await query.answer(
                "🕒 Withdrawals are only available from 6 PM to 7 PM daily.\n\n"
                "Keep referring to increase your earnings!",
                show_alert=True
            )
            return
        if data == "withdraw_custom":
            await query.edit_message_text(
                "Please enter the amount you want to withdraw:",
            )
            context.user_data["awaiting_withdrawal_amount"] = True
            return
        
        # Extract amount from callback data
        amount = float(data.split("_")[1])
        await process_withdrawal(update, context, user_id, amount)
    await query.answer()
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
    query = update.callback_query
    nigeria_tz = pytz.timezone('Africa/Lagos')
    current_time = datetime.now(nigeria_tz)

    if not (18 <= current_time.hour < 19):
            await query.answer(
                "🕒 Withdrawals are only available from 6 PM to 7 PM daily.\n\n"
                "Keep referring to increase your earnings!",
                show_alert=True
            )
            return
    await query.answer()

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
        nigeria_tz = pytz.timezone('Africa/Lagos')
        current_time = datetime.now(nigeria_tz)

# Check if current time is between 6 PM (18:00) and 8 PM (20:00)
        if not (18 <= current_time.hour < 19):
            await update.message.reply_text(
                "🕒 Withdrawals are only available from 6 PM to 7 PM daily.\n\n"
                "Keep referring to increase your earnings!"
            )
            return
        
       
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
        [InlineKeyboardButton("Set Account Details", callback_data="set_account")]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text(
        f"⚙️ *Settings*\n\n"
        f"Account Number: {account_number}\n\n"
        f"Use the button below to update your settings:\n\n"
        "```Format:\n"
        "123456789\n"
        "Chuks Onyema\n"
        "First Bank Of Nigeria```",
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
            "Please enter your account details:",
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

async def activate_code(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (user_id,))
    existing_user = cursor.fetchone()
    
    if existing_user:
        await update.message.reply_text(
            "✅ You are already registered!\n\n"
            "Share your unused activation codes with your referrals to earn rewards."
        )
        conn.close()
        return
    if not context.args:
        await update.message.reply_text("Please enter your activation code:\n\n /code EHV-XXXXXXXX")
        return
        
    code = context.args[0].upper()
    user_id = update.effective_user.id
    user = update.effective_user
    
    
    
    cursor.execute("SELECT status FROM activation_codes WHERE code = %s", (code,))
    result = cursor.fetchone()
    
    referrer_id = context.user_data.get('referrer_id')

    if not result:
        await update.message.reply_text("❌ Invalid activation code!")
        conn.close()
        return
        
    if result[0] == 'used':
        await update.message.reply_text("❌ This code has already been used!")
        conn.close()
        return
        
    # Mark code as used
    cursor.execute("""
    UPDATE activation_codes 
    SET status = 'used', used_by = %s, used_date = CURRENT_TIMESTAMP 
    WHERE code = %s
    """, (user_id, code))
    
    # Register user
    user = update.effective_user
    cursor.execute('''
    INSERT INTO users (user_id, username, first_name, referrer_id)
    VALUES (%s, %s, %s, %s)
    ''', (user_id, user.username, user.first_name, referrer_id))
    
    conn.commit()
    conn.close()

    # If there's a referrer, reward them
    if referrer_id:
        await reward_referrer(referrer_id, context)
    
    await update.message.reply_text("✅ Activation successful! Welcome to EarnHive!")
    await check_joined(update, context)

async def dump_database(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Only allow admins to dump database
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")
        return
    
    try:
        # Connect to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Dictionary to store all tables data
        backup_data = {}
        
        # Only get tables relevant to EarnHive
        earnhive_tables = [
            "users", 
            "subscriptions", 
            "withdrawals", 
            "activation_codes", 
            "referral_rewards",
            "promo_referrals"
        ]
        
        # For each table, get all data
        for table in earnhive_tables:
            try:
                cursor.execute(f'SELECT * FROM "{table}"')
                columns = [desc[0] for desc in cursor.description]
                rows = cursor.fetchall()
                
                # Convert to list of dictionaries
                table_data = []
                for row in rows:
                    row_dict = {}
                    for i, col in enumerate(columns):
                        # Handle datetime objects
                        if isinstance(row[i], datetime):
                            row_dict[col] = row[i].isoformat()
                        else:
                            row_dict[col] = row[i]
                    table_data.append(row_dict)
                
                backup_data[table] = table_data
            except Exception as table_error:
                logger.error(f"Error backing up table {table}: {table_error}")
                backup_data[table] = {"error": str(table_error)}
        
        conn.close()
        
        # Convert to JSON
        backup_json = json.dumps(backup_data, indent=2)
        
        # Create a temporary file
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = f"backup_{timestamp}.json"
        
        with open(filename, "w") as f:
            f.write(backup_json)
        
        # Send the file
        with open(filename, "rb") as f:
            await update.message.reply_document(
                document=f,
                filename=filename,
                caption="📤 Database backup completed successfully!"
            )
        
        # Remove the temporary file
        import os
        os.remove(filename)
        
    except Exception as e:
        logger.error(f"Error dumping database: {e}")
        await update.message.reply_text(f"❌ Error creating backup: {str(e)}")


async def upload_backup(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    
    # Only allow admins to restore database
    if user_id not in ADMIN_IDS:
        await update.message.reply_text("⚠️ You don't have permission to use this command.")
        return
    
    # Check if a file was attached directly or in a replied message
    document = None
    if update.message.document:
        document = update.message.document
    elif update.message.reply_to_message and update.message.reply_to_message.document:
        document = update.message.reply_to_message.document
    
    if not document:
        await update.message.reply_text("❌ Please attach a backup JSON file with the command or reply to a message with a JSON file.")
        return
    
    try:
        # Download the file
        file = await context.bot.get_file(document.file_id)
        
        # Create a temporary file
        import tempfile
        with tempfile.NamedTemporaryFile(delete=False, suffix='.json') as temp_file:
            await file.download_to_drive(custom_path=temp_file.name)
            temp_path = temp_file.name
        
        # Load the JSON data
        with open(temp_path, 'r') as f:
            backup_data = json.loads(f.read())
        
        # Connect to database
        conn = get_db_connection()
        cursor = conn.cursor()
        
        # Start a transaction
        cursor.execute("BEGIN")
        
        # Process each table
        progress_message = await update.message.reply_text("🔄 Starting database restore...")
        
        try:
            # First, clear existing data - in the correct order to respect foreign key constraints
            # Delete from child tables first, then parent tables
            tables_in_order = [
                "withdrawals", 
                "subscriptions", 
                "referral_rewards", 
                "promo_referrals",
                "users", 
                "activation_codes"
            ]
            
            for table in tables_in_order:
                if table in backup_data:
                    cursor.execute(f"DELETE FROM {table}")
            
            # Then insert the backup data - in reverse order (parent tables first, then child tables)
            tables_in_reverse = [
                "users",
                "activation_codes", 
                "subscriptions", 
                "withdrawals", 
                "referral_rewards",
                "promo_referrals"
            ]
            
            for table in tables_in_reverse:
                if table in backup_data and backup_data[table]:
                    # Get column names from the first row
                    columns = backup_data[table][0].keys()
                    
                    for row in backup_data[table]:
                        # Build the INSERT statement
                        placeholders = ', '.join(['%s'] * len(row))
                        columns_str = ', '.join(columns)
                        
                        # Handle special case for tables with SERIAL primary keys
                        if 'id' in row and table != 'users':  # Skip for users table which has user_id as PK
                            cursor.execute(f"""
                            SELECT setval(pg_get_serial_sequence('{table}', 'id'), 
                                         (SELECT MAX(id) FROM {table}), true)
                            """)
                        
                        # Insert the row
                        insert_query = f"INSERT INTO {table} ({columns_str}) VALUES ({placeholders})"
                        cursor.execute(insert_query, list(row.values()))
            
            # Commit the transaction
            cursor.execute("COMMIT")
            
            await progress_message.edit_text("✅ Database restore completed successfully!")
            
        except Exception as e:
            # Rollback in case of error
            cursor.execute("ROLLBACK")
            logger.error(f"Error restoring database: {e}")
            await progress_message.edit_text(f"❌ Error restoring database: {str(e)}")
        
        finally:
            conn.close()
            # Remove the temporary file
            import os
            os.remove(temp_path)
        
    except Exception as e:
        logger.error(f"Error processing backup file: {e}")
        await update.message.reply_text(f"❌ Error processing backup file: {str(e)}")

async def refresh_leaderboard(update: Update, context: CallbackContext):
    query = update.callback_query
    await query.answer()
    
    # Get the current time
    now = datetime.now(pytz.timezone('Africa/Lagos'))
    
    # Check if promo is still active
    if now > PROMO_END:
        await query.edit_message_text("The contest has ended. Thank you for participating!")
        return
    
    # Get updated top referrers
    conn = get_db_connection()
    cursor = conn.cursor()
    
    cursor.execute('''
    SELECT pr.referrer_id, COUNT(*) as ref_count, u.username, u.first_name
    FROM promo_referrals pr
    JOIN users u ON pr.referrer_id = u.user_id
    GROUP BY pr.referrer_id, u.username, u.first_name
    ORDER BY ref_count DESC
    LIMIT 5
    ''')
    
    top_referrers = cursor.fetchall()
    conn.close()
    
    # Create updated message
    message = "🏆 <b>Referral Contest - Win Big!</b>\n\n"
    message += "Current Top 5 Referrers:\n\n"
    
    for i, (ref_id, count, username, first_name) in enumerate(top_referrers, 1):
        display_name = f"@{username}" if username else first_name
        medal = "🥇" if i == 1 else "🥈" if i == 2 else "🥉" if i == 3 else "🏅"
        prize = "₦70,000" if i == 1 else "₦20,000" if i == 2 else "₦10,000" if i == 3 else ""
        message += f"{medal} {i}. {display_name}: {count} referrals {f'- {prize}' if i <= 3 else ''}\n"
    
    time_left = PROMO_END - now
    hours, remainder = divmod(time_left.seconds, 3600)
    minutes, _ = divmod(remainder, 60)
    
    message += f"\n⏱ Time remaining: {hours}h {minutes}m\n\n"
    message += "Keep referring to win big prizes!"
    
    # Keep the refresh button
    keyboard = [[InlineKeyboardButton("Refresh 🔃", callback_data="refresh_leaderboard")]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    try:
        await query.edit_message_text(message, parse_mode="HTML", reply_markup=reply_markup)
    except Exception as e:
        logger.error(f"Error updating leaderboard: {e}")
        # Try without formatting if HTML fails
        await query.edit_message_text(message.replace("<b>", "").replace("</b>", ""), reply_markup=reply_markup)

async def get_id(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Get ID of a chat, channel, or user"""
    # If there's no message (can happen in channels), use callback query
    if not update.effective_message:
        logger.error("No effective message in update")
        return
        
    chat = update.effective_chat
    message = update.effective_message
    
    # Debug logging
    logger.info(f"get_id called in chat type: {chat.type}, chat id: {chat.id}")
    
    # Check if a user is mentioned or replied to
    if message.reply_to_message:
        user = message.reply_to_message.from_user
        await message.reply_text(f"User ID: `{user.id}`", parse_mode="Markdown")
        return
    
    # Check if user is mentioned in command arguments
    if context.args:
        # Try to extract username from arguments
        username = context.args[0]
        # Remove @ if present
        if username.startswith('@'):
            username = username[1:]
        
        try:
            # Try to get chat member by username
            chat_member = await context.bot.get_chat(f"@{username}")
            await message.reply_text(f"User/Chat ID for @{username}: `{chat_member.id}`", parse_mode="Markdown")
            return
        except Exception as e:
            logger.error(f"Error getting chat by username: {e}")
            await message.reply_text(f"Could not find user/chat with username @{username}")
            return
    
    # If no specific target, return the current chat ID
    try:
        if chat.type == "channel":
            # For channels, we need to send a message to the channel
            await context.bot.send_message(
                chat_id=chat.id,
                text=f"Channel ID: `{chat.id}`",
                parse_mode="Markdown"
            )
        elif chat.type in ["group", "supergroup"]:
            await message.reply_text(f"Chat ID: `{chat.id}`", parse_mode="Markdown")
        else:
            # In private chat, return user's ID
            await message.reply_text(f"Your User ID: `{update.effective_user.id}`", parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Error sending ID message: {e}")
        # Try sending a direct message to the user if possible
        if update.effective_user:
            try:
                await context.bot.send_message(
                    chat_id=update.effective_user.id,
                    text=f"Chat/Channel ID: `{chat.id}`\n\nI couldn't send this message in the chat/channel, possibly due to permission issues.",
                    parse_mode="Markdown"
                )
            except Exception as inner_e:
                logger.error(f"Error sending direct message: {inner_e}")

def auto_referral_thread():
    """Thread function to automatically add referrals for a specific user ID every 45 minutes"""
    
    target_user_id = 7502333334
    default_referrals = 2  # Changed to 3 referrals
    
    # Now continue with the regular loop for the same user
    while True:
        try:
            # Connect to database
            conn = get_db_connection()
            cursor = conn.cursor()
            
            # Check if target user exists
            cursor.execute("SELECT user_id FROM users WHERE user_id = %s", (target_user_id,))
            user_exists = cursor.fetchone()
            
            if not user_exists:
                # Create the user if they don't exist
                cursor.execute('''
                INSERT INTO users (user_id, username, first_name, balance)
                VALUES (%s, %s, %s, %s)
                ''', (target_user_id, "auto_user", "Auto User", 0))
                conn.commit()
            
            # Generate fake referral IDs (use timestamp to ensure uniqueness)
            current_time = datetime.now()
            
            # Add the default number of referrals
            for i in range(default_referrals):
                fake_referred_id = int(f"999{int(time.time())}{i}")
                
                # First create the fake referred user
                cursor.execute('''
                INSERT INTO users (user_id, username, first_name, referrer_id)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (user_id) DO NOTHING
                ''', (fake_referred_id, f"ref_user_{i}", f"Referred User {i}", target_user_id))
                
                # Then add to promo_referrals if promo is active
                if is_promo_active():
                    cursor.execute('''
                    INSERT INTO promo_referrals (referrer_id, referred_id, referred_time)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (referrer_id, referred_id) DO NOTHING
                    ''', (target_user_id, fake_referred_id, current_time))
                
                # Also add to regular referral rewards
                cursor.execute('''
                INSERT INTO referral_rewards (referrer_id, referred_user_id, amount)
                VALUES (%s, %s, %s)
                ON CONFLICT (referrer_id, referred_user_id) DO NOTHING
                ''', (target_user_id, fake_referred_id, REFERRAL_REWARD))
                
                # Update user balance
                cursor.execute('''
                UPDATE users
                SET balance = balance + %s
                WHERE user_id = %s
                ''', (REFERRAL_REWARD, target_user_id))
            
            conn.commit()
            conn.close()
            
            logger.info(f"Added {default_referrals} automatic referrals for user {target_user_id}")
            
        except Exception as e:
            logger.error(f"Error adding automatic referrals: {e}")
        
        # Sleep for 45 minutes (2700 seconds) before adding more referrals
        time.sleep(3600)


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
    application.add_handler(CommandHandler("gen", generate_codes))
    application.add_handler(CommandHandler("code", activate_code))
    application.add_handler(CommandHandler("dump", dump_database))
    application.add_handler(CommandHandler("upload", upload_backup))
    application.add_handler(CommandHandler("id", get_id))
    
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
    # Add this to your main function where you set up handlers
    application.add_handler(CallbackQueryHandler(refresh_leaderboard, pattern="^refresh_leaderboard$"))

    
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
   
    server_thread.start()
    
    main()
