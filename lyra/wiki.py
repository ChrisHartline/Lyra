"""Read-only, agent-isolated Markdown wiki with deterministic lexical retrieval."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re
from typing import Any


WIKI_BUCKETS = frozenset(
    {"lore", "place", "expertise", "creative_constraint", "terminology", "person"}
)
ALLOWED_SHARED_PREFIXES = ("locations/",)
TOKEN_RE = re.compile(r"[a-z0-9]+(?:['-][a-z0-9]+)?", re.IGNORECASE)
MAX_QUERY_CHARS = 500
MAX_PAGE_CHARS = 16_000
MAX_EXCERPT_CHARS = 700


class WikiError(RuntimeError):
    """Base error for catalog or wiki access failures."""


class WikiPageNotFound(WikiError):
    """Raised when a page is absent from the active agent's allowlist."""


@dataclass(frozen=True)
class WikiPage:
    page_id: str
    title: str
    path: str
    bucket: str
    tags: tuple[str, ...]
    provenance: tuple[str, ...]
    sha256: str


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _body(text: str) -> str:
    if not text.startswith("---"):
        return text.strip()
    end = text.find("\n---", 3)
    return text[end + 4 :].strip() if end >= 0 else text.strip()


def _tokens(text: str) -> tuple[str, ...]:
    return tuple(token.lower() for token in TOKEN_RE.findall(text))


def _safe_path(root: Path, relative: str) -> Path | None:
    candidate = Path(relative)
    if candidate.is_absolute() or candidate.suffix.lower() != ".md":
        return None
    resolved_root = root.resolve()
    resolved = (root / candidate).resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError:
        return None
    return resolved


def validate_wiki_catalog(root: Path, agent_id: str = "lyra") -> list[str]:
    """Return catalog errors; an empty result is a valid, closed allowlist."""
    errors: list[str] = []
    if not re.fullmatch(r"[a-z0-9_-]+", agent_id):
        return [f"invalid agent_id: {agent_id!r}"]
    catalog_path = root / "agents" / agent_id / "wiki" / "catalog.json"
    try:
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [f"wiki catalog: {exc}"]
    if payload.get("agent_id") != agent_id:
        errors.append(f"catalog agent_id must be {agent_id!r}")
    if payload.get("retrieval") != "lexical":
        errors.append("catalog retrieval must be 'lexical'")
    if payload.get("automatic_chat_ingest") is not False:
        errors.append("automatic_chat_ingest must be false")
    pages = payload.get("pages")
    if not isinstance(pages, list):
        return errors + ["catalog pages must be a list"]
    seen: set[str] = set()
    agent_prefix = f"agents/{agent_id}/references/"
    wiki_prefix = f"agents/{agent_id}/wiki/pages/"
    for index, item in enumerate(pages):
        label = f"pages[{index}]"
        if not isinstance(item, dict):
            errors.append(f"{label}: expected object")
            continue
        page_id = item.get("page_id")
        if not isinstance(page_id, str) or not re.fullmatch(r"[a-z0-9_.-]+", page_id):
            errors.append(f"{label}: invalid page_id")
        elif page_id in seen:
            errors.append(f"{label}: duplicate page_id {page_id!r}")
        else:
            seen.add(page_id)
        relative = item.get("path")
        if not isinstance(relative, str):
            errors.append(f"{label}: path must be a string")
            continue
        if not relative.startswith((agent_prefix, wiki_prefix, *ALLOWED_SHARED_PREFIXES)):
            errors.append(f"{label}: path is outside agent wiki allowlist: {relative}")
        if "/source_material/" in f"/{relative}":
            errors.append(f"{label}: source material cannot be exposed as a wiki page")
        path = _safe_path(root, relative)
        if path is None:
            errors.append(f"{label}: unsafe Markdown path: {relative}")
        else:
            allowed_roots = (
                (root / "agents" / agent_id / "references").resolve(),
                (root / "agents" / agent_id / "wiki" / "pages").resolve(),
                (root / "locations").resolve(),
            )
            if not any(
                path == allowed or allowed in path.parents for allowed in allowed_roots
            ):
                errors.append(f"{label}: resolved path escapes its allowed owner: {relative}")
            elif not path.is_file():
                errors.append(f"{label}: missing page: {relative}")
            elif item.get("sha256") != _sha256(path):
                errors.append(f"{label}: SHA-256 drift for {relative}")
        if item.get("bucket") not in WIKI_BUCKETS:
            errors.append(f"{label}: invalid bucket {item.get('bucket')!r}")
        provenance = item.get("provenance")
        if not isinstance(provenance, list) or not provenance or not all(
            isinstance(value, str) and value.strip() for value in provenance
        ):
            errors.append(f"{label}: provenance must be a non-empty string list")
        elif any(value.lower().startswith(("chat.", "session.")) for value in provenance):
            errors.append(f"{label}: chat/session logs cannot be wiki provenance")
        tags = item.get("tags")
        if not isinstance(tags, list) or not all(isinstance(value, str) for value in tags):
            errors.append(f"{label}: tags must be a string list")
    return errors


class WikiService:
    """Loads one agent catalog and exposes bounded, read-only retrieval."""

    def __init__(self, root: Path | None = None, agent_id: str = "lyra") -> None:
        self.root = (root or Path(__file__).resolve().parents[1]).resolve()
        self.agent_id = agent_id
        errors = validate_wiki_catalog(self.root, agent_id)
        if errors:
            raise WikiError("invalid wiki catalog:\n" + "\n".join(errors))
        payload = json.loads(
            (self.root / "agents" / agent_id / "wiki" / "catalog.json").read_text(
                encoding="utf-8"
            )
        )
        self._pages = {
            item["page_id"]: WikiPage(
                page_id=item["page_id"],
                title=item["title"],
                path=item["path"],
                bucket=item["bucket"],
                tags=tuple(item["tags"]),
                provenance=tuple(item["provenance"]),
                sha256=item["sha256"],
            )
            for item in payload["pages"]
        }

    @property
    def page_ids(self) -> tuple[str, ...]:
        return tuple(sorted(self._pages))

    def _content(self, page: WikiPage) -> str:
        return _body((self.root / page.path).read_text(encoding="utf-8"))

    @staticmethod
    def _metadata(page: WikiPage) -> dict[str, Any]:
        return {
            "page_id": page.page_id,
            "title": page.title,
            "bucket": page.bucket,
            "path": page.path,
            "provenance": list(page.provenance),
            "sha256": page.sha256,
            "authority": "standing_reference",
            "epistemic_status": "reference_not_lived_memory",
            "usage_warning": "Do not present this page as a remembered interaction or invented anecdote.",
        }

    def search(self, query: str, limit: int = 5, bucket: str | None = None) -> dict[str, Any]:
        normalized = query.strip()
        if not normalized or len(normalized) > MAX_QUERY_CHARS:
            raise ValueError("Wiki query must contain 1-500 characters")
        if bucket is not None and bucket not in WIKI_BUCKETS:
            raise ValueError(f"Unknown wiki bucket: {bucket}")
        query_tokens = set(_tokens(normalized))
        scored: list[tuple[int, str, WikiPage, str]] = []
        for page in self._pages.values():
            if bucket is not None and page.bucket != bucket:
                continue
            content = self._content(page)
            title_tokens = _tokens(page.title)
            tag_tokens = _tokens(" ".join(page.tags))
            body_tokens = _tokens(content)
            score = sum(5 for token in query_tokens if token in title_tokens)
            score += sum(3 for token in query_tokens if token in tag_tokens)
            score += sum(min(body_tokens.count(token), 3) for token in query_tokens)
            if score:
                scored.append((score, page.page_id, page, content))
        scored.sort(key=lambda row: (-row[0], row[1]))
        results = []
        for score, _page_id, page, content in scored[: min(max(limit, 1), 10)]:
            item = self._metadata(page)
            item.update({"score": score, "excerpt": content[:MAX_EXCERPT_CHARS]})
            results.append(item)
        return {
            "query": normalized,
            "agent_id": self.agent_id,
            "retrieval": "lexical",
            "results": results,
        }

    def read(self, page_id: str) -> dict[str, Any]:
        try:
            page = self._pages[page_id]
        except KeyError as exc:
            raise WikiPageNotFound(
                f"Wiki page {page_id!r} is not available for agent {self.agent_id!r}"
            ) from exc
        item = self._metadata(page)
        content = self._content(page)
        item["content"] = content[:MAX_PAGE_CHARS]
        item["truncated"] = len(content) > MAX_PAGE_CHARS
        item["agent_id"] = self.agent_id
        return item


class WikiToolRouter:
    def __init__(self, service: WikiService) -> None:
        self.service = service

    def call_tool(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        if name == "wiki_search":
            return self.service.search(
                query=str(arguments["query"]),
                limit=int(arguments.get("limit", 5)),
                bucket=arguments.get("bucket"),
            )
        if name == "wiki_read":
            return self.service.read(str(arguments["page_id"]))
        raise ValueError(f"Unknown tool: {name}")
