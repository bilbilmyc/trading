"""Tests for the Ok/Err Result wrapper used at module boundaries."""

from __future__ import annotations

import pytest

from app.core.result import Err, Ok


def test_ok_is_ok_and_unwraps_value() -> None:
    r = Ok(42)
    assert r.is_ok()
    assert not r.is_err()
    assert r.unwrap() == 42


def test_ok_unwrap_or_returns_value() -> None:
    assert Ok("hello").unwrap_or("default") == "hello"


def test_err_is_err_and_unwrap_raises() -> None:
    r = Err("boom")
    assert not r.is_ok()
    assert r.is_err()
    with pytest.raises(RuntimeError, match="boom"):
        r.unwrap()


def test_err_unwrap_or_returns_default() -> None:
    assert Err("boom").unwrap_or("default") == "default"


def test_err_unwrap_err_returns_error() -> None:
    assert Err("boom").unwrap_err() == "boom"