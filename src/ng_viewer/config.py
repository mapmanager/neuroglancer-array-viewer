"""Immutable browser configuration for :mod:`ng_viewer`."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class ChromePlacement(StrEnum):
    """Supported positions for the project-owned layout chrome."""

    OVERLAY_TOP = "overlay_top"
    OVERLAY_LEFT = "overlay_left"
    OVERLAY_BOTTOM = "overlay_bottom"
    OUTSIDE = "outside"


@dataclass(frozen=True)
class NgConfig:
    """Initial viewer presentation and navigation configuration."""

    chrome_placement: ChromePlacement = ChromePlacement.OVERLAY_TOP
    show_options_control: bool = True
    show_z_control: bool = True
    show_scale_bar: bool = False
    show_axis_lines: bool = False
    show_display_dimensions: bool = False
    show_native_layout_buttons: bool = False
    show_channels_control: bool = False
    show_layout_control: bool = False
    show_dataset_control: bool = False
    show_diagnostics: bool = False

    def to_json(self) -> dict[str, object]:
        """Return JSON-compatible browser configuration."""
        return {
            "chromePlacement": self.chrome_placement.value,
            "showOptionsControl": self.show_options_control,
            "showZControl": self.show_z_control,
            "showScaleBar": self.show_scale_bar,
            "showAxisLines": self.show_axis_lines,
            "showDisplayDimensions": self.show_display_dimensions,
            "showNativeLayoutButtons": self.show_native_layout_buttons,
            "showChannelsControl": self.show_channels_control,
            "showLayoutControl": self.show_layout_control,
            "showDatasetControl": self.show_dataset_control,
            "showDiagnostics": self.show_diagnostics,
        }
