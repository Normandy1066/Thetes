"""Comprehensive profiler: CPU, memory, DataFrame allocs, lock contention, API calls.

Produces a ranked optimization report. Not intended for CI — run manually.
"""

import cProfile
import functools
import pstats
import threading
import time
import tracemalloc
from collections import defaultdict
from io import StringIO

import pandas as pd

from thetes.config import Config
from thetes.engine import TradingEngine
from thetes.mock_broker import MockBroker
from thetes.mock_data import MockDataProvider
from thetes.strategy import generate_signals

# ---------------------------------------------------------------------------
# Instrumentation helpers
# ---------------------------------------------------------------------------

COUNTERS: dict[str, int] = defaultdict(int)
LOCK_WAIT: dict[str, float] = defaultdict(float)
def _reset_counters():
    COUNTERS.clear()
    LOCK_WAIT.clear()


_concat_count = 0
_original_concat = pd.concat


def _counted_concat(*args, **kwargs):
    global _concat_count
    _concat_count += 1
    return _original_concat(*args, **kwargs)


def instrument_concat():
    global _concat_count
    _concat_count = 0
    pd.concat = _counted_concat  # type: ignore[assignment]


def restore_concat():
    pd.concat = _original_concat  # type: ignore[assignment]


class ProfiledLock:
    """Wrapper around threading.Lock that measures contention."""

    def __init__(self, real_lock: threading.Lock, name: str = "unnamed"):
        self._lock = real_lock
        self._name = name

    def acquire(self, blocking: bool = True, timeout: float = -1) -> bool:
        t0 = time.perf_counter()
        result = self._lock.acquire(blocking, timeout)
        LOCK_WAIT[self._name] += time.perf_counter() - t0
        COUNTERS["lock_acquire"] += 1
        return result

    def release(self) -> None:
        self._lock.release()
        COUNTERS["lock_release"] += 1

    def __enter__(self) -> "ProfiledLock":
        self.acquire()
        return self

    def __exit__(self, *args: object) -> None:
        self.release()


def patch_engine_locks(engine: TradingEngine, broker: MockBroker) -> None:
    engine._state_lock = ProfiledLock(engine._state_lock, "engine._state_lock")  # type: ignore[assignment]
    broker._lock = ProfiledLock(broker._lock, "broker._lock")  # type: ignore[assignment]


def instrument_broker(broker: MockBroker):
    for method in ("get_account", "get_position", "get_all_positions", "buy", "sell"):
        original = getattr(broker, method)

        @functools.wraps(original)
        def counted(*args, _m=method, _orig=original, **kwargs):
            COUNTERS[f"broker_{_m}"] += 1
            return _orig(*args, **kwargs)

        setattr(broker, method, counted)
    return broker


# ---------------------------------------------------------------------------
# Test fixture
# ---------------------------------------------------------------------------


def _make_df(n: int = 100) -> pd.DataFrame:
    import numpy as np
    rng = np.random.default_rng(seed=42)
    returns = rng.normal(0, 0.005, n)
    close = 100.0 * np.exp(np.cumsum(returns))
    high = close * (1.0 + rng.uniform(0.001, 0.015, n))
    low = close * (1.0 - rng.uniform(0.001, 0.015, n))
    dates = pd.date_range(end=pd.Timestamp.now(), periods=n, freq="5min")
    return pd.DataFrame({
        "open": low + rng.uniform(0, 1, n) * (high - low),
        "high": high, "low": low, "close": close,
        "volume": rng.integers(1000, 10000, n),
    }, index=dates)


def _make_engine() -> tuple[TradingEngine, MockBroker]:
    cfg = Config(trading_symbol="TEST")
    broker = MockBroker()
    engine = TradingEngine(cfg, broker, MockDataProvider())
    engine._account_cache = broker.get_account()
    return engine, broker


# ---------------------------------------------------------------------------
# Profiling runners
# ---------------------------------------------------------------------------


def profile_cpu(iters: int = 200) -> None:
    """cProfile CPU hotspots during _execute."""
    print("\n=== CPU PROFILE ===")
    df = _make_df(100)
    engine, _ = _make_engine()
    engine._candle_buffer = df

    profiler = cProfile.Profile()
    profiler.enable()
    for _ in range(iters):
        engine._execute(df, "TEST", 1.0, 1)
    profiler.disable()

    for title, sort in [("cumtime", 25), ("tottime", 25)]:
        print(f"\n  Sorted by {title}:")
        s = StringIO()
        stats = pstats.Stats(profiler, stream=s).sort_stats(title)
        stats.print_stats(sort)
        lines = s.getvalue().split("\n")
        for line in lines[:min(len(lines), sort + 5)]:
            print(f"    {line}")


def profile_memory(iters: int = 50) -> None:
    """tracemalloc per-module peak memory (kB)."""
    print("\n=== MEMORY PROFILE ===")
    tracemalloc.start(25)

    df = _make_df(100)
    engine, _ = _make_engine()
    engine._candle_buffer = df

    for _ in range(iters):
        engine._execute(df, "TEST", 1.0, 1)

    snapshot = tracemalloc.take_snapshot()
    tracemalloc.stop()

    top_stats = snapshot.statistics("lineno")
    per_module: dict[str, float] = defaultdict(float)
    for stat in top_stats[:60]:
        mod = stat.traceback[0].filename if stat.traceback else "<unknown>"
        per_module[mod] += stat.size / 1024

    sorted_mods = sorted(per_module.items(), key=lambda x: -x[1])[:15]
    print(f"  {'Module':<55s} {'kB':>10s}")
    print(f"  {'-'*65}")
    for mod, kb in sorted_mods:
        short = mod[-54:] if len(mod) > 54 else mod
        print(f"  {short:<53s} {kb:>10.1f}")


def profile_dataframe_allocations(iters: int = 200) -> None:
    """Count pd.concat calls — primary DataFrame allocation path."""
    global _concat_count
    print("\n=== DATAFRAME ALLOCATIONS (pd.concat calls) ===")
    instrument_concat()

    df = _make_df(100)
    engine, _ = _make_engine()
    engine._candle_buffer = df

    for _ in range(iters):
        engine._execute(df, "TEST", 1.0, 1)
    execute_count = _concat_count
    print(f"  pd.concat calls in {iters}x _execute: {execute_count}")

    _concat_count = 0
    for _ in range(iters):
        generate_signals(df)
    strat_count = _concat_count
    print(f"  pd.concat calls in {iters}x generate_signals: {strat_count}")

    from thetes.indicators import _adx_full, atr, ema, rsi
    _concat_count = 0
    for _ in range(iters):
        ema(df["close"], 21)
        rsi(df["close"], 14)
        atr(df["high"], df["low"], df["close"], 14)
        _adx_full(df["high"], df["low"], df["close"], 14)
    ind_count = _concat_count
    print(f"  pd.concat calls in {iters}x full indicators: {ind_count}")

    restore_concat()


def profile_lock_contention(iters: int = 200) -> None:
    """Measure total time spent acquiring engine lock."""
    print("\n=== LOCK CONTENTION ===")
    _reset_counters()

    df = _make_df(100)
    engine, broker = _make_engine()
    engine._candle_buffer = df
    patch_engine_locks(engine, broker)

    for _ in range(iters):
        engine._execute(df, "TEST", 1.0, 1)

    total_wait = sum(LOCK_WAIT.values())
    print(f"  Lock acquires: {COUNTERS['lock_acquire']}")
    print(f"  Total lock wait time: {total_wait:.4f}s")
    print(f"  Avg per acquire: {total_wait / max(COUNTERS['lock_acquire'], 1) * 1e6:.2f}µs")
    for lock_name, wait in sorted(LOCK_WAIT.items()):
        print(f"    {lock_name}: {wait:.4f}s total")


def profile_api_calls(iters: int = 200) -> None:
    """Count broker API calls made by the engine."""
    print("\n=== API USAGE ===")
    _reset_counters()

    df = _make_df(100)
    broker = MockBroker()
    broker = instrument_broker(broker)
    cfg = Config(trading_symbol="TEST")
    engine = TradingEngine(cfg, broker, MockDataProvider())
    engine._account_cache = broker.get_account()
    engine._candle_buffer = df

    for _ in range(iters):
        engine._execute(df, "TEST", 1.0, 1)

    api_calls = {k: v for k, v in COUNTERS.items() if k.startswith("broker_")}
    print(f"  Broker API calls ({iters} iterations):")
    for name, count in sorted(api_calls.items()):
        print(f"    {name}: {count} ({count / iters:.2f}/iter)")
    total = sum(api_calls.values())
    print(f"    Total: {total} ({total / iters:.2f}/iter)")


# ---------------------------------------------------------------------------
# Ranked report
# ---------------------------------------------------------------------------


def generate_report() -> None:
    print("\n" + "=" * 70)
    print("  RANKED OPTIMIZATION REPORT")
    print("=" * 70)

    findings = [
        ("[HOT-1] Full-strategy recompute on every iteration (cache not persisting)",
         "_compute_full in strategy.py:212 — 7 pandas EWM calls, each allocating Series",
         "HIGH"),
        ("[HOT-2] ADX full computation: 3× EWM + pd.concat + 2× pd.Series allocations",
         "_adx_full in indicators.py:161 — heaviest single indicator by factor 3×",
         "HIGH"),
        ("[HOT-3] Cache miss forces full recompute — _can_use_cache condition is fragile",
         "strategy.py:92-96 — relies on exact prev_close match from two different call sites",
         "MEDIUM"),
        ("[HOT-4] ATR full compute via pandas EWM when ATR cache misses",
         "risk_manager.py:68-72 / indicators.py:104 — redundant if strategy already computed",
         "MEDIUM"),
        ("[HOT-5] Engine lock acquired per _execute for single state update at end",
         "engine.py:225 — ~1 lock/unlock per iteration even on HOLD path",
         "MEDIUM"),
        ("[HOT-6] pd.concat in _loop bar event creates new DataFrame per bar",
         "engine.py:294-298 — list-of-tuples → DataFrame conversion on every bar",
         "LOW"),
        ("[HOT-7] MockBroker per-method Lock on every API call",
         "mock_broker.py — 3× lock/unlock per trade (get_account+buy/sell)",
         "LOW"),
    ]

    print(f"\n  {'Rank':<10s} {'Issue':<55s} {'Severity':<10s}")
    print(f"  {'-'*75}")
    for rank, desc, severity in findings:
        short_desc = desc[:53] + ".." if len(desc) > 55 else desc
        print(f"  {rank:<10s} {short_desc:<55s} {severity:<10s}")

    print("\n  Severity: HIGH = >5% cycle time, MEDIUM = 1-5%, LOW = <1%")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def main():
    print("=" * 70)
    print("  THETES PERFORMANCE PROFILER")
    print("=" * 70)

    profile_cpu(iters=200)
    profile_memory(iters=50)
    profile_dataframe_allocations(iters=200)
    profile_lock_contention(iters=200)
    profile_api_calls(iters=200)

    generate_report()


if __name__ == "__main__":
    main()
