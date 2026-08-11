"""Run the standalone iframe reference for synthetic Neuroglancer datasets."""

from __future__ import annotations

import argparse
import copy
import json
import re
import threading
import time
import webbrowser
from dataclasses import dataclass, field
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import neuroglancer
import numpy as np


ROOT = Path(__file__).resolve().parent
WEB_ROOT = ROOT / "web"
@dataclass(frozen=True)
class DatasetSpec:
    """Describe one synthetic iframe-reference dataset.

    Attributes:
        key: Stable dataset identifier.
        label: User-facing selector label.
        shape_zcyx: Natural NumPy shape in Z,C,Y,X order.
        scales_um: X, Y, and Z calibration in micrometers.
        colors: Initial per-channel LUT colors.
        patterns: Human-readable expected channel contents.
    """
    key: str
    label: str
    shape_zcyx: tuple[int, int, int, int]
    scales_um: tuple[float, float, float]
    colors: tuple[str, ...]
    patterns: tuple[str, ...]


DATASETS = {
    "a": DatasetSpec(
        "a", "Dataset A · 70Z × 2C × 1024²", (70, 2, 1024, 1024),
        (0.25, 0.25, 1.0), ("#00ff00", "#ff00ff"),
        ("moving filled circle plus horizontal ramp", "moving square ring plus diagonal stripes"),
    ),
    "b": DatasetSpec(
        "b", "Dataset B · 31Z × 1C × 512×768", (31, 1, 512, 768),
        (0.65, 0.40, 2.5), ("#00bfff",),
        ("moving cyan diamond plus vertical bars",),
    ),
    "c": DatasetSpec(
        "c", "Dataset C · 18Z × 3C × 640×384", (18, 3, 640, 384),
        (0.18, 0.55, 0.8), ("#ff3b30", "#34c759", "#0a84ff"),
        ("moving red disk", "moving green rectangle", "blue horizontal bands"),
    ),
}


def make_dataset(spec: DatasetSpec) -> np.ndarray:
    """Create visibly distinct uint16 data in natural Z,C,Y,X order.

    Args:
        spec: Synthetic dataset definition.

    Returns:
        Newly allocated uint16 array matching `spec.shape_zcyx`.
    """
    z_count, c_count, y_count, x_count = spec.shape_zcyx
    yy, xx = np.ogrid[:y_count, :x_count]
    data = np.empty(spec.shape_zcyx, dtype=np.uint16)
    for z in range(z_count):
        if spec.key == "a":
            cx, cy = 260 + z * 7, 390 + int(90 * np.sin(z / 8))
            circle = np.maximum(0, 1 - np.sqrt((xx - cx) ** 2 + (yy - cy) ** 2) / 180)
            data[z, 0] = np.clip((circle + xx / (x_count - 1) * 0.25) * 52000, 0, 65535)
            sx, sy = 690 - z * 5, 610 + int(70 * np.cos(z / 7))
            outer = (np.abs(xx - sx) < 150) & (np.abs(yy - sy) < 150)
            inner = (np.abs(xx - sx) < 95) & (np.abs(yy - sy) < 95)
            data[z, 1] = np.where(outer & ~inner, 54000, np.where(((xx + yy + z * 11) % 190) < 24, 15000, 500))
        elif spec.key == "b":
            cx, cy = 100 + z * 17, y_count // 2 + int(90 * np.sin(z / 4))
            diamond = np.maximum(0, 1 - (np.abs(xx - cx) + np.abs(yy - cy)) / 150)
            bars = ((xx + z * 9) % 120) < 18
            data[z, 0] = np.where(bars, 12000, 400) + (diamond * 50000).astype(np.uint16)
        else:
            cx, cy = 70 + z * 14, 130 + z * 15
            data[z, 0] = np.where((xx - cx) ** 2 + (yy - cy) ** 2 < 70**2, 52000, 300)
            rx, ry = x_count - 80 - z * 9, y_count // 2 + int(120 * np.sin(z / 3))
            data[z, 1] = np.where((np.abs(xx - rx) < 55) & (np.abs(yy - ry) < 100), 47000, 500)
            data[z, 2] = np.where(((yy + z * 13) % 105) < 22, 38000, 250)
    return data.astype(np.uint16, copy=False)


@dataclass
class RequestedState:
    """Track control-page state requested by the user."""
    dataset: str = "a"
    z: int = 35
    mode: str = "composite"
    channel_mins: list[int] = field(default_factory=lambda: [0, 0])
    channel_maxs: list[int] = field(default_factory=lambda: [55000, 55000])
    channel_colors: list[str] = field(default_factory=lambda: ["#00ff00", "#ff00ff"])
    scale_bar: bool = True
    axis_lines: bool = False


class Demo:
    """Own the iframe Neuroglancer viewer and its transactional state."""

    def __init__(self) -> None:
        """Create the initial Dataset A viewer and register state observation."""
        self.viewer = neuroglancer.Viewer()
        self.requested = RequestedState()
        self.spec = DATASETS[self.requested.dataset]
        self.data_zcyx = make_dataset(self.spec)
        self.data_cxyz = self.data_zcyx.transpose(1, 3, 2, 0)
        self.volume: Any = None
        self.dataset_revision = 1
        self.switch_count = 0
        self.requested_lock = threading.Lock()
        self.update_lock = threading.Lock()
        self.last_viewer_change = time.time()
        self._configure_once()
        self.viewer.shared_state.add_changed_callback(self._viewer_changed)

    def _viewer_changed(self) -> None:
        """Record native Neuroglancer changes for diagnostics."""
        self.last_viewer_change = time.time()

    @staticmethod
    def _dimension_names(state: Any) -> list[str]:
        """Return coordinate names from a Neuroglancer state object.

        Args:
            state: Neuroglancer viewer state.

        Returns:
            Ordered coordinate names.
        """
        return [str(name) for name in state.dimensions.names]

    @classmethod
    def _spatial_axis_index(cls, state: Any, name: str) -> int:
        """Resolve a named spatial dimension.

        Args:
            state: Neuroglancer viewer state.
            name: Required coordinate name.

        Returns:
            Coordinate index.

        Raises:
            RuntimeError: If the named coordinate is absent.
        """
        names = cls._dimension_names(state)
        try:
            return names.index(name)
        except ValueError as exc:
            raise RuntimeError(
                f"Viewer position has dimensions {names!r}; expected spatial axis {name!r}"
            ) from exc

    @staticmethod
    def _color_vector(value: str) -> str:
        """Convert a CSS hexadecimal color to a GLSL vector.

        Args:
            value: Six-digit CSS hexadecimal color.

        Returns:
            GLSL `vec3` expression.

        Raises:
            ValueError: If the color is not six-digit hexadecimal.
        """
        if not re.fullmatch(r"#[0-9a-fA-F]{6}", value):
            raise ValueError(f"Invalid RGB color: {value!r}")
        rgb = [int(value[i : i + 2], 16) / 255 for i in (1, 3, 5)]
        return f"vec3({rgb[0]:.8f}, {rgb[1]:.8f}, {rgb[2]:.8f})"

    @classmethod
    def _shader(cls, r: RequestedState) -> str:
        """Build the iframe layer shader from requested channel controls.

        Args:
            r: Requested display state.

        Returns:
            Neuroglancer GLSL shader source.
        """
        # Current upstream represents uint16 samples as its own uint16_t GLSL struct.
        # toNormalized is the supported conversion and maps uint16 to [0, 1].
        def channel(name: str, index: int, low: int, high: int) -> str:
            """Build one normalized uint16 channel expression.

            Args:
                name: GLSL local variable name.
                index: Source channel index.
                low: Lower contrast bound.
                high: Upper contrast bound.

            Returns:
                GLSL statement defining the normalized channel.
            """
            low_n = low / 65535
            width_n = max(1, high - low) / 65535
            return (
                f"float {name} = clamp((toNormalized(getDataValue({index})) - "
                f"{low_n:.10f}) / {width_n:.10f}, 0.0, 1.0);"
            )

        channel_lines = [
            channel(f"c{i}", i, r.channel_mins[i], r.channel_maxs[i])
            for i in range(len(r.channel_colors))
        ]
        color_vectors = [cls._color_vector(color) for color in r.channel_colors]
        if re.fullmatch(r"c\d+", r.mode):
            index = int(r.mode[1:])
            rgb = f"c{index} * {color_vectors[index]}"
        else:
            terms = [f"c{i} * {color}" for i, color in enumerate(color_vectors)]
            rgb = f"clamp({' + '.join(terms)}, 0.0, 1.0)"
        return "\n".join(
            [
                "void main() {",
                *[f"  {line}" for line in channel_lines],
                f"  emitRGB({rgb});",
                "}",
            ]
        )

    def _configure_once(self) -> None:
        """Configure the initial dataset and supported native chrome."""
        with self.viewer.txn() as state:
            self._replace_dataset_state(state, self.spec, self.requested)
            state.show_scale_bar = self.requested.scale_bar
            state.show_axis_lines = self.requested.axis_lines
            state.show_default_annotations = False
        with self.viewer.config_state.txn() as config:
            config.show_ui_controls = False
            config.show_top_bar = False
            config.show_location = False
            config.show_layer_panel = False
            config.show_help_button = False
            config.show_settings_button = False
            config.show_panel_borders = False

    def _replace_dataset_state(
        self, state: Any, spec: DatasetSpec, requested: RequestedState
    ) -> None:
        """Replace dataset, coordinate, layer, and navigation state.

        Args:
            state: Open Neuroglancer transaction state.
            spec: Dataset being installed.
            requested: Requested display settings for the new dataset.
        """
        z_count, _, y_count, x_count = spec.shape_zcyx
        x_um, y_um, z_um = spec.scales_um
        volume_dimensions = neuroglancer.CoordinateSpace(
            names=["c^", "x", "y", "z"],
            units=["", "um", "um", "um"],
            scales=[1, x_um, y_um, z_um],
        )
        navigation_dimensions = neuroglancer.CoordinateSpace(
            names=["x", "y", "z"],
            units=["um", "um", "um"],
            scales=[x_um, y_um, z_um],
        )
        self.volume = neuroglancer.LocalVolume(
            data=self.data_cxyz,
            dimensions=volume_dimensions,
            volume_type="image",
        )
        state.dimensions = navigation_dimensions
        state.layers["dataset"] = neuroglancer.ImageLayer(
            source=self.volume,
            shader=self._shader(requested),
        )
        state.layout = "xy"
        state.position = [x_count / 2, y_count / 2, min(requested.z, z_count - 1)]

    @staticmethod
    def _default_requested(spec: DatasetSpec, presentation: RequestedState) -> RequestedState:
        """Construct dataset defaults while preserving presentation toggles.

        Args:
            spec: Newly selected dataset.
            presentation: Previous state supplying presentation toggles.

        Returns:
            Fresh requested state for `spec`.
        """
        z_count, c_count, _, _ = spec.shape_zcyx
        return RequestedState(
            dataset=spec.key,
            z=z_count // 2,
            mode="composite",
            channel_mins=[0] * c_count,
            channel_maxs=[55000] * c_count,
            channel_colors=list(spec.colors),
            scale_bar=presentation.scale_bar,
            axis_lines=presentation.axis_lines,
        )

    def update(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Snapshot requested state, then perform exactly one viewer transaction.

        No helper called inside `viewer.txn` acquires `requested_lock`. This
        structural rule fixes the v1 nested non-reentrant-lock deadlock.

        Args:
            payload: Partial requested-state update from the control page.

        Returns:
            Diagnostics after the successful transaction.

        Raises:
            ValueError: If a dataset, channel, mode, or value is invalid.
        """
        if not isinstance(payload, dict):
            raise ValueError("JSON request body must be an object")

        # Serialize HTTP mutations. Build a prospective snapshot without changing the
        # reported requested state; publish it only after the NG transaction succeeds.
        with self.update_lock:
            with self.requested_lock:
                snapshot = copy.deepcopy(self.requested)
            switching = "dataset" in payload
            old_dataset = (self.spec, self.data_zcyx, self.data_cxyz, self.volume)
            if switching:
                key = str(payload["dataset"])
                if key not in DATASETS:
                    raise ValueError(f"Unknown dataset: {key!r}")
                new_spec = DATASETS[key]
                snapshot = self._default_requested(new_spec, snapshot)
                self.spec = new_spec
                self.data_zcyx = make_dataset(new_spec)
                self.data_cxyz = self.data_zcyx.transpose(1, 3, 2, 0)
            if "z" in payload:
                snapshot.z = max(
                    0, min(self.spec.shape_zcyx[0] - 1, int(payload["z"]))
                )
            if "mode" in payload:
                valid_modes = {"composite"} | {
                    f"c{i}" for i in range(self.spec.shape_zcyx[1])
                }
                if payload["mode"] not in valid_modes:
                    raise ValueError(f"Invalid display mode: {payload['mode']!r}")
                snapshot.mode = payload["mode"]
            if "channel" in payload:
                channel_index = int(payload["channel"])
                if not 0 <= channel_index < self.spec.shape_zcyx[1]:
                    raise ValueError(f"Invalid channel index: {channel_index}")
                if "min" in payload:
                    snapshot.channel_mins[channel_index] = max(
                        0, min(65535, int(payload["min"]))
                    )
                if "max" in payload:
                    snapshot.channel_maxs[channel_index] = max(
                        0, min(65535, int(payload["max"]))
                    )
                if "color" in payload:
                    value = str(payload["color"]).lower()
                    self._color_vector(value)
                    snapshot.channel_colors[channel_index] = value
            if "scale_bar" in payload:
                snapshot.scale_bar = bool(payload["scale_bar"])
            if "axis_lines" in payload:
                snapshot.axis_lines = bool(payload["axis_lines"])

            try:
                with self.viewer.txn() as state:
                    if switching:
                        self._replace_dataset_state(state, self.spec, snapshot)
                        state.show_scale_bar = snapshot.scale_bar
                        state.show_axis_lines = snapshot.axis_lines
                        state.show_default_annotations = False
                    elif "z" in payload:
                        position = list(state.position)
                        position[self._spatial_axis_index(state, "z")] = snapshot.z
                        state.position = position
                    if not switching and any(
                        key in payload for key in ("mode", "channel")
                    ):
                        state.layers["dataset"].shader = self._shader(snapshot)
                    if "scale_bar" in payload:
                        state.show_scale_bar = snapshot.scale_bar
                    if "axis_lines" in payload:
                        state.show_axis_lines = snapshot.axis_lines
            except Exception:
                if switching:
                    self.spec, self.data_zcyx, self.data_cxyz, self.volume = old_dataset
                raise

            with self.requested_lock:
                self.requested = snapshot
            if switching:
                self.dataset_revision += 1
                self.switch_count += 1
        return self.diagnostics()

    def diagnostics(self) -> dict[str, Any]:
        """Return requested, actual, and dataset diagnostic state.

        Returns:
            JSON-compatible diagnostic snapshot.
        """
        with self.requested_lock:
            requested = vars(copy.deepcopy(self.requested))
        state = self.viewer.state
        position = [float(x) for x in state.position]
        dimension_names = self._dimension_names(state)
        z_index = self._spatial_axis_index(state, "z")
        return {
            "requested": requested,
            "actual": {
                "position": position,
                "dimensionNames": dimension_names,
                "z": position[z_index],
                "layout": state.layout.to_json(),
                "showScaleBar": state.show_scale_bar,
                "showAxisLines": state.show_axis_lines,
                "shader": state.layers["dataset"].shader,
                "viewerChangedAt": self.last_viewer_change,
            },
            "data": {
                "dataset": self.spec.key,
                "label": self.spec.label,
                "datasetRevision": self.dataset_revision,
                "switchCount": self.switch_count,
                "naturalShapeZCYX": list(self.data_zcyx.shape),
                "dtype": str(self.data_zcyx.dtype),
                "arrayBytes": int(self.data_zcyx.nbytes),
                "coordinateNames": ["c^", "x", "y", "z"],
                "units": ["", "um", "um", "um"],
                "scales": [1, *self.spec.scales_um],
                "transposeSharesMemory": bool(
                    np.shares_memory(self.data_zcyx, self.data_cxyz)
                ),
                "expectedPatterns": {
                    f"C{i}": pattern for i, pattern in enumerate(self.spec.patterns)
                },
            },
        }

    @staticmethod
    def dataset_catalog() -> list[dict[str, Any]]:
        """Return JSON-compatible metadata for iframe demo datasets.

        Returns:
            Dataset selector records.
        """
        return [
            {
                "key": spec.key,
                "label": spec.label,
                "shapeZCYX": list(spec.shape_zcyx),
                "scalesUm": list(spec.scales_um),
                "channelCount": spec.shape_zcyx[1],
            }
            for spec in DATASETS.values()
        ]


def make_handler(demo: Demo):
    """Create an HTTP request-handler class bound to one demo.

    Args:
        demo: Viewer instance served by every request handler.

    Returns:
        Configured `SimpleHTTPRequestHandler` subclass.
    """
    class Handler(SimpleHTTPRequestHandler):
        """Serve static iframe controls and their JSON state API."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            """Initialize a handler rooted at the project web directory."""
            super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

        def _json(self, value: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
            """Write one JSON response.

            Args:
                value: JSON-serializable response value.
                status: HTTP response status.
            """
            body = json.dumps(value, indent=2).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self) -> None:
            """Serve bootstrap/state endpoints or a static web asset."""
            path = urlparse(self.path).path
            if path == "/api/bootstrap":
                self._json(
                    {
                        "viewerUrl": demo.viewer.get_viewer_url(),
                        "datasets": demo.dataset_catalog(),
                        **demo.diagnostics(),
                    }
                )
                return
            if path == "/api/state":
                self._json(demo.diagnostics())
                return
            super().do_GET()

        def do_POST(self) -> None:
            """Validate and apply a control-page state mutation."""
            if urlparse(self.path).path != "/api/state":
                self._json({"error": "not found"}, HTTPStatus.NOT_FOUND)
                return
            try:
                length = int(self.headers.get("Content-Length", "0"))
                payload = json.loads(self.rfile.read(length) or b"{}")
                self._json(demo.update(payload))
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._json({"error": str(exc)}, HTTPStatus.BAD_REQUEST)
            except Exception as exc:
                print(f"control-http update failed: {type(exc).__name__}: {exc}")
                self._json(
                    {"error": type(exc).__name__, "detail": str(exc)},
                    HTTPStatus.INTERNAL_SERVER_ERROR,
                )

        def log_message(self, fmt: str, *args: Any) -> None:
            """Log non-polling control requests.

            Args:
                fmt: Base request-handler format string.
                *args: Values interpolated into `fmt`.
            """
            if self.command == "GET" and urlparse(self.path).path == "/api/state":
                return
            print(f"control-http: {fmt % args}")

    return Handler


def main() -> None:
    """Parse command-line options and run the iframe control server."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    neuroglancer.set_server_bind_address(bind_address=args.host, bind_port=0)
    demo = Demo()
    server = ThreadingHTTPServer((args.host, args.port), make_handler(demo))
    url = f"http://{args.host}:{server.server_port}/"
    print(f"ng-array-demo v2: {url}")
    print(f"Neuroglancer iframe endpoint: {demo.viewer.get_viewer_url()}")
    if not args.no_browser:
        threading.Timer(0.5, lambda: webbrowser.open_new(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
