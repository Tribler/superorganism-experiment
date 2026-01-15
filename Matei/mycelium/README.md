# Mycelium Autonomous Orchestrator

Autonomous server infrastructure orchestration system that only Auto-Updates itself.

## Architecture

The orchestrator runs continuously and:
- Monitors GitHub repository for code updates every 30 seconds
- Automatically pulls changes and restarts when updates are detected
- Runs BitTorrent seedbox 

## Local Development:

### Please clone https://github.com/DogariuMatei/mycelium-bootstrap
### THIS DOES NOT WORK WITHOUT IT!!!

## Testing Auto-Update Feature

1. Make a change to the codebase (modify a log message in `code/main.py`)
2. Commit and push to GitHub
3. Within 30 seconds, the orchestrator will see the change
4. It will pull updates and restart automatically
5. Verify the change in the logs
6. Verify that the change was applied and the system resumes


## Seedbox
It's just a basic seedbox that is seeding a single test song (or whatever you put in `/CreativeCommonsMusic`
from the bootstrap repo).
