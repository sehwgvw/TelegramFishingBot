from flask import Flask
import os

app = Flask(__name__)

@app.route('/')
def home():
    return "🤖 Bot is ALIVE and RUNNING 24/7!"

@app.route('/health')
def health():
    return "OK"

if __name__ == "__main__":
    app.run(host='0.0.0.0', port=5000)
