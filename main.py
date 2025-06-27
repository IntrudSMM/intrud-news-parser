import os
import json
import datetime
import requests
import feedparser
import gspread
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials
from urllib.parse import quote_plus
import pymorphy2

# 📅 Дата поиска: вчера
yesterday = (datetime.datetime.now() - datetime.timedelta(days=1)).strftime("%Y-%m-%d")

print("✅ Скрипт main.py запущен")

# 📁 Загрузка ключевых слов
with open("keywords.txt", "r", encoding="utf-8") as f:
    KEYWORDS = [line.strip() for line in f if line.strip()]

print(f"🔑 Загружено {len(KEYWORDS)} ключевых слов")

# 📄 Авторизация Google Sheets
scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
creds_json = json.loads(os.environ["GOOGLE_CREDS_JSON"])
creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_json, scope)
client = gspread.authorize(creds)
sheet = client.open_by_url(os.environ["SHEET_URL"]).sheet1

print("📗 Авторизация в Google Sheets успешна")

# 🧠 Морфологический разбор
morph = pymorphy2.MorphAnalyzer()

def normalize_text(text):
    return " ".join([morph.parse(word)[0].normal_form for word in text.lower().split()])

# 🔍 Поиск в Яндексе
def search_yandex_news(query):
    url = f"https://yandex.ru/news/search?text={quote_plus(query)}&rdr=1&lr=213"
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

# 🔍 Поиск в Google News
def search_google_news(query):
    cleaned_query = query.strip().replace('\n', ' ').replace('\r', ' ')
    encoded_query = quote_plus(cleaned_query)
    url = f"https://news.google.com/rss/search?q={encoded_query}+when:{yesterday}&hl=ru&gl=RU&ceid=RU:ru"
    feed = feedparser.parse(url)
    return [(entry.title, entry.link) for entry in feed.entries]

# 📋 Чтение уже отправленных новостей
sent_links = set()
with open("sent_posts.json", "r", encoding="utf-8") as f:
    try:
        sent_links = set(json.load(f))
    except json.JSONDecodeError:
        pass

# 🚀 Основной цикл по ключевым словам
found_links = []
print(f"🔍 Поиск новостей за {yesterday}")

for keyword in KEYWORDS:
    print(f"🔎 Яндекс: {keyword}")
    yandex_results = search_yandex_news(keyword)

    print(f"🔎 Google News: {keyword}")
    google_results = search_google_news(keyword)

    combined = yandex_results + google_results
    found_count = len(combined)

# Логируем всё, что нашли
for source, results in [('🟡 Яндекс', yandex_results), ('🔵 Google', google_results)]:
    for title, link in results:
        print(f"{source} ➤ {title}\n   ↪ {link}")

# Морфологическая проверка (если включена)
filtered_results = []
for title, link in combined:
    if is_relevant(title, keyword):
        filtered_results.append((title, link))

# Итог по ключу
new_count = save_and_log(filtered_results, keyword)
print(f"📌 {keyword} — новых: {new_count}, всего найдено: {found_count}\n")


# 💾 Сохраняем отправленные ссылки
with open("sent_posts.json", "w", encoding="utf-8") as f:
    json.dump(list(sent_links), f, ensure_ascii=False, indent=2)

# 📨 Если ничего не найдено — добавляем строку-заглушку
if not found_links:
    sheet.append_row([yesterday, "Нет новостей", "", ""])
    print("📭 Новостей не найдено — добавлена строка-заглушка")
