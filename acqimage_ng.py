"""Small AcqImage-to-Neuroglancer boundary used only by the demo server."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np
from acqstore.acq_image import AcqImage, AcqPixels


@dataclass(frozen=True)
class NgVolumeData:
    """One display-oriented NumPy volume and its Neuroglancer coordinates.

    Attributes:
        data_cxyz: Contiguous uint16 volume in Neuroglancer C,X,Y,Z order.
        scales: Per-axis coordinate scale in C,X,Y,Z order.
        units: Per-axis Neuroglancer unit labels.
        source_axes: Original AcqImage axis names.
        source_shape: Original acquisition shape.
    """

    data_cxyz: np.ndarray
    scales: tuple[float, float, float, float]
    units: tuple[str, str, str, str]
    source_axes: tuple[str, ...]
    source_shape: tuple[int, ...]


def acq_pixels_to_ng(pixels: AcqPixels) -> NgVolumeData:
    """Materialize and orient AcqStore pixels as contiguous ``C,X,Y,Z``.

    Every source ``(Y, X)`` plane is transposed and then flipped along its new
    display-Y axis. Consequently, Neuroglancer X corresponds to source Y while
    Neuroglancer Y corresponds to reversed source X.

    Args:
        pixels: Loaded AcqStore pixels containing Y/X and optional C/Z axes.

    Returns:
        Display-oriented pixels and matching coordinate calibration.

    Raises:
        ValueError: If axes are repeated, unsupported, or omit Y/X.
    """
    source_axes = tuple(str(axis).upper() for axis in pixels.axes)
    if len(source_axes) != len(set(source_axes)):
        raise ValueError(f"AcqPixels axes must be unique; got {source_axes!r}")
    unsupported = set(source_axes) - {"C", "Z", "Y", "X"}
    if unsupported:
        raise ValueError(
            f"Direct demo supports C/Z/Y/X axes only; unsupported axes: {sorted(unsupported)}"
        )
    if "Y" not in source_axes or "X" not in source_axes:
        raise ValueError(f"AcqPixels must contain Y and X axes; got {source_axes!r}")

    source = np.asarray(pixels.get_array())
    ordered_present = tuple(axis for axis in ("C", "Z", "Y", "X") if axis in source_axes)
    source_czyx = source.transpose(tuple(source_axes.index(axis) for axis in ordered_present))
    if "C" not in source_axes:
        source_czyx = source_czyx[np.newaxis, ...]
    if "Z" not in source_axes:
        source_czyx = source_czyx[:, np.newaxis, ...]

    # Equivalent on each plane to: display_yx = source_yx.T[::-1, :].
    # LocalVolume is indexed C,X,Y,Z, so the transpose back into named axes
    # leaves source Y as display X and reversed source X as display Y.
    display_czyx = np.flip(source_czyx.swapaxes(-2, -1), axis=-2)
    data_cxyz = np.ascontiguousarray(display_czyx.transpose(0, 3, 2, 1))

    spacing = _axis_values(pixels, pixels.header.physical_units, default=1.0)
    labels = _axis_values(pixels, pixels.header.physical_units_labels, default="")
    return NgVolumeData(
        data_cxyz=data_cxyz,
        scales=(1.0, float(spacing["Y"]), float(spacing["X"]), float(spacing.get("Z", 1.0))),
        units=("", _ng_unit(labels["Y"]), _ng_unit(labels["X"]), _ng_unit(labels.get("Z", ""))),
        source_axes=source_axes,
        source_shape=tuple(int(size) for size in source.shape),
    )


def acquisition_to_ng(acquisition: AcqImage) -> NgVolumeData:
    """Return display-oriented full-resolution pixels for one acquisition.

    Args:
        acquisition: AcqImage whose complete pixels should be transported.

    Returns:
        Display-oriented pixels and matching coordinate calibration.

    Raises:
        ValueError: If acquisition axes are unsupported or omit Y/X.
    """
    return acq_pixels_to_ng(acquisition.pixels)


def _axis_values(pixels: AcqPixels, values: tuple[Any, ...], *, default: Any) -> dict[str, Any]:
    """Associate an AcqPixels metadata tuple with its named axes.

    Args:
        pixels: Pixels supplying the ordered axis names.
        values: Metadata values in the same order as the pixel axes.
        default: Value used when the metadata tuple is shorter than the axes.

    Returns:
        Mapping from axis name to metadata value.
    """
    return {
        axis: values[index] if index < len(values) else default
        for index, axis in enumerate(pixels.axes)
    }


def _ng_unit(value: Any) -> str:
    """Normalize an AcqStore unit label for Neuroglancer.

    Args:
        value: AcqStore unit label.

    Returns:
        Neuroglancer-compatible label, with pixel units represented as empty.
    """
    label = str(value or "").strip()
    if label.lower() in {"pixel", "pixels", "px", "unitless"}:
        return ""
    return {"µm": "um", "μm": "um"}.get(label, label)
