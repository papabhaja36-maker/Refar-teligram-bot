"""
main.py — Entry point
Flask server (keep_alive) pehle start hota hai,
phir Telegram bot polling shuru hoti hai.
"""
from keep_alive import keep_alive
import bot

if __name__ == "__main__":
    keep_alive()   # Flask thread background mein
    bot.main()     # Telegram bot (blocking)
