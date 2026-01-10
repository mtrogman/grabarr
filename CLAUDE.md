# Claude Code Guidelines for Grabarr

## Git Commits
- Never use Co-Authored-By with Claude in commits
- Keep commit messages concise and descriptive

## Testing
- Always stop the test bot after testing (shared bot: token starts with MTE1MzQzNDA2...)
- Clean up any movies/shows added to Radarr/Sonarr during testing
- Run the full test suite before committing: `python -m pytest tests/ -v`

## Configuration
- The test bot token should remain in config/config.yml for testing
- config/config.yml is gitignored - never commit credentials
- Use environment variables for CI/CD secrets

## Development
- Default config path for Docker: /config/config.yml
- For local testing, set GRABARR_CONFIG_PATH=config/config.yml
