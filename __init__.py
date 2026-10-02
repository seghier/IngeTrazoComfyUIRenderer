# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 seghier and IngeTrazo ComfyUI Renderer contributors.
"""IngeTrazo ComfyUI Viewport Renderer Extension.

Renders IngeTrazo 3D viewports using local or remote ComfyUI workflows and
displays the resulting AI rendering directly as a real-time viewport overlay.
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("ingetrazo.plugins.comfyui_renderer")


def setup(app) -> None:
    """Extension initialization called by IngeTrazo at startup.

    Registers:
    1. 'ComfyUI' side tray panel alongside Properties, BIM, Levels.
    2. Viewport overlay delegate for real-time AI rendering display.
    3. Extensions menu action for easy access.
    """
    try:
        from .panel import ComfyUIRenderPanel

        # 1. Instantiate the renderer panel
        panel = ComfyUIRenderPanel(app)

        # 2. Register dock panel in IngeTrazo side tray
        dock = app.add_panel("ComfyUI", panel, panel="comfyui_render")

        # 3. Store references on main window for quick access
        win = getattr(app, "window", None) or getattr(app, "_window", None)
        if win:
            win._comfyui_render_panel = panel
            win._comfyui_render_dock = dock

        # 4. Add action in Extensions menu
        def show_comfyui_panel():
            if dock is not None:
                if hasattr(app, "show_panel"):
                    app.show_panel(dock)
                dock.show()
                dock.raise_()

        if hasattr(app, "add_menu_action"):
            app.add_menu_action(
                "ComfyUI Viewport Renderer…",
                show_comfyui_panel,
                tip="Render 3D viewport with ComfyUI and view as viewport overlay",
            )
        elif hasattr(app, "add_menu"):
            sub = app.add_menu("ComfyUI Renderer")
            if sub:
                sub.addAction("Open ComfyUI Renderer…", show_comfyui_panel)

        # 5. Register viewport overlay
        app.add_overlay(lambda vp, painter: panel.draw_viewport_overlay(vp, painter))

        log.info("ComfyUI Viewport Renderer plugin registered in side tray successfully.")

    except Exception as ex:
        log.error(f"Error during ComfyUI Renderer setup: {ex}", exc_info=True)
