"""
LRU set-associative cache simulator.

Geometry:
  num_sets   = cache_size_bytes // (block_size_bytes * associativity)
  set_index  = block_address  % num_sets
  tag        = block_address // num_sets

LRU is maintained per set via an OrderedDict (oldest at front, newest at end).
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
from typing import List


@dataclass
class AccessRecord:
    address: int
    block_address: int
    set_index: int
    tag: int
    hit: bool


class CacheSimulator:
    def __init__(
        self,
        cache_size_bytes: int = 512,
        block_size_bytes: int = 64,
        associativity: int = 2,
    ) -> None:
        if cache_size_bytes <= 0 or block_size_bytes <= 0 or associativity <= 0:
            raise ValueError("All cache parameters must be positive integers.")
        if cache_size_bytes % (block_size_bytes * associativity) != 0:
            raise ValueError(
                "cache_size_bytes must be divisible by (block_size_bytes * associativity)."
            )

        self.cache_size_bytes = cache_size_bytes
        self.block_size_bytes = block_size_bytes
        self.associativity = associativity
        self.num_sets: int = cache_size_bytes // (block_size_bytes * associativity)

        self._sets: List[OrderedDict[int, None]] = [
            OrderedDict() for _ in range(self.num_sets)
        ]

        self.hits: int = 0
        self.misses: int = 0
        self.access_log: List[AccessRecord] = []

    # ------------------------------------------------------------------
    # Core operation
    # ------------------------------------------------------------------

    def access(self, address: int) -> bool:
        """Simulate one memory access. Returns True on hit, False on miss."""
        block_address = address // self.block_size_bytes
        set_index = block_address % self.num_sets
        tag = block_address // self.num_sets

        cache_set = self._sets[set_index]

        if tag in cache_set:
            cache_set.move_to_end(tag)
            hit = True
            self.hits += 1
        else:
            hit = False
            self.misses += 1
            if len(cache_set) >= self.associativity:
                cache_set.popitem(last=False)
            cache_set[tag] = None

        self.access_log.append(
            AccessRecord(
                address=address,
                block_address=block_address,
                set_index=set_index,
                tag=tag,
                hit=hit,
            )
        )
        return hit

    # ------------------------------------------------------------------
    # Bulk helpers
    # ------------------------------------------------------------------

    def access_many(self, addresses: List[int]) -> None:
        """Simulate a sequence of memory accesses."""
        for addr in addresses:
            self.access(addr)

    # ------------------------------------------------------------------
    # Statistics
    # ------------------------------------------------------------------

    @property
    def total_accesses(self) -> int:
        return self.hits + self.misses

    @property
    def hit_rate(self) -> float:
        return self.hits / self.total_accesses if self.total_accesses else 0.0

    @property
    def miss_rate(self) -> float:
        return 1.0 - self.hit_rate

    def stats(self) -> dict:
        return {
            "hits": self.hits,
            "misses": self.misses,
            "total_accesses": self.total_accesses,
            "hit_rate": round(self.hit_rate, 6),
            "miss_rate": round(self.miss_rate, 6),
            "cache_size_bytes": self.cache_size_bytes,
            "block_size_bytes": self.block_size_bytes,
            "associativity": self.associativity,
            "num_sets": self.num_sets,
        }

    def reset(self) -> None:
        """Clear all cache state and counters."""
        self._sets = [OrderedDict() for _ in range(self.num_sets)]
        self.hits = 0
        self.misses = 0
        self.access_log = []

    # ------------------------------------------------------------------
    # Access-log serialisation (for API / heatmap)
    # ------------------------------------------------------------------

    def access_log_as_dicts(self, max_records: int = 4096) -> List[dict]:
        """Return access log as plain dicts, capped at max_records."""
        records = self.access_log[:max_records]
        return [
            {
                "address": r.address,
                "block_address": r.block_address,
                "set_index": r.set_index,
                "tag": r.tag,
                "hit": r.hit,
            }
            for r in records
        ]

    def __repr__(self) -> str:  # pragma: no cover
        return (
            f"CacheSimulator(size={self.cache_size_bytes}B, "
            f"block={self.block_size_bytes}B, "
            f"assoc={self.associativity}, "
            f"sets={self.num_sets}, "
            f"hit_rate={self.hit_rate:.2%})"
        )
