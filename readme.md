# Telegram Referral & Earning Bot

A Telegram bot for managing referrals and earnings with subscription checks, withdrawal functionality, and admin controls.

## Features

- Referral system (70 Naira per referral)
- Subscription check for 2 Telegram channels and 1 WhatsApp link
- Dashboard with reply markup keyboards
- Balance checking
- Withdrawal system with admin approval
- Account settings management
- SQLite3 database (with future migration to PostgreSQL)

## Setup

1. Create a new bot with BotFather on Telegram and get your token
2. Set the following environment variables:
   - `TELEGRAM_BOT_TOKEN`: Your bot token from BotFather

3. Update the following constants in the code:
   - `TELEGRAM_CHANNEL1_ID`: ID of the first Telegram channel
   - `TELEGRAM_CHANNEL2_ID`: ID of the second Telegram channel
   - `WHATSAPP_LINK`: Link to your WhatsApp group
   - `ADMIN_IDS`: List of admin user IDs

4. Install dependencies:
```bash
pip install -r requirements.txt

```

5. Add the values to env
```bash
TELEGRAM_BOT_TOKEN = 'BOT_TOKEN'
TELEGRAM_CHANNEL2_ID = "ID ONE" 
TELEGRAM_CHANNEL1_ID = "ID TWO"
TELEGRAM_CHANNEL1_URL = "URL ONE"
TELEGRAM_CHANNEL2_URL = "URL TWO"
WHATSAPP_LINK = "https://chat.whatsapp.com/example"
DATABASE_URL = 'YOUR_DATABASE_URL'

```