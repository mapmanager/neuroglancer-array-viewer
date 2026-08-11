from __future__ import annotations

import argparse
import json
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import neuroglancer
import numpy as np
from neuroglancer.json_utils import json_encoder_default

from acqstore.acq_image import AcqImage
from acqstore.sample_data import ensure_sample_file

from acqimage_ng import NgVolumeData, acquisition_to_ng
from server import DATASETS, make_dataset


SOURCE_PREFIX = "direct-demo-"
RR30A_SAMPLE_ID = "rr30a-two-channel"
DATASET_KEYS = (*DATASETS, "long-2c", "long-1c", "rr30a")


def source_key(dataset_key: str) -> str:
    return f"{SOURCE_PREFIX}{dataset_key}"


def make_volume(dataset_key: str) -> neuroglancer.LocalVolume:
    ng_data = make_ng_data(dataset_key)
    return neuroglancer.LocalVolume(
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


def make_ng_data(dataset_key: str) -> NgVolumeData:
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
        )
    elif dataset_key == "long-1c":
        acquisition = AcqImage.from_array(
            make_gaussian_band_data(channels=1, y_count=30_000, x_count=100),
            axes=("C", "Y", "X"),
            source_id="ng-array-demo-long-1c",
        )
    elif dataset_key == "rr30a":
        acquisition = AcqImage(str(ensure_sample_file(RR30A_SAMPLE_ID)))
    else:
        raise ValueError(f"Unknown dataset: {dataset_key!r}")
    return acquisition_to_ng(acquisition)


def make_gaussian_band_data(
    *, channels: int, y_count: int, x_count: int, block_rows: int = 512
) -> np.ndarray:
    """Create ``C,Y,X`` uint16 data with smoothly curving Gaussian bands."""
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
    volumes: dict[str, neuroglancer.LocalVolume]
    volume_locks: dict[str, threading.Lock]

    @classmethod
    def get_volume(cls, key: str) -> neuroglancer.LocalVolume | None:
        dataset_key = key.removeprefix(SOURCE_PREFIX)
        if key == dataset_key or dataset_key not in DATASET_KEYS:
            return None
        with cls.volume_locks[key]:
            volume = cls.volumes.get(key)
            if volume is None:
                print(f"numpy-http: preparing {dataset_key!r}")
                volume = make_volume(dataset_key)
                cls.volumes[key] = volume
            return volume

    def end_headers(self) -> None:
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def do_GET(self) -> None:  # noqa: N802
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

    def _send_json(self, value: object) -> None:
        payload = json.dumps(
            value, default=json_encoder_default, separators=(",", ":")
        ).encode()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        self.wfile.write(payload)

    def log_message(self, fmt: str, *args: object) -> None:
        print(f'numpy-http: {fmt % args}')


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve the direct-JS NumPy milestone")
    parser.add_argument("--port", type=int, default=8001)
    args = parser.parse_args()
    Handler.volumes = {}
    Handler.volume_locks = {source_key(key): threading.Lock() for key in DATASET_KEYS}
    server = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    print(f"NumPy datasource: http://127.0.0.1:{args.port}/")
    for key in DATASET_KEYS:
        print(f"Neuroglancer source: python://volume/{source_key(key)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
