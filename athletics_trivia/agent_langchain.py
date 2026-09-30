import os
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

# Load API key from .env
load_dotenv(os.path.join(os.path.dirname(__file__), "..", ".env"))


# Wrap your existing functions as LangChain tools using the @tool decorator
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


# Set up the LLM (OpenRouter with a free model)
llm = ChatOpenAI(
    model="openrouter/free",
    api_key=os.getenv("OPENROUTER_API_KEY"),
    base_url="https://openrouter.ai/api/v1",
)

# System prompt — same instructions as ADK version
SYSTEM_PROMPT = """You are an athletics trivia agent. You ONLY cover Indian athletes.

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

Be enthusiastic and share interesting facts about Indian athletes."""

# Create the agent
tools = [get_athlete_info, scrape_and_add_athlete, check_nationality, save_user_preference, get_user_preferences, compare_to_records]
agent = create_agent(
    model=llm,
    tools=tools,
    system_prompt=SYSTEM_PROMPT,
)


def main():
    """Run the agent in a chat loop."""
    print("Athletics Trivia Agent (LangChain + OpenRouter)")
    print("Type 'exit' to quit.\n")

    messages = []
    while True:
        user_input = input("[you]: ").strip()
        if user_input.lower() in ("exit", "quit"):
            break
        if not user_input:
            continue

        # Add user message to history
        messages.append({"role": "user", "content": user_input})

        # Send full conversation history
        result = agent.invoke({"messages": messages})

        # Get the last AI message from the result
        last_message = result["messages"][-1]
        print(f"\n[agent]: {last_message.content}\n")

        # Add agent response to history for next turn
        messages.append({"role": "assistant", "content": last_message.content})


if __name__ == "__main__":
    main()
