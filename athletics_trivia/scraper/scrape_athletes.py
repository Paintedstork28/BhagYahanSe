import json
import os
import requests
from bs4 import BeautifulSoup


# List of Indian athletes to scrape (Wikipedia page titles)
ATHLETES = [
    "Neeraj_Chopra",
    "Hima_Das",
    "Dutee_Chand",
    "Avinash_Sable",
    "Murali_Sreeshankar",
    "Tajinderpal_Singh_Toor",
    "Jyothi_Yarraji",
    "Annu_Rani",
    "Parul_Chaudhary",
    "Kishore_Jena",
    "D._P._Manu",
    "Jeswin_Aldrin",
    "Harmilan_Bains",
    "Amoj_Jacob",
    "Priyanka_Goswami",
]


def scrape_athlete(page_title):
    """Scrape one athlete's Wikipedia page and return structured data."""
    url = f"https://en.wikipedia.org/wiki/{page_title}"
    print(f"Scraping {url}...")

    headers = {"User-Agent": "AthleticsTrivia/1.0 (student project)"}
    response = requests.get(url, headers=headers)
    if response.status_code != 200:
        print(f"  Failed to fetch {url} (status {response.status_code})")
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Get the athlete's display name from the page title
    name_tag = soup.find("span", class_="mw-page-title-main")
    name = name_tag.text if name_tag else page_title.replace("_", " ")

    # Parse the infobox (the card on the right side of Wikipedia)
    infobox = soup.find("table", class_="infobox")
    info = {}
    if infobox:
        rows = infobox.find_all("tr")
        for row in rows:
            header = row.find("th")
            value = row.find("td")
            if header and value:
                key = header.get_text(strip=True).lower()
                val = value.get_text(strip=True)
                info[key] = val

    # Extract key fields from infobox (Wikipedia uses different field names)
    event = info.get("event", info.get("event(s)", info.get("events", info.get("discipline", "Unknown"))))
    personal_best = info.get("personalbests", info.get("personal best", info.get("personal best(s)", info.get("personalbest", "Unknown"))))
    birth_date = info.get("born", "Unknown")
    sport = info.get("sport", "Athletics")

    # Get the first paragraph as a summary
    paragraphs = soup.find_all("p")
    summary = ""
    for p in paragraphs:
        text = p.get_text(strip=True)
        if len(text) > 50:  # Skip short/empty paragraphs
            summary = text
            break

    # Look for achievements in the page
    achievements = []
    for li in soup.select(".mw-parser-output ul li"):
        text = li.get_text(strip=True)
        # Look for medal-related text
        if any(word in text.lower() for word in ["gold", "silver", "bronze", "champion", "olympic", "asian games", "world"]):
            if len(text) < 200:  # Skip overly long items
                achievements.append(text)
            if len(achievements) >= 5:
                break

    return {
        "name": name,
        "event": event,
        "personal_best": personal_best,
        "birth_date": birth_date,
        "sport": sport,
        "summary": summary[:500],  # Limit summary length
        "achievements": achievements,
    }


def main():
    """Scrape all athletes and save to JSON."""
    # Create data directory
    data_dir = os.path.join(os.path.dirname(__file__), "..", "data")
    os.makedirs(data_dir, exist_ok=True)

    athletes_data = {}
    for page_title in ATHLETES:
        data = scrape_athlete(page_title)
        if data:
            # Use lowercase name as key for easy lookup
            key = data["name"].lower()
            athletes_data[key] = data
            print(f"  OK: {data['name']} — {data['event']}")
        else:
            print(f"  SKIP: {page_title}")

    # Save to JSON
    output_path = os.path.join(data_dir, "athletes.json")
    with open(output_path, "w") as f:
        json.dump(athletes_data, f, indent=2, ensure_ascii=False)

    print(f"\nDone! Saved {len(athletes_data)} athletes to {output_path}")


if __name__ == "__main__":
    main()
