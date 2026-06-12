import asyncio
from stocktwits_fetcher import fetch_stocktwits


async def main():
    print("抓取 $AAPL 前10条...")
    posts = await fetch_stocktwits("AAPL", limit=10)

    if not posts:
        print("未拿到数据")
        return

    print(f"成功获取 {len(posts)} 条\n")
    for p in posts:
        sentiment = f"[{p['sentiment']}]" if p['sentiment'] else "[无情绪]"
        print(f"{sentiment} @{p['username']} ({p['created_at'][:10]})")
        print(f"  {p['body'][:100]}")
        print()


if __name__ == "__main__":
    asyncio.run(main())
