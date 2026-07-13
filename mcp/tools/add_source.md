# Tool: add_source

## Purpose
Trigger ingestion for a URL or local file through the A3 ingestion pipeline.

## Input
- `source` (string, required) - URL or local file path
- `source_type` (string, optional) - `url` or `file` (default `url`)
- `title` (string, optional)

## Output
- `source_id`
- `active_source_id`
- `was_deduped`
