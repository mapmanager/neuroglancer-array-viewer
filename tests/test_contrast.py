"""Tests for deterministic uint16 channel-contrast statistics."""

from __future__ import annotations

import unittest

import numpy as np

from ng_viewer.contrast import uint16_channel_contrast, volume_channel_contrast


class ContrastTests(unittest.TestCase):
    """Verify observed domains and automatic percentile windows."""

    def test_separates_observed_domain_from_percentile_range(self) -> None:
        """Ignore sparse outliers only in the automatic range."""
        values = np.concatenate(
            (
                np.array([0], dtype=np.uint16),
                np.full(98, 100, dtype=np.uint16),
                np.array([4_500], dtype=np.uint16),
            )
        )

        domain, automatic = uint16_channel_contrast(values)

        self.assertEqual(domain, (0, 4_500))
        self.assertEqual(automatic, (0, 100))

    def test_returns_json_ready_ranges_for_each_channel(self) -> None:
        """Preserve independent statistics for multiple channels."""
        volume = np.array(
            [
                [[[0, 10], [10, 20]]],
                [[[100, 200], [200, 300]]],
            ],
            dtype=np.uint16,
        )

        domains, automatic = volume_channel_contrast(volume)

        self.assertEqual(domains, [[0, 20], [100, 300]])
        self.assertEqual(automatic, [[0, 20], [100, 300]])

    def test_rejects_non_uint16_data(self) -> None:
        """Fail clearly instead of inferring another intensity domain."""
        with self.assertRaisesRegex(TypeError, "uint16"):
            uint16_channel_contrast(np.arange(4, dtype=np.uint8))

    def test_rejects_invalid_percentiles(self) -> None:
        """Reject reversed or equal percentile limits."""
        with self.assertRaisesRegex(ValueError, "low < high"):
            uint16_channel_contrast(
                np.arange(4, dtype=np.uint16),
                percentiles=(99, 1),
            )


if __name__ == "__main__":
    unittest.main()
