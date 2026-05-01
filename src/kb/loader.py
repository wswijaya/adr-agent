"""
loader.py — Knowledge base loader and keyword matcher.

KBLoader reads YAML pattern files and past ADR markdown files, then scores
options against intake keywords using Jaccard similarity. No vector DB
required — pure Python, zero extra dependencies.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Optional

import yaml

from ..models.adr import Domain

_DOMAIN_FILE_MAP: dict[Domain, str] = {
    Domain.DATA_PLATFORM: "data_platform.yaml",
    Domain.AI_MLOPS: "ai_mlops.yaml",
    Domain.INTEGRATION: "integration.yaml",
    Domain.GOVERNANCE: "governance.yaml",
}

# Heading pattern used to split ADR history files into per-option blocks.
_OPTION_HEADING = re.compile(r"###\s+Option\s+\d+:\s+(.+)", re.IGNORECASE)


class KBLoader:

    def __init__(self, kb_dir: Path) -> None:
        self._kb_dir = kb_dir
        self._pattern_dir = kb_dir / "patterns"
        self._history_dir = kb_dir / "adr_history"

    def load_patterns(self, domain: Optional[Domain] = None) -> list[dict]:
        """Load all options from YAML pattern files, filtered to domain if given."""
        if domain and domain in _DOMAIN_FILE_MAP:
            files = [_DOMAIN_FILE_MAP[domain]]
        else:
            files = list(_DOMAIN_FILE_MAP.values())

        options: list[dict] = []
        for fname in files:
            fpath = self._pattern_dir / fname
            if not fpath.exists():
                continue
            data = yaml.safe_load(fpath.read_text(encoding="utf-8")) or {}
            for opt in data.get("options", []):
                options.append({**opt, "from_kb": True})
        return options

    def load_adr_history(self) -> list[dict]:
        """Extract options from past ADR markdown files in adr_history/."""
        results: list[dict] = []
        if not self._history_dir.exists():
            return results
        for md_file in sorted(self._history_dir.glob("*.md")):
            try:
                results.extend(self._parse_adr_options(md_file))
            except Exception:
                pass  # Skip malformed files silently
        return results

    def keyword_match(
        self,
        options: list[dict],
        keywords: list[str],
        top_n: int = 5,
    ) -> list[dict]:
        """
        Score each option by Jaccard similarity between its tags and the
        intake keywords. Return the top_n options with score > 0.
        """
        kw_set = {k.lower() for k in keywords}
        scored: list[tuple[float, dict]] = []

        for option in options:
            tags = {t.lower() for t in option.get("tags", [])}
            score = _jaccard(tags, kw_set)
            if score > 0:
                scored.append((score, option))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [opt for _, opt in scored[:top_n]]

    @staticmethod
    def _parse_adr_options(path: Path) -> list[dict]:
        """Extract Option sections from a markdown ADR file."""
        text = path.read_text(encoding="utf-8")
        options: list[dict] = []

        # Split on option headings; capture everything until the next heading.
        parts = _OPTION_HEADING.split(text)
        # parts = [preamble, name1, body1, name2, body2, ...]
        for i in range(1, len(parts) - 1, 2):
            name = parts[i].strip()
            body = parts[i + 1].strip()
            # First non-empty paragraph is the summary.
            summary = next((p.strip() for p in body.split("\n\n") if p.strip()), "")
            options.append({
                "name": name,
                "summary": summary[:400],
                "tags": [],
                "from_kb": True,
                "source": path.name,
            })
        return options


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)
