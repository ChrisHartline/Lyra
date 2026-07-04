# Lyra Model Configuration (Grok)

## Provider
Lyra is intended to run on Grok via xAI.

## Secret Handling
- Put the API key in `.env` as `GROK_API_KEY`.
- Never hardcode secrets in code, prompts, skills, or MCP content.

## Runtime Notes
- Most SDKs can target Grok through an OpenAI-compatible interface.
- Keep model selection and temperature in runtime config, not in persona files.
- Start with conservative settings for reliability, then tune for style.

## Suggested Runtime Environment Variables
- `GROK_API_KEY`
- `GROK_BASE_URL` (optional, if your runtime supports endpoint override)
- `LYRA_MODEL` (optional model id override)

## Ownership Boundaries
- `agents/lyra/system_prompt.md`: persona + behavior contract
- `agents/lyra/skills/**`: specialized technical know-how
- `mcp/**`: tools/resources/prompts and integration content
