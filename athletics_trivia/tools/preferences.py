import json
import os


DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "user_preferences.json")


def _load_preferences() -> dict:
    """Load preferences from file."""
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            return json.load(f)
    return {"favorite_athletes": [], "favorite_events": [], "interests": []}


def _save_preferences(prefs: dict):
    """Save preferences to file."""
    os.makedirs(os.path.dirname(DATA_PATH), exist_ok=True)
    with open(DATA_PATH, "w") as f:
        json.dump(prefs, f, indent=2, ensure_ascii=False)


def save_user_preference(category: str, value: str) -> dict:
    """Save a user preference. Call this when the user mentions they like or follow
    a specific athlete, event, or topic.

    Args:
        category: One of "favorite_athletes", "favorite_events", or "interests".
        value: The value to save (e.g. "Neeraj Chopra", "javelin", "sprinting").

    Returns:
        A confirmation message.
    """
    prefs = _load_preferences()

    if category not in prefs:
        return {"error": f"Unknown category '{category}'. Use: favorite_athletes, favorite_events, or interests."}

    if value not in prefs[category]:
        prefs[category].append(value)
        _save_preferences(prefs)
        return {"status": "saved", "message": f"Noted! Added '{value}' to your {category.replace('_', ' ')}."}
    else:
        return {"status": "already_exists", "message": f"'{value}' is already in your {category.replace('_', ' ')}."}


def get_user_preferences() -> dict:
    """Get all saved user preferences. Call this when the user asks for recommendations,
    or says things like "what should I watch" or "who do I follow".

    Returns:
        A dictionary with the user's favorite athletes, events, and interests.
    """
    prefs = _load_preferences()
    if not any(prefs.values()):
        return {"message": "No preferences saved yet. Ask the user what athletes or events they're interested in."}
    return prefs
