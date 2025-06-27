import os
import json
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import feedparser

print("✅ Скрипт main.py запущен", flush=True)

# Загрузка ключевых слов из файла
with open("keywords.txt", "r", encoding="utf-8") as f:
    KEYWORDS = [line.strip() for line in f if line.strip()]
print(f"🔑 Загружено {len(KEYWORDS)} ключевых слов", flush=True)

# Время - ищем за вчера
yesterday = (datetime.utcnow() + timedelta(hours=3) - timedelta(days=1)).strftime('%Y-%m-%d')

# Авторизация в Google Sheets
try:
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    creds_json = os.getenv("GOOGLE_CREDS_JSON")
    creds_dict = json.loads(creds_json)
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    client = gspread.authorize(creds)
    sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1ar4pf2_6zqmplMAFFuB2BsolhpHh00jFvn5kmigaVlE/edit")
    worksheet = sheet.sheet1
    print("📗 Авторизация в Google Sheets прошла успешно", flush=True)
except Exception as e:
    print(f"❌ Ошибка авторизации в Google Sheets: {e}", flush=True)
    exit(1)

# Получаем уже существующие ссылки (3-я колонка)
existing_records = worksheet.get_all_values()
existing_links = {row[2] for row in existing_records if len(row) > 2 and row[2]}
print(f"🔍 Поиск новостей за {yesterday} по {len(KEYWORDS)} ключевым словам...", flush=True)

# --- Поиск в Яндексе
def search_yandex_news(query):
    url = f"https://yandex.ru/news/search?text={query}&from=day"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []
    for item in soup.select("article"):
        title_tag = item.find("h2")
        link_tag = item.find("a")
        if title_tag and link_tag:
            title = title_tag.get_text(strip=True)
            link = link_tag.get("href")
            if link and link.startswith("/news"):
                link = "https://yandex.ru" + link
            results.append((title, link))
    return results

# --- Поиск в Google News
def search_google_news(query):
    url = f"https://news.google.com/rss/search?q={query}"
    feed = feedparser.parse(url)
    results = []
    for entry in feed.entries:
        results.append((entry.title, entry.link))
    return results

# --- Основной парсинг
found_rows = []
for keyword in KEYWORDS:
    yandex_results = search_yandex_news(keyword)
    google_results = search_google_news(keyword)

    combined = yandex_results + google_results
    new_items = 0

    for title, link in combined:
        if link not in existing_links:
            found_rows.append([yesterday, title, link, "", keyword, "Да"])
            existing_links.add(link)
            new_items += 1

    print(f"🔸 {keyword} — найдено {new_items} новых из {len(combined)} всего", flush=True)

# --- Запись результатов
if found_rows:
    try:
        worksheet.append_rows(found_rows)
        print(f"✅ Добавлено {len(found_rows)} строк в Google Sheets", flush=True)
    except Exception as e:
        print(f"❌ Ошибка записи в Google Sheets: {e}", flush=True)
else:
    worksheet.append_row([yesterday, "Нет новостей по ключевым словам", "", "", "", "Нет"])
    print("⚠️ Новостей не найдено. Добавлена строка с пометкой.", flush=True)

# Telegram уведомление
def send_telegram_message(text):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("⚠️ Telegram переменные окружения не заданы", flush=True)
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, json=payload)
        print(f"📬 Telegram статус: {resp.status_code}, ответ: {resp.text}", flush=True)
    except Exception as e:
        print(f"❌ Ошибка отправки Telegram: {e}", flush=True)

# Отправка уведомления
if found_rows:
    send_telegram_message(f"📰 Добавлено {len(found_rows)} новостей за {yesterday}")
else:
    send_telegram_message(f"📭 За {yesterday} новостей по ключевым словам не найдено")
