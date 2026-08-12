"""Typed state models emitted by the browser viewer."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ViewerLayout(StrEnum):
    """Layouts emitted by the direct viewer."""

    XY = "xy"
    CHANNELS_ROW = "channels-row"
    CHANNELS_COLUMN = "channels-column"
    XY_3D = "xy-3d"
    FOUR_PANEL_ALT = "4panel-alt"
    THREE_D = "3d"


@dataclass(frozen=True)
class AxisRange:
    """One calibrated visible-axis interval."""

    minimum: float
    maximum: float
    unit: str


@dataclass(frozen=True)
class ViewState:
    """Semantic state emitted when the browser view changes."""

    dataset_id: str
    layout: ViewerLayout
    x: AxisRange | None
    y: AxisRange | None
    z: float | None
    z_unit: str | None
    raw: dict[str, object]

    @classmethod
    def from_json(cls, value: dict[str, object]) -> "ViewState":
        """Parse and validate one browser snapshot.

        Args:
            value: Browser JSON view-state object.

        Returns:
            Typed state retaining the original JSON.

        Raises:
            ValueError: If required identity or layout data is invalid.
        """
        dataset_id = value.get("datasetId")
        if not isinstance(dataset_id, str) or not dataset_id:
            raise ValueError("View state requires a non-empty datasetId")
        try:
            layout = ViewerLayout(str(value["layout"]))
        except (KeyError, ValueError) as error:
            raise ValueError(f"Unsupported viewer layout: {value.get('layout')!r}") from error
        bounds = value.get("xyPhysicalBounds")
        panel = bounds[0] if isinstance(bounds, list) and bounds else None

        def axis(name: str) -> AxisRange | None:
            item = panel.get(name) if isinstance(panel, dict) else None
            if not isinstance(item, dict):
                return None
            return AxisRange(float(item["min"]), float(item["max"]), str(item.get("unit", "")))

        position = value.get("physicalPosition")
        z_value = position.get("z") if isinstance(position, dict) else None
        z = float(z_value["value"]) if isinstance(z_value, dict) and "value" in z_value else None
        z_unit = str(z_value.get("unit", "")) if isinstance(z_value, dict) else None
        return cls(dataset_id, layout, axis("x"), axis("y"), z, z_unit, dict(value))
