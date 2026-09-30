import requests
from bs4 import BeautifulSoup


HEADERS = {"User-Agent": "AthleticsTrivia/1.0 (student project)"}


def check_nationality(name: str) -> dict:
    """Check if an athlete is Indian.

    Tries three sources in order:
    1. Wikipedia (search API + infobox/first paragraph)
    2. DuckDuckGo Instant Answer API
    3. DuckDuckGo search results scrape

    Args:
        name: The name of the athlete to check.

    Returns:
        A dictionary with the athlete's nationality and whether they are Indian.
    """
    # 1. Try Wikipedia first
    result = _check_wikipedia(name)
    if result["nationality"] != "Unknown":
        return result

    # 2. Try DuckDuckGo Instant Answer API
    result = _check_ddg_instant(name)
    if result["nationality"] != "Unknown":
        return result

    # 3. Try DuckDuckGo search results scrape
    result = _check_ddg_search(name)
    return result


def _check_wikipedia(name: str) -> dict:
    """Check nationality via Wikipedia search API + page scrape."""
    # Use Wikipedia search API to find the right page (handles misspellings)
    search_url = "https://en.wikipedia.org/w/api.php"
    params = {
        "action": "query",
        "list": "search",
        "srsearch": name,
        "srlimit": 1,
        "format": "json",
    }
    try:
        search_resp = requests.get(search_url, headers=HEADERS, params=params, timeout=10)
        search_data = search_resp.json()
        results = search_data.get("query", {}).get("search", [])
        if results:
            page_title = results[0]["title"].replace(" ", "_")
        else:
            page_title = name.strip().replace(" ", "_")
    except Exception:
        page_title = name.strip().replace(" ", "_")

    url = f"https://en.wikipedia.org/wiki/{page_title}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
    except requests.exceptions.RequestException:
        return {"name": name, "nationality": "Unknown", "is_indian": False,
                "source": "wikipedia", "note": "Could not reach Wikipedia"}

    if response.status_code != 200:
        return {"name": name, "nationality": "Unknown", "is_indian": False,
                "source": "wikipedia", "note": "No Wikipedia page found"}

    soup = BeautifulSoup(response.text, "html.parser")

    # Check the infobox for nationality/country
    infobox = soup.find("table", class_="infobox")
    if infobox:
        for row in infobox.find_all("tr"):
            header = row.find("th")
            value = row.find("td")
            if header and value:
                key = header.get_text(strip=True).lower()
                val = value.get_text(strip=True).lower()
                if key in ("nationality", "country", "allegiance"):
                    is_indian = "india" in val
                    return {
                        "name": name,
                        "nationality": value.get_text(strip=True),
                        "is_indian": is_indian,
                        "source": "wikipedia",
                    }

    # Fallback: check the first paragraph for "Indian"
    for p in soup.find_all("p"):
        text = p.get_text(strip=True)
        if len(text) > 50:
            is_indian = "indian" in text.lower()
            if is_indian:
                return {"name": name, "nationality": "Indian", "is_indian": True,
                        "source": "wikipedia"}
            # Found a substantial paragraph but no Indian mention — keep looking
            # in other sources rather than concluding non-Indian from Wikipedia alone
            break

    return {"name": name, "nationality": "Unknown", "is_indian": False,
            "source": "wikipedia"}


def _check_ddg_instant(name: str) -> dict:
    """Check nationality via DuckDuckGo Instant Answer API.

    Free, no API key. Returns a JSON summary if DDG has an instant answer.
    """
    try:
        url = "https://api.duckduckgo.com/"
        params = {
            "q": f"{name} athlete",
            "format": "json",
            "no_redirect": 1,
        }
        response = requests.get(url, headers=HEADERS, params=params, timeout=10)
        data = response.json()

        # Check Abstract (main summary text)
        abstract = (data.get("Abstract", "") or "").lower()
        heading = (data.get("Heading", "") or "").lower()

        # Also check Related Topics
        related_texts = []
        for topic in data.get("RelatedTopics", []):
            if isinstance(topic, dict) and "Text" in topic:
                related_texts.append(topic["Text"].lower())

        all_text = f"{abstract} {heading} {' '.join(related_texts)}"

        if "indian" in all_text or "india" in all_text:
            return {"name": name, "nationality": "Indian", "is_indian": True,
                    "source": "duckduckgo_api"}

        # If we got a meaningful response but no Indian mention, it's likely non-Indian
        if abstract and len(abstract) > 30:
            return {"name": name, "nationality": "Non-Indian", "is_indian": False,
                    "source": "duckduckgo_api"}

    except Exception:
        pass

    return {"name": name, "nationality": "Unknown", "is_indian": False,
            "source": "duckduckgo_api"}


def _check_ddg_search(name: str) -> dict:
    """Check nationality by scraping DuckDuckGo search results.

    Searches for the athlete name and checks if snippets mention India/Indian.
    """
    try:
        url = "https://html.duckduckgo.com/html/"
        params = {"q": f"{name} athlete nationality"}
        response = requests.post(url, data=params, headers={
            "User-Agent": "AthleticsTrivia/1.0 (student project)",
        }, timeout=10)

        if response.status_code != 200:
            return {"name": name, "nationality": "Unknown", "is_indian": False,
                    "source": "duckduckgo_search"}

        soup = BeautifulSoup(response.text, "html.parser")

        # Extract text from search result snippets
        snippets = []
        for result in soup.find_all("a", class_="result__snippet"):
            snippets.append(result.get_text(strip=True).lower())
        # Also check result titles
        for result in soup.find_all("a", class_="result__a"):
            snippets.append(result.get_text(strip=True).lower())

        all_text = " ".join(snippets)

        if not all_text:
            return {"name": name, "nationality": "Unknown", "is_indian": False,
                    "source": "duckduckgo_search"}

        # Count Indian vs other nationality signals
        indian_signals = all_text.count("indian") + all_text.count("india")

        if indian_signals >= 1:
            return {"name": name, "nationality": "Indian", "is_indian": True,
                    "source": "duckduckgo_search"}

        # Got search results but no Indian mention
        return {"name": name, "nationality": "Non-Indian", "is_indian": False,
                "source": "duckduckgo_search"}

    except Exception:
        pass

    return {"name": name, "nationality": "Unknown", "is_indian": False,
            "source": "duckduckgo_search"}
