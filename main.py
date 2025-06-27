import os
import json
import requests
from datetime import datetime, timedelta
from bs4 import BeautifulSoup
import gspread
from oauth2client.service_account import ServiceAccountCredentials
import feedparser
from urllib.parse import quote_plus, urlparse

print("✅ Скрипт main.py запущен", flush=True)

# Загрузка ключевых слов
with open("keywords.txt", "r", encoding="utf-8") as f:
    KEYWORDS = [line.strip() for line in f if line.strip()]
print(f"🔑 Загружено {len(KEYWORDS)} ключевых слов", flush=True)

# Дата
yesterday = (datetime.utcnow() + timedelta(hours=3) - timedelta(days=1)).strftime('%Y-%m-%d')

# Авторизация в Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = os.getenv("GOOGLE_CREDS_JSON")
creds_dict = json.loads(creds_json)
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url("https://docs.google.com/spreadsheets/d/1ar4pf2_6zqmplMAFFuB2BsolhpHh00jFvn5kmigaVlE/edit")
worksheet = sheet.sheet1

# Получаем ссылки
existing_links = {row[2] for row in worksheet.get_all_values() if len(row) > 2 and row[2]}

# Поиск в Яндексе
def search_yandex_news(query):
    results = []
    url = f"https://yandex.ru/news/search?text={quote_plus(query)}&lr=213&from=day"  # 213 = Москва
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")
    for item in soup.select("article"):
        a_tag = item.find("a")
        h2_tag = item.find("h2")
        if a_tag and h2_tag:
            link = a_tag.get("href")
            title = h2_tag.get_text(strip=True)
            if link and link.startswith("/news"):
                link = "https://yandex.ru" + link
            results.append((title, link))
    return results

# Поиск в Google News
def search_google_news(query):
    encoded_query = quote_plus(f"{query} when:1d location:Russia")
    url = f"https://news.google.com/rss/search?q={encoded_query}&hl=ru&gl=RU&ceid=RU:ru"
    return [(entry.title, entry.link) for entry in feedparser.parse(url).entries]

# Проверка текста страницы
def keyword_in_article(link, keyword):
    try:
        resp = requests.get(link, timeout=5)
        if resp.status_code == 200:
            text = BeautifulSoup(resp.text, "html.parser").get_text(" ", strip=True).lower()
            return keyword.lower() in text
    except:
        pass
    return False

# Парсинг
found_rows = []
for keyword in KEYWORDS:
    yandex_results = search_yandex_news(keyword)
    google_results = search_google_news(keyword)
    combined = yandex_results + google_results
    new_items = 0

    for title, link in combined:
        if link in existing_links:
            continue
        if not keyword_in_article(link, keyword):
            continue
        found_rows.append([yesterday, title, link, "", keyword, "Да"])
        existing_links.add(link)
        new_items += 1

    print(f"🔸 {keyword} — новых: {new_items}, всего найдено: {len(combined)}", flush=True)

# Запись
if found_rows:
    worksheet.append_rows(found_rows)
    print(f"✅ Добавлено {len(found_rows)} строк в таблицу", flush=True)
else:
    worksheet.append_row([yesterday, "Нет новостей по ключевым словам", "", "", "", "Нет"])
    print("📭 Новостей не найдено", flush=True)

# Telegram
def send_telegram(text):
    token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")
    if token and chat_id:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = {"chat_id": chat_id, "text": text}
        try:
            requests.post(url, json=payload, timeout=5)
        except Exception as e:
            print(f"❌ Telegram error: {e}", flush=True)

send_telegram(f"📰 За {yesterday} добавлено {len(found_rows)} новостей." if found_rows else f"📭 За {yesterday} новостей не найдено.")
