import os
import json
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import feedparser
from urllib.parse import quote_plus
from pymorphy2 import MorphAnalyzer

print("✅ Скрипт main.py запущен", flush=True)

# Инициализация морфоанализатора
morph = MorphAnalyzer()

def normalize(text):
    words = text.lower().split()
    return ' '.join([morph.parse(w)[0].normal_form for w in words])

# Загрузка ключевых слов
with open("keywords.txt", "r", encoding="utf-8") as f:
    KEYWORDS = [line.strip() for line in f if line.strip()]
print(f"🔑 Загружено {len(KEYWORDS)} ключевых слов", flush=True)

# Дата: вчера
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
    print("📗 Авторизация в Google Sheets успешна", flush=True)
except Exception as e:
    print(f"❌ Ошибка авторизации в Google Sheets: {e}", flush=True)
    exit(1)

existing_links = {
    row[2] for row in worksheet.get_all_values() if len(row) > 2 and row[2]
}

# --- Поиск в Яндексе
def search_yandex_news(query):
    print(f"🔎 Яндекс: {query}", flush=True)
    url = f"https://yandex.ru/news/search?text={quote_plus(query)}&from=day"
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
    print(f"🔎 Google News: {query}", flush=True)
    encoded_query = quote_plus(f"{query} when:1d location:Russia")
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ru&gl=RU&ceid=RU:ru"
    feed = feedparser.parse(url)
    return [(entry.title, entry.link) for entry in feed.entries]

# --- Проверка совпадения по леммам
def is_match(keyword, title):
    return normalize(keyword) in normalize(title)

# --- Основной цикл
found_rows = []
for keyword in KEYWORDS:
    yandex_results = search_yandex_news(keyword)
    google_results = search_google_news(keyword)
    combined = yandex_results + google_results
    new_items = 0

    for title, link in combined:
        if link in existing_links:
            continue
        if not is_match(keyword, title):
            continue
        found_rows.append([yesterday, title, link, "", keyword, "Да"])
        existing_links.add(link)
        new_items += 1

    print(f"📌 {keyword} — новых: {new_items}, всего получено: {len(combined)}", flush=True)

# --- Запись результатов
if found_rows:
    try:
        worksheet.append_rows(found_rows)
        print(f"✅ Добавлено {len(found_rows)} строк в Google Sheets", flush=True)
    except Exception as e:
        print(f"❌ Ошибка записи в Google Sheets: {e}", flush=True)
else:
    worksheet.append_row([yesterday, "Нет новостей по ключевым словам", "", "", "", "Нет"])
    print("📭 Новостей не найдено — добавлена строка-заглушка", flush=True)

# --- Telegram уведомление
def send_telegram_message(text):
    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if not bot_token or not chat_id:
        print("⚠️ Отсутствуют переменные Telegram", flush=True)
        return
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {"chat_id": chat_id, "text": text}
    try:
        resp = requests.post(url, json=payload)
        print(f"📬 Telegram статус: {resp.status_code}, ответ: {resp.text}", flush=True)
    except Exception as e:
        print(f"❌ Ошибка Telegram: {e}", flush=True)

# Отправка уведомления
if found_rows:
    send_telegram_message(f"📰 Добавлено {len(found_rows)} новостей за {yesterday}")
else:
    send_telegram_message(f"📭 За {yesterday} новостей по ключевым словам не найдено")
