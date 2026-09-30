import json
import os


DATA_PATH = os.path.join(os.path.dirname(__file__), "..", "data", "athletes.json")


def get_athlete_info(name: str) -> dict:
    """Look up information about an Indian athlete from the database.
    This tool MUST be called before answering any question about an athlete.
    If the athlete is not found, the agent must call scrape_and_add_athlete next.

    Args:
        name: The name of the athlete to look up.

    Returns:
        A dictionary with the athlete's information, or an error if not found.
    """
    # Load athletes from JSON file
    if os.path.exists(DATA_PATH):
        with open(DATA_PATH, "r") as f:
            athletes = json.load(f)
    else:
        athletes = {}

    # Try exact match first
    result = athletes.get(name.lower())
    if result:
        return result

    # Try partial match — but ask for clarification instead of auto-returning
    partial_matches = []
    for key, data in athletes.items():
        if name.lower() in key:
            partial_matches.append(data["name"])

    if len(partial_matches) == 1:
        return {
            "clarification_needed": f"Did you mean {partial_matches[0]}? Please confirm the full name."
        }
    elif len(partial_matches) > 1:
        names = ", ".join(partial_matches)
        return {
            "clarification_needed": f"Multiple matches found: {names}. Which athlete did you mean?"
        }

    return {
        "error": f"Athlete '{name}' not found in database. You MUST call scrape_and_add_athlete to look them up. Do NOT answer from your own knowledge."
    }
