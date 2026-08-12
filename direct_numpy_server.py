"""Serve AcqImage-backed NumPy volumes and direct-viewer state callbacks."""

from __future__ import annotations

import argparse
import json
import logging
import queue
import threading
from collections.abc import Callable
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import neuroglancer
import numpy as np
from neuroglancer.json_utils import json_encoder_default

from acqstore.acq_image import AcqImage
from acqstore.sample_data import ensure_sample_file

from ng_viewer import NgArrayViewer, NgConfig, ViewState
from ng_viewer.acqimage import NgVolumeData, acquisition_to_ng
from ng_viewer.contrast import volume_channel_contrast
from server import DATASETS, make_dataset


SOURCE_PREFIX = "direct-demo-"
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


class ViewStateDispatcher:
    """Dispatch direct-viewer state snapshots without blocking HTTP requests."""

    def __init__(self) -> None:
        """Start the single background callback-dispatch thread."""
        self._callbacks: set[Callable[[dict[str, object]], None]] = set()
        self._lock = threading.Lock()
        self._pending: queue.Queue[dict[str, object] | None] = queue.Queue(maxsize=1)
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def subscribe(
        self, callback: Callable[[dict[str, object]], None]
    ) -> Callable[[], None]:
        """Register a non-blocking view-state callback.

        Args:
            callback: Function invoked with the newest viewer-state snapshot.

        Returns:
            Function that unregisters `callback`.
        """
        with self._lock:
            self._callbacks.add(callback)

        def unsubscribe() -> None:
            """Remove this subscription from the dispatcher."""
            with self._lock:
                self._callbacks.discard(callback)

        return unsubscribe

    def publish(self, state: dict[str, object]) -> None:
        """Queue the newest snapshot, replacing an older pending snapshot.

        Args:
            state: JSON-compatible direct-viewer state.
        """
        try:
            self._pending.put_nowait(state)
        except queue.Full:
            try:
                self._pending.get_nowait()
            except queue.Empty:
                pass
            self._pending.put_nowait(state)

    def close(self) -> None:
        """Stop dispatching after any currently running callback finishes."""
        try:
            self._pending.put_nowait(None)
        except queue.Full:
            try:
                self._pending.get_nowait()
            except queue.Empty:
                pass
            self._pending.put_nowait(None)
        self._thread.join(timeout=1)

    def _run(self) -> None:
        """Dispatch queued snapshots until the close sentinel is received."""
        while (state := self._pending.get()) is not None:
            with self._lock:
                callbacks = tuple(self._callbacks)
            for callback in callbacks:
                try:
                    callback(state)
                except Exception as error:
                    LOGGER.exception("view-state callback failed: %s", error)


def source_key(dataset_key: str) -> str:
    """Return the Python datasource key for a dataset identifier.

    Args:
        dataset_key: Registered demo dataset identifier.

    Returns:
        Source key used by Neuroglancer's Python datasource protocol.
    """
    return f"{SOURCE_PREFIX}{dataset_key}"


def make_volume(dataset_key: str) -> tuple[neuroglancer.LocalVolume, dict[str, object]]:
    """Build one lazy Neuroglancer volume and its browser metadata.

    Args:
        dataset_key: Registered demo dataset identifier.

    Returns:
        The local volume and JSON-compatible dataset metadata.

    Raises:
        ValueError: If the dataset key is unknown or its pixels are invalid.
        TypeError: If the dataset does not contain uint16 pixels.
    """
    ng_data = make_ng_data(dataset_key)
    ranges, auto_ranges = volume_channel_contrast(ng_data.data_cxyz)
    volume = neuroglancer.LocalVolume(
        data=ng_data.data_cxyz,
        dimensions=neuroglancer.CoordinateSpace(
            names=["c^", "x", "y", "z"],
            units=list(ng_data.units),
            scales=list(ng_data.scales),
        ),
        volume_type="image",
        encoding="npz",
        downsampling=None,
    )
    return volume, {
        "key": dataset_key,
        "dtype": str(ng_data.data_cxyz.dtype),
        "shapeCXYZ": list(ng_data.data_cxyz.shape),
        "channelRanges": ranges,
        "channelAutoRanges": auto_ranges,
        "scales": list(ng_data.scales),
        "units": list(ng_data.units),
    }


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
            source_id=f"ng-array-demo-{dataset_key}",
            axis_spacing={"X": x_um, "Y": y_um, "Z": z_um},
            axis_units={"X": "um", "Y": "um", "Z": "um"},
        )
    elif dataset_key == "long-2c":
        acquisition = AcqImage.from_array(
            make_gaussian_band_data(channels=2, y_count=50_000, x_count=1_024),
            axes=("C", "Y", "X"),
            source_id="ng-array-demo-long-2c",
            axis_spacing={"Y": 0.002, "X": 0.25},
            axis_units={"Y": "s", "X": "um"},
        )
    elif dataset_key == "long-1c":
        acquisition = AcqImage.from_array(
            make_gaussian_band_data(channels=1, y_count=30_000, x_count=100),
            axes=("C", "Y", "X"),
            source_id="ng-array-demo-long-1c",
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


class Handler(BaseHTTPRequestHandler):
    """Serve lazy volumes, metadata, chunks, and viewer-state updates."""
    volumes: dict[str, neuroglancer.LocalVolume]
    volume_metadata: dict[str, dict[str, object]]
    volume_locks: dict[str, threading.Lock]
    view_states: ViewStateDispatcher

    @classmethod
    def get_volume(cls, key: str) -> neuroglancer.LocalVolume | None:
        """Return or lazily create a registered local volume.

        Args:
            key: Python datasource key from the request path.

        Returns:
            Cached volume, or None when `key` is unknown.
        """
        dataset_key = key.removeprefix(SOURCE_PREFIX)
        if key == dataset_key or dataset_key not in DATASET_KEYS:
            return None
        with cls.volume_locks[key]:
            volume = cls.volumes.get(key)
            if volume is None:
                LOGGER.info("preparing dataset=%s", dataset_key)
                volume, metadata = make_volume(dataset_key)
                cls.volumes[key] = volume
                cls.volume_metadata[key] = metadata
            return volume

    def end_headers(self) -> None:
        """Add local-development CORS and cache headers."""
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
        """Handle health, metadata, info, and chunk requests."""
        parts = urlparse(self.path).path.strip("/").split("/")
        try:
            if parts == ["api", "health"]:
                self._send_json(
                    {
                        "ok": True,
                        "sources": [
                            f"python://volume/{source_key(key)}" for key in DATASET_KEYS
                        ],
                    }
                )
                return
            if len(parts) == 3 and parts[:2] == ["api", "dataset"]:
                volume = self.get_volume(source_key(parts[2]))
                if volume is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_json(self.volume_metadata[source_key(parts[2])])
                return
            if len(parts) == 3 and parts[:2] == ["neuroglancer", "info"]:
                volume = self.get_volume(parts[2])
                if volume is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                self._send_json(volume.info())
                return
            if (
                len(parts) == 6
                and parts[0] == "neuroglancer"
                and parts[1] in {"raw", "npz"}
            ):
                _, data_format, key, scale_key, start_text, end_text = parts
                volume = self.get_volume(key)
                if volume is None:
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                start = np.array(start_text.split(","), dtype=np.int64)
                end = np.array(end_text.split(","), dtype=np.int64)
                payload, content_type = volume.get_encoded_subvolume(
                    data_format=data_format, start=start, end=end, scale_key=scale_key
                )
                self.send_response(HTTPStatus.OK)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
                return
        except (ValueError, IndexError) as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        except Exception as error:
            self.send_error(HTTPStatus.INTERNAL_SERVER_ERROR, str(error))
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        """Validate and publish a direct-viewer state snapshot."""
        if urlparse(self.path).path != "/api/view-state":
            self.send_error(HTTPStatus.NOT_FOUND)
            return
        try:
            content_length = int(self.headers.get("Content-Length", "0"))
            if content_length <= 0 or content_length > 1_000_000:
                raise ValueError("Expected a non-empty view-state JSON payload")
            state = json.loads(self.rfile.read(content_length))
            if not isinstance(state, dict):
                raise ValueError("Expected a JSON object")
            required = {"datasetId", "layout", "position", "xyBounds"}
            if not required.issubset(state):
                raise ValueError(f"Missing view-state fields: {sorted(required - state.keys())}")
        except (ValueError, json.JSONDecodeError) as error:
            self.send_error(HTTPStatus.BAD_REQUEST, str(error))
            return
        self.view_states.publish(state)
        self._send_json({"ok": True})

    def _send_json(self, value: object) -> None:
        """Write one successful JSON response.

        Args:
            value: JSON-serializable response value.
        """
        payload = json.dumps(
            value, default=json_encoder_default, separators=(",", ":")
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        """Log control requests while suppressing high-volume chunk traffic.

        Args:
            fmt: Base request-handler format string.
            *args: Values interpolated into `fmt`.
        """
        path = str(args[0]) if args else ""
        if "/neuroglancer/npz/" not in path and "/neuroglancer/raw/" not in path:
            LOGGER.info("http %s", fmt % args)


def main() -> None:
    """Parse options and run the direct NumPy datasource server."""
    configure_logging()
    parser = argparse.ArgumentParser(description="Serve the direct-JS NumPy milestone")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    viewer = NgArrayViewer(config=NgConfig(), port=args.port)
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


def log_view_state(state: dict[str, object]) -> None:
    """Log calibrated X/Y/Z state from the public callback contract.

    Args:
        state: Direct-viewer state containing physical position and XY bounds.
    """
    bounds = state.get("xyPhysicalBounds")
    panel = bounds[0] if isinstance(bounds, list) and bounds else None
    if isinstance(panel, dict):
        x = panel.get("x", {})
        y = panel.get("y", {})
        summary = (
            f"x=[{x.get('min', 0):.3f}, {x.get('max', 0):.3f}] {x.get('unit') or 'index'} "
            f"y=[{y.get('min', 0):.3f}, {y.get('max', 0):.3f}] {y.get('unit') or 'index'}"
        )
    else:
        summary = "xy bounds unavailable"
    physical_position = state.get("physicalPosition", {})
    z = physical_position.get("z", {}) if isinstance(physical_position, dict) else {}
    LOGGER.info(
        "view-state dataset=%s layout=%s z=%.3f %s %s",
        state.get("datasetId"),
        state.get("layout"),
        z.get("value", 0),
        z.get("unit") or "index",
        summary,
    )


if __name__ == "__main__":
    main()
