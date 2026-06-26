"""Tests for the post-visit interview CLI tool (L-5 — previously untested).

Covers the input-parsing helpers and, importantly, the dynamic-SQL builders
(`save_updates`, `append_notes`) — asserting values are passed as bound
parameters, never interpolated into the query string.
"""
from contextlib import contextmanager

import pytest

from artcrm_interview_agent import interview


# ── input helpers ───────────────────────────────────────────────────────────

def _feed_inputs(monkeypatch, answers):
    """Make builtins.input return each item of `answers` in turn."""
    queued = iter(answers)
    monkeypatch.setattr("builtins.input", lambda *_args: next(queued))


def test_ask_returns_default_when_blank(monkeypatch):
    _feed_inputs(monkeypatch, [""])
    assert interview.ask("Date", default="2026-06-26") == "2026-06-26"


def test_ask_returns_entered_value(monkeypatch):
    _feed_inputs(monkeypatch, ["  hello  "])
    assert interview.ask("Note") == "hello"


def test_menu_selects_option(monkeypatch):
    _feed_inputs(monkeypatch, ["2"])
    assert interview.menu("pick", ["a", "b", "c"]) == "b"


def test_menu_skip_returns_none(monkeypatch):
    _feed_inputs(monkeypatch, ["0"])
    assert interview.menu("pick", ["a", "b"]) is None


def test_menu_reprompts_on_invalid_then_accepts(monkeypatch):
    _feed_inputs(monkeypatch, ["9", "x", "1"])
    assert interview.menu("pick", ["a", "b"]) == "a"


def test_multi_menu_parses_comma_list(monkeypatch):
    _feed_inputs(monkeypatch, ["1,3"])
    assert interview.multi_menu("pick", ["a", "b", "c"]) == ["a", "c"]


def test_multi_menu_skip_returns_empty(monkeypatch):
    _feed_inputs(monkeypatch, ["0"])
    assert interview.multi_menu("pick", ["a", "b"]) == []


# ── dynamic-SQL builders ─────────────────────────────────────────────────────

class _FakeCursor:
    def __init__(self, fetch_row=None):
        self.calls = []
        self._fetch_row = fetch_row

    def execute(self, sql, params=None):
        self.calls.append((sql, params))

    def fetchone(self):
        return self._fetch_row


class _FakeConn:
    def __init__(self, cursor):
        self._cursor = cursor

    def cursor(self):
        return self._cursor


def _patch_db(monkeypatch, cursor):
    @contextmanager
    def fake_db():
        yield _FakeConn(cursor)

    monkeypatch.setattr(interview, "db", fake_db)


def test_save_updates_noop_on_empty(monkeypatch):
    cursor = _FakeCursor()
    _patch_db(monkeypatch, cursor)
    interview.save_updates(1, {})
    assert cursor.calls == []  # early-returns without touching the DB


def test_save_updates_binds_values_as_parameters(monkeypatch):
    cursor = _FakeCursor()
    _patch_db(monkeypatch, cursor)

    # A value crafted to look like SQL must NOT end up in the query string.
    malicious_value = "x'; DROP TABLE contacts; --"
    interview.save_updates(42, {"status": "meeting", "email": malicious_value})

    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    # Column names (trusted keys) appear; the dangerous value does not.
    assert "status = %s" in sql and "email = %s" in sql
    assert malicious_value not in sql
    # The value is bound as a parameter, contact_id last.
    assert malicious_value in params
    assert params[-1] == 42
    assert sql.count("%s") == len(params)


def test_append_notes_prefixes_date_and_binds_params(monkeypatch):
    cursor = _FakeCursor(fetch_row={"notes": "old note"})
    _patch_db(monkeypatch, cursor)

    interview.append_notes(7, "met the owner")

    update_sql, update_params = cursor.calls[-1]
    combined = update_params[0]
    assert "old note" in combined and "met the owner" in combined
    assert combined.count("[") >= 1  # dated prefix added
    assert update_params[-1] == 7
    assert "met the owner" not in update_sql  # value bound, not interpolated
