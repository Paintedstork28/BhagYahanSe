"""Competition tracker tool.

Scrapes Wikipedia for current athletics competitions featuring Indian athletes.
Focuses on the Athletics section of "India at the YYYY Asian Games" and similar pages.
"""

import re
import requests
from bs4 import BeautifulSoup
from datetime import datetime


HEADERS = {"User-Agent": "AthleticsTrivia/1.0 (student project)"}


def get_medals() -> dict:
    """Get athletics medals won by Indian athletes at current competitions.

    Checks three sources in order for the fastest updates:
    1. DuckDuckGo News search — picks up medal announcements within minutes
    2. World Athletics website — structured results for WA-organized events
    3. Wikipedia Medalists section — reliable but slow to update

    Deduplicates by (athlete, event) across all sources.

    Returns:
        A dictionary with a list of medals: athlete, event, medal type, date, source.
    """
    year = datetime.now().year
    all_medals = []
    seen_keys = set()  # (athlete_lower, event_lower) for dedup

    # Determine active competitions
    active = get_current_competitions()
    competition_names = [c["competition"] for c in active.get("competitions", [])]

    def _dedup_key(medal):
        """Normalize athlete + event for deduplication across sources."""
        # Use first athlete name (before comma) for relay teams
        athlete = medal["athlete"].split(",")[0].strip().lower()
        event = _normalize_discipline(medal["event"])
        # Also normalize relay formats: 4x400 vs 4 × 400
        event = event.replace("×", "x").replace(" x ", "x").replace(",", "")
        return (athlete, event)

    # Build Indian athlete names from current competition data (already fetched above)
    # No extra HTTP requests needed — reuses the data from get_current_competitions()
    indian_names = set()
    for comp in active.get("competitions", []):
        for evt in comp.get("events", []):
            for a in evt.get("athletes", []):
                aname = a.get("name", "")
                for n in aname.split(","):
                    n = n.strip()
                    if n and len(n) > 2:
                        indian_names.add(n.lower())
                        parts = n.split()
                        if len(parts) >= 2:
                            indian_names.add(parts[-1].lower())

    def _is_indian_medal(medal):
        """Check if a medal entry is for an Indian athlete."""
        athlete = medal["athlete"].lower()
        # Check if any known Indian name appears in the athlete field
        for name in indian_names:
            if name in athlete or athlete in name:
                return True
        # Also check for "India" in relay team entries
        if "india" in athlete:
            return True
        return False

    # Source 1: DuckDuckGo News search (fastest)
    for comp_name in competition_names:
        ddg_medals = _scrape_medals_ddg_news(comp_name)
        for m in ddg_medals:
            m["competition"] = comp_name
            if not _is_indian_medal(m):
                continue
            key = _dedup_key(m)
            if key not in seen_keys:
                seen_keys.add(key)
                all_medals.append(m)

    # Source 2: World Athletics website (for WA-organized events)
    for comp_name in competition_names:
        wa_medals = _scrape_medals_world_athletics(comp_name)
        for m in wa_medals:
            m["competition"] = comp_name
            key = _dedup_key(m)
            if key not in seen_keys:
                seen_keys.add(key)
                all_medals.append(m)

    # Source 3: Wikipedia Medalists section (existing fallback)
    wiki_targets = [
        (f"https://en.wikipedia.org/wiki/India_at_the_{year}_Asian_Games", f"{year} Asian Games"),
        (f"https://en.wikipedia.org/wiki/India_at_the_{year}_World_Athletics_Championships", f"{year} World Athletics Championships"),
    ]
    for url, comp_name in wiki_targets:
        wiki_medals = _scrape_medalists_section(url, HEADERS)
        for m in wiki_medals:
            m["source"] = "wikipedia"
            m["competition"] = comp_name
            key = _dedup_key(m)
            if key not in seen_keys:
                seen_keys.add(key)
                all_medals.append(m)

    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "competitions": competition_names,
        "medals": all_medals,
    }


def get_all_sport_medals() -> dict:
    """Get ALL Indian medals (all sports) at current multi-sport competitions.

    Used for background notifications and medal banner — not the chatbot tool.
    Checks two sources:
    1. DDG News search — finds sports news pages with live medal tables (fastest)
    2. Wikipedia Medalists section — reliable fallback with sport labels

    Deduplicates across sources by (athlete, event).
    """
    year = datetime.now().year
    all_medals = []
    seen_keys = set()

    def _normalize_event_key(event_raw):
        """Aggressively normalize event name for dedup."""
        event = event_raw.lower().strip()
        event = event.replace("\u2019", "'")
        # Strip gender prefixes (including standalone "Women's" or "Men's")
        event = re.sub(r"^(men'?s?|women'?s?|mixed)\s*", "", event)
        # Remove filler words including "team" — we distinguish individual vs team
        # using athlete count instead (more reliable across sources)
        for word in ("tournament", "team", "traditional", "event"):
            event = re.sub(rf"\b{word}\b", " ", event)
        event = re.sub(r"\s+", " ", event).strip()
        # Normalize relay: "4 × 100 m" -> "4x100m", "4x100" -> "4x100m"
        event = event.replace("×", "x")
        event = re.sub(r"(\d+)\s*x\s*(\d+)\s*m?\s*", r"\1x\2m ", event)
        # Normalize distances
        event = re.sub(r"(\d+)\s*m\b", r"\1m", event)
        event = event.replace("metres", "m").replace("meters", "m")
        event = event.replace(",", "")
        # Normalize weight classes: "-78kg" -> "78kg", "78 kg" -> "78kg"
        event = re.sub(r"-?(\d+)\s*kg", r"\1kg", event)
        # Normalize "3 positions" / "3p" / "three positions"
        event = event.replace("three positions", "3p").replace("3 positions", "3p")
        # Remove extra whitespace, sort words
        words = sorted(event.split())
        return " ".join(w for w in words if w)

    def _is_team_entry(medal):
        """Check if this medal is a team event (relay, team, tournament, roster)."""
        athlete = medal["athlete"].lower()
        event = medal.get("event", "").lower()
        if "team" in event or "relay" in event or "tournament" in event:
            return True
        if "team india" in athlete or "india " in athlete:
            return True
        # Multiple athletes listed (3+) suggests a team roster
        if athlete.count(",") >= 2:
            return True
        return False

    def _dedup_key_all(medal):
        """Build a normalized key for cross-source dedup.

        For team events: use (sport, medal_type, event) — ignore athlete names
        since sources list different members or "Team India" vs full roster.

        For individual events: use (sport, medal_type, event) too — within the
        same sport+event+medal, there's only one Indian winner (or one entry).
        The athlete name is unreliable for dedup due to spelling variants.
        """
        sport = medal.get("sport", "").lower().strip()
        medal_type = medal.get("medal", "").lower().strip()
        event_key = _normalize_event_key(medal.get("event", ""))

        # Extract gender from original event to avoid collapsing men's and women's
        event_lower = medal.get("event", "").lower()
        if "women" in event_lower or "female" in event_lower:
            gender = "w"
        elif "mixed" in event_lower:
            gender = "x"
        elif "men" in event_lower:
            gender = "m"
        else:
            # No gender prefix — could be men's or women's
            # Use "u" (unknown) so it can match either
            gender = "u"

        # Distinguish individual vs team by athlete count
        # (more reliable than "team" keyword which varies across sources)
        athlete_text = medal.get("athlete", "")
        is_team = (athlete_text.count(",") >= 1
                   or "team india" in athlete_text.lower()
                   or "india " in athlete_text.lower()
                   or "national" in athlete_text.lower())
        entry_type = "t" if is_team else "i"

        return (sport, medal_type, gender, event_key, entry_type)

    # Use only active competitions (not hardcoded)
    active = get_current_competitions()
    competition_names = [c["competition"] for c in active.get("competitions", [])]

    if not competition_names:
        return {"checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"), "medals": []}

    def _key_exists(key):
        """Check if key exists in seen_keys, handling unknown gender ('u').

        A key with gender 'u' matches any gender with same sport+medal+event.
        A gendered key matches 'u' keys already stored.
        """
        if key in seen_keys:
            return True
        sport, medal_type, gender, event_key, entry_type = key
        if gender == "u":
            # Unknown gender — check if any gendered version exists
            for g in ("m", "w", "x"):
                if (sport, medal_type, g, event_key, entry_type) in seen_keys:
                    return True
        else:
            # Gendered — check if unknown-gender version exists
            if (sport, medal_type, "u", event_key, entry_type) in seen_keys:
                return True
        return False

    def _add_key(key):
        """Add key and its gender-neutral variant to seen_keys."""
        seen_keys.add(key)

    # Source 1: DDG News search (fastest — finds live medal tables)
    for comp_name in competition_names:
        ddg_medals = _scrape_all_medals_ddg_news(comp_name)
        for m in ddg_medals:
            m["competition"] = comp_name
            key = _dedup_key_all(m)
            if not _key_exists(key):
                _add_key(key)
                all_medals.append(m)

    # Source 2: Wikipedia Medalists section (reliable, has sport labels)
    wiki_targets = []
    for comp_name in competition_names:
        # Build Wikipedia URL from competition name
        wiki_slug = comp_name.replace(" ", "_")
        url = f"https://en.wikipedia.org/wiki/India_at_the_{wiki_slug}"
        wiki_targets.append((url, comp_name))

    for url, comp_name in wiki_targets:
        medals = _scrape_medalists_section(url, HEADERS, sport_filter=None)
        for m in medals:
            m["competition"] = comp_name
            m.setdefault("source", "wikipedia")
            key = _dedup_key_all(m)
            if not _key_exists(key):
                _add_key(key)
                all_medals.append(m)
            elif m.get("sport"):
                # Wikipedia has sport labels — backfill onto DDG entries missing sport
                for existing in all_medals:
                    ekey = _dedup_key_all(existing)
                    if ekey[0] == key[0] and ekey[2:] == key[2:] and not existing.get("sport"):
                        existing["sport"] = m["sport"]
                        break

    # Source 3: IOA official page — cross-check total counts
    official_tally = _scrape_ioa_tally()

    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "medals": all_medals,
        "official_tally": official_tally,
    }


def _scrape_ioa_tally() -> dict:
    """Scrape Indian Olympic Association's official Asian Games page for
    the overall medal tally (Gold/Silver/Bronze/Total).

    URL: https://olympic.ind.in/asian-games-2026/
    Used as a cross-check against our scraped medal data.
    """
    url = "https://olympic.ind.in/asian-games-2026/"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=10)
        if resp.status_code != 200:
            return {}
        soup = BeautifulSoup(resp.text, "html.parser")

        # Find the medal table — look for India's row
        for table in soup.find_all("table"):
            for row in table.find_all("tr"):
                cells = row.find_all(["td", "th"])
                cell_texts = [c.get_text(strip=True).lower() for c in cells]
                if any("india" in t for t in cell_texts):
                    # Extract numbers from the row
                    nums = []
                    for c in cells:
                        text = c.get_text(strip=True)
                        if text.isdigit():
                            nums.append(int(text))
                    # Expected: [rank, gold, silver, bronze, total] or subset
                    if len(nums) >= 4:
                        return {
                            "gold": nums[-4] if len(nums) >= 5 else nums[0],
                            "silver": nums[-3] if len(nums) >= 5 else nums[1],
                            "bronze": nums[-2] if len(nums) >= 5 else nums[2],
                            "total": nums[-1],
                            "source": "olympic.ind.in",
                        }
        return {}
    except requests.exceptions.RequestException:
        return {}


def _scrape_all_medals_ddg_news(competition_name: str) -> list:
    """Find and scrape a sports news page with ALL Indian medal data.

    Same two-step approach as _scrape_medals_ddg_news but with a broader
    query (not athletics-specific). Sports news sites like khelnow.com
    maintain live-updated medal tables covering all sports.
    """
    query = f"{competition_name} India medal winners results"
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Collect candidate URLs — prefer India medal summary pages
    candidate_urls = []
    for link in soup.find_all("a", class_="result__a")[:8]:
        href = link.get("href", "")
        title = link.get_text(strip=True).lower()
        if "medal" in title and ("india" in title or "winner" in title):
            candidate_urls.append(href)

    # Scrape candidate pages for structured medal tables
    for url in candidate_urls[:5]:
        medals = _scrape_all_sport_medal_page(url)
        if not medals:
            continue
        # Sanity check: if >80% are same medal type and >10 entries, likely a parsing error
        if len(medals) > 10:
            from collections import Counter
            mc = Counter(m["medal"] for m in medals)
            most_common_count = mc.most_common(1)[0][1]
            if most_common_count / len(medals) > 0.8:
                continue  # Skip this page, try next candidate
        return medals

    return []


def _scrape_all_sport_medal_page(url: str) -> list:
    """Scrape a sports news page for all-sport Indian medal data.

    Handles pages like khelnow.com that have 3 sequential tables
    (Gold, Silver, Bronze) under a 'medal winners' heading, with
    columns: Sl No. | Player(s) | Sport | Event.
    Also falls back to _scrape_news_medal_page for other formats.
    """
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }, timeout=10)
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    if len(resp.text) < 5000:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategy: Find 'medal winners' heading, then parse sequential tables as Gold/Silver/Bronze
    medal_heading = None
    for h in soup.find_all(["h2", "h3"]):
        text = h.get_text(strip=True).lower()
        if "medal winner" in text or "medal list" in text or "medallists" in text:
            medal_heading = h
            break

    if not medal_heading:
        # Fallback to athletics-style scraper
        medals = _scrape_news_medal_page(url)
        for m in medals:
            m["source"] = "news"
        return medals

    # Collect tables after the medal heading until next same-level heading
    # Tables may not be direct siblings (nested in divs), so use find_all_next()
    # Look for h3/h4 headings (Gold/Silver/Bronze) that label each table
    medal_tables = []  # list of (medal_type, table_element)
    current_medal_type = None
    table_index = 0
    position_types = ["Gold", "Silver", "Bronze"]
    heading_level = int(medal_heading.name[1])  # 2 for h2, 3 for h3

    for el in medal_heading.find_all_next():
        if el.name in ["h1", "h2", "h3", "h4"]:
            el_level = int(el.name[1])
            if el_level <= heading_level:
                # Same or higher level heading — stop (different section)
                break
            # Sub-heading — check for medal type labels
            label = el.get_text(strip=True).lower()
            if "gold" in label:
                current_medal_type = "Gold"
            elif "silver" in label:
                current_medal_type = "Silver"
            elif "bronze" in label:
                current_medal_type = "Bronze"
        if el.name == "table":
            # Skip tally tables (Gold | Silver | Bronze | Total columns)
            header_cells = el.find("tr")
            if header_cells:
                header_text = header_cells.get_text(strip=True).lower()
                if "total" in header_text and "gold" in header_text:
                    continue
            # Use h4-based type if available, else fall back to position
            medal_type = current_medal_type or (position_types[table_index] if table_index < 3 else None)
            if medal_type:
                medal_tables.append((medal_type, el))
                table_index += 1
                current_medal_type = None  # reset for next table

    if not medal_tables:
        return []

    all_medals = []

    for medal_type, table in medal_tables:
        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Parse header to find column indices
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True).lower() for c in header_cells]

        player_col = None
        sport_col = None
        event_col = None
        medal_col = None  # Some tables have their own Medal column
        for j, h in enumerate(header_texts):
            if "player" in h or "athlete" in h or "name" in h:
                player_col = j
            if "sport" in h:
                sport_col = j
            if "event" in h or "discipline" in h:
                event_col = j
            if h == "medal" or h == "medal type":
                medal_col = j

        if player_col is None:
            # Try: Sl No | Player | Sport | Event
            if len(header_texts) >= 3 and ("sl" in header_texts[0] or "no" in header_texts[0] or "#" in header_texts[0]):
                player_col = 1
                if len(header_texts) >= 4:
                    sport_col = 2
                    event_col = 3
            else:
                continue

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= player_col:
                continue

            athlete = cells[player_col].get_text(strip=True)
            sport = cells[sport_col].get_text(strip=True) if sport_col is not None and sport_col < len(cells) else ""
            event = cells[event_col].get_text(strip=True) if event_col is not None and event_col < len(cells) else ""

            # Use per-row medal type from column if available, else use section type
            row_medal_type = medal_type
            if medal_col is not None and medal_col < len(cells):
                cell_text = cells[medal_col].get_text(strip=True).lower()
                if "gold" in cell_text:
                    row_medal_type = "Gold"
                elif "silver" in cell_text:
                    row_medal_type = "Silver"
                elif "bronze" in cell_text:
                    row_medal_type = "Bronze"

            if not athlete or len(athlete) < 2:
                continue

            all_medals.append({
                "medal": row_medal_type,
                "athlete": athlete,
                "event": event,
                "sport": sport,
                "date": "",
                "source": "news",
            })

    return all_medals


def _scrape_medals_ddg_news(competition_name: str) -> list:
    """Find and scrape a sports news page with structured athletics medal data.

    Two-step approach:
    1. Search DuckDuckGo for an athletics-specific medal summary page
    2. Scrape that page's tables for structured Gold/Silver/Bronze data

    Sports sites like khelnow.com, olympics.com, etc. maintain live-updated
    medal tables that are faster than Wikipedia.
    """
    # Step 1: Find athletics medal results page via DDG
    # Strip year prefix for cleaner search
    query = f"{competition_name} India athletics medal winners results"
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Collect candidate URLs — prefer sports news sites with structured data
    candidate_urls = []
    for link in soup.find_all("a", class_="result__a")[:8]:
        href = link.get("href", "")
        title = link.get_text(strip=True).lower()
        # Prioritize athletics-specific results pages
        if "athletics" in title or "athletics" in href:
            candidate_urls.insert(0, href)
        elif "medal" in title and ("india" in title or "winner" in title):
            candidate_urls.append(href)

    # Step 2: Scrape candidate pages for structured medal tables
    for url in candidate_urls[:3]:
        medals = _scrape_news_medal_page(url)
        if medals:
            return medals

    # Fallback: try to extract medals from DDG snippets directly
    return _extract_medals_from_snippets(soup)


def _scrape_news_medal_page(url: str) -> list:
    """Scrape a sports news page for structured medal tables.

    Looks for tables preceded by Gold/Silver/Bronze headings with
    Player(s) and Event columns.
    """
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }, timeout=10)
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    # Skip tiny responses (JS-only pages)
    if len(resp.text) < 5000:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    if not tables:
        return []

    medals = []
    medal_map = {"gold": "Gold", "silver": "Silver", "bronze": "Bronze"}

    for table in tables:
        # Determine medal type from heading before this table
        medal_type = None
        for prev in [table.find_previous(tag) for tag in ["h2", "h3", "h4", "strong", "p"]]:
            if prev:
                heading_text = prev.get_text(strip=True).lower()
                for word, label in medal_map.items():
                    if word in heading_text and "tally" not in heading_text:
                        medal_type = label
                        break
            if medal_type:
                break

        if not medal_type:
            continue

        rows = table.find_all("tr")
        if len(rows) < 2:
            continue

        # Find player and event columns
        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True).lower() for c in header_cells]

        player_col = None
        event_col = None
        for i, h in enumerate(header_texts):
            if "player" in h or "athlete" in h or "name" in h:
                player_col = i
            if "event" in h or "discipline" in h:
                event_col = i

        # Validate this looks like a medal table, not a schedule/tally
        # Skip tables with headers like "Gold | Silver | Bronze | Total" (tally tables)
        # or "Day | Date | Session" (schedule tables)
        skip_headers = {"total", "date", "session", "day", "programme", "time"}
        if skip_headers & set(header_texts):
            continue

        if player_col is None:
            # Try column 1 as player, 2 as event (common pattern: Sl No | Player | Event)
            if len(header_texts) >= 3 and ("sl" in header_texts[0] or "no" in header_texts[0] or "#" in header_texts[0]):
                player_col = 1
                event_col = 2
            else:
                continue

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(player_col, event_col or 0):
                continue

            athlete = cells[player_col].get_text(strip=True)
            event = cells[event_col].get_text(strip=True) if event_col is not None and event_col < len(cells) else ""

            # Skip entries that don't look like athlete names
            if not athlete or len(athlete) < 3:
                continue
            if athlete.lower().startswith("day ") or athlete[0].isdigit():
                continue
            # Skip if event looks like a date/time
            if event and re.match(r"^\d{1,2}\s", event):
                continue

            medals.append({
                "medal": medal_type,
                "athlete": athlete,
                "event": event,
                "date": "",
                "source": "news",
            })

    return medals


def _extract_medals_from_snippets(soup) -> list:
    """Extract medal info from DuckDuckGo search snippets as a last resort.

    Parses headlines and snippets for patterns like:
    "Yashvir Singh wins silver in javelin"
    """
    texts = []
    for title in soup.find_all("a", class_="result__a"):
        texts.append(title.get_text(strip=True))
    for snippet in soup.find_all("a", class_="result__snippet"):
        texts.append(snippet.get_text(strip=True))

    medals = []
    seen = set()
    medal_words = {"gold": "Gold", "silver": "Silver", "bronze": "Bronze"}

    patterns = [
        # "Name wins/won/bags gold/silver/bronze in event"
        r"([A-Z][a-z]+ [A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+(?:wins?|won|bags?|clinche?s?|grab?s?|claim?s?|secure?s?)\s+(gold|silver|bronze)\s+(?:medal\s+)?in\s+(.+?)(?:\s+at\s|\s+final|\.|,|$)",
        # "gold/silver/bronze for Name in event"
        r"(gold|silver|bronze)\s+(?:medal\s+)?for\s+([A-Z][a-z]+ [A-Z][a-z]+(?:\s+[A-Z][a-z]+)?)\s+in\s+(.+?)(?:\s+at\s|\.|,|$)",
    ]

    for text in texts:
        if "india" not in text.lower() and "indian" not in text.lower():
            continue

        for pattern in patterns:
            for match in re.finditer(pattern, text, re.IGNORECASE):
                groups = match.groups()
                if len(groups) == 3:
                    if groups[0].lower() in medal_words:
                        # Pattern 2: medal, name, event
                        medal_type = medal_words[groups[0].lower()]
                        athlete = groups[1].strip()
                        event = groups[2].strip()
                    else:
                        # Pattern 1: name, medal, event
                        athlete = groups[0].strip()
                        medal_type = medal_words.get(groups[1].lower(), groups[1])
                        event = groups[2].strip()

                    event = re.sub(r"\s+at\s+.*$", "", event).strip(" .,;:")
                    if len(event) > 50:
                        event = event[:50]
                    if len(athlete) < 4 or len(event) < 3:
                        continue

                    key = (athlete.lower(), event.lower())
                    if key in seen:
                        continue
                    seen.add(key)

                    medals.append({
                        "medal": medal_type,
                        "athlete": athlete,
                        "event": event,
                        "date": "",
                        "source": "news",
                    })

    return medals


def _scrape_medals_world_athletics(competition_name: str) -> list:
    """Try to get medal results from the World Athletics website.

    Only works for World Athletics-organized events (World Championships,
    Diamond League). Returns empty list if the site blocks us or returns
    JS-only content.
    """
    # Only try for WA-organized events
    comp_lower = competition_name.lower()
    if "world" not in comp_lower and "diamond" not in comp_lower:
        return []

    # Map competition to World Athletics URL slug
    year = datetime.now().year
    if "indoor" in comp_lower:
        slug = f"world-athletics-indoor-championships/world-athletics-indoor-championships-{year}"
    elif "diamond" in comp_lower:
        # Diamond League has per-meet results, skip for now
        return []
    else:
        slug = f"world-athletics-championships/budapest{year}"

    url = f"https://worldathletics.org/competitions/{slug}/results"
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
            "Accept": "text/html",
        }, timeout=10)
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    # World Athletics pages are mostly JS-rendered. Check if we got
    # useful HTML content — if not, return empty gracefully.
    soup = BeautifulSoup(resp.text, "html.parser")

    medals = []

    # Look for result tables with Indian athletes
    for table in soup.find_all("table"):
        rows = table.find_all("tr")
        for row in rows:
            cells = row.find_all(["td", "th"])
            row_text = row.get_text(strip=True).lower()

            # Check if row mentions India/IND
            if "india" not in row_text and "ind" not in row_text:
                continue

            # Check if this is a podium position (1st, 2nd, 3rd)
            for cell in cells:
                text = cell.get_text(strip=True)
                if text in ("1", "2", "3"):
                    rank = int(text)
                    medal_type = {1: "Gold", 2: "Silver", 3: "Bronze"}[rank]
                    # Try to extract athlete name from the row
                    name_parts = []
                    for c in cells:
                        ct = c.get_text(strip=True)
                        if ct and not ct.isdigit() and ct not in ("IND", "India") and ":" not in ct and "." not in ct:
                            name_parts.append(ct)
                    if name_parts:
                        medals.append({
                            "medal": medal_type,
                            "athlete": name_parts[0],
                            "event": "",
                            "date": "",
                            "source": "world_athletics",
                        })
                    break

    return medals


def _scrape_medalists_section(url: str, headers: dict, sport_filter: str = "athletics") -> list:
    """Scrape the Medalists section. Pass sport_filter=None for all sports."""
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    soup = BeautifulSoup(response.text, "html.parser")
    medals = []

    # Find the Medalists heading, then get tables until next h2
    in_medalists = False
    for element in soup.find_all(["h2", "table"]):
        if element.name == "h2":
            text = element.get_text(strip=True).replace("[edit]", "").strip()
            if text == "Medalists":
                in_medalists = True
                continue
            elif in_medalists:
                break
        elif element.name == "table" and in_medalists:
            classes = element.get("class") or []
            if "wikitable" not in classes:
                continue

            rows = element.find_all("tr")
            if len(rows) < 2:
                continue

            # Check if this is the detailed medalists table
            # Expected columns: Medal | Athlete | Sport | Event | Date
            header_cells = rows[0].find_all(["th", "td"])
            header_texts = [c.get_text(strip=True).lower() for c in header_cells]

            if "medal" not in header_texts or "sport" not in header_texts:
                continue

            medal_col = header_texts.index("medal")
            sport_col = header_texts.index("sport")
            athlete_col = header_texts.index("athlete") if "athlete" in header_texts else 1
            event_col = header_texts.index("event") if "event" in header_texts else 3
            date_col = header_texts.index("date") if "date" in header_texts else -1

            for row in rows[1:]:
                cells = row.find_all(["td", "th"])
                if len(cells) <= max(medal_col, sport_col, athlete_col, event_col):
                    continue

                sport = cells[sport_col].get_text(strip=True)
                if sport_filter and sport.lower() != sport_filter.lower():
                    continue

                medal_type = cells[medal_col].get_text(strip=True)
                athlete_name = _clean_medal_athlete(cells[athlete_col])
                event_name = cells[event_col].get_text(strip=True)
                date_text = cells[date_col].get_text(strip=True) if date_col >= 0 and date_col < len(cells) else ""

                entry = {
                    "medal": medal_type,
                    "athlete": athlete_name,
                    "event": event_name,
                    "date": date_text,
                }
                if not sport_filter:
                    entry["sport"] = sport
                medals.append(entry)

    return medals


def _extract_athlete_names(cell) -> str:
    """Extract athlete name(s) from a table cell, handling relay teams.

    Wikipedia relay cells have multiple <a> tags and <br> separators.
    get_text(strip=True) concatenates them all. Instead, extract individual
    names from links and join with ', '.
    """
    links = cell.find_all("a")
    if links:
        names = []
        reserves = []

        # Check if cell text contains "Reserve" — need to split names accordingly
        full_text = cell.get_text()
        has_reserves = "Reserve" in full_text
        reserve_pos = full_text.find("Reserve") if has_reserves else len(full_text)

        running_pos = 0
        for a in links:
            name = _clean_text(a.get_text(strip=True))
            if not name or len(name) < 2:
                continue
            if has_reserves:
                pos = full_text.find(name, running_pos)
                if pos >= 0 and pos > reserve_pos:
                    reserves.append(name)
                else:
                    names.append(name)
                if pos >= 0:
                    running_pos = pos + len(name)
            else:
                names.append(name)

        if len(names) <= 1 and not reserves:
            # Individual event — single name
            return _clean_text(names[0]) if names else _clean_text(cell.get_text(strip=True))

        # Relay team
        result = ", ".join(names)
        if reserves:
            result += f" (Reserves: {', '.join(reserves)})"
        return result

    # No links — fallback to raw text, but try to split on <br> tags
    parts = []
    for content in cell.children:
        if hasattr(content, "name") and content.name == "br":
            continue
        text = content.get_text(strip=True) if hasattr(content, "get_text") else str(content).strip()
        text = _clean_text(text)
        if text and len(text) > 1:
            parts.append(text)

    if len(parts) > 1:
        return ", ".join(parts)
    return _clean_text(cell.get_text(strip=True))


def _clean_medal_athlete(cell) -> str:
    """Extract athlete name(s) from a medalist table cell.

    Relay events list multiple athletes concatenated. Uses the same
    extraction logic as competition table cells.
    """
    return _extract_athlete_names(cell)


def get_current_competitions() -> dict:
    """Get current and upcoming athletics competitions featuring Indian athletes.

    Returns:
        A dictionary with competitions grouped by event, showing Indian athletes
        and their results.
    """
    year = datetime.now().year
    competitions = []

    # Pages to check, in priority order
    targets = [
        (f"https://en.wikipedia.org/wiki/India_at_the_{year}_Asian_Games", f"{year} Asian Games"),
        (f"https://en.wikipedia.org/wiki/India_at_the_{year}_World_Athletics_Championships", f"{year} World Athletics Championships"),
    ]

    for url, label in targets:
        result = _scrape_india_at_competition(url, label, HEADERS)
        if result:
            competitions.append(result)

    if not competitions:
        return {
            "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
            "message": "No current athletics competition data found for Indian athletes.",
            "competitions": [],
        }

    return {
        "checked_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "competitions": competitions,
    }


def get_upcoming_competitions() -> dict:
    """Get upcoming athletics competitions in the next 12 months.

    Checks Wikipedia for event pages directly (not 'India at...').
    Cross-references disciplines with known Indian athletes from recent
    competitions to show potential Indian participation.

    Returns:
        A dictionary with upcoming competitions, dates, locations, disciplines,
        and potential Indian athletes.
    """
    now = datetime.now()
    year = now.year
    next_year = year + 1
    upcoming = []

    # Step 1: Build Indian athlete roster from current/recent competitions
    # Maps discipline -> list of athlete names
    indian_roster = _build_indian_roster(year)

    # Step 2: Check major event pages directly
    event_targets = [
        (f"{year}_Asian_Games", f"{year} Asian Games"),
        (f"{year}_World_Athletics_Championships", f"{year} World Athletics Championships"),
        (f"{year}_Asian_Athletics_Championships", f"{year} Asian Athletics Championships"),
        (f"{year}_Commonwealth_Games", f"{year} Commonwealth Games"),
        (f"{year}_World_Athletics_Indoor_Championships", f"{year} World Indoor Championships"),
        (f"{year}_Summer_Olympics", f"{year} Summer Olympics"),
        (f"{next_year}_World_Athletics_Championships", f"{next_year} World Athletics Championships"),
        (f"{next_year}_Asian_Athletics_Championships", f"{next_year} Asian Athletics Championships"),
        (f"{next_year}_Commonwealth_Games", f"{next_year} Commonwealth Games"),
        (f"{next_year}_World_Athletics_Indoor_Championships", f"{next_year} World Indoor Championships"),
        (f"{next_year}_Asian_Games", f"{next_year} Asian Games"),
        (f"{next_year}_Summer_Olympics", f"{next_year} Summer Olympics"),
        (f"{next_year}_Diamond_League", f"{next_year} Diamond League"),
    ]

    for page_title, label in event_targets:
        result = _scrape_event_page(page_title, label, now, indian_roster)
        if result:
            upcoming.append(result)

    # Step 3: Check Diamond League for current year
    dl = _scrape_diamond_league(year, now)
    if dl:
        upcoming.append(dl)

    # Step 4: DDG fallback for Diamond League if Wikipedia had nothing
    seen_names = {u["competition"].lower() for u in upcoming}
    if not any("diamond league" in name for name in seen_names):
        # Try current year, then next year
        for y in [year, next_year]:
            dl_ddg = _scrape_upcoming_ddg("Diamond League", y, now)
            if dl_ddg and dl_ddg["competition"].lower() not in seen_names:
                upcoming.append(dl_ddg)
                seen_names.add(dl_ddg["competition"].lower())
                break

    # Step 5: DDG search for other upcoming international athletics events
    news_events = _scrape_upcoming_events_news(year, now)
    for ev in news_events:
        if ev["competition"].lower() not in seen_names:
            upcoming.append(ev)
            seen_names.add(ev["competition"].lower())

    # Sort by earliest date (chronological order)
    upcoming.sort(key=lambda u: _extract_sort_date(u.get("dates", ""), now))

    return {
        "checked_at": now.strftime("%Y-%m-%d %H:%M"),
        "upcoming": upcoming,
    }


def _extract_sort_date(dates_str: str, now: datetime) -> datetime:
    """Parse a dates string and return the earliest date for sorting.

    Handles formats like:
    - '19 September 2027'
    - '19 September – 4 October 2026'
    - 'Season: 7 May 2027 onwards'
    - 'Dates TBA'
    """
    if not dates_str or dates_str == "Dates TBA":
        return datetime(9999, 1, 1)  # Unknown dates sort last

    # Strip prefixes like "Season: "
    cleaned = re.sub(r"^[A-Za-z]+:\s*", "", dates_str)
    # Strip suffixes like " onwards"
    cleaned = re.sub(r"\s+onwards.*$", "", cleaned)
    # Take the first date in a range: "19 September – 4 October 2026" -> "19 September 2026"
    # If no year in the first part, borrow from the second part
    range_match = re.match(r"(\d{1,2}\s+\w+)\s*[–-]\s*(\d{1,2}\s+\w+\s+\d{4})", cleaned)
    if range_match:
        start_part = range_match.group(1)
        end_part = range_match.group(2)
        # Extract year from end part
        year_match = re.search(r"(\d{4})", end_part)
        if year_match:
            cleaned = f"{start_part} {year_match.group(1)}"

    for fmt in ["%d %B %Y", "%B %d, %Y", "%B %d %Y", "%d %B"]:
        try:
            dt = datetime.strptime(cleaned.strip(), fmt)
            if dt.year == 1900:
                dt = dt.replace(year=now.year)
            return dt
        except ValueError:
            continue

    return datetime(9999, 1, 1)


def _build_indian_roster(year: int) -> dict:
    """Build a mapping of discipline -> Indian athlete names.

    Scrapes recent 'India at...' competition pages to get active athletes
    and their events. Returns {discipline_lower: [athlete_names]}.
    """
    roster = {}

    targets = [
        f"https://en.wikipedia.org/wiki/India_at_the_{year}_Asian_Games",
        f"https://en.wikipedia.org/wiki/India_at_the_{year}_World_Athletics_Championships",
        f"https://en.wikipedia.org/wiki/India_at_the_{year - 1}_Asian_Athletics_Championships",
        f"https://en.wikipedia.org/wiki/India_at_the_{year - 1}_World_Athletics_Championships",
    ]

    for url in targets:
        try:
            response = requests.get(url, headers=HEADERS, timeout=10)
            if response.status_code != 200:
                continue
        except requests.exceptions.RequestException:
            continue

        soup = BeautifulSoup(response.text, "html.parser")

        # Find Athletics section tables
        in_athletics = False
        for element in soup.find_all(["h2", "table"]):
            if element.name == "h2":
                heading = element.get_text(strip=True).replace("[edit]", "").strip()
                if heading == "Athletics":
                    in_athletics = True
                    continue
                elif in_athletics:
                    break
            elif element.name == "table" and in_athletics:
                classes = element.get("class") or []
                if "wikitable" in classes:
                    events = {}
                    _parse_athletics_table(element, events)
                    for event_name, athletes in events.items():
                        key = _normalize_discipline(event_name)
                        if key not in roster:
                            roster[key] = []
                        for a in athletes:
                            if a["name"] not in roster[key]:
                                roster[key].append(a["name"])

    return roster


def _normalize_discipline(event_name: str) -> str:
    """Normalize an event name for matching across competitions.

    '100m' / '100 m' / 'Men's 100 metres' -> '100m'
    """
    name = event_name.lower().strip()
    # Normalize smart quotes first (before prefix stripping)
    name = name.replace("\u2019", "'")
    # Remove gendered prefixes
    name = re.sub(r"^(men'?s?|women'?s?|mixed)\s+", "", name)
    # Normalize spacing around distances
    name = re.sub(r"(\d+)\s*m\b", r"\1m", name)
    # Normalize common variations
    name = name.replace("metres", "m").replace("meters", "m")
    name = name.replace("kilometre", "km").replace("kilometer", "km")
    return name.strip()


def _scrape_event_page(page_title: str, label: str, now: datetime,
                       indian_roster: dict) -> dict:
    """Scrape a competition's Wikipedia page for dates and disciplines.

    Unlike _scrape_upcoming_event, this checks the EVENT page (not 'India at...').
    Cross-references disciplines with indian_roster to show potential athletes.
    """
    url = f"https://en.wikipedia.org/wiki/{page_title}"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None
    except requests.exceptions.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract dates and location
    dates_str = ""
    location = ""
    start_date = None
    end_date = None

    for p in soup.find_all("p")[:5]:
        text = p.get_text(strip=True)
        if len(text) > 50:
            # Date range
            date_match = re.search(
                r"(\d{1,2}\s+\w+)\s+(?:to|–|-)\s+(\d{1,2}\s+\w+\s+\d{4})", text
            )
            if date_match:
                dates_str = f"{date_match.group(1)} – {date_match.group(2)}"
                try:
                    end_date = datetime.strptime(date_match.group(2), "%d %B %Y")
                    start_date = datetime.strptime(
                        f"{date_match.group(1)} {end_date.year}", "%d %B %Y"
                    )
                except ValueError:
                    pass

            # Single date
            if not date_match:
                single_match = re.search(r"(\d{1,2}\s+\w+\s+\d{4})", text)
                if single_match:
                    dates_str = single_match.group(1)
                    try:
                        start_date = datetime.strptime(single_match.group(1), "%d %B %Y")
                        end_date = start_date
                    except ValueError:
                        pass

            # Location — try multiple patterns
            for pattern in [r"in\s*([A-Z][^.]+?(?:,\s*[A-Z][a-z]+)?)\s+from",
                            r"in\s*([A-Z][^.]+?(?:,\s*[A-Z][a-z]+)?)\s+on",
                            r"held in\s*([A-Z][^.]+?(?:,\s*[A-Z][a-z]+)?)"]:
                loc_match = re.search(pattern, text)
                if loc_match:
                    location = loc_match.group(1).strip()
                    break
            break

    # Filter: only future events
    if start_date and start_date <= now:
        return None
    if end_date:
        if (end_date - now).days < -1:
            return None
        if (end_date - now).days > 365:
            return None
    if not dates_str:
        dates_str = "Dates TBA"

    # Match disciplines with Indian roster
    event_list = []
    if indian_roster:
        # Standard athletics disciplines
        disciplines = [
            "100m", "200m", "400m", "800m", "1500m", "5000m", "10000m",
            "100m hurdles", "110m hurdles", "400m hurdles",
            "3000m steeplechase", "marathon", "20km walk",
            "high jump", "long jump", "triple jump", "pole vault",
            "shot put", "discus throw", "hammer throw", "javelin throw",
            "decathlon", "heptathlon",
            "4 x 100m relay", "4 x 400m relay",
        ]

        for disc in disciplines:
            disc_key = _normalize_discipline(disc)
            # Find matching athletes across all roster keys
            matched_athletes = []
            for roster_key, athletes in indian_roster.items():
                if disc_key in roster_key or roster_key in disc_key:
                    for a in athletes:
                        if a not in matched_athletes:
                            matched_athletes.append(a)

            if matched_athletes:
                event_list.append({
                    "event": disc.title(),
                    "athletes": [{"name": a} for a in matched_athletes],
                })

    result = {
        "competition": label,
        "url": url,
        "dates": dates_str,
        "participation": "potential" if event_list else "pending",
    }
    if location:
        result["location"] = location
    if event_list:
        result["events"] = event_list

    return result


def _scrape_upcoming_ddg(event_name: str, year: int, now: datetime) -> dict:
    """Search DDG for an upcoming event schedule when Wikipedia has no page.

    Two-step approach:
    1. Search DDG for schedule pages
    2. Scrape found pages for structured date/venue lists
    3. Fall back to extracting from DDG snippets

    Returns a dict in the same format as _scrape_diamond_league() or None.
    """
    query = f"{event_name} {year} schedule dates venues"
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return None
    except requests.exceptions.RequestException:
        return None

    soup = BeautifulSoup(resp.text, "html.parser")

    # Step 1: Try scraping candidate pages for structured schedule lists
    candidate_urls = []
    for link in soup.find_all("a", class_="result__a")[:6]:
        href = link.get("href", "")
        title = link.get_text(strip=True).lower()
        if "schedule" in title or "dates" in title or "calendar" in title:
            candidate_urls.append(href)

    for url in candidate_urls[:3]:
        meets = _scrape_schedule_list_page(url, year, now)
        if meets:
            return {
                "competition": f"{year} {event_name}",
                "dates": f"Season: {meets[0]['athletes'][0]['name'].split('—')[0].strip()} onwards",
                "events": meets,
                "source": "web",
            }

    # Step 2: Extract from DDG snippets as fallback
    snippets = []
    for el in soup.find_all("a", class_="result__snippet"):
        snippets.append(el.get_text(strip=True))

    if not snippets:
        return None

    combined = " ".join(snippets)
    meets = _extract_meets_from_text(combined, year, now)

    if not meets:
        return None

    return {
        "competition": f"{year} {event_name}",
        "dates": f"Season: {meets[0]['athletes'][0]['name'].split('—')[0].strip()} onwards",
        "events": meets,
        "source": "web",
    }


def _scrape_schedule_list_page(url: str, year: int, now: datetime) -> list:
    """Scrape a page for schedule data in lists or paragraphs.

    Handles sites like 3s.info that use <ul>/<ol> or <p> tags with
    'Day Month — City, Country' format.
    """
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }, timeout=10)
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    if len(resp.text) < 3000:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Strategy 1: Find heading mentioning the year + schedule, then parse nearby lists
    target_heading = None
    for tag in ["h2", "h3", "h4"]:
        for el in soup.find_all(tag):
            text = el.get_text(strip=True).lower()
            if str(year) in text and any(kw in text for kw in ["date", "schedule", "venue", "calendar", "diamond", "league"]):
                target_heading = el
                break
        if target_heading:
            break

    if target_heading:
        # Get text from siblings after the heading
        schedule_text = ""
        for sib in target_heading.find_next_siblings()[:15]:
            if sib.name and sib.name.startswith("h"):
                break
            schedule_text += " " + sib.get_text(strip=True)

        meets = _extract_meets_from_text(schedule_text, year, now)
        if meets:
            return meets

    # Strategy 2: Search all <ul>/<ol> elements for date patterns
    for lst in soup.find_all(["ul", "ol"]):
        list_text = lst.get_text(strip=True)
        # Must contain multiple date-like entries
        date_count = len(re.findall(r"\d{1,2}\s+(?:January|February|March|April|May|June|July|August|September|October|November|December)", list_text, re.IGNORECASE))
        if date_count >= 3:
            meets = _extract_meets_from_text(list_text, year, now)
            if meets:
                return meets

    return []


def _extract_meets_from_text(text: str, year: int, now: datetime) -> list:
    """Extract meet dates and cities from free-form text.

    Handles patterns like:
    - '7 May — Doha, Qatar'
    - '14–15 August — Silesia, Poland'
    - 'May 8, 2026 - Doha Meeting (Qatar)'
    """
    meets = []

    # Pattern 1: "Day Month — City, Country" (3s.info style)
    # City/country ends at next digit (next date entry) or end of string
    for m in re.finditer(
        r"(\d{1,2}(?:[–-]\d{1,2})?\s+(?:January|February|March|April|May|June|July|August|September|October|November|December))"
        r"\s*[-–—]+\s*"
        r"([A-Z][a-zA-Z\s,]+?)(?=\d|\Z)",
        text, re.IGNORECASE
    ):
        date_str = m.group(1).strip()
        city = m.group(2).strip().rstrip(",. ")
        meet_date = _parse_snippet_date(f"{date_str} {year}", year)
        if meet_date and 0 <= (meet_date - now).days <= 365:
            meets.append({
                "event": city,
                "athletes": [{"name": f"{date_str} {year}"}],
            })

    if meets:
        return meets

    # Pattern 2: "Month Day, Year - Meet Name (City)"
    for m in re.finditer(
        r"(\w+ \d{1,2},?\s*\d{4})\s*[-–—]\s*(.+?)\s*\(([^)]+)\)", text
    ):
        date_str = m.group(1).strip()
        meet_name = m.group(2).strip()
        city = m.group(3).strip()
        meet_date = _parse_snippet_date(date_str, year)
        if meet_date and 0 <= (meet_date - now).days <= 365:
            meets.append({
                "event": f"{meet_name} ({city})",
                "athletes": [{"name": date_str}],
            })

    return meets


def _parse_snippet_date(date_str: str, fallback_year: int) -> datetime:
    """Try to parse a date string from a DDG snippet. Returns datetime or None."""
    date_str = date_str.strip().rstrip(",")
    # Remove day ranges: "3-4 July 2026" -> "4 July 2026"
    date_str = re.sub(r"^\d+[–-]", "", date_str).strip()

    formats = [
        "%B %d, %Y",      # "May 8, 2026"
        "%B %d %Y",       # "May 8 2026"
        "%d %B %Y",       # "8 May 2026"
        "%d %B",          # "8 May" (no year)
        "%B %d",          # "May 8" (no year)
    ]
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            if dt.year == 1900:  # No year in format
                dt = dt.replace(year=fallback_year)
            return dt
        except ValueError:
            continue
    return None


def _scrape_upcoming_events_news(year: int, now: datetime) -> list:
    """Search DDG for upcoming international athletics events with Indian athletes.

    Returns a list of competition dicts (same format as _scrape_event_page output).
    """
    query = f"upcoming international athletics events {year} {year + 1} schedule"
    try:
        resp = requests.post(
            "https://html.duckduckgo.com/html/",
            data={"q": query},
            headers=HEADERS,
            timeout=10,
        )
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")

    # Collect candidate URLs for schedule pages
    candidate_urls = []
    for link in soup.find_all("a", class_="result__a")[:8]:
        href = link.get("href", "")
        title = link.get_text(strip=True).lower()
        if any(kw in title for kw in ["schedule", "calendar", "upcoming", "events"]):
            if any(kw in title for kw in ["athletics", "track", "field"]):
                candidate_urls.insert(0, href)
            elif "sport" in title or str(year) in title:
                candidate_urls.append(href)

    results = []
    for url in candidate_urls[:3]:
        events = _scrape_schedule_page(url, now)
        results.extend(events)

    return results


def _scrape_schedule_page(url: str, now: datetime) -> list:
    """Scrape a schedule/calendar page for upcoming athletics events.

    Looks for tables with Date/Event/Location columns.
    """
    try:
        resp = requests.get(url, headers={
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
        }, timeout=10)
        if resp.status_code != 200:
            return []
    except requests.exceptions.RequestException:
        return []

    if len(resp.text) < 3000:
        return []

    soup = BeautifulSoup(resp.text, "html.parser")
    tables = soup.find_all("table")
    results = []

    for table in tables:
        rows = table.find_all("tr")
        if len(rows) < 3:
            continue

        header_cells = rows[0].find_all(["th", "td"])
        header_texts = [c.get_text(strip=True).lower() for c in header_cells]

        date_col = None
        event_col = None
        location_col = None
        for i, h in enumerate(header_texts):
            if "date" in h or "when" in h:
                date_col = i
            if "event" in h or "competition" in h or "name" in h or "meet" in h:
                event_col = i
            if "location" in h or "venue" in h or "city" in h or "where" in h:
                location_col = i

        if date_col is None or event_col is None:
            continue

        for row in rows[1:]:
            cells = row.find_all(["td", "th"])
            if len(cells) <= max(date_col, event_col):
                continue

            date_text = cells[date_col].get_text(strip=True)
            event_name = cells[event_col].get_text(strip=True)
            location = cells[location_col].get_text(strip=True) if location_col is not None and location_col < len(cells) else ""

            if not event_name or len(event_name) < 3:
                continue

            # Try to parse the date
            meet_date = _parse_snippet_date(date_text, now.year)
            if meet_date and (meet_date - now).days < 0:
                continue  # Past event
            if meet_date and (meet_date - now).days > 365:
                continue  # Too far out

            results.append({
                "competition": event_name,
                "dates": date_text,
                "location": location,
                "source": "web",
            })

    return results


def _scrape_diamond_league(year: int, now: datetime) -> dict:
    """Scrape the Diamond League schedule for upcoming meets.

    Diamond League is a season-long series of meets (May–September).
    Individual Indian athletes enter specific meets — Wikipedia doesn't
    list per-meet rosters, so we show the schedule of upcoming meets.
    """
    url = f"https://en.wikipedia.org/wiki/{year}_Diamond_League"
    try:
        response = requests.get(url, headers=HEADERS, timeout=10)
        if response.status_code != 200:
            return None
    except requests.exceptions.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Find the Schedule section and its table
    in_schedule = False
    schedule_table = None
    for element in soup.find_all(["h2", "table"]):
        if element.name == "h2":
            heading = element.get_text(strip=True).replace("[edit]", "").strip()
            if heading == "Schedule":
                in_schedule = True
                continue
            elif in_schedule:
                break
        elif element.name == "table" and in_schedule:
            classes = element.get("class") or []
            if "wikitable" in classes:
                schedule_table = element
                break

    if not schedule_table:
        return None

    # Parse schedule rows into upcoming meets
    rows = schedule_table.find_all("tr")
    meets = []
    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if len(cells) < 5:
            continue

        date_text = cells[1].get_text(strip=True)
        meet_name = cells[2].get_text(strip=True)
        city = cells[4].get_text(strip=True)

        # Parse date to check if it's in the future
        # Dates are like "16 May", "3–4 July"
        # Extract the last date in a range
        date_clean = re.sub(r"^\d+[–-]", "", date_text).strip()
        try:
            meet_date = datetime.strptime(f"{date_clean} {year}", "%d %B %Y")
        except ValueError:
            # Try without day for ranges like "3–4 July"
            try:
                month_match = re.search(r"([A-Z][a-z]+)$", date_text)
                day_match = re.search(r"(\d+)\s*$", date_text.split("–")[-1].split(month_match.group(1))[0]) if month_match else None
                if month_match and day_match:
                    meet_date = datetime.strptime(f"{day_match.group(1)} {month_match.group(1)} {year}", "%d %B %Y")
                else:
                    meet_date = None
            except (ValueError, AttributeError):
                meet_date = None

        if meet_date:
            days_until = (meet_date - now).days
            if days_until < -1:
                continue  # Already happened
            if days_until > 365:
                continue  # Too far out

        meets.append({
            "event": meet_name,
            "athletes": [{"name": f"{date_text} — {city}"}],
        })

    if not meets:
        return None

    return {
        "competition": f"{year} Diamond League",
        "url": url,
        "dates": "Season: May – September",
        "events": meets,
    }


def _scrape_india_at_competition(url: str, label: str, headers: dict) -> dict:
    """Scrape the Athletics section from an 'India at...' Wikipedia page.

    Extracts tables between the Athletics h2 heading and the next h2 heading.
    Groups athletes by event.
    """
    try:
        response = requests.get(url, headers=headers, timeout=10)
        if response.status_code != 200:
            return None
    except requests.exceptions.RequestException:
        return None

    soup = BeautifulSoup(response.text, "html.parser")

    # Extract dates and location from intro paragraph
    dates = ""
    location = ""
    for p in soup.find_all("p")[:5]:
        text = p.get_text(strip=True)
        if len(text) > 50:
            # Look for date range like "19 September to 4 October 2026"
            date_match = re.search(
                r"(\d{1,2}\s+\w+)\s+to\s+(\d{1,2}\s+\w+\s+\d{4})", text
            )
            if date_match:
                dates = f"{date_match.group(1)} – {date_match.group(2)}"
            # Look for location like "inAichi Prefecture, Japan from"
            loc_match = re.search(r"in\s*([A-Z][^.]+?(?:,\s*[A-Z][a-z]+)?)\s+from", text)
            if loc_match:
                location = loc_match.group(1).strip()
            break

    # Collect all elements in document order to find the Athletics section
    athletics_tables = []
    in_athletics = False

    for element in soup.find_all(["h2", "table"]):
        if element.name == "h2":
            heading_text = element.get_text(strip=True).replace("[edit]", "").strip()
            if heading_text == "Athletics":
                in_athletics = True
                continue
            elif in_athletics:
                break  # hit the next sport section
        elif element.name == "table" and in_athletics:
            classes = element.get("class") or []
            if "wikitable" in classes:
                athletics_tables.append(element)

    if not athletics_tables:
        return None

    # Parse each table into event-grouped entries
    events = {}
    for table in athletics_tables:
        _parse_athletics_table(table, events)

    if not events:
        return None

    # Cross-reference with medals data to tag medal winners
    medal_lookup = {}
    medalists = _scrape_medalists_section(url, headers)
    for m in medalists:
        # Key by first athlete name + event
        first_name = m["athlete"].split(",")[0].strip()
        medal_lookup[f"{first_name}_{m['event']}"] = m["medal"]

    # Format into sorted list
    event_list = []
    for event_name in sorted(events.keys()):
        athletes = events[event_name]
        # Tag medal winners
        for a in athletes:
            for mk, mv in medal_lookup.items():
                m_name, m_event = mk.split("_", 1)
                # Match athlete name (either direction)
                name_match = (m_name.lower() in a["name"].lower() or
                              a["name"].lower() in m_name.lower())
                # Match event — normalize for comparison
                ev_norm = event_name.lower().replace("'", "").replace("\u2019", "")
                me_norm = m_event.lower().replace("'", "").replace("\u2019", "")
                event_match = (ev_norm in me_norm or me_norm in ev_norm or
                               ev_norm.replace("m", " m") in me_norm)
                if name_match and event_match:
                    a["medal"] = mv
        event_list.append({
            "event": event_name,
            "athletes": athletes,
        })

    result = {
        "competition": label,
        "url": url,
        "events": event_list,
    }
    if dates:
        result["dates"] = dates
    if location:
        result["location"] = location
    return result


def _parse_athletics_table(table, events: dict):
    """Parse a wikitable from the Athletics section.

    Extracts athlete, event, best result, final placement, and round reached.
    """
    rows = table.find_all("tr")
    if len(rows) < 3:
        return

    # Determine column layout from headers
    header_cells = rows[0].find_all(["th", "td"])
    header_texts = [c.get_text(strip=True).lower() for c in header_cells]

    # Detect which rounds exist (Heats, Semi-final, Final, Qualification)
    has_final = "final" in header_texts
    has_semifinal = "semi-final" in header_texts

    athlete_col = None
    event_col = None
    for i, h in enumerate(header_texts):
        if "athlete" in h:
            athlete_col = i
        if "event" in h:
            event_col = i

    if athlete_col is None:
        athlete_col = 0
    if event_col is None:
        event_col = 1

    current_event = None
    pending_rowspan = 0

    for row in rows[1:]:
        cells = row.find_all(["td", "th"])
        if not cells:
            continue

        first_text = cells[0].get_text(strip=True).lower()
        if first_text in ("result", "rank", "points", "category"):
            continue

        if pending_rowspan > 0:
            pending_rowspan -= 1
            athlete_text = _extract_athlete_names(cells[0])
            data_cells = cells[1:]
        else:
            if len(cells) <= max(athlete_col, event_col):
                continue

            raw_athlete = cells[athlete_col]
            raw_event = cells[event_col]

            athlete_text = _extract_athlete_names(raw_athlete)
            event_text = _clean_text(raw_event.get_text(strip=True))

            rowspan = raw_event.get("rowspan") or raw_athlete.get("rowspan")
            if rowspan:
                try:
                    pending_rowspan = int(rowspan) - 1
                except ValueError:
                    pending_rowspan = 0

            if event_text and not _looks_like_result_text(event_text):
                current_event = event_text

            data_cells = [c for i, c in enumerate(cells) if i not in (athlete_col, event_col)]

        if not athlete_text or len(athlete_text) < 2:
            continue
        if _looks_like_result_text(athlete_text):
            continue

        event_name = current_event or "Unknown event"
        if event_name not in events:
            events[event_name] = []

        # Extract all cell texts to find result + placement
        all_texts = [c.get_text(strip=True) for c in data_cells]
        result_info = _extract_result_and_placement(all_texts, has_final, has_semifinal, event_name)

        entry = {"name": athlete_text}
        if result_info["result"]:
            entry["result"] = _format_result(result_info["result"])
        if result_info["placement"]:
            entry["placement"] = result_info["placement"]

        existing_names = [a["name"] for a in events[event_name]]
        if athlete_text not in existing_names:
            events[event_name].append(entry)


def _extract_result_and_placement(cell_texts: list, has_final: bool, has_semifinal: bool, event_name: str = "") -> dict:
    """Extract the best result and final placement from row cells.

    Cell pattern (from sub-header): Result | Rank | Result | Rank | Result | Rank
    The last pair is the furthest round reached.
    """
    result = ""
    placement = ""

    # Walk through cells collecting result/rank pairs
    # Results look like times/distances, ranks look like small numbers or "Did not advance"
    is_combined = any(k in event_name.lower() for k in ("decathlon", "heptathlon"))

    pairs = []
    i = 0
    while i < len(cell_texts):
        text = _clean_text(cell_texts[i])
        if _looks_like_result_text(text):
            rank = ""
            if i + 1 < len(cell_texts):
                next_text = _clean_text(cell_texts[i + 1])
                if next_text and (next_text.isdigit() or next_text.lower().startswith("did not") or next_text == ""):
                    rank = next_text
                    i += 1
            pairs.append({"result": text, "rank": rank})
        elif text.isdigit() and is_combined:
            # Combined events: standalone number is total points
            num = int(text)
            if num > 100:
                # This is a points total — look for rank in next cell
                actual_rank = ""
                if i + 1 < len(cell_texts):
                    next_text = _clean_text(cell_texts[i + 1])
                    if next_text.isdigit() and int(next_text) <= 50:
                        actual_rank = next_text
                        i += 1
                pairs.append({"result": f"{num} pts", "rank": actual_rank})
        elif text.lower().startswith("did not"):
            pairs.append({"result": "", "rank": text})
        i += 1

    if not pairs:
        return {"result": "", "placement": ""}

    # The last pair with a result is the furthest round
    last_with_result = None
    for p in reversed(pairs):
        if p["result"]:
            last_with_result = p
            break

    if last_with_result:
        result = last_with_result["result"]
        rank = last_with_result["rank"]

        # Determine round name
        total_pairs = len(pairs)
        pair_index = pairs.index(last_with_result)

        if rank:
            if rank.isdigit():
                rank_num = int(rank)
                # Safety: any rank > 50 is not a real placement
                if rank_num > 50:
                    placement = ""
                elif pair_index == total_pairs - 1 and has_final:
                    placement = f"Final — {_ordinal(rank_num)}"
                elif has_semifinal and pair_index == total_pairs - 2:
                    placement = f"Semi-final — {_ordinal(rank_num)}"
                else:
                    placement = f"Heats — {_ordinal(rank_num)}"
            elif rank.lower().startswith("did not"):
                placement = rank
        elif pair_index == total_pairs - 1 and has_final:
            placement = "Final"
        # Check if eliminated in heats (last pair has "Did not advance")
        last_pair = pairs[-1]
        if last_pair["rank"] and last_pair["rank"].lower().startswith("did not"):
            if pair_index < total_pairs - 1:
                round_name = "Heats" if pair_index == 0 else "Semi-final"
                placement = f"{round_name} — did not advance"

    return {"result": result, "placement": placement}


def _ordinal(n: int) -> str:
    """Return ordinal string for a number: 1 -> '1st', 2 -> '2nd', etc."""
    if 11 <= n % 100 <= 13:
        suffix = "th"
    else:
        suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def _format_result(text: str) -> str:
    """Add space before PB/SB/NR markers. '8:21.67SB' -> '8:21.67 SB'"""
    text = re.sub(r"(\d)(PB|SB|NR|AR|WR|CR)$", r"\1 \2", text, flags=re.IGNORECASE)
    return text


def _looks_like_result_text(text: str) -> bool:
    """Check if text looks like an athletics result (time, distance, DNF, etc.)."""
    text = text.strip().lower()
    if not text:
        return False
    if text in ("dns", "dnf", "dsq", "dq", "nr", "pb", "sb"):
        return True
    # Times: 10.36, 2:01.39, 45.27
    if re.match(r"^\d{1,2}[:.]\d", text):
        return True
    # Distances: 7.84, 87.58
    if re.match(r"^\d+\.\d+", text) and len(text) < 10:
        return True
    # Did not advance, etc.
    if text.startswith("did not"):
        return True
    return False


def _clean_text(text: str) -> str:
    """Remove Wikipedia reference markers like [1], [a], PB, SB, Q suffixes."""
    # Remove reference markers [1], [2], [a], etc.
    text = re.sub(r"\[\w+\]", "", text)
    # Remove trailing PB, SB, Q markers from names (but keep them in results)
    text = text.strip()
    # Remove N/a markers
    text = text.replace("—N/a", "").replace("N/a", "")
    return text.strip()
