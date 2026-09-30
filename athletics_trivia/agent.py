from google.adk import Agent
from google.genai import types
from athletics_trivia.tools.athlete import get_athlete_info
from athletics_trivia.tools.scraper_tool import scrape_and_add_athlete

root_agent = Agent(
    model="gemini-2.5-flash",
    name="asiangames2026_agent",
    description="An athletics trivia agent focused exclusively on Indian athletes.",
    instruction="""You are an athletics trivia agent. You ONLY cover Indian athletes.

    RULES:
    1. When asked about any athlete, ALWAYS call get_athlete_info first.
    2. If not found, ALWAYS call scrape_and_add_athlete. Never answer from your own knowledge.
    3. If scrape_and_add_athlete returns an error saying BLOCKED, tell the user:
       "Sorry, this agent only covers Indian athletes." Say nothing else about that person.
    4. You must NEVER answer questions about athletes without using your tools first.
    5. You have no knowledge of your own. You can only share what the tools return.

    Be enthusiastic and share interesting facts about Indian athletes.""",
    tools=[get_athlete_info, scrape_and_add_athlete],
    generate_content_config=types.GenerateContentConfig(
        tool_config=types.ToolConfig(
            function_calling_config=types.FunctionCallingConfig(mode="ANY")
        )
    ),
)
