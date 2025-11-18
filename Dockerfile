FROM python:3.9-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p sessions backups tdata ChatsForSpam

# Запускаем только основного бота
CMD python main.py
