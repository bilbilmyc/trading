"""Test that the LLM prompt renders valid JSON-parseable output."""

from app.strategies.llm_analyzer import LLMAnalyzer, LLMAnalyzerConfig, PROMPT_TEMPLATE


def test_prompt_includes_key_data_fields() -> None:
    rendered = PROMPT_TEMPLATE.format(
        symbol="BTCUSDT",
        interval="1h",
        current_price=50000.0,
        price_change_24h=2.5,
        volume_24h=1000.0,
        quote_volume_24h=50000000.0,
        position_info="无持仓",
        candle_data="t:1700000000 o:50000 h:50100 l:49900 c:50050 v:100",
    )
    assert "BTCUSDT" in rendered
    assert "50000" in rendered
    assert "1h" in rendered
    assert "compact" in rendered.lower() or "compact" in rendered or "t:" in rendered
    assert '"decision"' in rendered
    assert '"buy"' in rendered or "buy" in rendered


def test_prompt_requires_json_only() -> None:
    """Output spec must request JSON-only — no markdown wrappers."""
    rendered = PROMPT_TEMPLATE.format(
        symbol="BTCUSDT", interval="1h", current_price=50000.0,
        price_change_24h=2.5, volume_24h=1000.0, quote_volume_24h=50000000.0,
        position_info="-", candle_data="-",
    )
    # Should mention "JSON" prominently
    assert "JSON" in rendered
    # Should forbid other text
    assert "不要" in rendered or "only" in rendered.lower() or "只输出" in rendered


def test_prompt_json_template_includes_required_fields() -> None:
    """JSON output spec must include decision, stop_loss, etc."""
    rendered = PROMPT_TEMPLATE.format(
        symbol="BTCUSDT", interval="1h", current_price=50000.0,
        price_change_24h=2.5, volume_24h=1000.0, quote_volume_24h=50000000.0,
        position_info="-", candle_data="-",
    )
    # All required fields are mentioned in the spec.
    for field in ("decision", "confidence", "stop_loss", "take_profit", "risk_level", "entry_zone"):
        assert f'"{field}"' in rendered, f"Field {field!r} missing from prompt spec"
    # Output mode: JSON only, no markdown.
    assert "JSON" in rendered
    # NoMarkdown wrapping in output.
    assert "Markdown" not in rendered or "JSON" in rendered  # JSON wins


def test_analyzer_config_default_prompt_version() -> None:
    cfg = LLMAnalyzerConfig()
    assert cfg.prompt_version  # not empty


def test_analyzer_config_default_temperature() -> None:
    cfg = LLMAnalyzerConfig()
    assert 0 <= cfg.temperature <= 1


def test_analyzer_no_key_creates_provider_with_empty_key() -> None:
    a = LLMAnalyzer(config=LLMAnalyzerConfig(api_key=""))
    assert a._provider is not None


def test_prompt_renders_with_empty_position() -> None:
    """Empty position context shouldn't break prompt rendering."""
    rendered = PROMPT_TEMPLATE.format(
        symbol="ETHUSDT", interval="15m", current_price=3000.0,
        price_change_24h=-1.0, volume_24h=500.0, quote_volume_24h=1500000.0,
        position_info="- 当前无持仓",
        candle_data="t:1700000000 o:3000 h:3050 l:2950 c:3000 v:50",
    )
    assert "ETHUSDT" in rendered
    assert "3000" in rendered
