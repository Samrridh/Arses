import feedparser

def fetch_new_entries(feed_url, seen_links):
    feed = feedparser.parse(feed_url)
    new_items = []
    for entry in feed.entries:
        if entry.link not in seen_links:
            seen_links.add(entry.link)
            new_items.append((entry.title, entry.link))
    return new_items
