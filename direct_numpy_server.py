"""Serve AcqImage-backed NumPy volumes and direct-viewer state callbacks."""

from __future__ import annotations

import argparse
import logging
import threading
from dataclasses import dataclass

import numpy as np

from acqstore.acq_image import AcqImage
from acqstore.sample_data import ensure_sample_file

from ng_viewer import NgArrayViewer, NgConfig, ViewState
from ng_viewer.acqimage import NgVolumeData, acquisition_to_ng


@dataclass(frozen=True)
class DatasetSpec:
    """Describe one synthetic development dataset."""

    key: str
    shape_zcyx: tuple[int, int, int, int]
    scales_um: tuple[float, float, float]


DATASETS = {
    "a": DatasetSpec("a", (70, 2, 1024, 1024), (0.25, 0.25, 1.0)),
    "b": DatasetSpec("b", (31, 1, 512, 768), (0.65, 0.40, 2.5)),
    "c": DatasetSpec("c", (18, 3, 640, 384), (0.18, 0.55, 0.8)),
}


def make_dataset(spec: DatasetSpec) -> np.ndarray:
    """Create visibly distinct uint16 data in Z,C,Y,X order.

    Args:
        spec: Synthetic dataset definition.

    Returns:
        Newly allocated array matching ``spec.shape_zcyx``.
    """
    z_count, _, y_count, x_count = spec.shape_zcyx
    yy, xx = np.ogrid[:y_count, :x_count]
    data = np.empty(spec.shape_zcyx, dtype=np.uint16)
    for z in range(z_count):
        if spec.key == "a":
            cx, cy = 260 + z * 7, 390 + int(90 * np.sin(z / 8))
            circle = np.maximum(0, 1 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / 180)
            data[z, 0] = np.clip((circle + xx / (x_count - 1) * 0.25) * 52_000, 0, 65_535)
            sx, sy = 690 - z * 5, 610 + int(70 * np.cos(z / 7))
            outer = (np.abs(xx - sx) < 150) & (np.abs(yy - sy) < 150)
            inner = (np.abs(xx - sx) < 95) & (np.abs(yy - sy) < 95)
            data[z, 1] = np.where(outer & ~inner, 54_000, np.where(((xx + yy + z * 11) % 190) < 24, 15_000, 500))
        elif spec.key == "b":
            cx, cy = 100 + z * 17, y_count // 2 + int(90 * np.sin(z / 4))
            diamond = np.maximum(0, 1 - (np.abs(xx - cx) + np.abs(yy - cy)) / 150)
            data[z, 0] = np.where(((xx + z * 9) % 120) < 18, 12_000, 400) + (diamond * 50_000).astype(np.uint16)
        else:
            cx, cy = 70 + z * 14, 130 + z * 15
            data[z, 0] = np.where((xx - cx) ** 2 + (yy - cy) ** 2 < 70**2, 52_000, 300)
            rx, ry = x_count - 80 - z * 9, y_count // 2 + int(120 * np.sin(z / 3))
            data[z, 1] = np.where((np.abs(xx - rx) < 55) & (np.abs(yy - ry) < 100), 47_000, 500)
            data[z, 2] = np.where(((yy + z * 13) % 105) < 22, 38_000, 250)
    return data


RR30A_SAMPLE_ID = "rr30a-two-channel"
DATASET_KEYS = (*DATASETS, "long-2c", "long-1c", "rr30a")
LOGGER = logging.getLogger(__name__)


def configure_logging() -> None:
    """Configure concise source-aware logging for the standalone demo."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(filename)s | %(funcName)s | %(lineno)d | %(message)s",
        datefmt="%Y-%m-%d | %H:%M:%S",
    )


def make_ng_data(dataset_key: str) -> NgVolumeData:
    """Load or synthesize one acquisition and orient it for Neuroglancer.

    Args:
        dataset_key: Registered demo dataset identifier.

    Returns:
        Display-oriented uint16 pixels with coordinate calibration.

    Raises:
        ValueError: If the key or acquisition axes are unsupported.
    """
    if dataset_key in DATASETS:
        spec = DATASETS[dataset_key]
        data_czyx = make_dataset(spec).transpose(1, 0, 2, 3)
        x_um, y_um, z_um = spec.scales_um
        acquisition = AcqImage.from_array(
            data_czyx,
            axes=("C", "Z", "Y", "X"),
            source_id=f"ng-viewer-{dataset_key}",
            axis_spacing={"X": x_um, "Y": y_um, "Z": z_um},
            axis_units={"X": "um", "Y": "um", "Z": "um"},
        )
    elif dataset_key == "long-2c":
        acquisition = AcqImage.from_array(
            make_gaussian_band_data(channels=2, y_count=50_000, x_count=1_024),
            axes=("C", "Y", "X"),
            source_id="ng-viewer-long-2c",
            axis_spacing={"Y": 0.002, "X": 0.25},
            axis_units={"Y": "s", "X": "um"},
        )
    elif dataset_key == "long-1c":
        acquisition = AcqImage.from_array(
            make_gaussian_band_data(channels=1, y_count=30_000, x_count=100),
            axes=("C", "Y", "X"),
            source_id="ng-viewer-long-1c",
            axis_spacing={"Y": 0.002, "X": 0.25},
            axis_units={"Y": "s", "X": "um"},
        )
    elif dataset_key == "rr30a":
        acquisition = AcqImage(str(ensure_sample_file(RR30A_SAMPLE_ID)))
    else:
        raise ValueError(f"Unknown dataset: {dataset_key!r}")
    return acquisition_to_ng(acquisition)


def make_gaussian_band_data(
    *, channels: int, y_count: int, x_count: int, block_rows: int = 512
) -> np.ndarray:
    """Create C,Y,X uint16 data with smoothly curving Gaussian bands.

    Args:
        channels: Number of channels; currently one or two.
        y_count: Long source-Y dimension.
        x_count: Short source-X dimension.
        block_rows: Rows generated per temporary calculation block.

    Returns:
        Synthetic uint16 array in C,Y,X order.

    Raises:
        ValueError: If dimensions, block size, or channel count are invalid.
    """
    if channels not in {1, 2} or y_count <= 0 or x_count <= 0 or block_rows <= 0:
        raise ValueError("Expected 1/2 channels and positive Y, X, and block sizes")
    data = np.empty((channels, y_count, x_count), dtype=np.uint16)
    source_x = np.arange(x_count, dtype=np.float32)
    display_y = (x_count - 1) - source_x
    period = max(18.0, x_count / 7.5)
    sigma = max(2.5, period * 0.11)
    for start in range(0, y_count, block_rows):
        stop = min(start + block_rows, y_count)
        display_x = np.arange(start, stop, dtype=np.float32)[:, None]
        # A sinusoidal phase term makes the local band slope vary continuously
        # along the long displayed-X axis.
        bend = 0.22 * period * np.sin(2 * np.pi * display_x / max(2_000, y_count / 3))
        slope = (0.10 + 0.06 * np.sin(2 * np.pi * display_x / max(5_000, y_count))) * display_x
        for channel in range(channels):
            phase = display_y[None, :] - slope - bend - channel * period * 0.43
            distance = np.abs((phase + period / 2) % period - period / 2)
            bands = np.exp(-0.5 * (distance / sigma) ** 2)
            envelope = 0.82 + 0.18 * np.sin(
                2 * np.pi * display_x / max(3_000, y_count / 2) + channel
            )
            data[channel, start:stop] = np.clip(
                700 + bands * envelope * (52_000 - channel * 4_000), 0, 65_535
            ).astype(np.uint16)
    return data


def main() -> None:
    """Parse options and run the direct NumPy datasource server."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Serve frontend development datasets")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    viewer = NgArrayViewer(
        config=NgConfig(
            show_dataset_control=True,
            show_diagnostics=True,
            show_channels_control=True,
            show_layout_control=True,
        ),
        port=args.port,
    )
    for key in DATASET_KEYS:
        viewer.register_volume_data(key, lambda key=key: make_ng_data(key), name=key)
    unsubscribe = viewer.subscribe_view_state(log_typed_view_state)
    viewer.start()
    LOGGER.info("NumPy datasource: %s/", viewer.transport_url)
    for key in DATASET_KEYS:
        LOGGER.info("Neuroglancer source: python://volume/%s", key)
    try:
        threading.Event().wait()
    except KeyboardInterrupt:
        pass
    finally:
        unsubscribe()
        viewer.stop()


def log_typed_view_state(state: ViewState) -> None:
    """Log one typed public-wrapper state update.

    Args:
        state: Parsed semantic viewer state.
    """
    x = state.x
    y = state.y
    summary = "xy bounds unavailable"
    if x is not None and y is not None:
        summary = (
            f"x=[{x.minimum:.3f}, {x.maximum:.3f}] {x.unit or 'index'} "
            f"y=[{y.minimum:.3f}, {y.maximum:.3f}] {y.unit or 'index'}"
        )
    LOGGER.info(
        "view-state dataset=%s layout=%s z=%.3f %s %s",
        state.dataset_id,
        state.layout.value,
        state.z or 0,
        state.z_unit or "index",
        summary,
    )


if __name__ == "__main__":
    main()
