"""
策略模块

提供策略基类和示例策略实现。
"""

from app.strategies.base import StrategyBase, Signal, SignalAction
from app.strategies.sma import SMAStrategy

__all__ = [
    "StrategyBase",
    "Signal",
    "SignalAction",
    "SMAStrategy",
]


# Lazy imports for LLM-related symbols (avoid circular import).
def __getattr__(name):
    if name in ("LLMAnalyzer", "LLMAnalyzerConfig", "LLMAnalysisResult", "LLMStrategy"):
        from app.strategies import llm_analyzer, llm_strategy
        if name in ("LLMAnalyzer", "LLMAnalyzerConfig", "LLMAnalysisResult"):
            return getattr(llm_analyzer, name)
        return getattr(llm_strategy, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
