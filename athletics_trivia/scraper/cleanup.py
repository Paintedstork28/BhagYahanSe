"""Database cleanup script.

Re-generates athletes.json with only the original 15 pre-loaded athletes.
Any dynamically added athletes are removed.

Run manually: python -m athletics_trivia.scraper.cleanup
Or set up a cron job to run every 48 hours:
  crontab -e
  0 */48 * * * cd /Users/ambikapande/Desktop/claude-projects/athletics-agent && /Users/ambikapande/Desktop/claude-projects/athletics-agent/venv/bin/python -m athletics_trivia.scraper.cleanup
"""

from athletics_trivia.scraper.scrape_athletes import main

if __name__ == "__main__":
    print("Cleaning up database — resetting to original 15 athletes...")
    main()
    print("Cleanup complete.")
