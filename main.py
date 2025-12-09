import os
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
    """خلاصه/تحلیل فارسی با Gemini؛ اگر در دسترس نبود None برمی‌گرداند."""
    if not client:
        return None

    full_text = f"Title: {title_en}\n\nSummary: {summary_en}\n\nLink: {url}"

    prompt = f"""
تو یک ویراستار و تحلیل‌گر خبری فارسی‌زبان هستی.
این خبر سیاسی دربارهٔ جمهوری اسلامی ایران، نیروهای نیابتی‌اش یا موضوعات مرتبط مثل حجاب، اسرائیل و غزه است.

۱. یک خلاصهٔ دقیق و کوتاه (حداکثر ۳–۴ جمله) به زبان فارسی بنویس.
۲. اگر نقش سپاه پاسداران، نیروی قدس، حزب‌الله لبنان، حوثی‌های یمن، حشد الشعبی عراق یا دیگر گروه‌های نیابتی مطرح است، در متن روشن توضیح بده.
۳. اگر خبر به اسرائیل یا غزه مربوط است، این را هم شفاف بگو.
۴. لحن خبری، مستند و بدون شعار باشد.
۵. فقط بر اساس همین متن جمع‌بندی کن، چیزی اضافه نساز.

متن خبر:
{full_text}
"""

    try:
        resp = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
        )
        text = (resp.text or "").strip()
        if not text:
            return None
        return text[:1200]  # برای احتیاط در محدودیت تلگرام
    except Exception as e:
        print("AI error:", e)
        return None


def build_message_from_entry(entry) -> str | None:
    """از یک entry فید، پیام نهایی تلگرام را می‌سازد."""
    title = getattr(entry, "title", "").strip()
    summary = getattr(entry, "summary", "") or ""
    link = getattr(entry, "link", "") or ""

    if not title and not summary:
        return None

    content_for_filter = f"{title} {summary}"

    if not is_relevant(content_for_filter):
        return None

    ai_text = ai_process(title, summary, link)

    if ai_text:
        body_fa = ai_text
    else:
        body_fa = (
            "خلاصه‌ٔ خودکار این خبر موقتاً در دسترس نیست.\n\n"
            "چکیدهٔ انگلیسی:\n"
            f"{summary[:700]}"
        )

    msg = (
        f"{title}\n\n"
        f"{body_fa}\n\n"
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
    """خواندن همهٔ فیدها و ارسال خبرهای مهم به تلگرام."""
    for feed_url in RSS_FEEDS:
        print("Parsing feed:", feed_url)
        parsed = feedparser.parse(feed_url)
        entries = getattr(parsed, "entries", []) or []

        for entry in entries[:10]:
            msg = build_message_from_entry(entry)
            if msg:
                send_telegram(msg)


if __name__ == "__main__":
    process_rss()
