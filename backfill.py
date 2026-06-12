"""
backfill.py — 拉取 symbols.yaml 中所有 ticker 近 N 天的历史帖子
使用 StockTwits API 的 max 参数向前翻页，直到超出日期范围为止

运行示例：
  python backfill.py                        # 全部 ticker，30 天
  python backfill.py --symbol NVDA          # 只回填 NVDA，30 天
  python backfill.py --symbol NVDA --days 10  # 只回填 NVDA，10 天
"""
import argparse
import asyncio
import json
import logging
import yaml
from datetime import datetime, timezone, timedelta
from pathlib import Path
from playwright.async_api import async_playwright
from database import get_conn, init_db, save_post, total_count

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
DELAY = 5.0          # 每次请求间隔（秒），避免触发限流
MAX_PAGES = 2000     # 单个 symbol 最多翻页数（防止死循环）

USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


def load_symbols() -> list[str]:
    with open(BASE_DIR / "symbols.yaml", encoding="utf-8") as f:
        return yaml.safe_load(f)["symbols"]


def cutoff_dt(days: int) -> datetime:
    return datetime.now(timezone.utc) - timedelta(days=days)


def parse_dt(s: str) -> datetime | None:
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except Exception:
        return None


async def fetch_json(page, url: str) -> dict | None:
    for attempt in range(1, 4):
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=60000)
            raw = await page.inner_text("body")
            if "Just a moment" in raw or "Enable JavaScript" in raw:
                logger.warning("Cloudflare 拦截: %s", url)
                return None
            return json.loads(raw)
        except Exception as e:
            wait = attempt * 30
            logger.warning("第%d次失败（%s），等待%ds后重试…", attempt, type(e).__name__, wait)
            await asyncio.sleep(wait)
    logger.error("3次重试均失败，跳过: %s", url)
    return None


def parse_messages(data: dict, symbol: str) -> list[dict]:
    results = []
    for msg in data.get("messages", []):
        sentiment = ""
        if msg.get("entities", {}).get("sentiment"):
            sentiment = msg["entities"]["sentiment"].get("basic", "")
        results.append({
            "id":           str(msg["id"]),
            "symbol":       symbol,
            "source":       "symbol",
            "body":         msg.get("body", ""),
            "sentiment":    sentiment,
            "likes":        msg.get("likes", {}).get("total", 0) or 0,
            "username":     msg.get("user", {}).get("username", ""),
            "published_at": msg.get("created_at", ""),
        })
    return results


async def backfill_symbol(page, conn, symbol: str, cutoff: datetime) -> int:
    saved_total = 0
    cursor_max = None

    for page_num in range(1, MAX_PAGES + 1):
        if cursor_max:
            url = (f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
                   f"?limit=30&max={cursor_max}")
        else:
            url = (f"https://api.stocktwits.com/api/2/streams/symbol/{symbol}.json"
                   f"?limit=30")

        data = await fetch_json(page, url)
        if not data or not data.get("messages"):
            break

        messages = parse_messages(data, symbol)
        if not messages:
            break

        # 保存本页，记录最旧消息时间
        oldest_dt = None
        for m in messages:
            save_post(conn, m["id"], m["symbol"], m["source"],
                      m["body"], m["sentiment"], m["likes"],
                      m["username"], m["published_at"])
            saved_total += 1
            dt = parse_dt(m["published_at"])
            if dt and (oldest_dt is None or dt < oldest_dt):
                oldest_dt = dt

        logger.info("    $%s 第%d页 %d条  最旧：%s",
                    symbol, page_num, len(messages),
                    oldest_dt.strftime("%Y-%m-%d") if oldest_dt else "?")

        # 超出30天范围，停止
        if oldest_dt and oldest_dt < cutoff:
            break

        # 取下一页游标
        cursor_max = data.get("cursor", {}).get("max")
        if not cursor_max:
            break

        await asyncio.sleep(DELAY)

    return saved_total


async def run(symbols: list[str], days: int) -> None:
    cutoff = cutoff_dt(days)
    conn = get_conn()
    init_db(conn)

    logger.info("开始回填，目标：%d 个 ticker，%d 天历史（截止 %s）",
                len(symbols), days, cutoff.strftime("%Y-%m-%d"))

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(user_agent=USER_AGENT)
        pg = await context.new_page()

        grand_total = 0
        for i, symbol in enumerate(symbols, 1):
            before = total_count(conn)
            logger.info("[%d/%d] $%s ...", i, len(symbols), symbol)
            saved = await backfill_symbol(pg, conn, symbol, cutoff)
            after = total_count(conn)
            logger.info("  $%s 完成，新入库 %d 条（数据库共 %d 条）",
                        symbol, after - before, after)
            grand_total += after - before
            await asyncio.sleep(DELAY)

        await browser.close()

    logger.info("全部完成，共新增 %d 条", grand_total)
    conn.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="StockTwits 历史数据回填")
    parser.add_argument("--symbol", type=str, default=None,
                        help="只回填指定 ticker（如 NVDA）；省略则回填全部")
    parser.add_argument("--days", type=int, default=30,
                        help="回填天数（默认 30）")
    args = parser.parse_args()

    all_symbols = load_symbols()
    target = [args.symbol.upper()] if args.symbol else all_symbols
    asyncio.run(run(target, args.days))
