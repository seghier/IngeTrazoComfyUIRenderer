# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 seghier and IngeTrazo ComfyUI Renderer contributors.
"""Viewport overlay manager for rendering ComfyUI output over IngeTrazo 3D viewports."""

from __future__ import annotations

import logging
from typing import Callable, Optional, Tuple

from PySide6.QtCore import QPointF, QRect, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPixmap

log = logging.getLogger("ingetrazo.plugins.comfyui_renderer.overlay")


def get_cam_key(cam) -> Optional[Tuple]:
    """Extract a lightweight hashable coordinate signature from an IngeTrazo OrbitCamera."""
    if cam is None:
        return None
    try:
        from core import render_blender as rb
        if hasattr(rb, "camera_key"):
            return rb.camera_key(cam)
    except Exception:
        pass

    try:
        t = getattr(cam, "target", None)
        tx = round(t.x(), 2) if t and hasattr(t, "x") else 0.0
        ty = round(t.y(), 2) if t and hasattr(t, "y") else 0.0
        tz = round(t.z(), 2) if t and hasattr(t, "z") else 0.0
        yaw = round(float(getattr(cam, "yaw", 0.0)), 3)
        pitch = round(float(getattr(cam, "pitch", 0.0)), 3)
        dist = round(float(getattr(cam, "distance", 0.0)), 2)
        return (tx, ty, tz, yaw, pitch, dist)
    except Exception:
        return None


class ViewportOverlay:
    """Draws rendered ComfyUI image over the active 3D OpenGL viewport."""

    def __init__(self):
        self.pixmap: Optional[QPixmap] = None
        self.opacity: float = 1.0
        self.enabled: bool = True
        self.fit_mode: str = "Fit"  # "Fit", "Fill", "Stretch"
        self.show_badge: bool = True
        self.clear_on_cam_change: bool = False
        self._render_cam_key: Optional[Tuple] = None
        self._status_text: str = ""
        self.on_cleared: Optional[Callable[[], None]] = None

    def set_image(self, pixmap: QPixmap, cam=None, cam_sig=None, note: str = "") -> None:
        """Set the rendered image and record the camera state at render time."""
        self.pixmap = pixmap
        target_cam = cam if cam is not None else cam_sig
        self._render_cam_key = get_cam_key(target_cam)
        self._status_text = note

    def capture_cam_key(self, cam) -> None:
        """Capture the current camera state as the reference baseline."""
        self._render_cam_key = get_cam_key(cam)

    def clear(self) -> None:
        """Clear current overlay image."""
        self.pixmap = None
        self._render_cam_key = None
        self._status_text = ""

    def draw(self, viewport, painter: QPainter) -> None:
        """Overlay paint callback called by IngeTrazo's viewport paint event."""
        if not self.enabled or self.pixmap is None or self.pixmap.isNull():
            return

        # Check camera movement if user enabled "Clear when camera moves"
        if self.clear_on_cam_change and hasattr(viewport, "camera"):
            cam = getattr(viewport, "camera", None)
            cur_key = get_cam_key(cam)
            if self._render_cam_key is not None and cur_key is not None and cur_key != self._render_cam_key:
                self.clear()
                if self.on_cleared:
                    try:
                        self.on_cleared()
                    except Exception:
                        pass
                return

        vp_w = viewport.width()
        vp_h = viewport.height()
        if vp_w <= 0 or vp_h <= 0:
            return

        painter.save()
        painter.setOpacity(max(0.0, min(1.0, self.opacity)))
        painter.setRenderHint(QPainter.SmoothPixmapTransform, True)

        try:
            if self.fit_mode == "Fit":
                scaled = self.pixmap.scaled(vp_w, vp_h, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                x = (vp_w - scaled.width()) // 2
                y = (vp_h - scaled.height()) // 2
                painter.drawPixmap(x, y, scaled)
            elif self.fit_mode == "Fill":
                scaled = self.pixmap.scaled(vp_w, vp_h, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
                x = (vp_w - scaled.width()) // 2
                y = (vp_h - scaled.height()) // 2
                painter.setClipRect(0, 0, vp_w, vp_h)
                painter.drawPixmap(x, y, scaled)
            else:  # Stretch
                painter.drawPixmap(0, 0, vp_w, vp_h, self.pixmap)
        finally:
            painter.restore()

        # Draw subtle badge in bottom-right corner
        if self.show_badge:
            painter.save()
            try:
                painter.setOpacity(0.85)
                font = QFont("Segoe UI", 8)
                font.setBold(True)
                painter.setFont(font)
                fm = QFontMetrics(font)

                badge_text = f"🤖 ComfyUI · {int(self.opacity * 100)}%"
                tw = fm.horizontalAdvance(badge_text)
                th = fm.height()
                padding_x = 8
                padding_y = 4
                bx = vp_w - tw - (padding_x * 2) - 14
                by = vp_h - th - (padding_y * 2) - 14

                # Dark rounded pill background
                painter.setPen(Qt.NoPen)
                painter.setBrush(QColor(24, 25, 32, 220))
                painter.drawRoundedRect(bx, by, tw + (padding_x * 2), th + (padding_y * 2), 5, 5)

                # Accent border
                painter.setPen(QColor(242, 115, 41, 180))  # IngeTrazo orange accent
                painter.setBrush(Qt.NoBrush)
                painter.drawRoundedRect(bx, by, tw + (padding_x * 2), th + (padding_y * 2), 5, 5)

                # Text
                painter.setPen(QColor(240, 240, 245))
                painter.drawText(bx + padding_x, by + th + padding_y - 2, badge_text)
            finally:
                painter.restore()
