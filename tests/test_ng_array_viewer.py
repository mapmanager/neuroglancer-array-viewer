"""Tests for the public Python Neuroglancer application wrapper."""

from __future__ import annotations

import json
import builtins
import threading
import unittest
from unittest.mock import patch
from urllib.request import urlopen

import numpy as np
from acqstore.acq_image import AcqImage

from ng_viewer import (
    ChromePlacement,
    NgArrayViewer,
    NgConfig,
    ViewerLayout,
    ViewState,
)


class NgArrayViewerTests(unittest.TestCase):
    """Verify configuration, registration, state parsing, and lifecycle."""

    def test_config_serializes_agreed_defaults(self) -> None:
        """Keep navigation available while optional chrome defaults hidden."""
        config = NgConfig()

        self.assertEqual(config.chrome_placement, ChromePlacement.OVERLAY_TOP)
        self.assertEqual(
            config.to_json(),
            {
                "chromePlacement": "overlay_top",
                "showOptionsControl": True,
                "showZControl": True,
                "showScaleBar": False,
                "showAxisLines": False,
                "showDisplayDimensions": False,
                "showNativeLayoutButtons": False,
                "showChannelsControl": False,
                "showLayoutControl": False,
                "showDatasetControl": False,
                "showDiagnostics": False,
            },
        )

    def test_public_imports_and_packaged_frontend(self) -> None:
        """Keep the curated API importable and the one-process UI present."""
        from importlib.resources import files

        import ng_viewer

        self.assertIs(ng_viewer.NgArrayViewer, NgArrayViewer)
        self.assertTrue(files("ng_viewer").joinpath("static", "index.html").is_file())

    def test_view_state_uses_layout_enum_and_calibrated_ranges(self) -> None:
        """Parse the browser contract into immutable semantic objects."""
        state = ViewState.from_json(
            {
                "datasetId": "rr30a",
                "layout": "xy",
                "xyPhysicalBounds": [
                    {
                        "x": {"min": 1, "max": 2, "unit": "um"},
                        "y": {"min": 3, "max": 4, "unit": "um"},
                    }
                ],
                "physicalPosition": {"z": {"value": 5, "unit": "um"}},
            }
        )

        self.assertIs(state.layout, ViewerLayout.XY)
        self.assertEqual((state.x.minimum, state.x.maximum), (1, 2))
        self.assertEqual(state.z, 5)

    def test_rejects_duplicate_dataset_keys(self) -> None:
        """Fail clearly rather than replacing application-owned data."""
        acquisition = AcqImage.from_array(
            np.zeros((2, 3), dtype=np.uint16), axes=("Y", "X"), source_id="test"
        )
        viewer = NgArrayViewer()
        viewer.register_acqimage("sample", acquisition)

        with self.assertRaisesRegex(ValueError, "already registered"):
            viewer.register_acqimage("sample", acquisition)
        viewer.stop()

    def test_numpy_registration_does_not_import_acqstore(self) -> None:
        """Keep the core NumPy path independent of optional AcqStore."""
        original_import = builtins.__import__

        def guarded_import(name: str, *args: object, **kwargs: object) -> object:
            if name == "acqstore" or name.startswith("acqstore."):
                raise AssertionError("register_numpy imported AcqStore")
            return original_import(name, *args, **kwargs)

        viewer = NgArrayViewer()
        with patch("builtins.__import__", side_effect=guarded_import):
            viewer.register_numpy(
                "numpy-only",
                np.zeros((2, 3), dtype=np.uint16),
                axes=("Y", "X"),
            )
        viewer.stop()

    def test_instance_server_exposes_config_and_runtime_selection(self) -> None:
        """Publish per-instance state and revision live dataset replacement."""
        viewer = NgArrayViewer(port=0)
        viewer.register_numpy(
            "first", np.zeros((2, 3), dtype=np.uint16), axes=("Y", "X")
        )
        viewer.register_numpy(
            "second", np.ones((2, 3), dtype=np.uint16), axes=("Y", "X")
        )
        viewer.start()
        try:
            with urlopen(f"{viewer.transport_url}/api/app-state") as response:
                initial = json.load(response)
            with urlopen(viewer.viewer_url) as response:
                frontend = response.read().decode()
            viewer.select_dataset("second")
            with urlopen(f"{viewer.transport_url}/api/app-state") as response:
                replaced = json.load(response)
        finally:
            viewer.stop()

        self.assertEqual(initial["selectedDataset"], "first")
        self.assertIn("Neuroglancer Array Viewer", frontend)
        self.assertEqual(replaced["selectedDataset"], "second")
        self.assertGreater(replaced["revision"], initial["revision"])

    def test_callback_subscription_delivers_typed_state(self) -> None:
        """Deliver callbacks off-request and allow unsubscription."""
        viewer = NgArrayViewer()
        received: list[ViewState] = []
        ready = threading.Event()

        def callback(state: ViewState) -> None:
            received.append(state)
            ready.set()

        unsubscribe = viewer.subscribe_view_state(callback)
        viewer._dispatcher.publish(
            ViewState.from_json({"datasetId": "a", "layout": "xy"})
        )
        self.assertTrue(ready.wait(1))
        unsubscribe()
        viewer.stop()
        self.assertEqual(received[0].dataset_id, "a")


if __name__ == "__main__":
    unittest.main()
