"""News feed configuration.

Check each publisher's feed availability, licensing, and terms of use before
production use. A publisher homepage is not automatically an RSS endpoint.
To add PNA, PIA, GMA, ABS-CBN, or Manila Bulletin, confirm their feed URLs first.
"""

GN = "https://news.google.com/rss/search?hl=en-PH&gl=PH&ceid=PH:en&q="

FEEDS = [
    # Local Caraga and broader Mindanao regional coverage
    {"source": "Google News (Caraga)", "section": "local", "url": GN + "Caraga+OR+Surigao"},
    {"source": "Google News (Mindanao)", "section": "regional", "url": GN + "Mindanao"},
    # Philippine national
    {"source": "Rappler", "section": "national", "url": "https://www.rappler.com/feed/"},
    {"source": "Philippine Daily Inquirer", "section": "national", "url": "https://www.inquirer.net/fullfeed"},
    {"source": "Google News (Philippines)", "section": "national", "url": GN + "Philippines"},
    # International
    {"source": "BBC News", "section": "international", "url": "https://feeds.bbci.co.uk/news/rss.xml"},
    {"source": "Al Jazeera English", "section": "international", "url": "https://www.aljazeera.com/xml/rss/all.xml"},
    {"source": "The Guardian", "section": "international", "url": "https://www.theguardian.com/international/rss"},
    {"source": "Deutsche Welle", "section": "international", "url": "https://rss.dw.com/rdf/rss-en-all"},
    {"source": "France 24", "section": "international", "url": "https://www.france24.com/en/rss"},
]

# High-signal terms for the dashboard's fixed news categories. Supporting terms
# only count when the headline or description also contains a category anchor.
NEWS_TOPIC_RULES = {
    "Business": {
        "anchors": [
            "business", "businesses", "economy", "economic", "company", "companies",
            "corporate", "corporation", "stock", "stocks", "stock market", "finance",
            "financial", "banking", "startup", "startups", "earnings", "revenue",
            "profit", "inflation", "investment", "investor", "investors", "merger",
            "acquisition", "retail", "commerce",
        ],
        "support": [
            "bank", "banks", "market", "markets", "trade", "trading", "sale", "sales",
            "price", "prices", "job", "jobs", "employment", "worker", "workers",
            "shares", "loan", "loans", "rate", "rates", "debt", "tax", "taxes",
            "budget", "commercial", "supply chain", "union", "labor", "wage", "wages",
            "consumer", "consumers", "industry", "industries",
        ],
    },
    "Sports": {
        "anchors": [
            "sport", "sports", "athlete", "athletes", "basketball", "football",
            "volleyball", "soccer", "baseball", "boxing", "olympic", "olympics",
            "tennis", "cricket", "rugby", "badminton", "marathon", "esports",
            "fifa", "uefa", "nba", "wnba", "pba", "ncaa", "uaap", "fiba",
            "mpbl", "cesafi", "pff", "pga", "mvp", "governor's cup",
        ],
        "support": [
            "game", "games", "league", "player", "players", "match", "matches",
            "coach", "season", "score", "won", "defeated", "medal", "final", "finals",
            "championship", "tournament", "golf", "golfer", "golfers", "race",
            "goal", "pitch", "court", "referee", "fans", "club", "team",
        ],
    },
    "Agriculture": {
        "anchors": [
            "agriculture", "agricultural", "farmer", "farmers", "farming", "crop",
            "crops", "harvest", "fisheries", "fishing", "livestock", "aquaculture",
            "irrigation", "fertilizer", "poultry", "plantation",
        ],
        "support": [
            "farm", "farms", "soil", "grain", "grains", "rice", "corn", "cattle",
            "yield", "rural", "seed", "seeds", "fish", "food production",
        ],
    },
    "Politics": {
        "anchors": [
            "politics", "political", "politician", "politicians", "election", "elections",
            "president", "presidential", "congress", "congressional", "senate", "senator",
            "parliament", "government", "governor", "mayor", "lawmaker", "lawmakers",
            "legislator", "legislators", "minister", "cabinet", "legislation", "candidate",
            "referendum", "politburo", "opposition", "administration", "impeachment",
            "democrat", "democrats", "republican", "republicans", "midterm election",
            "vice president", "vice-president", "senate impeachment court",
            "supreme court", "prime minister", "parliamentary", "mp", "mps", "trump",
            "macron",
        ],
        "support": [
            "protest", "protests", "protester", "protesters", "rally", "rallies",
            "demonstration", "demonstrations", "activist", "activists", "march",
            "marchers", "public hearing", "ordinance", "civil rights", "lobby",
            "voting", "vote", "policy", "policies", "bill", "campaign",
            "trial", "verdict", "witness", "witnesses", "defense", "senate seat",
        ],
    },
    "Health": {
        "anchors": [
            "health", "healthcare", "public health", "mental health", "hospital",
            "hospitals", "medical", "doctor", "doctors", "physician", "disease",
            "illness", "patient", "patients", "medicine", "outbreak", "vaccine",
            "vaccination", "virus", "clinical", "cancer", "diabetes", "dengue",
            "epidemic", "infection", "treatment", "surgery", "diagnosis",
        ],
        "support": [
            "care", "clinic", "clinics", "nurse", "nurses", "wellness", "nutrition",
            "therapy", "symptom", "symptoms", "recovery", "injury", "injuries",
            "exercise",             "fitness", "pharmaceutical",
        ],
    },
    "Technology": {
        "anchors": [
            "technology", "technologies", "artificial intelligence", "software",
            "cybersecurity", "cyberattack", "robotics", "semiconductor", "chip",
            "chips", "smartphone", "smartphones", "internet", "computer", "computing",
            "telecommunications",
        ],
        "support": [
            "digital", "app", "apps", "platform", "platforms", "data", "device",
            "devices", "online", "algorithm", "automation", "tech",
        ],
    },
    "Education": {
        "anchors": [
            "education", "school", "schools", "university", "universities", "college",
            "colleges", "student", "students", "teacher", "teachers", "classroom",
            "scholarship", "scholarships", "curriculum", "exam", "exams", "enrollment",
        ],
        "support": [
            "learning", "lesson", "lessons", "tuition", "literacy", "class", "classes",
            "campus", "faculty", "graduate", "graduation",
        ],
    },
    "Environment": {
        "anchors": [
            "environment", "environmental", "climate", "weather", "typhoon", "storm",
            "flood", "flooding", "earthquake", "pollution", "wildlife", "conservation",
            "biodiversity", "emissions", "deforestation", "wildfire", "drought",
            "carbon", "renewable energy", "sea level", "ecosystem",
        ],
        "support": [
            "nature", "forest", "forests", "river", "rivers", "ocean", "oceans",
            "temperature", "disaster", "sustainable", "sustainability",
        ],
    },
    "Entertainment": {
        "anchors": [
            "film", "films", "movie", "movies", "music", "actor",
            "actress", "celebrity", "celebrities", "concert", "concerts", "television",
            "singer", "singers", "album", "albums", "cinema", "showbiz", "theatre",
            "theater", "premiere", "streaming", "gaming", "video game", "video games",
        ],
        "support": [
            "festival", "festivals", "audience", "performance", "performer", "performers",
            "star", "stars", "series", "show", "shows", "release", "entertainment",
            "game", "games", "console", "consoles", "game developer", "gaming industry",
        ],
    },
    "Crime & Safety": {
        "anchors": [
            "crime", "criminal", "police", "arrest", "arrested", "suspect", "murder",
            "robbery", "robbed", "heist", "assault", "kidnapping", "safety",
            "investigation", "shooting", "homicide", "drug bust", "collision",
            "accident", "arson", "fire department",
        ],
        "support": [
            "victim", "victims", "charged", "charges", "court", "fatality", "fatalities",
            "emergency", "missing", "missing person", "firefighter", "firefighters",
            "theft", "fire", "rescue", "abuse",
        ],
    },
}

# Used for legacy/custom journalism interests; fixed news categories use
# NEWS_TOPIC_RULES above instead of substring matching.
INTEREST_KEYWORDS = {
    "Business": ["business", "economy", "economic", "company", "companies", "market", "markets", "stock", "finance", "financial", "trade", "bank", "banking", "startup", "industry"],
    "Sports": ["sport", "athlete", "league", "tournament", "olympic", "basketball", "football", "volleyball", "soccer", "baseball", "boxing", "championship"],
    "Agriculture": ["agriculture", "agricultural", "farmer", "farmers", "farming", "farm", "crops", "crop", "harvest", "fisheries", "fishing", "livestock"],
    "Politics": ["politic", "government", "president", "congress", "senate", "senator", "election", "mayor", "governor", "lawmakers", "politician"],
    "Health": ["health", "hospital", "medical", "doctor", "disease", "medicine", "patient", "healthcare", "outbreak"],
    "Technology": ["technology", "tech", "artificial intelligence", "cybersecurity", "software", "digital", "robotics", "innovation"],
    "Education": ["education", "school", "university", "college", "student", "teacher", "classroom", "scholarship"],
    "Environment": ["environment", "climate", "weather", "typhoon", "storm", "flood", "earthquake", "pollution", "wildlife", "conservation"],
    "Entertainment": ["entertainment", "film", "movie", "music", "actor", "actress", "concert", "celebrity", "television", "festival"],
    "Crime & Safety": ["crime", "police", "arrest", "suspect", "murder", "robbery", "fire", "rescue", "safety", "investigation"],
    "Photojournalism": ["photo", "photograph", "photojournal", "image"],
    "Sports Journalism": ["sport", "athlete", "league", "tournament", "olympic", "basketball", "football"],
    "Mobile Journalism": ["mobile", "smartphone", "app", "social media", "tiktok", "facebook"],
    "Mobile journalism": ["mobile", "smartphone", "app", "social media", "tiktok", "facebook"],
    "Media Arts": ["film", "art", "music", "design", "media", "festival", "theater", "theatre"],
    "Campus Journalism": ["campus", "student", "school", "university", "college", "education"],
    "Campus journalism": ["campus", "student", "school", "university", "college", "education"],
    "News Writing": ["report", "news", "journalist", "journalism", "press", "media"],
    "Feature Writing": ["feature", "profile", "culture", "community", "human interest"],
    "Editorial Writing": ["editorial", "opinion", "column", "commentary", "policy"],
    "Science and Technology": ["science", "technology", "tech", "research", "climate", "health", "artificial intelligence"],
    "Investigative Journalism": ["investigation", "investigative", "corruption", "accountability", "audit", "probe", "whistleblower"],
    "Campus News Writing": ["campus", "student", "school", "university", "college", "education"],
    "Campus Editorial Writing": ["editorial", "opinion", "column", "commentary", "policy", "campus"],
    "Campus Feature Writing": ["feature", "profile", "culture", "community", "human interest", "campus"],
    "Campus Sports Writing": ["sport", "athlete", "league", "tournament", "campus", "school team"],
    "Campus Science and Technology Writing": ["science", "technology", "research", "climate", "health", "campus"],
    "Campus Photojournalism": ["photo", "photograph", "photojournal", "image", "campus"],
    "Campus Copyreading and Headline Writing": ["editing", "headline", "copyreading", "newspaper", "campus"],
    "Campus Cartooning": ["cartoon", "illustration", "editorial art", "campus"],
    "Campus Radio Broadcasting": ["radio", "broadcast", "on air", "campus"],
    "Campus TV Broadcasting": ["television", "tv", "broadcast", "video", "campus"],
    "Campus Collaborative Publishing": ["publication", "newspaper", "publishing", "campus"],
    "Campus Online Publishing": ["online", "digital", "website", "social media", "campus"],
}
