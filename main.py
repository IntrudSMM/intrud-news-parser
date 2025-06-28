import os
import json
from dotenv import load_dotenv
load_dotenv()

import datetime
import requests
import feedparser
import gspread
from bs4 import BeautifulSoup
from oauth2client.service_account import ServiceAccountCredentials
from urllib.parse import quote_plus
import pymorphy2
import telegram

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
sheet = client.open_by_key(os.environ["SPREADSHEET_ID"]).sheet1
print("📗 Авторизация в Google Sheets успешна")

bot = None
chat_id = os.environ.get("TELEGRAM_CHAT_ID")
token = os.environ.get("TELEGRAM_BOT_TOKEN")

if chat_id and token:
    bot = telegram.Bot(token=token)


# 🧠 Морфологический разбор
morph = pymorphy2.MorphAnalyzer()
def normalize_text(text):
    return " ".join([morph.parse(word)[0].normal_form for word in text.lower().split()])

def is_relevant(title, keyword):
    norm_title = normalize_text(title)
    norm_keyword = normalize_text(keyword)
    return norm_keyword in norm_title

# 🔍 Поиск в Яндексе
def search_yandex_news(query):
    url = f"https://yandex.ru/news/search?text={quote_plus(query)}&rdr=1&lr=213"
    headers = {"User-Agent": "Mozilla/5.0"}
    resp = requests.get(url, headers=headers)
    soup = BeautifulSoup(resp.text, "html.parser")
    results = []

    for article in soup.select("article"):
        title_tag = article.find("h2")
        link_tag = article.find("a")

        if title_tag and link_tag:
            title = title_tag.get_text(strip=True)
            yandex_link = link_tag.get("href")

            # Преобразуем внутреннюю ссылку в внешнюю
            if yandex_link and yandex_link.startswith("/news"):
                full_yandex_url = "https://yandex.ru" + yandex_link
                try:
                    preview = requests.get(full_yandex_url, headers=headers, timeout=5)
                    preview_soup = BeautifulSoup(preview.text, "html.parser")
                    real_link = None

                    for tag in preview_soup.find_all("a", href=True):
                        if "yandex.ru" not in tag["href"] and tag["href"].startswith("http"):
                            real_link = tag["href"]
                            break

                    if real_link:
                        results.append((title, real_link))
                    else:
                        results.append((title, full_yandex_url))  # fallback

                except Exception as e:
                    print(f"⚠️ Ошибка при получении внешней ссылки Яндекса: {e}")
                    results.append((title, full_yandex_url))
            else:
                results.append((title, yandex_link))

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
if os.path.exists("sent_posts.json"):
    with open("sent_posts.json", "r", encoding="utf-8") as f:
        try:
            sent_links = set(json.load(f))
        except json.JSONDecodeError:
            pass

def save_and_log(results, keyword):
    saved = []
    for title, link in results:
        if link not in sent_links:
            sheet.append_row([yesterday, keyword, title, link])
            sent_links.add(link)
            saved.append((title, link, keyword))
    return saved

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

    # 📈 Логируем все найденные статьи
    for source, results in [("🟡 Яндекс", yandex_results), ("🔵 Google", google_results)]:
        for title, link in results:
            print(f"{source} ➤ {title}\n   ↪ {link}")

    # 🧰 Морфологическая фильтрация
    filtered_results = []
    for title, link in combined:
        if is_relevant(title, keyword):
            filtered_results.append((title, link))

    # 📊 Сохраняем новые
    new_items = save_and_log(filtered_results, keyword)
    found_links.extend(new_items)
    print(f"📌 {keyword} — новых: {len(new_items)}, всего найдено: {found_count}\n")


# 📆 Сохраняем все ссылки
with open("sent_posts.json", "w", encoding="utf-8") as f:
    json.dump(list(sent_links), f, ensure_ascii=False, indent=2)

# 📨 Если ничего не найдено — пишем в таблицу
if not found_links:
    sheet.append_row([yesterday, "Нет новостей", "", ""])
    print("👭 Новостей не найдено — добавлена строка-заглушка")

import re
def escape_markdown(text):
    return re.sub(r'([_*\[\]()~`>#+\-=|{}.!])', r'\\\1', text)

if bot:
    if found_links:
        max_length = 4096
        header = f"🗞 Новости за {yesterday}:\n\n"
        footer = f"\n📊 Всего новостей: {len(found_links)}"
        message_blocks = []
        current_block = header
        i = 1

        for title, link, keyword in found_links:
            entry = f"{i}. 📰 *{escape_markdown(title)}*\n🔗 [Читать статью]({link})\n🏷 Ключ: `{escape_markdown(keyword)}`\n\n"
            if len(current_block) + len(entry) + len(footer) > max_length:
                message_blocks.append(current_block)
                current_block = ""
            current_block += entry
            i += 1

        if current_block:
            message_blocks.append(current_block)

        for j, block in enumerate(message_blocks):
            final_text = block
            if j == len(message_blocks) - 1:
                final_text += footer
            try:
                bot.send_message(chat_id=chat_id, text=final_text, parse_mode=telegram.ParseMode.MARKDOWN)
            except Exception as e:
                print(f"❌ Ошибка при отправке сообщения {j+1}: {e}")
    else:
        bot.send_message(chat_id=chat_id, text=f"📭 За {yesterday} новостей не найдено.")
else:
    print("⚠️ Telegram переменные окружения не заданы")

