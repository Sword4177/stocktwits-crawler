import asyncio
import json
from playwright.async_api import async_playwright

BASE_URL = "https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json?limit={limit}"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


async def fetch_stocktwits(ticker: str, limit: int = 30) -> list[dict]:
    url = BASE_URL.format(ticker=ticker.upper(), limit=limit)

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()

        try:
            await page.goto(url, wait_until="networkidle", timeout=30000)
            raw = await page.inner_text("body")
        finally:
            await browser.close()

    # Cloudflare チェック
    if "Just a moment" in raw or "Enable JavaScript" in raw:
        print(f"[警告] Cloudflare 拦截未通过: {raw[:200]}")
        return []

    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        print(f"[警告] JSON 解析失败，原始内容: {raw[:200]}")
        return []

    messages = data.get("messages", [])
    results = []
    for msg in messages:
        sentiment = ""
        if msg.get("entities", {}).get("sentiment"):
            sentiment = msg["entities"]["sentiment"].get("basic", "")
        results.append({
            "id":         str(msg["id"]),
            "body":       msg.get("body", ""),
            "created_at": msg.get("created_at", ""),
            "username":   msg.get("user", {}).get("username", ""),
            "sentiment":  sentiment,
        })

    await asyncio.sleep(2)
    return results
