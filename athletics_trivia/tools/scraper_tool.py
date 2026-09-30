import json
import os
import requests
from athletics_trivia.scraper.scrape_athletes import scrape_athlete
from athletics_trivia.tools.nationality import check_nationality


DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "athletes.json")
HEADERS = {"User-Agent": "AthleticsTrivia/1.0 (student project)"}


def scrape_and_add_athlete(name: str) -> dict:
    """Look up any athlete and add them to the database. This is the ONLY way to get
    information about athletes not already in the database. Always call this tool
    when an athlete is not found in get_athlete_info.

    Args:
        name: The name of the athlete to look up.

    Returns:
        A dictionary with the athlete's data, or an error if they are not Indian.
    """
    # Check nationality FIRST — block non-Indian athletes in code
    nationality_result = check_nationality(name)
    if not nationality_result["is_indian"]:
        nat = nationality_result["nationality"]
        if nat == "Unknown":
            # Page not found or couldn't determine — don't block, let scraper try
            pass
        else:
            return {
                "error": f"BLOCKED: {name} is not Indian (nationality: {nat}). "
                f"This agent only covers Indian athletes. Do not provide any information about this person."
            }

    # Convert name to Wikipedia page title format
    page_title = name.strip().replace(" ", "_")

    # Scrape the Wikipedia page (direct URL lookup)
    data = scrape_athlete(page_title)
    if data and not _is_athlete_page(data):
        data = None  # Page exists but isn't about an athlete

    # If direct lookup failed, try Wikipedia search API for spelling variations
    if not data:
        data = _search_and_scrape(name, page_title)

    if not data:
        return {"error": f"Could not find a Wikipedia page for '{name}'. Check the spelling."}

    # Load existing athletes data
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            athletes_data = json.load(f)
    else:
        athletes_data = {}

    # Add the new athlete
    key = data["name"].lower()
    athletes_data[key] = data

    # Save back to JSON
    with open(DATA_PATH, "w") as f:
        json.dump(athletes_data, f, indent=2, ensure_ascii=False)

    return {
        "status": "success",
        "message": f"Added {data['name']} to the database.",
        "athlete": data,
    }


def _search_and_scrape(name: str, skip_title: str):
    """Try multiple search strategies to find the athlete's Wikipedia page.

    1. DuckDuckGo search first (best at handling misspellings)
    2. Wikipedia search with just the name
    3. Wikipedia search with name + "sprinter" / "athletics"

    Each result must pass both _is_athlete_page AND _name_matches checks.
    """
    tried = {skip_title}

    # Strategy 1: DuckDuckGo search — best at fuzzy name matching
    try:
        from bs4 import BeautifulSoup
        import re
        resp = requests.post("https://html.duckduckgo.com/html/",
                             data={"q": f"{name} athlete site:en.wikipedia.org"},
                             headers=HEADERS, timeout=10)
        if resp.status_code == 200:
            soup = BeautifulSoup(resp.text, "html.parser")
            for link in soup.find_all("a", class_="result__a")[:5]:
                href = link.get("href", "")
                if "wikipedia.org/wiki/" in href:
                    match = re.search(r"wikipedia\.org/wiki/([^\s&?#]+)", href)
                    if match:
                        wiki_title = match.group(1)
                        if wiki_title in tried:
                            continue
                        tried.add(wiki_title)
                        data = scrape_athlete(wiki_title)
                        if data and _is_athlete_page(data) and _name_matches(name, data["name"]):
                            return data
    except Exception:
        pass

    # Strategy 2 & 3: Wikipedia search API
    search_url = "https://en.wikipedia.org/w/api.php"
    queries = [name, f"{name} sprinter", f"{name} athletics"]
    for query in queries:
        try:
            params = {
                "action": "query",
                "list": "search",
                "srsearch": query,
                "srlimit": 3,
                "format": "json",
            }
            resp = requests.get(search_url, headers=HEADERS, params=params, timeout=10)
            results = resp.json().get("query", {}).get("search", [])
            for result in results:
                alt_title = result["title"].replace(" ", "_")
                if alt_title in tried:
                    continue
                tried.add(alt_title)
                data = scrape_athlete(alt_title)
                if data and _is_athlete_page(data) and _name_matches(name, data["name"]):
                    return data
        except Exception:
            pass

    return None


def _name_matches(query_name: str, found_name: str) -> bool:
    """Check if the found page name is a reasonable match for what we searched.

    Handles minor spelling differences (Abhinaya vs Abinaya) by checking
    if the surname matches and first name is similar.
    """
    q_parts = query_name.lower().split()
    f_parts = found_name.lower().split()

    if not q_parts or not f_parts:
        return False

    # Check if surname (last word) matches
    if q_parts[-1] == f_parts[-1]:
        return True

    # Check if first name is similar (allow 1-2 char difference)
    if len(q_parts) >= 2 and len(f_parts) >= 2:
        # Surname match
        if q_parts[-1] == f_parts[-1]:
            return True
        # First name match with surname close
        if q_parts[0] == f_parts[0]:
            return True

    # Check if one name contains the other
    q_full = " ".join(q_parts)
    f_full = " ".join(f_parts)
    if q_full in f_full or f_full in q_full:
        return True

    return False


def _is_athlete_page(data: dict) -> bool:
    """Check if scraped data is about a sports athlete (not a non-sport page)."""
    summary = (data.get("summary") or "").lower()
    event = (data.get("event") or "").lower()
    combined = f"{summary} {event}"

    # Reject non-sport pages
    non_sport = [
        "film", "movie", "album", "song", "actor", "actress",
        "director", "novel", "politician", "village", "city",
        "district", "municipality", "television", "band",
    ]
    for kw in non_sport:
        if kw in combined:
            return False

    # Positive signals — any competitive sport
    sport_keywords = [
        # Athletics / track & field
        "sprinter", "runner", "jumper", "thrower", "walker",
        "marathon", "javelin", "discus", "shot put", "hammer", "pole vault",
        "high jump", "long jump", "triple jump", "hurdles", "steeplechase",
        "decathlon", "heptathlon", "race walk", "track and field",
        "100 m", "200 m", "400 m", "800 m", "1500 m", "5000 m", "10000 m",
        "athletics", "personal best",
        # Other Olympic / Asian Games sports
        "shooter", "shooting", "archer", "archery",
        "boxer", "boxing", "wrestler", "wrestling",
        "weightlift", "badminton", "squash", "table tennis",
        "swimmer", "swimming", "rowing", "fencer", "fencing",
        "gymnast", "gymnastics", "judo", "karate", "taekwondo",
        "kabaddi", "cricket", "hockey", "wushu", "kurash",
        "tennis", "volleyball", "cyclist", "cycling",
        "golfer", "golf", "sailing",
        # Generic sport signals
        "athlete", "medal", "olympic", "asian games", "commonwealth",
        "world championship", "national champion",
    ]
    for kw in sport_keywords:
        if kw in combined:
            return True

    return False
