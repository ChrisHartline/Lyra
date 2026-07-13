# Tool: search_corpus

## Purpose
Semantic retrieval over ingested corpus chunks with source citations.

## Input
- `query` (string, required)
- `limit` (integer, optional, default `5`)

## Output
- `query`
- `results[]` where each item includes:
  - `chunk_id`
  - `content`
  - `score`
  - `citation` (`source_id`, `title`, `url`, `file_path`)
