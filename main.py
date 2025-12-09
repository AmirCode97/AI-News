import os
import time
import requests
import feedparser
from google import genai


# ---------- تنظیمات عمومی ----------

# فیدهایی که می‌خواهی مانیتور کنی
RSS_FEEDS = [
    # اسرائیل / انگلیسی
    "https://www.jpost.com//rss/rssfeedsiran",
    "https://www.jpost.com//rss/rssfeedsmiddleeastnews.aspx",

    # الجزیره (همهٔ خبرها؛ با فیلتر کلمه‌کلیدی خودت محدودش می‌کنی)
    "https://www.aljazeera.com/xml/rss/all.xml",

    # AJ+ English
    "https://www.ajplus.net/rss",

    # اینجا می‌توانی فیدهای عربی/آمریکایی دیگر را که از لیست‌های RSS پیدا می‌کنی اضافه کنی
    # "https://example.com/path/to/arabic-feed.xml",
]

# کلیدواژه‌ها برای تشخیص ربط داشتن خبر
KEYWORDS = [
    "Iran", "IRGC", "Revolutionary Guard", "Revolutionary Guards",
    "Hezbollah", "Houthi", "Houthis", "militia", "proxy",
    "Quds Force", "IRAN", "Tehran",
    "Hijab", "Hejab", "Gaza", "Israel",
]

# متغیرهای محیطی (در GitHub Secrets یا روی سرور ست کن)
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHANNEL_ID = os.environ["TELEGRAM_CHANNEL_ID"]  # مثلا @your_channel یا عدد
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")

# نام مدل Gemini
GEMINI_MODEL = "gemini-2.5-flash"

# ---------- کلاینت Gemini ----------

client = None
if GEMINI_API_KEY:
    client = genai.Client(api_key=GEMINI_API_KEY)


# ---------- توابع کمکی ----------

def is_relevant(text: str) -> bool:
    """بررسی این‌که متن به ایران/نیروهای نیابتی و موضوعات مرتبط ربط دارد یا نه."""
    t = text.lower()
    return any(k.lower() in t for k in KEYWORDS)


def ai_process(title_en: str, summary_en: str, url: str) -> str | None:
    """ترجمه و بازنویسی خبر به فارسی؛ فقط متن فارسی برمی‌گرداند."""
    if not client:
        return None

    full_text = f"Title: {title_en}\n\nSummary: {summary_en}\n\nLink: {url}"

    prompt = f"""
متن زیر یک خبر سیاسی به زبان انگلیسی است.

لطفاً:

- یک عنوان خبری کوتاه و روان به فارسی بنویس (در یک جمله).
- سپس در ۳ تا ۵ جمله، متن خبر را به فارسی ترجمه و بازنویسی کن.
- از هیچ جملهٔ انگلیسی استفاده نکن.
- لحن کاملاً خبری و روشن باشد، نه شعاری.
- چیزی خارج از متن اصلی اضافه نکن.

خروجی نهایی تو باید فقط فارسی باشد؛
خط اول عنوان، بقیه خطوط متن خبر.

متن خبر:
{full_text}
"""

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )  # مطابق داک رسمی Gemini API. [web:60][web:70]
        text = (resp.text or "").strip()
        if not text:
            return None
        return text[:1500]
    except Exception as e:
        print("AI error:", e)
        return None


def build_message_from_entry(entry) -> str | None:
    """از یک entry فید، پیام نهایی تلگرام را می‌سازد (فقط فارسی)."""
    title_en = getattr(entry, "title", "").strip()
    summary_en = getattr(entry, "summary", "") or ""
    link = getattr(entry, "link", "") or ""

    if not title_en and not summary_en:
        return None

    content_for_filter = f"{title_en} {summary_en}"
    if not is_relevant(content_for_filter):
        return None

    ai_text = ai_process(title_en, summary_en, link)

    if not ai_text:
        # اگر AI در دسترس نبود، فقط یک توضیح کوتاه فارسی + لینک بفرست
        body_fa = "ترجمه خودکار این خبر در حال حاضر انجام نشد. برای دیدن متن اصلی روی لینک زیر بزنید."
        msg = (
            f"{body_fa}\n\n"
            f"منبع اصلی: {link}\n\n"
            f"#Iran #IRGC #Hezbollah #Houthis #Hijab #Israel #Gaza"
        )
        return msg[:3500]

    # ai_text خودش شامل عنوان و متن فارسی است، همان را استفاده می‌کنیم
    msg = (
        f"{ai_text}\n\n"
        f"منبع اصلی: {link}\n\n"
        f"#Iran #IRGC #Hezbollah #Houthis #Hijab #Israel #Gaza"
    )
    return msg[:3500]


def send_telegram(text: str):
    """ارسال پیام به کانال تلگرام از طریق Bot API."""
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHANNEL_ID,
        "text": text,
        "disable_web_page_preview": False,
    }
    try:
        r = requests.post(url, data=data, timeout=20)
        print("Telegram status:", r.status_code, r.text)
    except Exception as e:
        print("Telegram error:", e)


def process_rss():
    """خواندن همهٔ فیدها و ارسال خبرهای مهم و غیرتکراری به تلگرام."""
    seen_links = set()
    now_ts = time.time()
    max_age_seconds = 30 * 60  # فقط خبرهای 30 دقیقهٔ اخیر

    for feed_url in RSS_FEEDS:
        print("Parsing feed:", feed_url)
        parsed = feedparser.parse(feed_url)
        entries = getattr(parsed, "entries", []) or []

        for entry in entries[:20]:
            link = getattr(entry, "link", "") or ""
            if link in seen_links:
                continue
            seen_links.add(link)

            # اگر فید زمان انتشار دارد، خبرهای قدیمی را رد کن
            published_ts = None
            if hasattr(entry, "published_parsed") and entry.published_parsed:
                published_ts = time.mktime(entry.published_parsed)

            if published_ts and (now_ts - published_ts) > max_age_seconds:
                continue

            msg = build_message_from_entry(entry)
            if msg:
                send_telegram(msg)
