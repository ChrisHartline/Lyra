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
- `GROK_BASE_URL` (defaults to `https://api.x.ai/v1`)
- `LYRA_MODEL` (back-compatible conversation model id)
- `LYRA_CONVERSATION_PROVIDER` / `LYRA_CONVERSATION_MODEL`
- `ANTHROPIC_API_KEY` / `ANTHROPIC_MODEL`
- `LYRA_SPECIALIST_PROVIDER` / `LYRA_SPECIALIST_MODEL`

Logical profiles are resolved when a request starts, not when the module is
imported. `conversation` defaults to the OpenAI-compatible Grok adapter and
`specialist` defaults to the Anthropic adapter. A profile with no model or no
credential produces a sanitized runtime error event; it never falls back to an
unconfigured provider or includes a secret value in output.

## Ownership Boundaries
- `personality/system_prompt.md`: persona + behavior contract
- `agents/lyra/skills/**`: specialized technical know-how
- `mcp/**`: tools/resources/prompts and integration content
