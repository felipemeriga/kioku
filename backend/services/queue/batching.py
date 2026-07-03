"""Generic batching helper for chunk fan-out."""

from __future__ import annotations

from typing import Iterator, TypeVar

T = TypeVar("T")


def into_batches(items: list[T], *, size: int) -> Iterator[list[T]]:
    """Yield consecutive slices of `items` of length up to `size`."""
    if size < 1:
        raise ValueError("batch size must be >= 1")
    for i in range(0, len(items), size):
        yield items[i : i + size]
