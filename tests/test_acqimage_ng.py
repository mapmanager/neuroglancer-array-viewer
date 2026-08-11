from __future__ import annotations

import unittest

import numpy as np
from acqstore.acq_image import AcqImage

from acqimage_ng import acquisition_to_ng


class AcqImageNgTests(unittest.TestCase):
    def test_transpose_then_flip_y_and_swap_calibration(self) -> None:
        source_yx = np.arange(6, dtype=np.uint16).reshape(2, 3)
        acquisition = AcqImage.from_array(
            source_yx,
            axes=("Y", "X"),
            source_id="orientation-test",
            axis_spacing={"Y": 0.4, "X": 0.7},
            axis_units={"Y": "um", "X": "um"},
        )

        result = acquisition_to_ng(acquisition)

        self.assertEqual(result.data_cxyz.shape, (1, 2, 3, 1))
        np.testing.assert_array_equal(
            result.data_cxyz[0, :, :, 0],
            np.array([[2, 1, 0], [5, 4, 3]], dtype=np.uint16),
        )
        self.assertEqual(result.scales, (1.0, 0.4, 0.7, 1.0))
        self.assertEqual(result.units, ("", "um", "um", ""))
        self.assertTrue(result.data_cxyz.flags.c_contiguous)

    def test_reorders_zcyx_without_losing_channels_or_z(self) -> None:
        source = np.arange(2 * 2 * 3 * 4, dtype=np.uint16).reshape(2, 2, 3, 4)
        acquisition = AcqImage.from_array(
            source.transpose(1, 0, 2, 3),
            axes=("C", "Z", "Y", "X"),
            source_id="volume-test",
        )

        result = acquisition_to_ng(acquisition)

        self.assertEqual(result.data_cxyz.shape, (2, 3, 4, 2))
        expected_plane = source[1, 0].T[::-1, :]
        np.testing.assert_array_equal(result.data_cxyz[0, :, :, 1].T, expected_plane)


if __name__ == "__main__":
    unittest.main()
