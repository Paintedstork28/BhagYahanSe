import requests
from bs4 import BeautifulSoup
from athletics_trivia.tools.athlete import get_athlete_info


def compare_to_records(athlete_name: str, event: str) -> dict:
    """Compare an athlete's personal best to the current world record and Olympic record
    for a given event. Call this when the user asks how an athlete compares to world
    or Olympic records.

    Args:
        athlete_name: The full name of the athlete (e.g. "Neeraj Chopra").
        event: The athletics event (e.g. "javelin throw", "100m", "long jump").

    Returns:
        A dictionary with the athlete's PB, world record, and Olympic record.
    """
    # Get athlete's personal best from database
    athlete_data = get_athlete_info(athlete_name)
    athlete_pb = athlete_data.get("personal_best", "Unknown") if "error" not in athlete_data else "Unknown"

    # Scrape world record from Wikipedia
    event_slug = event.strip().lower().replace(" ", "_")
    world_record = _scrape_record(f"https://en.wikipedia.org/wiki/{event_slug}", "world record")
    olympic_record = _scrape_record(f"https://en.wikipedia.org/wiki/{event_slug}_at_the_Olympics", "olympic record")

    return {
        "athlete": athlete_name,
        "event": event,
        "athlete_personal_best": athlete_pb,
        "world_record": world_record,
        "olympic_record": olympic_record,
    }


def _scrape_record(url: str, record_type: str) -> dict:
    """Scrape a record from a Wikipedia page."""
    headers = {"User-Agent": "AthleticsTrivia/1.0 (student project)"}

    try:
        response = requests.get(url, headers=headers)
        if response.status_code != 200:
            return {"holder": "Unknown", "mark": "Unknown", "source": url}

        soup = BeautifulSoup(response.text, "html.parser")

        # Look for record information in infobox or tables
        infobox = soup.find("table", class_="infobox")
        if infobox:
            for row in infobox.find_all("tr"):
                header = row.find("th")
                value = row.find("td")
                if header and value:
                    key = header.get_text(strip=True).lower()
                    if "world record" in key or "wr" in key:
                        return {"mark": value.get_text(strip=True), "source": url}
                    if "olympic record" in key or "or" in key:
                        return {"mark": value.get_text(strip=True), "source": url}

        # Fallback: search page text for record mentions
        for p in soup.find_all("p"):
            text = p.get_text(strip=True).lower()
            if "world record" in text or "olympic record" in text:
                return {"info": p.get_text(strip=True)[:300], "source": url}

        return {"holder": "Unknown", "mark": "Not found on page", "source": url}

    except Exception as e:
        return {"error": str(e), "source": url}
