#!/usr/bin/env python3
"""
BLUE WAVE BEACON — daily aggregator
Fetches RSS feeds + Bluesky trending, generates index.html
Run: python scripts/aggregate.py
"""

import feedparser
import requests
import json
import html
import random
import re
import sys
import calendar
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import quote

# ── CONFIG ─────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).parent.parent

SITE_NAME = "BLUE WAVE BEACON"
SITE_TAGLINE = "Progressive News · Updated Daily"
DONATE_URL = "donations.html"
ABOUT_URL = "about.html"

# Left-leaning RSS sources  {name, url, category}
SOURCES = [
    # Top news
    # Guardian: use the /us-news section feed (hard US news) NOT /us/rss, which is the
    # soft front page full of culture/sport/lifestyle features.
    {"name": "The Guardian US", "url": "https://www.theguardian.com/us-news/rss",      "cat": "top"},
    {"name": "HuffPost",        "url": "https://www.huffpost.com/section/front-page/feed", "cat": "top"},
    {"name": "Vox",             "url": "https://www.vox.com/rss/index.xml",            "cat": "top"},
    {"name": "NBC News",        "url": "https://feeds.nbcnews.com/nbcnews/public/news","cat": "top"},
    # CNN has deprecated all its RSS feeds (they serve frozen 2023 content); kept here in
    # case it ever revives — the MAX_AGE_DAYS freshness guard drops its stale entries.
    {"name": "CNN",             "url": "http://rss.cnn.com/rss/cnn_topstories.rss",    "cat": "top"},
    {"name": "ABC News",        "url": "https://feeds.abcnews.com/abcnews/topstories", "cat": "top"},
    {"name": "CBS News",        "url": "https://www.cbsnews.com/latest/rss/main",      "cat": "top"},
    # Politics
    {"name": "Talking Points Memo","url": "https://feeds.feedburner.com/talkingpointsmemo/main","cat": "politics"},
    {"name": "Daily Kos",       "url": "https://www.dailykos.com/stories/feed.rss",    "cat": "politics"},
    {"name": "Raw Story",       "url": "https://www.rawstory.com/feed/",               "cat": "politics"},
    {"name": "Politicus USA",   "url": "https://www.politicususa.com/feed",            "cat": "politics"},
    # Investigative
    {"name": "ProPublica",      "url": "https://www.propublica.org/feeds/propublica/main","cat": "investigation"},
    {"name": "The Intercept",   "url": "https://theintercept.com/feed/?lang=en",       "cat": "investigation"},
    {"name": "Mother Jones",    "url": "https://www.motherjones.com/feed/",            "cat": "investigation"},
    # Opinion / Analysis
    {"name": "The Nation",      "url": "https://www.thenation.com/feed/?post_type=article","cat": "opinion"},
    {"name": "Slate",           "url": "https://slate.com/feeds/all.rss",              "cat": "opinion"},
    {"name": "Salon",           "url": "https://www.salon.com/feed/",                  "cat": "opinion"},
    # Progressive
    {"name": "Common Dreams",   "url": "https://www.commondreams.org/feeds/latest",    "cat": "progressive"},
    {"name": "Truthout",        "url": "https://truthout.org/feed/",                   "cat": "progressive"},
    {"name": "Democracy Now",   "url": "https://www.democracynow.org/democracynow.rss","cat": "progressive"},
    # Science / Climate
    {"name": "Inside Climate News","url": "https://insideclimatenews.org/feed/",       "cat": "climate"},
    {"name": "Grist",           "url": "https://grist.org/feed/",                      "cat": "climate"},
    # Substack — liberal/progressive contributors
    {"name": "Heather Cox Richardson", "url": "https://heathercoxrichardson.substack.com/feed", "cat": "substack"},
    {"name": "Robert Reich",    "url": "https://robertreich.substack.com/feed",         "cat": "substack"},
    {"name": "The Contrarian",  "url": "https://www.thecontrarian.org/feed",            "cat": "substack"},
]

MAX_PER_SOURCE = 5   # articles per source
MAX_PER_COLUMN = 18  # links per column
MAX_AGE_DAYS = 14    # drop entries older than this (guards against zombie feeds like CNN's)
BLUESKY_POST_COUNT = 6
BLUESKY_TRENDING_COUNT = 12

COLUMN_TITLES = {
    "left":   "POLITICS & DEMOCRACY",
    "center": "TOP STORIES",
    "right":  "INVESTIGATION & ANALYSIS",
}

# ── HELPERS ────────────────────────────────────────────────────────────────────

def pick_quote() -> dict:
    try:
        quotes = json.loads((ROOT / "quotes.json").read_text(encoding="utf-8"))
        return random.choice(quotes)
    except Exception:
        return {"text": "The arc of the moral universe is long, but it bends toward justice.", "author": "Martin Luther King Jr."}

def render_substack_section(items: list[dict]) -> str:
    sub_items = [i for i in items if i["cat"] == "substack"]
    if not sub_items:
        return ""
    links = "\n".join(render_link(i) for i in sub_items[:9])
    return f"""<section id="substack-section">
  <div class="section-header" style="background:linear-gradient(135deg,#ff6719,#ff9a3d);color:white;font-family:'Oswald',sans-serif;font-size:14px;font-weight:600;letter-spacing:2px;text-transform:uppercase;padding:9px 16px;border-radius:4px 4px 0 0;">
    📰 From Our Substack Contributors
  </div>
  <div class="column" style="border-radius:0 0 4px 4px;">
    {links}
  </div>
</section>"""

def clean(text: str) -> str:
    text = re.sub(r"<[^>]+>", "", text or "")
    return html.unescape(text).strip()

def _entry_too_old(entry) -> bool:
    """True if the entry has a parseable date older than MAX_AGE_DAYS. Entries with no
    usable date are kept (we can't judge them). feedparser dates are UTC struct_times."""
    tm = entry.get("published_parsed") or entry.get("updated_parsed")
    if not tm:
        return False
    try:
        published = datetime.fromtimestamp(calendar.timegm(tm), tz=timezone.utc)
        return datetime.now(timezone.utc) - published > timedelta(days=MAX_AGE_DAYS)
    except Exception:
        return False

BROWSER_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
              "(KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36")
FEED_HEADERS = {
    "User-Agent": BROWSER_UA,
    "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml, */*",
    "Accept-Language": "en-US,en;q=0.9",
}

def _parse_feed(url: str):
    """Fetch via requests with browser-like headers (handles redirects + gzip and avoids
    the bot blocks that make Substack/HuffPost/etc. return empty for feedparser's bare
    fetcher), then hand the bytes to feedparser. Falls back to feedparser's own fetcher."""
    # 1) Direct fetch with browser-like headers.
    try:
        r = requests.get(url, headers=FEED_HEADERS, timeout=15)
        if r.status_code == 200 and r.content:
            return feedparser.parse(r.content)
        print(f"  [WARN] {url}: HTTP {r.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"  [WARN] requests failed for {url}: {e}", file=sys.stderr)
    # 2) Retry through a public proxy. Some feeds (Substack) return 403 to datacenter IPs
    #    such as GitHub Actions runners; the proxy fetches from a non-blocked IP. This is
    #    what keeps the Substack section from vanishing on the scheduled CI runs.
    try:
        proxied = "https://api.allorigins.win/raw?url=" + quote(url, safe="")
        r = requests.get(proxied, headers={"User-Agent": BROWSER_UA}, timeout=25)
        if r.status_code == 200 and r.content:
            f = feedparser.parse(r.content)
            if f.entries:
                return f
        print(f"  [WARN] proxy {url}: HTTP {r.status_code}", file=sys.stderr)
    except Exception as e:
        print(f"  [WARN] proxy failed for {url}: {e}", file=sys.stderr)
    # 3) Last resort: feedparser's own fetcher, guarded so a dropped connection can't
    #    crash the whole run.
    try:
        return feedparser.parse(url, request_headers={"User-Agent": BROWSER_UA})
    except Exception as e:
        print(f"  [WARN] feedparser failed for {url}: {e}", file=sys.stderr)
        return None

def fetch_feed(source: dict) -> list[dict]:
    # Retry once: several feeds (Substack especially) intermittently return empty/closed
    # connections, which is what made the Substack section vanish on some runs.
    feed = None
    for attempt in (1, 2):
        feed = _parse_feed(source["url"])
        if feed and feed.entries:
            break
    if not feed:
        return []
    # Judge the whole feed by its newest dated entry. A zombie/frozen feed (e.g. CNN's,
    # stuck in 2023) often has many DATELESS entries that would otherwise slip past the
    # per-entry check — so if the newest date we can find is itself stale, drop the entire
    # feed. Feeds with no dates anywhere can't be judged and are kept.
    dated = [calendar.timegm(e.get("published_parsed") or e.get("updated_parsed"))
             for e in feed.entries
             if e.get("published_parsed") or e.get("updated_parsed")]
    if dated:
        newest = datetime.fromtimestamp(max(dated), tz=timezone.utc)
        if datetime.now(timezone.utc) - newest > timedelta(days=MAX_AGE_DAYS):
            print(f"  [WARN] {source['name']}: feed stale (newest {newest.date()}); skipping", file=sys.stderr)
            return []
    items = []
    for entry in feed.entries:
        if len(items) >= MAX_PER_SOURCE:
            break
        if _entry_too_old(entry):
            continue  # skip stale entries within an otherwise-fresh feed
        title = clean(entry.get("title", ""))
        link  = entry.get("link", "#")
        if title and link:
            items.append({"title": title, "link": link, "source": source["name"], "cat": source["cat"]})
    return items

def fetch_all_feeds() -> list[dict]:
    all_items = []
    for source in SOURCES:
        items = fetch_feed(source)
        print(f"  {source['name']}: {len(items)} items")
        all_items.extend(items)
    return all_items

# ── BLUESKY ────────────────────────────────────────────────────────────────────

BSKY_API = "https://public.api.bsky.app/xrpc"

# Curated progressive voices on Bluesky. We pull their recent posts via the public
# getAuthorFeed endpoint (the old searchPosts endpoint now returns 403 without auth).
BSKY_ACCOUNTS = [
    "rbreich.bsky.social",        # Robert Reich
    "aoc.bsky.social",            # Alexandria Ocasio-Cortez
    "gtconway.bsky.social",       # George Conway
    "mehdirhasan.bsky.social",    # Mehdi Hasan
    "danrather.bsky.social",      # Dan Rather
    "wajahatali.bsky.social",     # Wajahat Ali
    "rgay.bsky.social",           # Roxane Gay
    "marcelias.bsky.social",      # Marc Elias (voting rights)
    "protectdemocracy.bsky.social",
    "crooksandliars.bsky.social",
    "emptywheel.bsky.social",     # Marcy Wheeler
    "propublica.org",             # ProPublica
]

def fetch_bluesky_trending() -> tuple[list[dict], list[str]]:
    """Returns (posts, trending_tags). Posts come from curated progressive accounts,
    ranked by engagement; the old public search endpoint is no longer available."""
    tags = []
    candidates = []

    # Trending topics (still public)
    try:
        r = requests.get(f"{BSKY_API}/app.bsky.unspecced.getTrendingTopics",
                         params={"limit": BLUESKY_TRENDING_COUNT}, timeout=10)
        if r.ok:
            topics = r.json().get("topics", [])
            tags = [t.get("topic", "") for t in topics if t.get("topic")]
    except Exception as e:
        print(f"  [WARN] Bluesky trending: {e}", file=sys.stderr)

    # Pull recent posts from each curated account, keep substantive original posts
    for actor in BSKY_ACCOUNTS:
        try:
            r = requests.get(f"{BSKY_API}/app.bsky.feed.getAuthorFeed",
                             params={"actor": actor, "limit": 8, "filter": "posts_no_replies"},
                             timeout=10)
            if not r.ok:
                continue
            for entry in r.json().get("feed", []):
                # Skip reposts — we want the account's own words
                if entry.get("reason"):
                    continue
                post   = entry.get("post", {})
                author = post.get("author", {})
                record = post.get("record", {})
                text   = clean(record.get("text", ""))
                # Skip very short posts and pure link/image drops
                if len(text) < 60:
                    continue
                handle  = author.get("handle", "")
                display = author.get("displayName", handle)
                uri     = post.get("uri", "")
                likes   = post.get("likeCount", 0)
                reposts = post.get("repostCount", 0)
                if uri.startswith("at://"):
                    parts = uri.replace("at://", "").split("/")
                    bsky_url = f"https://bsky.app/profile/{parts[0]}/post/{parts[-1]}" if len(parts) >= 3 else "#"
                else:
                    bsky_url = "#"
                candidates.append({
                    "display": display,
                    "handle": f"@{handle}",
                    "text": text[:300],
                    "url": bsky_url,
                    "likes": likes,
                    "reposts": reposts,
                })
        except Exception as e:
            print(f"  [WARN] Bluesky {actor}: {e}", file=sys.stderr)

    # Rank by engagement, but cap one post per author so it's not all one person
    candidates.sort(key=lambda p: p["likes"], reverse=True)
    posts = []
    seen_authors = set()
    for p in candidates:
        if p["handle"] in seen_authors:
            continue
        seen_authors.add(p["handle"])
        posts.append(p)
        if len(posts) >= BLUESKY_POST_COUNT:
            break

    return posts, tags[:BLUESKY_TRENDING_COUNT]

# ── HTML RENDERING ─────────────────────────────────────────────────────────────

def render_link(item: dict, cls: str = "") -> str:
    title = html.escape(item["title"])
    link  = html.escape(item["link"])
    src   = html.escape(item["source"])
    cls_str = f' class="news-link {cls}"' if cls else ' class="news-link"'
    return (f'<a href="{link}" target="_blank" rel="noopener noreferrer"{cls_str}>'
            f'{title}<span class="source">{src}</span></a>\n')

def render_bsky_post(post: dict) -> str:
    text = html.escape(post["text"])
    url  = html.escape(post["url"])
    display = html.escape(post["display"])
    handle  = html.escape(post["handle"])
    likes   = post["likes"]
    reposts = post["reposts"]
    return f"""<div class="bsky-post">
  <div class="bsky-author">{display} <span class="bsky-handle">{handle}</span></div>
  <div class="bsky-text">{text}</div>
  <div class="bsky-meta">
    <span>❤️ {likes:,}</span>
    <span>🔁 {reposts:,}</span>
    <a class="bsky-link" href="{url}" target="_blank" rel="noopener noreferrer">View on Bluesky →</a>
  </div>
</div>"""

def render_trend_tags(tags: list[str]) -> str:
    parts = ['<div id="bluesky-trending"><span class="trend-label">Trending:</span>']
    for tag in tags:
        enc = quote(tag)
        parts.append(f'<a class="trend-tag" href="https://bsky.app/search?q={enc}" target="_blank" rel="noopener noreferrer">{html.escape(tag)}</a>')
    parts.append("</div>")
    return "\n".join(parts)

# URL path segments that signal "soft"/lifestyle content we don't want as hard news.
SOFT_URL_SEGMENTS = (
    "/lifestyle", "/wellness", "/well/", "/food", "/recipes", "/music", "/culture",
    "/books", "/games", "/game", "/sport", "/football", "/soccer", "/fashion",
    "/travel", "/art-and-design", "/artanddesign", "/tv-and-radio", "/television",
    "/film", "/movies", "/stage", "/relationships", "/beauty", "/style", "/celebrity",
    "/entertainment", "/puzzles", "/crosswords", "/horoscope", "/global/", "/pets",
    "/lifeandstyle", "/audio", "/podcast", "/gallery", "/comics",
)

# Title markers for obvious sport/entertainment/lifestyle pieces that ride on hard-news
# feeds with flat URLs (e.g. Vox's /future-perfect/...) the URL filter can't catch.
# Kept tight to avoid false positives on real news.
SOFT_TITLE_PATTERNS = (
    "world cup", "super bowl", "premier league", "nba finals", "stanley cup",
    "box office", "red carpet", "movie review", "film review", "toy story",
    "best shows", "what to watch", "recipe", "horoscope", "taylor swift tour",
)

def is_soft(item: dict) -> bool:
    url = (item.get("link") or "").lower()
    if any(seg in url for seg in SOFT_URL_SEGMENTS):
        return True
    title = (item.get("title") or "").lower()
    return any(p in title for p in SOFT_TITLE_PATTERNS)

def build_columns(items: list[dict]) -> tuple[str, str, str, str]:
    """Returns (top_story_html, left_col_html, center_col_html, right_col_html)"""
    # Sort by category into buckets
    top_items   = [i for i in items if i["cat"] == "top"]
    pol_items   = [i for i in items if i["cat"] == "politics"]
    inv_items   = [i for i in items if i["cat"] in ("investigation", "opinion")]
    prog_items  = [i for i in items if i["cat"] in ("progressive", "climate")]
    other_items = [i for i in items if i["cat"] not in ("top","politics","investigation","opinion","progressive","climate","substack")]

    # Drop soft/lifestyle/sport/entertainment items from the top bucket entirely — this
    # section is hard news only. (Other categories keep their items.)
    hard_top = [i for i in top_items if not is_soft(i)]
    top_items = hard_top

    # Top story — prefer genuine breaking/hard news. Priority order:
    #   1. Hard headlines from the wire/cable networks (CNN, MSNBC, ABC, CBS)
    #   2. Political outlets (TPM, Daily Kos, Raw Story, PoliticusUSA)
    #   3. Any remaining hard top item (e.g. Guardian hard news)
    #   4. Absolute fallback: anything
    NETWORKS = {"NBC News", "CNN", "ABC News", "CBS News"}
    network_hard = [i for i in hard_top if i["source"] in NETWORKS]
    top_html = ""
    hero_pool = network_hard + pol_items + hard_top + top_items
    if hero_pool:
        hero = hero_pool[0]
        hero_link = html.escape(hero['link'])
        hero_title_enc = quote(hero['title'])
        top_html = f"""<div id="top-story">
  <div class="top-label">&#9733; Top Story</div>
  <h1><a href="{hero_link}" target="_blank" rel="noopener noreferrer">{html.escape(hero['title'])}</a></h1>
  <div class="source-badge">{html.escape(hero['source'])}</div>
  <div class="share-buttons" style="justify-content:center">
    <a href="https://bsky.app/intent/compose?text={hero_title_enc}%20{hero_link}" target="_blank" rel="noopener noreferrer" title="Share on Bluesky">🦋</a>
    <a href="https://twitter.com/intent/tweet?text={hero_title_enc}&url={hero_link}" target="_blank" rel="noopener noreferrer" title="Share on X">𝕏</a>
    <a href="https://www.threads.net/intent/post?text={hero_title_enc}%20{hero_link}" target="_blank" rel="noopener noreferrer" title="Share on Threads">@</a>
  </div>
</div>"""
        # Remove the chosen hero from whichever pool it came from (match by link)
        hero_link_raw = hero['link']
        top_items = [i for i in top_items if i['link'] != hero_link_raw]
        pol_items = [i for i in pol_items if i['link'] != hero_link_raw]

    # Center column gets top stories
    center_pool = top_items + prog_items + other_items
    # Left column: politics
    left_pool = pol_items
    # Right column: investigation/opinion
    right_pool = inv_items

    def render_col(pool, title, extra_pool=None):
        lines = [f'<div class="column"><div class="column-title">{title}</div>\n']
        count = 0
        for i, item in enumerate(pool):
            if count >= MAX_PER_COLUMN:
                break
            cls = "headline-big" if i == 0 else ("headline-medium" if i < 3 else "")
            lines.append(render_link(item, cls))
            count += 1
        # Fill remainder from extra pool
        if extra_pool:
            for item in extra_pool:
                if count >= MAX_PER_COLUMN:
                    break
                lines.append(render_link(item))
                count += 1
        lines.append("</div>")
        return "".join(lines)

    # NOTE: "Top Stories" rendered first (left/top position) per user request —
    # it appears above "Politics & Democracy" in both desktop columns and mobile stack.
    left_col   = render_col(center_pool, COLUMN_TITLES["center"], other_items)
    center_col = render_col(left_pool,   COLUMN_TITLES["left"],   prog_items)
    right_col  = render_col(right_pool,  COLUMN_TITLES["right"],  other_items)

    return top_html, left_col, center_col, right_col

# ── PAGE TEMPLATE ──────────────────────────────────────────────────────────────

PAGE_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1.0" />
  <meta name="description" content="BLUE WAVE BEACON — progressive news aggregator updated daily." />
  <title>BLUE WAVE BEACON</title>
  <link rel="stylesheet" href="style.css" />
  <link rel="alternate" type="application/rss+xml" title="BLUE WAVE BEACON RSS" href="feed.xml" />
  <link rel="icon" type="image/png" href="assets/logo.png" />
  <link rel="manifest" href="manifest.json" />
  <meta name="theme-color" content="#0d2247" />
  <meta property="og:type" content="website" />
  <meta property="og:title" content="BLUE WAVE BEACON — Progressive News, Updated Daily" />
  <meta property="og:description" content="A Drudge-style aggregator for progressive and independent news, updated daily." />
  <meta property="og:url" content="https://bluewavebeacon.com/" />
  <meta property="og:image" content="https://bluewavebeacon.com/assets/logo.png" />
  <meta name="twitter:card" content="summary" />
  <meta name="twitter:title" content="BLUE WAVE BEACON — Progressive News, Updated Daily" />
  <meta name="twitter:description" content="A Drudge-style aggregator for progressive and independent news, updated daily." />
  <meta name="twitter:image" content="https://bluewavebeacon.com/assets/logo.png" />
</head>
<body>

<header id="site-header">
  <a href="index.html" id="site-title-link">
    <img src="assets/logo.png" alt="Blue Wave Beacon logo" id="site-logo" />
    <span id="site-title"><span>BLUE WAVE</span> BEACON</span>
  </a>
  <div id="site-tagline">Progressive News · Updated Daily</div>
  <nav id="header-nav">
    <a href="index.html">Home</a>
    <a href="donations.html">💙 Donate</a>
    <a href="about.html">About</a>
    <a href="feed.xml">RSS Feed</a>
    <a href="archive.html">📅 Archive</a>
    <a href="merch.html">🛍️ Merch</a>
    <a href="https://bsky.app" target="_blank" rel="noopener noreferrer">🦋 Bluesky</a>
  </nav>
</header>

<div id="follow-bar">
  <span>Follow Us</span>
  <a href="https://bsky.app/profile/bluewavebeacon.com" target="_blank" rel="noopener noreferrer">🦋 Bluesky</a>
  <a href="https://instagram.com/BlueWaveBeacon" target="_blank" rel="noopener noreferrer">📸 Instagram</a>
  <a href="https://x.com/BlueWaveBeacon" target="_blank" rel="noopener noreferrer">𝕏 X</a>
</div>

<div id="breaking-banner" style="display:none">
  <span class="label">BREAKING</span>
  <span id="breaking-text"></span>
</div>

<div id="timestamp-bar">
  Last updated: {timestamp} ET &nbsp;|&nbsp; 🌊 BLUE WAVE BEACON &nbsp;|&nbsp; Progressive news, curated daily
</div>

<main id="main-wrapper">

  <!-- AD SLOT (replace with Google AdSense tag) -->
  <div class="ad-slot">Advertisement — <a href="donations.html">Support us instead</a></div>

  <!-- CATEGORY NAV -->
  <nav id="category-nav">
    <a href="index.html" class="active">All Stories</a>
    <a href="politics.html">Politics &amp; Democracy</a>
    <a href="climate.html">Climate &amp; Environment</a>
    <a href="economy.html">Economy &amp; Labor</a>
  </nav>

  <!-- SEARCH BAR -->
  <div id="search-bar">
    <input type="text" id="headline-search" placeholder="🔍 Search headlines..." />
  </div>

  <!-- QUOTE OF THE DAY -->
  <div id="quote-box">
    <div class="quote-label">Quote of the Day</div>
    <div class="quote-text">"{quote_text}"</div>
    <div class="quote-author">— {quote_author}</div>
  </div>

  {top_story}

  <div id="columns">
    {left_col}
    {center_col}
    {right_col}
  </div>

  {substack_section}

  <!-- BLUESKY SECTION -->
  <section id="bluesky-section">
    <div class="section-header">
      <span class="bsky-icon">🦋</span>
      TRENDING ON BLUESKY — PROGRESSIVE VOICES
    </div>
    {trend_tags}
    <div id="bluesky-grid">
      {bsky_posts}
    </div>
  </section>

  <!-- SOURCES -->
  <div id="sources-bar">
    <h3>Our Sources</h3>
    <div class="sources-list">
      {source_pills}
    </div>
  </div>

  <!-- NEWSLETTER -->
  <div id="newsletter">
    <h3>🌊 Daily Briefing Newsletter</h3>
    <p>Get the top progressive stories delivered to your inbox every morning.</p>
    <form action="https://formspree.io/f/YOUR_FORM_ID" method="POST">
      <input type="email" name="email" placeholder="your@email.com" required />
      <button type="submit">Subscribe</button>
    </form>
  </div>

  <!-- AD SLOT BOTTOM -->
  <div class="ad-slot">Advertisement</div>

</main>

<footer>
  <div class="footer-links">
    <a href="index.html">Home</a>
    <a href="donations.html">Donate</a>
    <a href="about.html">About</a>
    <a href="feed.xml">RSS</a>
    <a href="mailto:contact@bluewavebeacon.com">Contact</a>
    <a href="privacy.html">Privacy Policy</a>
    <a href="terms.html">Terms</a>
    <a href="merch.html">Merch Store</a>
    <a href="archive.html">Archive</a>
  </div>
  <div>
    &copy; {year} BLUE WAVE BEACON &mdash; Independent progressive journalism aggregator.<br/>
    All linked articles belong to their respective publishers.
  </div>
</footer>

<script>
// Show breaking banner if a ?breaking= param is set
const params = new URLSearchParams(location.search);
if (params.get('breaking')) {{
  document.getElementById('breaking-banner').style.display = 'block';
  document.getElementById('breaking-text').textContent = decodeURIComponent(params.get('breaking'));
}}

// Headline search
document.getElementById('headline-search').addEventListener('input', function (e) {{
  const q = e.target.value.trim().toLowerCase();
  document.querySelectorAll('.news-link').forEach(function (link) {{
    const text = link.textContent.toLowerCase();
    link.classList.toggle('search-hidden', q.length > 0 && !text.includes(q));
  }});
}});

// Register service worker for PWA
if ('serviceWorker' in navigator) {{
  navigator.serviceWorker.register('sw.js').catch(function () {{}});
}}
</script>
</body>
</html>
"""

# ── RSS FEED GENERATION ────────────────────────────────────────────────────────

def build_rss(items: list[dict], now: datetime) -> str:
    rfc822 = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
    item_xml = ""
    for item in items[:50]:
        title = html.escape(item["title"])
        link  = html.escape(item["link"])
        item_xml += f"""  <item>
    <title>{title}</title>
    <link>{link}</link>
    <source>{html.escape(item['source'])}</source>
    <pubDate>{rfc822}</pubDate>
  </item>\n"""
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0">
<channel>
  <title>BLUE WAVE BEACON</title>
  <link>https://bluewavebeacon.com</link>
  <description>Progressive news aggregated daily</description>
  <language>en-us</language>
  <lastBuildDate>{rfc822}</lastBuildDate>
{item_xml}</channel>
</rss>"""

# ── MAIN ───────────────────────────────────────────────────────────────────────

def main():
    now = datetime.now(timezone.utc)
    # Display the timestamp in US Eastern time (the label on the page says "ET")
    try:
        from zoneinfo import ZoneInfo
        now_et = now.astimezone(ZoneInfo("America/New_York"))
    except Exception:
        now_et = now  # fallback to UTC if tz data unavailable
    timestamp = now_et.strftime("%B %d, %Y — %I:%M %p")
    year = now_et.year

    print("Fetching RSS feeds...")
    items = fetch_all_feeds()
    print(f"Total items: {len(items)}")

    print("Fetching Bluesky...")
    bsky_posts, bsky_tags = fetch_bluesky_trending()
    print(f"Bluesky posts: {len(bsky_posts)}, tags: {len(bsky_tags)}")

    print("Building HTML...")
    top_html, left_col, center_col, right_col = build_columns(items)

    bsky_posts_html = "\n".join(render_bsky_post(p) for p in bsky_posts) if bsky_posts else "<p style='padding:16px;color:#9ca3af'>No Bluesky posts fetched. Check API.</p>"
    trend_tags_html = render_trend_tags(bsky_tags) if bsky_tags else ""

    source_pills_html = "\n".join(
        f'<a class="source-pill" href="{html.escape(s["url"])}" target="_blank" rel="noopener noreferrer">{html.escape(s["name"])}</a>'
        for s in SOURCES if s["cat"] != "substack"
    )

    substack_html = render_substack_section(items)
    quote = pick_quote()

    index_html = PAGE_TEMPLATE.format(
        timestamp=timestamp,
        year=year,
        top_story=top_html,
        left_col=left_col,
        center_col=center_col,
        right_col=right_col,
        substack_section=substack_html,
        bsky_posts=bsky_posts_html,
        trend_tags=trend_tags_html,
        source_pills=source_pills_html,
        quote_text=html.escape(quote["text"]),
        quote_author=html.escape(quote["author"]),
    )

    out_index = ROOT / "index.html"
    out_index.write_text(index_html, encoding="utf-8")
    print(f"Written: {out_index}")

    out_rss = ROOT / "feed.xml"
    out_rss.write_text(build_rss(items, now), encoding="utf-8")
    print(f"Written: {out_rss}")

    # Archive snapshot ("On This Day")
    archive_dir = ROOT / "archive"
    archive_dir.mkdir(exist_ok=True)
    date_str = now.strftime("%Y-%m-%d")
    (archive_dir / f"{date_str}.html").write_text(index_html, encoding="utf-8")
    print(f"Written: archive/{date_str}.html")

    update_archive_index(archive_dir)
    update_sitemap(now)

    print("Done.")

def fmt_date(d: str) -> str:
    # Portable "Month D, YYYY" (avoid %-d / %#d which differ by platform)
    dt = datetime.strptime(d, "%Y-%m-%d")
    return f"{dt.strftime('%B')} {dt.day}, {dt.year}"

def update_archive_index(archive_dir: Path):
    dates = sorted((p.stem for p in archive_dir.glob("*.html")), reverse=True)
    links = "\n  ".join(
        f'<a href="archive/{d}.html">{fmt_date(d)}</a>'
        for d in dates
    )
    archive_html = (ROOT / "archive.html").read_text(encoding="utf-8")
    archive_html = re.sub(
        r'<div class="archive-grid" id="archive-list">.*?</div>',
        f'<div class="archive-grid" id="archive-list">\n  {links}\n</div>',
        archive_html,
        flags=re.DOTALL,
    )
    (ROOT / "archive.html").write_text(archive_html, encoding="utf-8")
    print(f"Updated archive.html with {len(dates)} entries")

def update_sitemap(now: datetime):
    today = now.strftime("%Y-%m-%d")
    sitemap_path = ROOT / "sitemap.xml"
    sitemap = sitemap_path.read_text(encoding="utf-8")
    sitemap = re.sub(r"<lastmod>\d{4}-\d{2}-\d{2}</lastmod>", f"<lastmod>{today}</lastmod>", sitemap)
    sitemap_path.write_text(sitemap, encoding="utf-8")
    print(f"Updated sitemap.xml lastmod to {today}")

if __name__ == "__main__":
    main()
