from threading import Thread
import time
from datetime import datetime

def keep_alive():
    print("✅ Keep-alive started")

def log_status():
    while True:
        current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        print(f"🟢 Bot running: {current_time}")
        time.sleep(300)

Thread(target=log_status, daemon=True).start()
keep_alive()
