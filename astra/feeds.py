"""Curated German RSS/Atom feed catalog, grouped by topic. Pure data."""

FEEDS: dict[str, tuple[dict[str, str], ...]] = {
    "tech": (
        {"name": "heise online", "url": "https://www.heise.de/rss/heise-atom.xml"},
        {"name": "Golem.de", "url": "https://rss.golem.de/rss.php?feed=RSS2.0"},
        {"name": "t3n", "url": "https://t3n.de/rss.xml"},
        {"name": "netzpolitik.org", "url": "https://netzpolitik.org/feed/"},
    ),
    "nachrichten": (
        {
            "name": "tagesschau.de",
            "url": "https://www.tagesschau.de/infoservices/alle-meldungen-100~rss2.xml",
        },
        {"name": "Zeit Online", "url": "https://newsfeed.zeit.de/index"},
        {"name": "Spiegel", "url": "https://www.spiegel.de/schlagzeilen/index.rss"},
        {"name": "Süddeutsche Zeitung", "url": "https://rss.sueddeutsche.de/rss/Topthemen"},
    ),
    "wirtschaft": (
        {
            "name": "Handelsblatt",
            "url": "https://www.handelsblatt.com/contentexport/feed/schlagzeilen",
        },
        {
            "name": "WirtschaftsWoche",
            "url": "https://www.wiwo.de/contentexport/feed/rss/schlagzeilen",
        },
        {"name": "manager magazin", "url": "https://www.manager-magazin.de/unternehmen/index.rss"},
    ),
    "hilden": (
        {"name": "RP ONLINE Hilden", "url": "https://rp-online.de/nrw/staedte/hilden/feed.rss"},
    ),
}
TOPICS = tuple(FEEDS.keys())
