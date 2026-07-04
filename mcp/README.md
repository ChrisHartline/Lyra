# Lyra MCP Layout

This repository uses a local-first MCP content structure.

## Purpose
- Keep MCP prompts, resources, and tool specs in version control.
- Make local iteration easy before publishing to remote registries.
- Allow later sync/mirroring to GitHub or external MCP servers.

## Directory Structure
- `mcp/prompts/` - reusable prompt templates and system snippets
- `mcp/resources/` - static knowledge/context files exposed as MCP resources
- `mcp/tools/` - tool contracts, schemas, and implementation notes

## Local vs Remote Strategy
- Start local: faster iteration, less setup risk.
- Promote to GitHub once stable:
  - Option A: keep this folder in the main repo.
  - Option B: split into a dedicated `lyra-mcp` repo and consume as a submodule/subtree.

## Conventions
- Use kebab-case filenames.
- Keep each prompt/resource/tool focused on one concern.
- Add a short header to every file with purpose and required inputs.
- Never store live secrets in MCP content files.
