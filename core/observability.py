"""
Per-turn latency observability for the AI Meeting Representative.

Tracks timestamps across the full pipeline:
  audio_received → asr_complete → mention_checked → rag_retrieved
  → llm_started → llm_first_sentence → tts_complete → turn_complete

Usage:
    tracker = TurnTracker(turn_id="abc123")
    tracker.mark("asr_complete")
    tracker.mark("rag_retrieved")
    ...
    tracker.log_summary()
"""

from __future__ import annotations

import logging
import time
import uuid
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger("observability")

# Ordered pipeline stages for latency computation
PIPELINE_STAGES = [
    "audio_received",
    "asr_complete",
    "mention_checked",
    "rag_retrieved",
    "llm_started",
    "llm_first_sentence",
    "tts_started",
    "tts_complete",
    "turn_complete",
]


class TurnTracker:
    """
    Tracks per-turn latency across the full AI pipeline.

    Each conversational turn gets a unique turn_id. Timestamps are
    recorded at each pipeline stage via `mark()`. At the end of the
    turn, `log_summary()` prints a structured latency breakdown.
    """

    def __init__(self, turn_id: Optional[str] = None) -> None:
        self.turn_id: str = turn_id or str(uuid.uuid4())[:8]
        self._start: float = time.perf_counter()
        self._wall_start: float = time.time()
        self._stages: Dict[str, float] = {}
        self._metadata: Dict[str, str] = {}

    def mark(self, stage: str) -> None:
        """Record a timestamp for a named pipeline stage."""
        self._stages[stage] = time.perf_counter()

    def set_metadata(self, key: str, value: str) -> None:
        """Attach metadata to this turn (e.g., speaker, text length)."""
        self._metadata[key] = value

    def elapsed_since(self, stage: str) -> float:
        """Return seconds elapsed since a specific stage, or -1 if not recorded."""
        ts = self._stages.get(stage)
        if ts is None:
            return -1.0
        return time.perf_counter() - ts

    def stage_latency(self, from_stage: str, to_stage: str) -> float:
        """Return seconds between two stages, or -1 if either is missing."""
        t1 = self._stages.get(from_stage)
        t2 = self._stages.get(to_stage)
        if t1 is None or t2 is None:
            return -1.0
        return t2 - t1

    def summary(self) -> Dict[str, float]:
        """
        Return a dict of computed latencies between consecutive pipeline stages.
        Keys are formatted as 'from_stage→to_stage'.
        """
        result: Dict[str, float] = {}
        recorded = [s for s in PIPELINE_STAGES if s in self._stages]

        for i in range(len(recorded) - 1):
            key = f"{recorded[i]}→{recorded[i+1]}"
            result[key] = self._stages[recorded[i+1]] - self._stages[recorded[i]]

        # Total end-to-end
        if recorded:
            result["total_e2e"] = self._stages[recorded[-1]] - self._start

        return result

    def log_summary(self) -> None:
        """Log the full turn latency breakdown at INFO level."""
        latencies = self.summary()
        if not latencies:
            logger.info(f"[turn={self.turn_id}] No stages recorded.")
            return

        lines: List[str] = [
            f"\n{'='*50}",
            f"  TURN LATENCY REPORT  [turn={self.turn_id}]",
            f"{'='*50}",
        ]

        if self._metadata:
            meta_str = " | ".join(f"{k}={v}" for k, v in self._metadata.items())
            lines.append(f"  Metadata: {meta_str}")

        for key, val in latencies.items():
            if key == "total_e2e":
                lines.append(f"  {'─'*46}")
                lines.append(f"  ⏱  TOTAL E2E       : {val:.3f}s")
            else:
                lines.append(f"  {key:<36}: {val:.3f}s")

        # Stage timestamps (relative to turn start)
        lines.append(f"  {'─'*46}")
        lines.append("  Stage Timestamps (relative to turn start):")
        for stage in PIPELINE_STAGES:
            ts = self._stages.get(stage)
            if ts is not None:
                lines.append(f"    {stage:<24}: +{ts - self._start:.3f}s")

        lines.append(f"{'='*50}\n")

        logger.info("\n".join(lines))


class LatencyAggregator:
    """
    Aggregates turn-level latency stats over a rolling window.
    Useful for detecting latency degradation trends.
    """

    def __init__(self, window_size: int = 20) -> None:
        self._window_size = window_size
        self._e2e_latencies: List[float] = []
        self._turn_count: int = 0

    def record_turn(self, tracker: TurnTracker) -> None:
        """Record a completed turn's E2E latency."""
        self._turn_count += 1
        total = tracker.stage_latency(
            PIPELINE_STAGES[0], PIPELINE_STAGES[-1]
        )
        if total < 0:
            # Fallback: use start to last recorded stage
            latencies = tracker.summary()
            total = latencies.get("total_e2e", -1.0)

        if total > 0:
            self._e2e_latencies.append(total)
            if len(self._e2e_latencies) > self._window_size:
                self._e2e_latencies.pop(0)

    def average_e2e(self) -> float:
        """Return average E2E latency over the rolling window."""
        if not self._e2e_latencies:
            return -1.0
        return sum(self._e2e_latencies) / len(self._e2e_latencies)

    def p95_e2e(self) -> float:
        """Return 95th percentile E2E latency over the rolling window."""
        if not self._e2e_latencies:
            return -1.0
        sorted_lat = sorted(self._e2e_latencies)
        idx = int(len(sorted_lat) * 0.95)
        idx = min(idx, len(sorted_lat) - 1)
        return sorted_lat[idx]

    def log_stats(self) -> None:
        """Log rolling latency statistics."""
        avg = self.average_e2e()
        p95 = self.p95_e2e()
        if avg < 0:
            return
        logger.info(
            f" Latency Stats (last {len(self._e2e_latencies)} turns): "
            f"avg={avg:.3f}s | p95={p95:.3f}s | total_turns={self._turn_count}"
        )   