import asyncio
import json
import logging
import yaml
from playwright.async_api import async_playwright
from config import BASE_DIR, POLL_INTERVAL, SYMBOL_LIMIT, TRENDING_LIMIT
from database import get_conn, init_db, save_post, total_count

logger = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def load_symbols() -> list[str]:
    with open(BASE_DIR / "symbols.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["symbols"]


async def _fetch_json(page, url: str) -> dict | None:
    await page.goto(url, wait_until="networkidle", timeout=30000)
    raw = await page.inner_text("body")

    if "Just a moment" in raw or "Enable JavaScript" in raw:
        logger.warning("Cloudflare 拦截: %s", url)
        return None

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        logger.warning("JSON 解析失败: %s", raw[:200])
        return None


def _parse_messages(data: dict, symbol: str, source: str) -> list[dict]:
    results = []
    for msg in data.get("messages", []):
        sentiment = ""
        if msg.get("entities", {}).get("sentiment"):
            sentiment = msg["entities"]["sentiment"].get("basic", "")
        results.append({
            "id":         str(msg["id"]),
            "symbol":     symbol,
            "source":     source,
            "body":       msg.get("body", ""),
            "sentiment":  sentiment,
            "likes":      msg.get("likes", {}).get("total", 0) or 0,
            "username":   msg.get("user", {}).get("username", ""),
            "published_at": msg.get("created_at", ""),
        })
    return results


async def crawl_once() -> None:
    symbols = load_symbols()
    conn = get_conn()
    init_db(conn)

    logger.info("=" * 50)
    logger.info("开始抓取，固定列表 %d 个股票 + trending", len(symbols))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        page = await context.new_page()
        total_saved = 0

        # 固定列表
        for symbol in symbols:
            url = f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json?limit={SYMBOL_LIMIT}"
            data = await _fetch_json(page, url)
            saved = 0
            if data:
                for p_data in _parse_messages(data, symbol, "symbol"):
                    if save_post(conn, p_data["id"], p_data["symbol"], p_data["source"],
                                 p_data["body"], p_data["sentiment"], p_data["likes"],
                                 p_data["username"], p_data["published_at"]):
                        saved += 1
            logger.info("  $%s 新增 %d 条", symbol, saved)
            total_saved += saved
            await asyncio.sleep(2)

        # trending
        logger.info("▶ 抓取 trending...")
        trend_url = f"https://api.stocktwits.com/api/2/trending/symbols/equities.json?limit={TRENDING_LIMIT}"
        trend_data = await _fetch_json(page, trend_url)
        trend_saved = 0
        if trend_data:
            for item in trend_data.get("symbols", []):
                sym = item.get("symbol", "")
                if not sym:
                    continue
                sym_url = f"https://api.stocktwits.com/api/2/streams/symbol/{sym}.json?limit=10"
                sym_data = await _fetch_json(page, sym_url)
                if sym_data:
                    for p_data in _parse_messages(sym_data, sym, "trending"):
                        if save_post(conn, p_data["id"], p_data["symbol"], p_data["source"],
                                     p_data["body"], p_data["sentiment"], p_data["likes"],
                                     p_data["username"], p_data["published_at"]):
                            trend_saved += 1
                await asyncio.sleep(2)

        logger.info("  trending 新增 %d 条", trend_saved)
        total_saved += trend_saved

        await browser.close()

    logger.info("完成 — 本次新增 %d 条，数据库累计 %d 条", total_saved, total_count(conn))
    logger.info("=" * 50)
    conn.close()


async def run_loop() -> None:
    logger.info("轮询启动，间隔 %d 秒", POLL_INTERVAL)
    while True:
        try:
            await crawl_once()
        except Exception as e:
            logger.error("抓取异常: %s", e)
        await asyncio.sleep(POLL_INTERVAL)
