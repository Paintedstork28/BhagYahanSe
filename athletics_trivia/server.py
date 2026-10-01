"""Flask API server wrapping the LangChain athletics trivia agent.

Endpoints:
    POST /api/chat          — send a message, get agent response
    GET  /api/competitions  — get current Indian athlete competitions

Run: python -m athletics_trivia.server
"""

import os
import re
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
from flask_cors import CORS
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain.agents import create_agent
from langchain.tools import tool

from athletics_trivia.tools.athlete import get_athlete_info as _get_athlete_info
from athletics_trivia.tools.scraper_tool import scrape_and_add_athlete as _scrape_and_add_athlete
from athletics_trivia.tools.nationality import check_nationality as _check_nationality
from athletics_trivia.tools.preferences import save_user_preference as _save_user_preference
from athletics_trivia.tools.preferences import get_user_preferences as _get_user_preferences
from athletics_trivia.tools.records import compare_to_records as _compare_to_records
from athletics_trivia.tools.competitions import get_current_competitions as _get_current_competitions
from athletics_trivia.tools.competitions import get_medals as _get_medals
from athletics_trivia.tools.competitions import get_all_sport_medals as _get_all_sport_medals
from athletics_trivia.tools.competitions import get_upcoming_competitions as _get_upcoming_competitions

# Load API key
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# ── LangChain tools (same as agent_langchain.py) ──────────────────────

@tool
def get_athlete_info(name: str) -> dict:
    """Look up information about an Indian athlete from the database.
    This tool MUST be called before answering any question about an athlete.
    If the athlete is not found, the agent must call scrape_and_add_athlete next."""
    return _get_athlete_info(name)


@tool
def scrape_and_add_athlete(name: str) -> dict:
    """Look up any athlete and add them to the database. This tool checks if the
    athlete is Indian. If they are not Indian, it returns a BLOCKED error.
    Always call this when an athlete is not found in get_athlete_info."""
    return _scrape_and_add_athlete(name)


@tool
def check_nationality(name: str) -> dict:
    """Check if an athlete is Indian by looking up their Wikipedia page."""
    return _check_nationality(name)


@tool
def save_user_preference(category: str, value: str) -> dict:
    """Save a user preference. Call this when the user mentions they like or follow
    a specific athlete, event, or topic.
    category must be one of: favorite_athletes, favorite_events, or interests."""
    return _save_user_preference(category, value)


@tool
def get_user_preferences() -> dict:
    """Get all saved user preferences. Call this when the user asks for recommendations,
    or says things like 'what should I watch' or 'who do I follow'."""
    return _get_user_preferences()


@tool
def compare_to_records(athlete_name: str, event: str) -> dict:
    """Compare an athlete's personal best to the current world record and Olympic record.
    Call this when the user asks how an athlete compares to world or Olympic records,
    or asks about records in a specific event."""
    return _compare_to_records(athlete_name, event)


@tool
def get_competitions() -> dict:
    """Get current and upcoming athletics competitions featuring Indian athletes.
    Call this when the user asks about current competitions, who is competing,
    or what events are happening."""
    return _get_current_competitions()


@tool
def get_medals() -> dict:
    """Get all athletics medals won by Indian athletes at current competitions.
    Call this when the user asks specifically about athletics/track-and-field medals.
    Returns a list of medals with athlete name, event, and medal type."""
    return _get_medals()


@tool
def get_all_sport_medals() -> dict:
    """Get ALL medals won by India across ALL sports (shooting, archery, wrestling,
    athletics, swimming, etc.) at the current multi-sport competition like the Asian Games.
    Call this when the user asks about India's overall medal tally, medals in non-athletics
    sports (e.g. shooting, archery, boxing, wrestling).
    This is the preferred tool for general medal queries."""
    return _get_all_sport_medals()


# Japan Standard Time (UTC+9) for Asian Games in Nagoya
JST = timezone(timedelta(hours=9))


@tool
def get_medals_by_date(date: str) -> dict:
    """Get medals won by India on a specific date. Use this when the user asks about
    'today's medals', 'yesterday's medals', or medals on a specific date.
    Args:
        date: 'today', 'yesterday', or a date like '2026-09-25' or 'September 25'.
    All dates use Japan Standard Time (JST) since the Asian Games are in Nagoya, Japan."""
    now_jst = datetime.now(JST)
    year = now_jst.year

    if date.lower() == "today":
        target = now_jst.strftime("%Y-%m-%d")
    elif date.lower() == "yesterday":
        target = (now_jst - timedelta(days=1)).strftime("%Y-%m-%d")
    elif re.match(r"\d{4}-\d{2}-\d{2}", date):
        target = date
    else:
        # Try parsing "September 25" or "25 September"
        for fmt in ("%B %d", "%d %B"):
            try:
                dt = datetime.strptime(date.strip(), fmt)
                target = dt.replace(year=year).strftime("%Y-%m-%d")
                break
            except ValueError:
                continue
        else:
            return {"error": f"Could not parse date: '{date}'. Use 'today', 'yesterday', or 'YYYY-MM-DD'."}

    all_data = _get_all_sport_medals()
    day_medals = [m for m in all_data.get("medals", []) if m.get("date") == target]

    return {
        "date": target,
        "date_jst": f"{target} (JST)",
        "medals": day_medals,
        "count": len(day_medals),
        "gold": sum(1 for m in day_medals if m["medal"].lower() == "gold"),
        "silver": sum(1 for m in day_medals if m["medal"].lower() == "silver"),
        "bronze": sum(1 for m in day_medals if m["medal"].lower() == "bronze"),
    }


# ── Agent setup ────────────────────────────────────────────────────────

_now_jst = datetime.now(JST)
SYSTEM_PROMPT = f"""You are an athletics trivia agent. You ONLY cover Indian athletes.
Today's date is {_now_jst.strftime("%A, %B %d, %Y")} (Japan Standard Time — the Asian Games are in Nagoya, Japan).

CRITICAL: You must NEVER fabricate, guess, or infer any results, medals, times, or placements.
Only state facts that are explicitly present in tool responses. If a tool says an athlete won
gold in "Women's 4x400m relay", do NOT say they won gold in "Women's 400m" — those are
different events. Report exactly what the data says, word for word.

RULES:
1. ALWAYS ask for the full name (first name + last name of the athlete) if only one name has been given
2. When asked about any athlete, ALWAYS call get_athlete_info first.
3. If not found, ALWAYS call scrape_and_add_athlete. Never answer from your own knowledge.
4. If scrape_and_add_athlete returns an error saying BLOCKED, tell the user:
   "Sorry, this agent only covers Indian athletes." Say nothing else about that person.
5. You must NEVER answer questions about athletes without using your tools first.
6. You have no knowledge of your own. You can only share what the tools return.
7. When the user says they like, follow, or are a fan of an athlete or event, call
   save_user_preference to remember it. Use category "favorite_athletes" for athletes,
   "favorite_events" for events like javelin or 100m, and "interests" for general topics.
8. When the user asks "what should I watch", "who do I follow", or wants recommendations,
   call get_user_preferences first to check what they like.
9. When the user asks how an athlete's personal best compares to the world record or
   Olympic record, call compare_to_records with the athlete's name and event.
10. When the user asks about current competitions or who is competing, call get_competitions.
    When the user asks about medals across ALL sports (shooting, archery, wrestling, boxing, etc.)
    or India's overall medal tally, call get_all_sport_medals. When the user asks specifically about
    athletics/track-and-field medals only, call get_medals. If unsure which to use, prefer
    get_all_sport_medals as it covers everything. Always mention the competition name
    (e.g. "at the 2026 Asian Games") when reporting medals.
11. Use today's date (JST) to determine correct tense. If an event date is before today, say
    "yesterday" or the actual date — never say "today" unless it is actually today in JST.
12. When reporting medals or results, copy the exact athlete name and exact event name
    from the tool data. Do not paraphrase event names or combine separate entries.
13. When the user asks about "today's medals", "yesterday's medals", or medals on a
    specific date, call get_medals_by_date with "today", "yesterday", or the date.
    All dates use Japan Standard Time (JST, UTC+9) since the Asian Games are in Nagoya.

Be enthusiastic but accurate. Never guess — if the data doesn't say it, don't say it."""

llm = ChatOpenAI(
    model="openrouter/free",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

tools_list = [
    get_athlete_info,
    scrape_and_add_athlete,
    check_nationality,
    save_user_preference,
    get_user_preferences,
    compare_to_records,
    get_competitions,
    get_medals,
    get_all_sport_medals,
    get_medals_by_date,
]

agent = create_agent(
    model=llm,
    tools=tools_list,
    system_prompt=SYSTEM_PROMPT,
)


# ── Flask app ──────────────────────────────────────────────────────────

app = Flask(__name__)
CORS(app)

# Store conversation history per session (in-memory)
sessions = {}


@app.route("/api/chat", methods=["POST"])
def chat():
    """Receive a user message, run the agent, return the response."""
    data = request.get_json()
    if not data or "message" not in data:
        return jsonify({"error": "Missing 'message' field"}), 400

    session_id = data.get("session_id", "default")
    user_message = data["message"]

    # Get or create session history
    if session_id not in sessions:
        sessions[session_id] = []

    messages = sessions[session_id]
    messages.append({"role": "user", "content": user_message})

    try:
        result = agent.invoke({"messages": messages})
        last_message = result["messages"][-1]
        response_text = last_message.content

        # Save to session history
        messages.append({"role": "assistant", "content": response_text})

        return jsonify({"response": response_text, "session_id": session_id})

    except Exception as e:
        error_msg = str(e)
        if "429" in error_msg or "rate limit" in error_msg.lower():
            return jsonify({
                "error": "Daily free API limit reached (50 requests/day on OpenRouter free tier). "
                         "Resets tomorrow, or add credits at openrouter.ai."
            }), 429
        return jsonify({"error": error_msg}), 500


@app.route("/api/competitions", methods=["GET"])
def competitions():
    """Return current/upcoming competitions with Indian athletes."""
    try:
        result = _get_current_competitions()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/medals", methods=["GET"])
def medals():
    """Return athletics medals won by Indian athletes."""
    try:
        result = _get_medals()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/all-medals", methods=["GET"])
def all_medals():
    """Return ALL Indian medals (all sports) at current multi-sport events."""
    try:
        result = _get_all_sport_medals()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/upcoming", methods=["GET"])
def upcoming():
    """Return upcoming athletics competitions featuring Indian athletes."""
    try:
        result = _get_upcoming_competitions()
        return jsonify(result)
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@app.route("/api/health", methods=["GET"])
def health():
    """Health check endpoint."""
    return jsonify({"status": "ok", "agent": "athletics-trivia"})


if __name__ == "__main__":
    print("Starting Athletics Trivia API Server...")
    print("Endpoints:")
    print("  POST /api/chat          — chat with the agent")
    print("  GET  /api/competitions  — current Indian athlete competitions")
    print("  GET  /api/medals        — athletics medals won by India")
    print("  GET  /api/upcoming      — upcoming competitions (next 3 months)")
    print("  GET  /api/health        — health check")
    print()
    app.run(host="127.0.0.1", port=5000, debug=True)
