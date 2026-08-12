"""Deterministic uint16 channel-contrast statistics.

Volume registration and contrast helpers accept **uint16** pixels only. A
fixed 65_536-bin histogram matches that domain without sorting large arrays.
"""

from __future__ import annotations

import numpy as np

# Default Auto contrast window: drop the darkest/brightest 1% so sparse hot
# pixels and dark-floor noise do not collapse the display range, while still
# covering nearly all of the observed intensity mass. Manual controls still
# expose the full observed (min, max) domain separately from this Auto window.
AUTO_PERCENTILES = (1.0, 99.0)


def uint16_channel_contrast(
    channel: np.ndarray,
    *,
    percentiles: tuple[float, float] = AUTO_PERCENTILES,
) -> tuple[tuple[int, int], tuple[int, int]]:
    """Return the observed domain and histogram-percentile contrast range.

    A fixed-size uint16 histogram avoids sorting or copying very large image
    channels. Percentile ranks use the nearest observed intensity at or above
    each requested cumulative count.

    Args:
        channel: NumPy array containing one uint16 image channel.
        percentiles: Low and high percentiles in the inclusive range 0–100.

    Returns:
        A pair containing `((observed_min, observed_max), (auto_min, auto_max))`.

    Raises:
        TypeError: If `channel` is not uint16.
        ValueError: If the channel is empty, percentile bounds are invalid, or
            the observed channel is constant.
    """
    values = np.asarray(channel)
    if values.dtype != np.uint16:
        raise TypeError(f"Expected uint16 channel data; received {values.dtype}")
    if values.size == 0:
        raise ValueError("Cannot calculate contrast for an empty channel")
    low_percentile, high_percentile = percentiles
    if not 0 <= low_percentile < high_percentile <= 100:
        raise ValueError(
            "Expected percentile bounds satisfying 0 <= low < high <= 100"
        )

    histogram = np.bincount(values.ravel(), minlength=65_536)
    populated = np.flatnonzero(histogram)
    observed_min = int(populated[0])
    observed_max = int(populated[-1])
    if observed_min == observed_max:
        raise ValueError(
            f"Cannot define a contrast interval for constant value {observed_min}"
        )

    cumulative = np.cumsum(histogram, dtype=np.int64)
    # Rank 0 is the first sample; ceil keeps non-zero percentiles from selecting
    # an intensity below their requested cumulative population.
    ranks = [
        max(0, int(np.ceil(percentile / 100 * values.size)) - 1)
        for percentile in percentiles
    ]
    auto_min, auto_max = (
        int(np.searchsorted(cumulative, rank + 1, side="left")) for rank in ranks
    )
    auto_min = max(observed_min, min(auto_min, observed_max - 1))
    auto_max = max(auto_min + 1, min(auto_max, observed_max))
    return (observed_min, observed_max), (auto_min, auto_max)


def volume_channel_contrast(
    data_cxyz: np.ndarray,
) -> tuple[list[list[int]], list[list[int]]]:
    """Calculate observed and automatic ranges for every C-axis channel.

    Args:
        data_cxyz: Contiguous or strided uint16 data in `C,X,Y,Z` order.

    Returns:
        Two JSON-ready lists: observed channel ranges and automatic ranges.

    Raises:
        TypeError: If the volume is not uint16.
        ValueError: If the array lacks a non-empty channel axis or contains a
            constant channel.
    """
    volume = np.asarray(data_cxyz)
    if volume.ndim != 4 or volume.shape[0] == 0:
        raise ValueError(
            f"Expected non-empty C,X,Y,Z data; received shape {volume.shape}"
        )
    domains: list[list[int]] = []
    automatic: list[list[int]] = []
    for channel in volume:
        domain, auto_range = uint16_channel_contrast(channel)
        domains.append(list(domain))
        automatic.append(list(auto_range))
    return domains, automatic
