# BhagYahanSe

A Chrome extension + AI chatbot that tracks India's medal performance at the Asian Games in real time.

Built out of irritation — switching between SonyLIV, Olympics.com, and news sites mid-workday wasn't cutting it. The extension sits in your browser toolbar with a live medal banner, badge notifications for new medals, and a conversational AI agent that answers questions about athletes, events, and medal counts.

## What It Does

- **Live medal banner** — Gold/Silver/Bronze count in the toolbar popup, updated every 15 minutes
- **Badge notifications** — OS-level alerts when India wins a new medal
- **AI chatbot** — ask about any Indian athlete, compare records, check schedules
- **Date filtering** — "what did India win today?" works in JST (Nagoya timezone)
- **Expandable medal table** — full list grouped by sport with medal emoji

## Quick Start

### Prerequisites
- Python 3.10+
- Chrome browser
- Free API key from [OpenRouter](https://openrouter.ai/) (for the chatbot)

### 1. Clone the repo

```bash
git clone https://github.com/Paintedstork28/BhagYahanSe.git
cd BhagYahanSe
```

### 2. Set up Python environment

```bash
python3 -m venv venv
source venv/bin/activate      # macOS/Linux
# venv\Scripts\activate       # Windows
pip install -r requirements.txt
```

### 3. Add your API key

```bash
cp .env.example .env
```

Edit `.env` and add your OpenRouter API key:
```
OPENROUTER_API_KEY=sk-or-v1-your-key-here
```

The chatbot uses OpenRouter's free tier (no credit card needed). Sign up at [openrouter.ai](https://openrouter.ai/), go to Keys, and create one.

`GOOGLE_API_KEY` is optional (Gemini backup). The extension works without it.

### 4. Start the server

```bash
python -m athletics_trivia.server
```

You should see:
```
Starting Athletics Trivia API Server...
Endpoints:
  POST /api/chat          — chat with the agent
  GET  /api/competitions  — current Indian athlete competitions
  GET  /api/medals        — athletics medals won by India
  GET  /api/upcoming      — upcoming competitions (next 3 months)
  GET  /api/health        — health check
```

### 5. Load the Chrome extension

1. Open `chrome://extensions` in Chrome
2. Enable **Developer mode** (toggle in top right)
3. Click **Load unpacked**
4. Select the `athletics_trivia/extension/` folder
5. Pin the extension to your toolbar

The badge should show the medal count within a minute. Click the icon to see the full popup.

### 6. Verify it works

```bash
# Check the server is running
curl http://127.0.0.1:5000/api/health

# Get the medal tally
curl -s http://127.0.0.1:5000/api/all-medals | python3 -c "import json,sys;d=json.load(sys.stdin);print(f'Total: {len(d[\"medals\"])} — G:{d[\"official_tally\"].get(\"gold\",\"?\")} S:{d[\"official_tally\"].get(\"silver\",\"?\")} B:{d[\"official_tally\"].get(\"bronze\",\"?\")}')"
```

---

## Architecture

```
User (Chrome Extension / Chatbot)
    ↓ HTTP requests
Flask API Server (server.py)
    ↓ routes to
LangGraph Agent (LangChain + OpenRouter)
    ↓ decides
Tool calls (scrape, lookup, filter)
    ↓ returns
Structured data → LLM formats response → User
```

### Medal Pipeline

```
Indian Express liveblogs →  auto-discover day URLs + parse JSON-LD  →  medals with details
(Days 13, 14, 15, ...)       from IE tag page
        ↓
Wikipedia medalists page →  backfill dates only (never adds medals)
        ↓
IOA official tally       →  if IE < IOA, add TBD placeholders to match count
                             (not cached — replaced when IE catches up)
        ↓
Persistent cache         →  medals_cache.json (IE medals only, additive)
        ↓
5-tuple dedup key        →  (sport, medal_type, gender, event_key, entry_type)
        ↓
API response             →  Chrome extension badge + banner
```

### Data Sources

| Source | What It Provides | Reliability |
|---|---|---|
| [Indian Express liveblogs](https://indianexpress.com/) | Complete medal list (athlete, event, sport, medal type). Multiple day URLs scraped + auto-discovered. | High — editorially maintained |
| Wikipedia | Dates and sport labels for backfill | Medium — lags by hours |
| [IOA](https://olympic.ind.in/asian-games-2026/) | Official G/S/B tally. Gap-fills when IE is behind — adds TBD placeholders for missing medals. | High — official source |
| OpenRouter API | LLM for chatbot responses | Free tier — 50 req/day |

---

## Project Structure

```
BhagYahanSe/
├── .env.example                      # Template for API keys
├── requirements.txt                  # Python dependencies
├── athletics_trivia/
│   ├── server.py                     # Flask API server (main entry point)
│   ├── agent_langchain.py            # Terminal chatbot (standalone)
│   ├── data/
│   │   ├── athletes.json             # Scraped athlete database
│   │   └── medals_cache.json         # Runtime: persistent medal cache (gitignored)
│   ├── tools/
│   │   ├── athlete.py                # Athlete lookup from JSON
│   │   ├── scraper_tool.py           # Wikipedia scraper for new athletes
│   │   ├── nationality.py            # Indian athlete filter
│   │   ├── preferences.py            # User preferences (favorites)
│   │   ├── records.py                # World/Olympic record comparisons
│   │   └── competitions.py           # Medal tracking, dedup, IOA validation
│   ├── scraper/
│   │   ├── scrape_athletes.py        # Pre-load athletes from Wikipedia
│   │   └── cleanup.py                # Reset database
│   └── extension/
│       ├── manifest.json             # Chrome extension manifest v3
│       ├── popup.html                # Extension popup UI
│       ├── popup.js                  # Medal banner, chatbot, collapsible tables
│       ├── popup.css                 # Styling
│       ├── background.js             # Service worker — polling, notifications
│       └── icons/                    # Extension icons
└── venv/                             # Python virtual environment (gitignored)
```

## Agent Tools

The chatbot uses 10 custom tools. The LLM never answers from its own knowledge — every response must come from a tool call.

### Athlete Lookup Chain

When you ask "Who is Neeraj Chopra?" or "Tell me about Lovlina Borgohain":

1. **`get_athlete_info`** — checks the local JSON database (`athletes.json`) first. Supports partial name matching and asks for clarification if multiple matches exist.
2. **`scrape_and_add_athlete`** — if not in the database, scrapes the athlete's Wikipedia page. Tries three strategies in order:
   - Direct Wikipedia URL (`en.wikipedia.org/wiki/First_Last`)
   - Wikipedia Search API (handles alternate spellings)
   - DuckDuckGo web search (finds the correct Wikipedia page for misspelled names)
   - All three strategies ultimately resolve to a Wikipedia page. If no Wikipedia page exists for the athlete, the lookup fails.
3. **`check_nationality`** — verifies an athlete is Indian before scraping. Checks three sources: Wikipedia infobox → DuckDuckGo Instant Answer API → DuckDuckGo search results.

Non-Indian athletes are blocked in code (not by prompt) — the LLM can't override this.

**What you can ask:**
- "Who is [athlete name]?" — bio, events, personal bests from Wikipedia
- "What events does [athlete] compete in?" — parsed from Wikipedia infobox
- "What is [athlete]'s personal best?" — extracted from their Wikipedia page

### Record Comparison

**`compare_to_records`** — compares an athlete's personal best to the current world record and Olympic record. Scrapes Wikipedia for the event's record page.

**What you can ask:**
- "How does Neeraj Chopra's PB compare to the world record?"
- "What is the Olympic record in javelin?"

### Medal Tracking (Asian Games 2026)

| Tool | Scope | Use When |
|---|---|---|
| `get_all_sport_medals` | All sports — shooting, archery, wrestling, athletics, etc. | "How many golds has India won?" / "Medal tally" |
| `get_medals` | Athletics/track-and-field only | "How did India do in athletics?" |
| `get_medals_by_date` | All sports, filtered by date (JST) | "What did India win today?" / "Yesterday's medals" |
| `get_competitions` | Current competitions with Indian athletes | "What events are happening?" |

### User Preferences

| Tool | What It Does |
|---|---|
| `save_user_preference` | Remembers favorite athletes, events, or interests |
| `get_user_preferences` | Recalls preferences for personalized recommendations |

**What you can ask:**
- "I'm a fan of javelin" → saves to preferences
- "What should I watch?" → loads preferences and recommends based on them

---

## Known Issues

| Bug | Description | Root Cause |
|---|---|---|
| **LLM hallucinates medal results** | Asked "Who won gold for India at Asian Games 2026?", the chatbot returned fabricated results (P.T. Usha winning Women's 100m, Neeraj Chopra winning javelin) instead of querying the database. Returned 5 fake golds instead of the actual 19. | The free-tier model on OpenRouter (`openrouter/free`) has unreliable tool-calling. It skips tool calls and answers from its outdated training data. Switching to a model with reliable tool-use (e.g., `gpt-4o-mini`, `gemini-2.0-flash`) would fix this, however those models have a cost. |
| **Free tier rate limit** | OpenRouter free tier allows ~50 requests/day. After that, the chatbot returns a 429 error. | OpenRouter free tier quota. Resets daily, or add credits at openrouter.ai. |
| **No fallback for athletes without Wikipedia** | Many Indian athletes (especially in non-athletics sports or at the domestic level) don't have Wikipedia pages. The agent returns "Could not find a Wikipedia page" and gives up. DuckDuckGo is only used to find the *correct Wikipedia page* for misspelled names — it doesn't scrape non-Wikipedia sources. | Potential future sources: [indianathletics.in](https://indianathletics.in/athlete-profiles/) (requires headless browser — JS-rendered), [worldathletics.org](https://worldathletics.org) (also JS-rendered, has a GraphQL API but needs reverse-engineering). |

---

## Key Technical Decisions

- **Code-level guardrails over prompts** — telling the LLM "only Indian athletes" didn't work (it discussed Usain Bolt). Nationality check enforced in Python.
- **5-tuple dedup key** — `(sport, medal_type, gender, event_key, entry_type)` with sport canonicalization, fuzzy matching, and team name normalization.
- **Multi-URL IE scraping** — IE publishes a new liveblog each day. Scraper maintains known URLs + auto-discovers new ones from the IE tag page. Dedup handles cross-day overlaps.
- **IOA gap-fill** — if IE medal count < IOA official tally, TBD placeholders are added to match the IOA count. Placeholders are not cached and get replaced as IE publishes real data.
- **Persistent cache with `_is_team` flags** — medals once discovered are never lost. Team detection flags survive cache reload to prevent dedup key drift.
- **Discovery date stamping** — undated medals get stamped with today's date (JST) after Wikipedia backfill, so "today's medals" works even when Wikipedia lags.

## Polling Schedule

- **15 minutes** during active competition — checks for new medals
- **6 hours** during idle — checks if a competition is active
- Badge updates automatically. OS notifications fire for genuinely new medals (not on extension reload).

## Cost

| Component | Cost |
|---|---|
| OpenRouter API (free tier) | $0 |
| Google Gemini API (optional) | $0 |
| Wikipedia / Indian Express / IOA | $0 (no API key) |
| **Total** | **$0** |

---

## Build Log

<details>
<summary>Phase 13-14: Dedup fixes</summary>

- "MMA" vs "Mixed martial arts" → sport canonicalization map
- "Indian women's cricket team" vs "India women's national cricket team" → team name normalization
- "+90 kg" vs "90+kg" → weight class regex normalization
- "Marathon" as separate sport vs under "Athletics" → sport alias mapping
- 85 scraped medals → 60 actual (5 rounds of dedup iteration)
</details>

<details>
<summary>Phase 15: Persistent medal cache</summary>

- DDG search results were non-deterministic — medal counts fluctuated (59 → 62 → 59)
- Solution: `medals_cache.json` persists all discovered medals between polls
- Additive only — medals never removed once validated
</details>

<details>
<summary>Phase 16: Source architecture overhaul</summary>

- Dropped DDG News entirely (caused count drift 62 → 68 via non-deterministic results)
- Indian Express liveblog as primary source (JSON-LD FAQPage block)
- Wikipedia demoted to date backfill only
- Fixed: gender extraction from athlete names, team detection via athlete field, `_is_team` flag preservation across cache reloads
- Result: matches IOA exactly, stable across consecutive polls
</details>

<details>
<summary>Phase 17: Multi-URL IE scraping + IOA gap-fill</summary>

- IE publishes a new liveblog URL each day — scraper was hardcoded to Day 13, missing Days 14+
- Fix: scrape all known URLs + auto-discover new ones from IE tag page (`/about/asian-games-2026/`)
- Added IOA gap-fill: when IE count < IOA official tally, TBD placeholders fill the gap (not cached)
- Placeholders replaced naturally as IE publishes real medal data
- Result: 78 real medals + 3 TBD = 81 total, matching IOA
</details>
