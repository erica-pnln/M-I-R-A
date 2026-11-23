"""Shared Philippine broadcaster metadata for news, live, and podcast discovery."""

LANGUAGES = (
    "Tagalog / Filipino",
    "Bisaya / Cebuano",
    "Waray",
    "Hiligaynon",
    "Ilocano",
    "Bicolano",
    "Pangasinan",
    "Chavacano",
    "English",
    "Other Philippine Regional Languages",
)

NETWORKS = (
    "DZRH",
    "GMA Super Radyo DZBB",
    "DWIZ",
    "Radyo5 True FM",
    "Radyo Pilipinas",
    "RMN",
    "Bombo Radyo",
    "Aksyon Radyo",
    "Brigada News FM",
    "Radyo Veritas",
    "DWWW",
    "Radyo Agila",
)

RADIO_NETWORK_SOURCES = {
    "Aksyon Radyo": ("https://mbc.com.ph/", "mbc.com.ph"),
    "Radyo Natin": ("https://mbc.com.ph/", "mbc.com.ph"),
    "Radyo Ronda": ("https://mbc.com.ph/", "mbc.com.ph"),
    "DZRH": ("https://www.dzrh.com.ph/", "dzrh.com.ph"),
    "Bombo Radyo": ("https://www.bomboradyo.com/", "bomboradyo.com"),
    "RMN": ("https://rmn.ph/", "rmn.ph"),
    "Brigada News FM": ("https://brigada.ph/", "brigada.ph"),
}


def _station(name, network, language, region, province, city):
    station_type = (
        "Community Radio Stations"
        if name in {"FMR Tacloban", "Radyo Natin Calbayog"}
        else "Radio Broadcasters"
    )
    return {
        "id": name.casefold().replace(" ", "-"),
        "name": name,
        "network": network,
        "language": language,
        "region": region,
        "province": province,
        "city": city,
        "station_type": station_type,
        "categories": [
            "Radio Broadcasters",
            "National Broadcasters" if region == "NCR" else "Regional & Local Broadcasters",
            language,
            region,
            province,
            city,
            network,
            *([station_type] if station_type == "Community Radio Stations" else []),
        ],
    }


def _radio_source_fields(network):
    source = RADIO_NETWORK_SOURCES.get(network)
    if not source:
        return {}
    source_url, logo_domain = source
    return {
        "source_page_url": source_url,
        "logo_url": (
            "https://www.google.com/s2/favicons"
            f"?domain_url=https://{logo_domain}&sz=128"
        ),
    }


RADIO_STATIONS = (
    _station("Aksyon Radyo Tacloban", "Aksyon Radyo", "Waray", "Eastern Visayas", "Leyte", "Tacloban"),
    _station("Bombo Radyo Tacloban", "Bombo Radyo", "Waray", "Eastern Visayas", "Leyte", "Tacloban"),
    _station("Brigada News FM Tacloban", "Brigada News FM", "Waray", "Eastern Visayas", "Leyte", "Tacloban"),
    _station("iFM RMN Tacloban", "RMN", "Waray", "Eastern Visayas", "Leyte", "Tacloban"),
    _station("Aksyon Radyo Catbalogan", "Aksyon Radyo", "Waray", "Eastern Visayas", "Samar", "Catbalogan"),
    _station("Aksyon Radyo Catarman", "Aksyon Radyo", "Waray", "Eastern Visayas", "Northern Samar", "Catarman"),
    _station("Radyo Pilipinas Calbayog", "Radyo Pilipinas", "Waray", "Eastern Visayas", "Samar", "Calbayog"),
    _station("Radyo Pilipinas Borongan", "Radyo Pilipinas", "Waray", "Eastern Visayas", "Eastern Samar", "Borongan"),
    _station("Radyo Natin Calbayog", "Radyo Natin", "Waray", "Eastern Visayas", "Samar", "Calbayog"),
    _station("FMR Tacloban", "FMR", "Waray", "Eastern Visayas", "Leyte", "Tacloban"),
    _station("Brigada News FM Ormoc", "Brigada News FM", "Waray", "Eastern Visayas", "Leyte", "Ormoc"),
    _station("DYHP RMN Cebu", "RMN", "Bisaya / Cebuano", "Central Visayas", "Cebu", "Cebu City"),
    _station("Aksyon Radyo Cebu", "Aksyon Radyo", "Bisaya / Cebuano", "Central Visayas", "Cebu", "Cebu City"),
    _station("Bombo Radyo Cebu", "Bombo Radyo", "Bisaya / Cebuano", "Central Visayas", "Cebu", "Cebu City"),
    _station("Super Radyo Cebu", "GMA Super Radyo DZBB", "Bisaya / Cebuano", "Central Visayas", "Cebu", "Cebu City"),
    _station("Radyo Pilipinas Cebu", "Radyo Pilipinas", "Bisaya / Cebuano", "Central Visayas", "Cebu", "Cebu City"),
    _station("Radyo Ronda Cebu", "Radyo Ronda", "Bisaya / Cebuano", "Central Visayas", "Cebu", "Cebu City"),
    _station("Brigada News FM Cebu", "Brigada News FM", "Bisaya / Cebuano", "Central Visayas", "Cebu", "Cebu City"),
    _station("DYTR Tagbilaran", "DYTR", "Bisaya / Cebuano", "Central Visayas", "Bohol", "Tagbilaran"),
    _station("RMN Butuan", "RMN", "Bisaya / Cebuano", "Caraga", "Agusan del Norte", "Butuan"),
    _station("RMN Cagayan de Oro", "RMN", "Bisaya / Cebuano", "Northern Mindanao", "Misamis Oriental", "Cagayan de Oro"),
    _station("RMN Davao", "RMN", "Bisaya / Cebuano", "Davao Region", "Davao del Sur", "Davao City"),
    _station("RMN General Santos", "RMN", "Bisaya / Cebuano", "Soccsksargen", "South Cotabato", "General Santos"),
    _station("RMN Iligan", "RMN", "Bisaya / Cebuano", "Northern Mindanao", "Lanao del Norte", "Iligan"),
    _station("RMN Koronadal", "RMN", "Bisaya / Cebuano", "Soccsksargen", "South Cotabato", "Koronadal"),
    _station("RMN Malaybalay", "RMN", "Bisaya / Cebuano", "Northern Mindanao", "Bukidnon", "Malaybalay"),
    _station("RMN Pagadian", "RMN", "Bisaya / Cebuano", "Zamboanga Peninsula", "Zamboanga del Sur", "Pagadian"),
    _station("RMN Surigao", "RMN", "Bisaya / Cebuano", "Caraga", "Surigao del Norte", "Surigao City"),
    _station("RMN Zamboanga", "RMN", "Chavacano", "Zamboanga Peninsula", "Zamboanga del Sur", "Zamboanga City"),
    _station("DZRH", "DZRH", "Tagalog / Filipino", "NCR", "Metro Manila", "Manila"),
    _station("GMA Super Radyo DZBB", "GMA Super Radyo DZBB", "Tagalog / Filipino", "NCR", "Metro Manila", "Quezon City"),
    _station("DWIZ", "DWIZ", "Tagalog / Filipino", "NCR", "Metro Manila", "Quezon City"),
    _station("DZXL RMN", "RMN", "Tagalog / Filipino", "NCR", "Metro Manila", "Quezon City"),
    _station("Radyo Pilipinas 1", "Radyo Pilipinas", "Tagalog / Filipino", "NCR", "Metro Manila", "Quezon City"),
    _station("Radyo Pilipinas 2", "Radyo Pilipinas", "English", "NCR", "Metro Manila", "Quezon City"),
    _station("Radyo5 True FM", "Radyo5 True FM", "Tagalog / Filipino", "NCR", "Metro Manila", "Mandaluyong"),
    _station("Radyo Veritas", "Radyo Veritas", "Tagalog / Filipino", "NCR", "Metro Manila", "Quezon City"),
    _station("DWWW", "DWWW", "Tagalog / Filipino", "NCR", "Metro Manila", "Quezon City"),
    _station("Radyo Agila", "Radyo Agila", "Tagalog / Filipino", "NCR", "Metro Manila", "Quezon City"),
    _station("Aksyon Radyo Iloilo", "Aksyon Radyo", "Hiligaynon", "Western Visayas", "Iloilo", "Iloilo City"),
    _station("Bombo Radyo Iloilo", "Bombo Radyo", "Hiligaynon", "Western Visayas", "Iloilo", "Iloilo City"),
    _station("DYRI RMN Iloilo", "RMN", "Hiligaynon", "Western Visayas", "Iloilo", "Iloilo City"),
    _station("Bombo Radyo Bacolod", "Bombo Radyo", "Hiligaynon", "Western Visayas", "Negros Occidental", "Bacolod"),
    _station("Aksyon Radyo Bacolod", "Aksyon Radyo", "Hiligaynon", "Western Visayas", "Negros Occidental", "Bacolod"),
    _station("DZWT Baguio", "DZWT", "Ilocano", "Cordillera Administrative Region", "Benguet", "Baguio"),
    _station("Bombo Radyo Laoag", "Bombo Radyo", "Ilocano", "Ilocos Region", "Ilocos Norte", "Laoag"),
    _station("DZEA Laoag", "DZEA", "Ilocano", "Ilocos Region", "Ilocos Norte", "Laoag"),
    _station("DZGB Legazpi", "DZGB", "Bicolano", "Bicol Region", "Albay", "Legazpi"),
    _station("Bombo Radyo Naga", "Bombo Radyo", "Bicolano", "Bicol Region", "Camarines Sur", "Naga"),
    _station("Aksyon Radyo Naga", "Aksyon Radyo", "Bicolano", "Bicol Region", "Camarines Sur", "Naga"),
    _station("DZRD Dagupan", "DZRD", "Pangasinan", "Ilocos Region", "Pangasinan", "Dagupan"),
    _station("Aksyon Radyo Dagupan", "Aksyon Radyo", "Pangasinan", "Ilocos Region", "Pangasinan", "Dagupan"),
    _station("Bombo Radyo Dagupan", "Bombo Radyo", "Pangasinan", "Ilocos Region", "Pangasinan", "Dagupan"),
    _station("Bombo Radyo Zamboanga", "Bombo Radyo", "Chavacano", "Zamboanga Peninsula", "Zamboanga del Sur", "Zamboanga City"),
)


PODCAST_PUBLISHERS = {
    "DZRH": ("DZRH", "Tagalog / Filipino"),
    "GMA News": ("GMA Super Radyo DZBB", None),
    "RMN": ("RMN", None),
    "Bombo Radyo": ("Bombo Radyo", None),
    "Aksyon Radyo": ("Aksyon Radyo", None),
    "Brigada News FM": ("Brigada News FM", None),
    "Radyo Pilipinas": ("Radyo Pilipinas", None),
    "Radyo5": ("Radyo5 True FM", None),
    "Radyo Veritas": ("Radyo Veritas", "Tagalog / Filipino"),
    "DWWW": ("DWWW", "Tagalog / Filipino"),
    "Radyo Agila": ("Radyo Agila", "Tagalog / Filipino"),
}


def _matches_name(value, name):
    text = " ".join(str(value or "").casefold().replace("-", " ").split())
    candidate = " ".join(name.casefold().replace("-", " ").split())
    return candidate in text


def classify_publisher(value):
    for station in RADIO_STATIONS:
        if _matches_name(value, station["name"]):
            return {
                "publisher": station["name"],
                "network": station["network"],
                "language": station["language"],
                "region": station["region"],
                "province": station["province"],
                "city": station["city"],
                "categories": [
                    station["name"],
                    station["network"],
                    "Radio Networks",
                    "Regional Radio Networks",
                    "Radio Broadcasters",
                    "News Organizations",
                    station["language"],
                    station["region"],
                ],
            }
    for publisher, (network, language) in PODCAST_PUBLISHERS.items():
        if _matches_name(value, publisher):
            categories = [
                publisher,
                network,
                "News Organizations",
                "Radio Broadcasters",
                "Radio Networks",
                "Regional Radio Networks",
            ]
            result = {
                "publisher": publisher,
                "network": network,
                "categories": categories,
            }
            if language:
                result["language"] = language
                categories.append(language)
            return result
    return None


def classify_news_source(value):
    matches = [
        station for station in RADIO_STATIONS
        if _matches_name(value, station["name"])
    ]
    if matches:
        station = max(matches, key=lambda item: len(item["name"]))
        return {
            "publisher": station["name"],
            "network": station["network"],
            "language": station["language"],
            "region": station["region"],
            "province": station["province"],
            "city": station["city"],
            "categories": station["categories"],
        }
    publisher = classify_publisher(value)
    if publisher:
        return publisher
    return None


def media_search_text(media):
    return " ".join(
        str(value)
        for value in [
            media.get("publisher"),
            media.get("network"),
            media.get("language"),
            media.get("region"),
            media.get("province"),
            media.get("city"),
        ]
        if value
    )


def podcast_categories(episode):
    categories = set(episode.get("categories") or [])
    details = " ".join(
        str(value or "")
        for value in [
            episode.get("title"),
            episode.get("show"),
            episode.get("publisher"),
            episode.get("description"),
            episode.get("genres"),
        ]
    ).casefold()
    media = episode.get("media") or {}
    if media.get("region") and media.get("region") != "NCR":
        categories.add("Regional News")
    elif media.get("region") == "NCR":
        categories.add("National News")
    rules = {
        "National News": ("philippines", "philippine", "national news"),
        "Regional News": ("regional", "region", "visayas", "mindanao", "luzon"),
        "Politics & Government": ("politic", "election", "government", "senate", "president"),
        "Investigative Journalism": ("investigat", "investigation", "corruption", "accountability"),
        "Public Affairs": ("public affairs", "public service", "public policy"),
        "Business & Economy": ("business", "economy", "economic", "finance", "market"),
        "Sports": ("sports", "sport", "basketball", "football", "volleyball"),
        "Community News": ("community", "local news", "barangay"),
        "Interviews": ("interview", "in conversation", "guest"),
        "Current Affairs": ("current affairs", "news", "headlines", "daily briefing"),
    }
    for category, terms in rules.items():
        if any(term in details for term in terms):
            categories.add(category)
    if "campus" in details or "university" in details or "educational" in details:
        categories.add("Philippine Campus Journalism and Educational Media")
        categories.add("Educational & Campus Media")
    if "independent" in details:
        categories.add("Independent Philippine Podcast Creators")
        categories.add("Independent Creators")
    return sorted(categories)


def live_channels():
    return [
        {
            "category": station["region"],
            "categories": station["categories"],
            "description": (
                f'{station["language"]} radio station in {station["city"]}, '
                f'{station["province"]}. No verified live stream is currently available.'
            ),
            "tags": [
                station["network"],
                station["language"],
                station["region"],
                station["province"],
                station["city"],
                station["station_type"],
            ],
            "title": station["name"],
            "publisher": station["network"],
            "url": "",
            "is_live": False,
            "language": station["language"],
            "region": station["region"],
            "province": station["province"],
            "city": station["city"],
            "station_type": station["station_type"],
            **_radio_source_fields(station["network"]),
        }
        for station in RADIO_STATIONS
    ]
