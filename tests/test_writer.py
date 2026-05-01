"""
Tests for Phase 4: writer module.
Covers atomic writes, file-locked sequence allocation, and revision appending.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.agent.writer import append_revision, next_sequence, write_adr


# ---------------------------------------------------------------------------
# next_sequence
# ---------------------------------------------------------------------------

def test_next_sequence_empty_dir(tmp_path):
    assert next_sequence(tmp_path) == 1


def test_next_sequence_single_existing(tmp_path):
    (tmp_path / "ADR-0001-foo.md").write_text("x")
    assert next_sequence(tmp_path) == 2


def test_next_sequence_multiple_existing(tmp_path):
    (tmp_path / "ADR-0001-foo.md").write_text("x")
    (tmp_path / "ADR-0002-bar.md").write_text("x")
    assert next_sequence(tmp_path) == 3


def test_next_sequence_gap_picks_max_plus_one(tmp_path):
    (tmp_path / "ADR-0001-a.md").write_text("x")
    (tmp_path / "ADR-0005-b.md").write_text("x")
    assert next_sequence(tmp_path) == 6


def test_next_sequence_creates_dir(tmp_path):
    new_dir = tmp_path / "subdir" / "decisions"
    seq = next_sequence(new_dir)
    assert seq == 1
    assert new_dir.exists()


# ---------------------------------------------------------------------------
# write_adr
# ---------------------------------------------------------------------------

def test_write_adr_creates_file(tmp_path):
    out = tmp_path / "ADR-0001-test.md"
    result = write_adr("# Hello", out)
    assert result == out
    assert out.read_text() == "# Hello"


def test_write_adr_no_tmp_file_after(tmp_path):
    out = tmp_path / "ADR-0001-test.md"
    write_adr("# Hello", out)
    assert not (tmp_path / "ADR-0001-test.tmp").exists()


def test_write_adr_overwrites_existing(tmp_path):
    out = tmp_path / "ADR-0001-test.md"
    write_adr("old", out)
    write_adr("new", out)
    assert out.read_text() == "new"


def test_write_adr_creates_parent_dirs(tmp_path):
    out = tmp_path / "nested" / "ADR-0001-test.md"
    write_adr("content", out)
    assert out.exists()


# ---------------------------------------------------------------------------
# append_revision
# ---------------------------------------------------------------------------

def test_append_revision_adds_section(tmp_path):
    adr = tmp_path / "ADR-0001-test.md"
    write_adr("# ADR\n\nContent.", adr)
    append_revision(adr, "Updated the decision rationale")
    content = adr.read_text()
    assert "## Revision history" in content
    assert "Updated the decision rationale" in content


def test_append_revision_appends_to_existing_section(tmp_path):
    initial = "# ADR\n\n---\n\n## Revision history\n\n- 2025-01-01: First revision\n"
    adr = tmp_path / "ADR-0001-test.md"
    write_adr(initial, adr)
    append_revision(adr, "Second revision")
    content = adr.read_text()
    assert "First revision" in content
    assert "Second revision" in content


def test_append_revision_does_not_truncate(tmp_path):
    original_body = "# ADR\n\nThis is the original content.\n"
    adr = tmp_path / "ADR-0001-test.md"
    write_adr(original_body, adr)
    append_revision(adr, "Minor update")
    content = adr.read_text()
    assert "This is the original content." in content


def test_append_revision_multiple_entries_ordered(tmp_path):
    adr = tmp_path / "ADR-0001-test.md"
    write_adr("# ADR\n\nBody.", adr)
    append_revision(adr, "First change")
    append_revision(adr, "Second change")
    content = adr.read_text()
    first_pos = content.index("First change")
    second_pos = content.index("Second change")
    assert first_pos < second_pos
