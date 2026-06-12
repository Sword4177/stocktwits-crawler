"""
generate.py — 从 stocktwits.db 生成静态 HTML 展示页面
v2: 加入 7/30天提及量趋势图 + 散户热度×行情联合信号检测
"""
import sqlite3
import json
from collections import defaultdict
from datetime import datetime, timezone, timedelta, date
from config import DB_FILE

CST = timezone(timedelta(hours=8))

CHART_COLORS = [
    '#3d9eff', '#00e676', '#ff4d4f', '#ffb300', '#c084fc',
    '#00bcd4', '#ff7043', '#4db6ac', '#f06292', '#aed581',
]


def load_data():
    conn = sqlite3.connect(DB_FILE)
    conn.row_factory = sqlite3.Row

    # ── 基础数据 ──────────────────────────────────────────────────────────────
    rows = conn.execute("""
        SELECT id, symbol, source, body, sentiment, likes, username, published_at
        FROM posts ORDER BY published_at DESC LIMIT 1000
    """).fetchall()

    stats = conn.execute("""
        SELECT COUNT(*) as total,
               COUNT(DISTINCT symbol) as symbols,
               SUM(CASE WHEN sentiment='Bullish' THEN 1 ELSE 0 END) as bullish,
               SUM(CASE WHEN sentiment='Bearish' THEN 1 ELSE 0 END) as bearish,
               MAX(published_at) as latest_at
        FROM posts
    """).fetchone()

    by_symbol = conn.execute("""
        SELECT p.symbol, COUNT(*) as cnt,
               SUM(CASE WHEN p.sentiment='Bullish' THEN 1 ELSE 0 END) as bullish,
               SUM(CASE WHEN p.sentiment='Bearish' THEN 1 ELSE 0 END) as bearish,
               COALESCE(s.sector, '') as sector
        FROM posts p LEFT JOIN symbols s ON p.symbol = s.symbol
        GROUP BY p.symbol ORDER BY cnt DESC LIMIT 20
    """).fetchall()

    sector_map = {}
    for r in conn.execute("SELECT symbol, sector FROM symbols WHERE sector != ''").fetchall():
        sector_map.setdefault(r["sector"], []).append(r["symbol"])

    # ── 提及量趋势（30天，Top 10）─────────────────────────────────────────────
    trend_rows = conn.execute("""
        WITH top_syms AS (
            SELECT symbol FROM posts
            WHERE published_at >= datetime('now', '-30 days')
            GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 10
        )
        SELECT symbol, date(published_at) as day, COUNT(*) as cnt
        FROM posts
        WHERE symbol IN (SELECT symbol FROM top_syms)
          AND published_at >= datetime('now', '-30 days')
        GROUP BY symbol, day
        ORDER BY day
    """).fetchall()

    trend_by_sym = defaultdict(dict)
    for r in trend_rows:
        trend_by_sym[r["symbol"]][r["day"]] = r["cnt"]

    # 每个 symbol 的30天日均（基准线）
    avg_rows = conn.execute("""
        WITH top_syms AS (
            SELECT symbol FROM posts
            WHERE published_at >= datetime('now', '-30 days')
            GROUP BY symbol ORDER BY COUNT(*) DESC LIMIT 10
        )
        SELECT symbol, ROUND(COUNT(*) * 1.0 / 30, 1) as daily_avg
        FROM posts
        WHERE symbol IN (SELECT symbol FROM top_syms)
          AND published_at >= datetime('now', '-30 days')
        GROUP BY symbol
    """).fetchall()
    avg_by_sym = {r["symbol"]: r["daily_avg"] for r in avg_rows}

    # 强制生成完整30天日期轴，无数据的天填0
    today = date.today()
    all_days = [(today - timedelta(days=29 - i)).isoformat() for i in range(30)]
    datasets = []
    # 共享基准线：100% = 30天日均
    datasets.append({
        "label": "~base",
        "data": [100] * len(all_days),
        "borderColor": "#7a8a98",
        "borderWidth": 1.5,
        "borderDash": [6, 3],
        "pointRadius": 0,
        "tension": 0,
        "fill": False,
    })
    for i, sym in enumerate(trend_by_sym.keys()):
        c = CHART_COLORS[i % len(CHART_COLORS)]
        avg = avg_by_sym.get(sym, 0)
        datasets.append({
            "label": sym,
            "data": [
                round(trend_by_sym[sym].get(d, 0) / avg * 100, 1) if avg > 0 else 0
                for d in all_days
            ],
            "borderColor": c,
            "backgroundColor": c + "11",
            "borderWidth": 1.5,
            "tension": 0.35,
            "pointRadius": 2,
            "fill": False,
        })
    trend_json = json.dumps({"labels": all_days, "datasets": datasets}, ensure_ascii=False)

    # ── 信号检测：热度暴涨 + 股价未动 ────────────────────────────────────────
    prices_ok = False
    signals_list = []
    try:
        signals_list = [dict(r) for r in conn.execute("""
            WITH recent AS (
                SELECT symbol, COUNT(*) as cnt
                FROM posts WHERE published_at >= datetime('now', '-1 day')
                GROUP BY symbol
            ),
            avg30 AS (
                SELECT symbol, COUNT(*) * 1.0 / 30 as daily_avg
                FROM posts
                WHERE published_at >= datetime('now', '-31 days')
                  AND published_at < datetime('now', '-1 day')
                GROUP BY symbol
            ),
            lp AS (
                SELECT p.symbol, p.close, p.pct_change
                FROM prices p
                INNER JOIN (
                    SELECT symbol, MAX(date) as mx FROM prices GROUP BY symbol
                ) m ON p.symbol = m.symbol AND p.date = m.mx
            )
            SELECT r.symbol,
                   r.cnt           AS recent_24h,
                   ROUND(a.daily_avg, 1)            AS daily_avg,
                   ROUND(r.cnt * 1.0 / a.daily_avg, 1) AS ratio,
                   ROUND(lp.close, 2)               AS close,
                   ROUND(lp.pct_change * 100, 2)    AS pct_chg
            FROM recent r
            JOIN avg30 a  ON r.symbol = a.symbol
            JOIN lp       ON r.symbol = lp.symbol
            WHERE r.cnt >= a.daily_avg * 1.5
              AND ABS(lp.pct_change) < 0.03
            ORDER BY ratio DESC
        """).fetchall()]
        prices_ok = True
    except Exception:
        prices_ok = False

    conn.close()
    return rows, stats, by_symbol, sector_map, trend_json, signals_list, prices_ok


def fmt_time(iso):
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.astimezone(CST).strftime("%m-%d %H:%M")
    except Exception:
        return iso[:16]


def generate():
    rows, stats, by_symbol, sector_map, trend_json, signals_list, prices_ok = load_data()

    posts_json = json.dumps([{
        "id":        r["id"],
        "symbol":    r["symbol"],
        "source":    r["source"],
        "body":      r["body"],
        "sentiment": r["sentiment"] or "",
        "likes":     r["likes"] or 0,
        "username":  r["username"],
        "time":      fmt_time(r["published_at"]),
    } for r in rows], ensure_ascii=False)

    total     = stats["total"]
    sym_count = stats["symbols"]
    bullish   = stats["bullish"] or 0
    bearish   = stats["bearish"] or 0
    neutral   = total - bullish - bearish
    latest_at = fmt_time(stats["latest_at"] or "")
    now_str   = datetime.now().strftime("%Y-%m-%d %H:%M")

    symbol_rows = "".join(
        f"<tr>"
        f"<td class='mono' style='color:var(--blue)'>${r['symbol']}</td>"
        f"<td class='mono' style='color:var(--text3)'>{r['sector']}</td>"
        f"<td class='mono'>{r['cnt']}</td>"
        f"<td class='mono' style='color:var(--green)'>{r['bullish']}</td>"
        f"<td class='mono' style='color:var(--red)'>{r['bearish']}</td>"
        f"</tr>"
        for r in by_symbol
    )

    all_symbols = sorted(r["symbol"] for r in by_symbol)
    sym_btns = "".join(
        f'<button class="pill" onclick="filter(\'sym:{s}\',this)">${s}</button>'
        for s in all_symbols
    )
    sector_btns = "".join(
        f'<button class="pill" onclick="filter(\'sec:{sec}\',this)">{sec}</button>'
        for sec in sorted(sector_map)
    )

    # 信号区内容
    if not prices_ok:
        signal_content = (
            '<div class="signal-notice">'
            '行情数据未就绪。请先运行：<code>python fetch_prices.py</code>，然后重新运行 <code>python generate.py</code>。'
            '</div>'
        )
    elif not signals_list:
        signal_content = '<div class="signal-notice">当前无信号（暂无热度暴涨且股价未动的标的）</div>'
    else:
        sig_rows_parts = []
        for s in signals_list:
            color = "var(--green)" if s['pct_chg'] >= 0 else "var(--red)"
            sign  = "+" if s['pct_chg'] >= 0 else ""
            sig_rows_parts.append(
                "<tr>"
                f"<td class='mono' style='color:var(--blue)'>${s['symbol']}</td>"
                f"<td class='mono' style='color:var(--warn)'>{s['recent_24h']}</td>"
                f"<td class='mono' style='color:var(--text2)'>{s['daily_avg']}</td>"
                f"<td class='mono' style='color:var(--green);font-weight:600'>{s['ratio']}×</td>"
                f"<td class='mono'>${s['close']}</td>"
                f"<td class='mono' style='color:{color}'>{sign}{s['pct_chg']}%</td>"
                "</tr>"
            )
        sig_rows = "".join(sig_rows_parts)
        signal_content = (
            "<table><thead><tr>"
            "<th>股票</th><th>近24h提及</th><th>30日日均</th>"
            "<th>热度倍数</th><th>最新收盘价</th><th>当日涨跌</th>"
            f"</tr></thead><tbody>{sig_rows}</tbody></table>"
        )

    html = f"""<!DOCTYPE html>
<html lang="zh">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>StockTwits 信号 — SentinelFlow</title>
<script src="https://cdn.jsdelivr.net/npm/chart.js@4/dist/chart.umd.min.js"></script>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500&family=IBM+Plex+Sans:wght@300;400;500&display=swap" rel="stylesheet">
<style>
:root{{
  --bg:#070809;--bg2:#0e1012;--bg3:#161a1d;
  --border:#1f2529;--border2:#2a3038;
  --text:#d4dbe3;--text2:#7a8a98;--text3:#3d4f5c;
  --green:#00e676;--red:#ff4d4f;--blue:#3d9eff;--warn:#ffb300;--purple:#c084fc;
  --mono:'IBM Plex Mono',monospace;--sans:'IBM Plex Sans',sans-serif;
}}
*{{box-sizing:border-box;margin:0;padding:0;}}
body{{background:var(--bg);color:var(--text);font-family:var(--sans);font-size:14px;line-height:1.6;}}
.mono{{font-family:var(--mono);}}
header{{border-bottom:1px solid var(--border);padding:0 2rem;display:flex;align-items:center;justify-content:space-between;height:50px;position:sticky;top:0;background:var(--bg);z-index:100;}}
.logo{{font-family:var(--mono);font-size:12px;color:var(--blue);letter-spacing:.08em;}}
.hm{{font-family:var(--mono);font-size:10px;color:var(--text3);}}
.hm em{{color:var(--warn);font-style:normal;}}
.wrap{{max-width:1080px;margin:0 auto;padding:2rem;}}
.hero{{padding-bottom:1.5rem;margin-bottom:1.5rem;border-bottom:1px solid var(--border);}}
.hero-label{{font-family:var(--mono);font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.12em;margin-bottom:10px;}}
.hero h1{{font-size:24px;font-weight:300;letter-spacing:-.4px;margin-bottom:8px;}}
.hero h1 strong{{font-weight:500;color:var(--blue);}}
.hero-desc{{font-size:13px;color:var(--text2);line-height:1.7;}}
.metrics{{display:grid;grid-template-columns:repeat(5,1fr);gap:1px;background:var(--border);border:1px solid var(--border);margin-bottom:1.5rem;}}
.metric{{background:var(--bg2);padding:14px 18px;}}
.metric-val{{font-family:var(--mono);font-size:20px;font-weight:500;}}
.metric-label{{font-size:11px;color:var(--text3);margin-top:4px;text-transform:uppercase;letter-spacing:.06em;}}
.section-hd{{font-family:var(--mono);font-size:10px;color:var(--text3);text-transform:uppercase;letter-spacing:.1em;padding-bottom:8px;border-bottom:1px solid var(--border);margin-bottom:12px;}}
table{{width:100%;border-collapse:collapse;margin-bottom:1.5rem;font-size:12px;}}
th{{font-family:var(--mono);font-size:10px;color:var(--text3);text-align:left;padding:8px 12px;border-bottom:1px solid var(--border2);text-transform:uppercase;letter-spacing:.06em;}}
td{{padding:9px 12px;border-bottom:1px solid var(--border);color:var(--text2);}}
tr:hover td{{background:var(--bg2);}}
.filter-group{{margin-bottom:8px;display:flex;gap:6px;flex-wrap:wrap;align-items:center;}}
.filter-label{{font-family:var(--mono);font-size:10px;color:var(--text3);min-width:36px;}}
.pill{{font-family:var(--mono);font-size:11px;padding:4px 12px;border:1px solid var(--border2);background:transparent;color:var(--text2);cursor:pointer;transition:all .15s;}}
.pill:hover{{border-color:var(--text2);color:var(--text);}}
.pill.active{{border-color:var(--blue);color:var(--blue);background:rgba(61,158,255,.06);}}
.pill-bull{{border-color:#00e67644;color:var(--green);}}
.pill-bull.active{{background:rgba(0,230,118,.06);}}
.pill-bear{{border-color:#ff4d4f44;color:var(--red);}}
.pill-bear.active{{background:rgba(255,77,79,.06);}}
.pill-neutral{{border-color:#3d4f5c88;color:var(--text3);}}
.pill-neutral.active{{border-color:var(--text2);color:var(--text2);background:rgba(122,138,152,.06);}}
.feed{{display:flex;flex-direction:column;gap:6px;}}
.msg{{border:1px solid var(--border);background:var(--bg2);padding:12px 14px;}}
.msg.bull{{border-left:3px solid var(--green);}}
.msg.bear{{border-left:3px solid var(--red);}}
.msg.neutral{{border-left:3px solid var(--border2);}}
.msg-top{{display:flex;align-items:center;gap:8px;margin-bottom:6px;flex-wrap:wrap;}}
.msg-symbol{{font-family:var(--mono);font-size:11px;padding:2px 8px;background:var(--bg3);border:1px solid var(--border2);color:var(--blue);}}
.badge{{font-family:var(--mono);font-size:10px;padding:1px 6px;border:1px solid;}}
.msg-user{{font-family:var(--mono);font-size:10px;color:var(--text3);}}
.msg-time{{font-family:var(--mono);font-size:10px;color:var(--text3);margin-left:auto;}}
.msg-body{{font-size:13px;color:var(--text);line-height:1.6;margin-bottom:6px;white-space:pre-wrap;word-break:break-word;}}
.msg-meta{{display:flex;gap:12px;font-family:var(--mono);font-size:10px;color:var(--text3);}}
.source-tag{{font-size:10px;font-family:var(--mono);color:var(--text3);}}
footer{{border-top:1px solid var(--border);padding:1.5rem 2rem;margin-top:3rem;display:flex;justify-content:space-between;}}
.ft{{font-family:var(--mono);font-size:11px;color:var(--text3);}}
.chart-wrap{{background:var(--bg2);border:1px solid var(--border);padding:16px 18px;margin-bottom:1.5rem;}}
.chart-toolbar{{display:flex;gap:6px;margin-bottom:14px;}}
.chart-canvas{{width:100%!important;height:220px!important;}}
.signal-notice{{font-family:var(--mono);font-size:12px;color:var(--text3);padding:14px 16px;border:1px dashed var(--border2);margin-bottom:1.5rem;}}
.signal-notice code{{color:var(--warn);}}
.signal-tag{{display:inline-block;font-family:var(--mono);font-size:10px;padding:1px 6px;background:rgba(255,179,0,.1);border:1px solid #ffb30066;color:var(--warn);margin-right:8px;vertical-align:middle;}}
</style>
</head>
<body>
<header>
  <div class="logo">SENTINELFLOW // StockTwits 信号</div>
  <div class="hm">生成时间：<em>{now_str}</em></div>
</header>
<div class="wrap">
  <div class="hero">
    <div class="hero-label">社交情绪数据 — StockTwits</div>
    <h1>StockTwits <strong>散户情绪监控</strong></h1>
    <div class="hero-desc">追踪 {sym_count} 个股票，共 {total} 条讨论，最新数据：{latest_at}。含 Bullish / Bearish 情绪标注。</div>
  </div>

  <div class="metrics">
    <div class="metric"><div class="metric-val" style="color:var(--blue)">{total}</div><div class="metric-label">总条数</div></div>
    <div class="metric"><div class="metric-val" style="color:var(--blue)">{sym_count}</div><div class="metric-label">股票数</div></div>
    <div class="metric"><div class="metric-val" style="color:var(--green)">{bullish}</div><div class="metric-label">看涨 Bullish</div></div>
    <div class="metric"><div class="metric-val" style="color:var(--red)">{bearish}</div><div class="metric-label">看跌 Bearish</div></div>
    <div class="metric"><div class="metric-val" style="color:var(--text2)">{neutral}</div><div class="metric-label">无标注</div></div>
  </div>

  <div class="section-hd">提及量趋势（Top 10 股票）</div>
  <div class="chart-wrap">
    <div class="chart-toolbar">
      <button class="pill active" onclick="setRange(7,this)">7 天</button>
      <button class="pill" onclick="setRange(30,this)">30 天</button>
    </div>
    <canvas id="trendChart" class="chart-canvas"></canvas>
  </div>

  <div class="section-hd">
    <span class="signal-tag">SIGNAL</span>散户热度暴涨 × 股价未动（近24h ≥ 30日均值×1.5，且涨跌 &lt; ±3%）
  </div>
  {signal_content}

  <div class="section-hd">各股票数据分布（Top 20）</div>
  <table>
    <thead><tr><th>股票</th><th>板块</th><th>消息数</th><th>看涨</th><th>看跌</th></tr></thead>
    <tbody>{symbol_rows}</tbody>
  </table>

  <div class="section-hd" style="margin-bottom:12px">消息筛选（共 {total} 条，展示最新 200 条）</div>
  <div class="filter-group">
    <span class="filter-label">情绪</span>
    <button class="pill active" onclick="filter('all',this)">全部</button>
    <button class="pill pill-bull" onclick="filter('sent:Bullish',this)">▲ Bullish 看涨</button>
    <button class="pill pill-bear" onclick="filter('sent:Bearish',this)">▼ Bearish 看跌</button>
    <button class="pill pill-neutral" onclick="filter('sent:neutral',this)">— 中性</button>
  </div>
  <div class="filter-group">
    <span class="filter-label">板块</span>
    {sector_btns}
  </div>
  <div class="filter-group">
    <span class="filter-label">股票</span>
    {sym_btns}
  </div>
  <div class="feed" id="feed"></div>
</div>
<footer>
  <div class="ft">SentinelFlow · StockTwits 信号</div>
  <div class="ft">stocktwits.db · {total} 条 · {now_str}</div>
</footer>
<script>
const POSTS = {posts_json};
const SECTOR_SYMBOLS = {json.dumps(sector_map, ensure_ascii=False)};
const TREND = {trend_json};

// ── 趋势图 ───────────────────────────────────────────────────────────────────
let chart;
function initChart(days) {{
  const n = days === 7 ? Math.max(0, TREND.labels.length - 7) : 0;
  const labels = TREND.labels.slice(n);
  const datasets = TREND.datasets.map(ds => ({{
    ...ds, data: ds.data.slice(n),
  }}));
  const ctx = document.getElementById('trendChart').getContext('2d');
  if (chart) chart.destroy();
  chart = new Chart(ctx, {{
    type: 'line',
    data: {{ labels, datasets }},
    options: {{
      responsive: true,
      maintainAspectRatio: false,
      interaction: {{ mode: 'index', intersect: false }},
      plugins: {{
        legend: {{
          labels: {{
            color: '#7a8a98',
            font: {{ size: 11, family: 'IBM Plex Mono' }},
            filter: (item) => !item.text.startsWith('~'),
          }},
        }},
        tooltip: {{
          backgroundColor: '#0e1012', borderColor: '#1f2529', borderWidth: 1,
          titleColor: '#d4dbe3', bodyColor: '#7a8a98',
          titleFont: {{ family: 'IBM Plex Mono', size: 11 }},
          bodyFont:  {{ family: 'IBM Plex Mono', size: 11 }},
        }},
      }},
      scales: {{
        x: {{ ticks: {{ color: '#3d4f5c', font: {{ size: 10, family: 'IBM Plex Mono' }} }},
              grid:  {{ color: '#1f2529' }} }},
        y: {{ ticks: {{ color: '#3d4f5c', font: {{ size: 10, family: 'IBM Plex Mono' }},
                        callback: (v) => v + '%' }},
              grid:  {{ color: '#1f2529' }}, beginAtZero: true,
              title: {{ display: true, text: '% 30天均值', color: '#3d4f5c',
                        font: {{ size: 10, family: 'IBM Plex Mono' }} }} }},
      }},
    }},
  }});
}}

function setRange(days, btn) {{
  document.querySelectorAll('.chart-toolbar .pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  initChart(days);
}}

initChart(7);

// ── 消息 feed ────────────────────────────────────────────────────────────────
function sentBadge(s) {{
  if (s === 'Bullish') return '<span class="badge" style="border-color:#00e67644;background:#00e67611;color:#00e676">▲ Bullish</span>';
  if (s === 'Bearish') return '<span class="badge" style="border-color:#ff4d4f44;background:#ff4d4f11;color:#ff4d4f">▼ Bearish</span>';
  return '';
}}

function renderFeed(posts) {{
  const feed = document.getElementById('feed');
  feed.innerHTML = '';
  posts.slice(0, 200).forEach(p => {{
    const cls = p.sentiment === 'Bullish' ? 'bull' : p.sentiment === 'Bearish' ? 'bear' : 'neutral';
    const src = p.source === 'trending' ? '<span class="source-tag">trending</span>' : '';
    const body = p.body.length > 280 ? p.body.slice(0, 280) + '…' : p.body;
    const d = document.createElement('div');
    d.className = 'msg ' + cls;
    d.innerHTML =
      `<div class="msg-top">` +
        `<span class="msg-symbol">${{p.symbol}}</span>` +
        sentBadge(p.sentiment) + src +
        `<span class="msg-user">@${{p.username}}</span>` +
        `<span class="msg-time">${{p.time}}</span>` +
      `</div>` +
      `<div class="msg-body">${{body}}</div>` +
      `<div class="msg-meta"><span>♥ ${{p.likes}}</span></div>`;
    feed.appendChild(d);
  }});
}}

function filter(type, btn) {{
  document.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  btn.classList.add('active');
  let f;
  if (type === 'all') f = POSTS;
  else if (type === 'sent:neutral') f = POSTS.filter(p => !p.sentiment);
  else if (type.startsWith('sent:')) f = POSTS.filter(p => p.sentiment === type.slice(5));
  else if (type.startsWith('sym:'))  f = POSTS.filter(p => p.symbol === type.slice(4));
  else if (type.startsWith('sec:')) {{
    const syms = SECTOR_SYMBOLS[type.slice(4)] || [];
    f = POSTS.filter(p => syms.includes(p.symbol));
  }} else f = POSTS;
  renderFeed(f);
}}

renderFeed(POSTS);
</script>
</body>
</html>"""

    with open("index.html", "w", encoding="utf-8") as f:
        f.write(html)

    sig_count = len(signals_list)
    print(f"✓ 生成完成：index.html（{total} 条数据，{sig_count} 个信号）")


if __name__ == "__main__":
    generate()
