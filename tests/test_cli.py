"""
Tests for Phase 4: CLI commands (list, revise, demo, --search-provider, --no-clarify).
Uses typer.testing.CliRunner — no live API calls.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from src.cli import app

runner = CliRunner()

FIXTURES = Path(__file__).parent / "fixtures"
CONFIG_DIR = Path(__file__).parent.parent / "config"


# ---------------------------------------------------------------------------
# demo
# ---------------------------------------------------------------------------

def test_demo_exits_zero():
    result = runner.invoke(app, ["demo"])
    assert result.exit_code == 0, result.output


def test_demo_output_contains_adr(tmp_path):
    result = runner.invoke(app, ["demo"])
    assert "ADR" in result.output


# ---------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------

def test_list_missing_dir_exits_zero(tmp_path):
    result = runner.invoke(app, ["list", "--dir", str(tmp_path / "nonexistent")])
    assert result.exit_code == 0
    assert "No decisions found" in result.output


def test_list_empty_dir_exits_zero(tmp_path):
    result = runner.invoke(app, ["list", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "No ADR files found" in result.output


def test_list_shows_adr_entry(tmp_path):
    content = (
        "# ADR-0001: Choose a database\n\n"
        "**Status:** Accepted\n"
        "**Date:** 2025-01-15\n"
    )
    (tmp_path / "ADR-0001-database.md").write_text(content)
    result = runner.invoke(app, ["list", "--dir", str(tmp_path)])
    assert result.exit_code == 0
    assert "ADR-0001" in result.output
    assert "Choose a database" in result.output


def test_list_respects_last_flag(tmp_path):
    for i in range(1, 6):
        (tmp_path / f"ADR-{i:04d}-decision-{i}.md").write_text(
            f"# ADR-{i:04d}: Decision {i}\n\n**Status:** Proposed\n**Date:** 2025-01-{i:02d}\n"
        )
    result = runner.invoke(app, ["list", "--dir", str(tmp_path), "--last", "2"])
    assert result.exit_code == 0
    assert "ADR-0005" in result.output
    assert "ADR-0004" in result.output
    assert "ADR-0001" not in result.output


# ---------------------------------------------------------------------------
# revise
# ---------------------------------------------------------------------------

def test_revise_missing_file_exits_nonzero(tmp_path):
    result = runner.invoke(app, ["revise", str(tmp_path / "nonexistent.md")])
    assert result.exit_code != 0
    assert "not found" in result.output.lower() or "error" in result.output.lower()


def test_revise_empty_request_does_nothing(tmp_path):
    adr = tmp_path / "ADR-0001-test.md"
    original = "# ADR-0001: Test\n\n**Status:** Proposed\n"
    adr.write_text(original)
    result = runner.invoke(app, ["revise", str(adr)], input="\n")
    assert result.exit_code == 0
    assert "nothing changed" in result.output.lower()
    assert adr.read_text() == original


# ---------------------------------------------------------------------------
# run --search-provider validation
# ---------------------------------------------------------------------------

def test_run_invalid_search_provider_exits_nonzero():
    result = runner.invoke(
        app,
        ["run", "some problem", "--search-provider", "invalid-provider"],
    )
    assert result.exit_code != 0


# ---------------------------------------------------------------------------
# run --no-clarify (smoke: verifies flag is accepted)
# ---------------------------------------------------------------------------

def test_run_no_clarify_flag_accepted(tmp_path):
    """--no-clarify should be accepted without error (pipeline still runs via mock)."""
    import json
    from src.llm.mock_client import DEMO_PROBLEM

    # We invoke via runner which doesn't provide a real LLM key, so expect failure
    # at the LLM-creation stage — but the flag parsing should not itself raise.
    result = runner.invoke(
        app,
        ["run", DEMO_PROBLEM, "--no-clarify", "--dry-run"],
        catch_exceptions=True,
    )
    # The important check: no "No such option" or "Invalid value" for --no-clarify
    assert "--no-clarify" not in (result.output or "")
    assert "No such option" not in (result.output or "")
