# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 seghier and IngeTrazo ComfyUI Renderer contributors.
"""Side tray panel UI for ComfyUI Viewport Renderer in IngeTrazo."""

from __future__ import annotations

import json
import logging
import random
import time
from pathlib import Path
from typing import Any, Dict, Optional

from PySide6.QtCore import QBuffer, QIODevice, QSettings, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QImage, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QSizePolicy,
    QSlider,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from .comfy_client import ComfyClient
from .overlay import ViewportOverlay
from .worker import RenderWorker
from .workflow_utils import analyze_workflow, discover_workflows, get_default_workflow_dir

log = logging.getLogger("ingetrazo.plugins.comfyui_renderer.panel")


class ComfyUIRenderPanel(QWidget):
    """The side tray panel widget for ComfyUI Viewport Rendering."""

    def __init__(self, app, parent=None):
        super().__init__(parent)
        self.app = app
        settings = QSettings("IngeTrazo", "ComfyUIRenderer")
        saved_url = settings.value("server_url", "http://127.0.0.1:8000")
        self.client = ComfyClient(saved_url)
        self.overlay = ViewportOverlay()
        self.overlay.on_cleared = self._on_overlay_cleared_by_cam
        self.active_worker: Optional[RenderWorker] = None

        self.current_workflow_dict: Dict[str, Any] = {}
        self.current_analysis: Dict[str, Any] = {}
        self.current_workflow_path: Optional[Path] = None
        self.latest_rendered_bytes: Optional[bytes] = None
        self.latest_rendered_pixmap: Optional[QPixmap] = None

        self._build_ui()
        self._refresh_workflows()
        self._test_connection()

    def _build_ui(self) -> None:
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(6, 6, 6, 6)
        main_layout.setSpacing(6)

        # Scroll area for compact side tray integration
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(8)

        # ---- 1. Server Connection Group ----
        grp_server = QGroupBox("ComfyUI Server")
        lay_server = QVBoxLayout(grp_server)
        lay_server.setSpacing(4)
        lay_server.setContentsMargins(6, 8, 6, 6)

        row_srv = QHBoxLayout()
        settings = QSettings("IngeTrazo", "ComfyUIRenderer")
        saved_url = settings.value("server_url", "http://127.0.0.1:8000")
        self.txt_server = QLineEdit(saved_url)
        self.txt_server.setToolTip("URL of your local or remote ComfyUI instance")
        self.txt_server.textChanged.connect(self._on_server_url_changed)

        self.btn_check_srv = QPushButton("Check 🔄")
        self.btn_check_srv.setFixedWidth(70)
        self.btn_check_srv.clicked.connect(self._test_connection)
        row_srv.addWidget(self.txt_server)
        row_srv.addWidget(self.btn_check_srv)
        lay_server.addLayout(row_srv)

        self.lbl_server_status = QLabel("Checking connection…")
        self.lbl_server_status.setStyleSheet("font-size: 11px; color: #a0a0aa;")
        lay_server.addWidget(self.lbl_server_status)
        layout.addWidget(grp_server)

        # ---- 2. Workflow Selection Group ----
        grp_wf = QGroupBox("Workflow (API JSON)")
        lay_wf = QVBoxLayout(grp_wf)
        lay_wf.setSpacing(4)
        lay_wf.setContentsMargins(6, 8, 6, 6)

        row_wf = QHBoxLayout()
        self.combo_workflows = QComboBox()
        self.combo_workflows.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.combo_workflows.currentIndexChanged.connect(self._on_workflow_selected)

        self.btn_choose_folder = QPushButton("📁")
        self.btn_choose_folder.setToolTip("Choose custom workflows folder…")
        self.btn_choose_folder.setFixedWidth(30)
        self.btn_choose_folder.clicked.connect(self._choose_workflow_folder)

        self.btn_browse_wf = QPushButton("📄")
        self.btn_browse_wf.setToolTip("Browse for a single workflow API JSON file…")
        self.btn_browse_wf.setFixedWidth(30)
        self.btn_browse_wf.clicked.connect(self._browse_workflow_file)

        self.btn_reload_wfs = QPushButton("🔄")
        self.btn_reload_wfs.setToolTip("Refresh workflows")
        self.btn_reload_wfs.setFixedWidth(30)
        self.btn_reload_wfs.clicked.connect(self._refresh_workflows)

        row_wf.addWidget(self.combo_workflows)
        row_wf.addWidget(self.btn_choose_folder)
        row_wf.addWidget(self.btn_browse_wf)
        row_wf.addWidget(self.btn_reload_wfs)
        lay_wf.addLayout(row_wf)

        self.lbl_wf_info = QLabel("No workflow loaded")
        self.lbl_wf_info.setStyleSheet("font-size: 11px; color: #3689e6;")
        self.lbl_wf_info.setWordWrap(True)
        lay_wf.addWidget(self.lbl_wf_info)
        layout.addWidget(grp_wf)

        # ---- 3. Prompts Group ----
        grp_prompt = QGroupBox("Prompts")
        lay_prompt = QVBoxLayout(grp_prompt)
        lay_prompt.setSpacing(4)
        lay_prompt.setContentsMargins(6, 8, 6, 6)

        row_pos_lbl = QHBoxLayout()
        row_pos_lbl.addWidget(QLabel("Positive Prompt:"))
        btn_reset_prompt = QPushButton("Default")
        btn_reset_prompt.setToolTip("Reset prompt to workflow default")
        btn_reset_prompt.setFixedWidth(55)
        btn_reset_prompt.clicked.connect(self._restore_default_prompt)
        row_pos_lbl.addWidget(btn_reset_prompt)
        lay_prompt.addLayout(row_pos_lbl)

        self.txt_positive_prompt = QPlainTextEdit()
        self.txt_positive_prompt.setPlaceholderText("Describe the architectural scene, lighting, materials…")
        self.txt_positive_prompt.setMinimumHeight(75)
        self.txt_positive_prompt.setStyleSheet(
            "background-color: #1a1b22; color: #f0f0f5; border: 1px solid #363848; border-radius: 4px; padding: 4px;"
        )
        lay_prompt.addWidget(self.txt_positive_prompt)

        lay_prompt.addWidget(QLabel("Negative Prompt:"))
        self.txt_negative_prompt = QPlainTextEdit()
        self.txt_negative_prompt.setPlaceholderText("blurry, low quality, distorted, cartoon…")
        self.txt_negative_prompt.setMinimumHeight(45)
        self.txt_negative_prompt.setStyleSheet(
            "background-color: #1a1b22; color: #f0f0f5; border: 1px solid #363848; border-radius: 4px; padding: 4px;"
        )
        lay_prompt.addWidget(self.txt_negative_prompt)
        layout.addWidget(grp_prompt)

        # ---- 4. Parameters & Sampling Group ----
        grp_params = QGroupBox("Parameters & Resolution")
        lay_params = QGridLayout(grp_params)
        lay_params.setSpacing(6)
        lay_params.setContentsMargins(6, 8, 6, 6)

        lay_params.addWidget(QLabel("Resolution:"), 0, 0)
        self.combo_res = QComboBox()
        self.combo_res.addItems([
            "Native Viewport",
            "1024 × 768",
            "1280 × 720 (HD)",
            "1920 × 1080 (FHD)",
            "512 × 512 (Fast)",
        ])
        lay_params.addWidget(self.combo_res, 0, 1)

        lay_params.addWidget(QLabel("Steps:"), 1, 0)
        self.spin_steps = QSpinBox()
        self.spin_steps.setRange(1, 150)
        self.spin_steps.setValue(20)
        lay_params.addWidget(self.spin_steps, 1, 1)

        lay_params.addWidget(QLabel("Denoise:"), 2, 0)
        self.spin_denoise = QDoubleSpinBox()
        self.spin_denoise.setRange(0.05, 1.0)
        self.spin_denoise.setSingleStep(0.05)
        self.spin_denoise.setValue(1.0)
        lay_params.addWidget(self.spin_denoise, 2, 1)

        lay_params.addWidget(QLabel("CFG Scale:"), 3, 0)
        self.spin_cfg = QDoubleSpinBox()
        self.spin_cfg.setRange(1.0, 30.0)
        self.spin_cfg.setSingleStep(0.5)
        self.spin_cfg.setValue(6.0)
        lay_params.addWidget(self.spin_cfg, 3, 1)

        self.chk_rand_seed = QCheckBox("Randomize Seed")
        self.chk_rand_seed.setChecked(True)
        lay_params.addWidget(self.chk_rand_seed, 4, 0, 1, 2)
        layout.addWidget(grp_params)

        # ---- 5. Primary Render Controls ----
        grp_actions = QGroupBox("Controls")
        lay_actions = QVBoxLayout(grp_actions)
        lay_actions.setSpacing(6)
        lay_actions.setContentsMargins(6, 8, 6, 6)

        row_btns1 = QHBoxLayout()
        self.btn_render = QPushButton("⚡ Render Viewport")
        self.btn_render.setStyleSheet(
            "QPushButton { background-color: #f27329; color: white; font-weight: bold; font-size: 13px; "
            "border-radius: 5px; padding: 8px; border: none; } "
            "QPushButton:hover { background-color: #ff8533; } "
            "QPushButton:pressed { background-color: #d9621e; } "
            "QPushButton:disabled { background-color: #555761; color: #888a96; }"
        )
        self.btn_render.clicked.connect(self.start_render)

        self.btn_stop = QPushButton("⏹️ Stop")
        self.btn_stop.setEnabled(False)
        self.btn_stop.setFixedWidth(70)
        self.btn_stop.clicked.connect(self.stop_render)

        row_btns1.addWidget(self.btn_render, 1)
        row_btns1.addWidget(self.btn_stop)
        lay_actions.addLayout(row_btns1)

        row_btns2 = QHBoxLayout()
        self.btn_clear = QPushButton("🧹 Clear Overlay")
        self.btn_clear.clicked.connect(self.clear_overlay)

        self.btn_save = QPushButton("💾 Save Image…")
        self.btn_save.setEnabled(False)
        self.btn_save.clicked.connect(self.save_image)

        row_btns2.addWidget(self.btn_clear)
        row_btns2.addWidget(self.btn_save)
        lay_actions.addLayout(row_btns2)

        # Progress bar & status
        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFixedHeight(18)
        self.progress_bar.setAlignment(Qt.AlignCenter)
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #1a1b22; border: 1px solid #363848; border-radius: 4px; "
            "text-align: center; color: #e4e4e7; font-size: 10px; font-weight: bold; } "
            "QProgressBar::chunk { background-color: #f27329; border-radius: 3px; }"
        )
        lay_actions.addWidget(self.progress_bar)

        self.lbl_status = QLabel("Ready")
        self.lbl_status.setStyleSheet("font-size: 11px; color: #bbbbcc;")
        self.lbl_status.setWordWrap(True)
        lay_actions.addWidget(self.lbl_status)
        layout.addWidget(grp_actions)

        # ---- 6. Viewport Overlay Options ----
        grp_overlay = QGroupBox("Viewport Overlay")
        lay_overlay = QVBoxLayout(grp_overlay)
        lay_overlay.setSpacing(6)
        lay_overlay.setContentsMargins(6, 8, 6, 6)

        row_chk = QHBoxLayout()
        self.chk_show_overlay = QCheckBox("Show in Viewport")
        self.chk_show_overlay.setChecked(True)
        self.chk_show_overlay.toggled.connect(self._on_overlay_toggled)

        self.combo_fit = QComboBox()
        self.combo_fit.addItems(["Fit (Preserve Ratio)", "Fill (Crop/Cover)", "Stretch"])
        self.combo_fit.currentIndexChanged.connect(self._on_fit_mode_changed)

        row_chk.addWidget(self.chk_show_overlay)
        row_chk.addWidget(self.combo_fit)
        lay_overlay.addLayout(row_chk)

        row_opacity = QHBoxLayout()
        row_opacity.addWidget(QLabel("Opacity:"))
        self.slider_opacity = QSlider(Qt.Horizontal)
        self.slider_opacity.setRange(0, 100)
        self.slider_opacity.setValue(100)
        self.slider_opacity.valueChanged.connect(self._on_opacity_changed)
        self.lbl_opacity = QLabel("100%")
        self.lbl_opacity.setFixedWidth(36)
        row_opacity.addWidget(self.slider_opacity)
        row_opacity.addWidget(self.lbl_opacity)
        lay_overlay.addLayout(row_opacity)

        self.chk_clear_cam = QCheckBox("Clear when camera moves")
        self.chk_clear_cam.setChecked(False)
        self.chk_clear_cam.toggled.connect(self._on_clear_cam_toggled)
        lay_overlay.addWidget(self.chk_clear_cam)
        layout.addWidget(grp_overlay)

        # ---- 7. Result Preview Thumbnail Card ----
        grp_preview = QGroupBox("Last Render")
        lay_preview = QVBoxLayout(grp_preview)
        lay_preview.setSpacing(4)
        lay_preview.setContentsMargins(6, 6, 6, 6)

        self.lbl_preview_img = QLabel("No render yet")
        self.lbl_preview_img.setAlignment(Qt.AlignCenter)
        self.lbl_preview_img.setMinimumHeight(130)
        self.lbl_preview_img.setStyleSheet(
            "background-color: #15161c; border: 1px dashed #363848; border-radius: 4px; color: #777988;"
        )
        lay_preview.addWidget(self.lbl_preview_img)

        self.lbl_preview_info = QLabel("")
        self.lbl_preview_info.setStyleSheet("font-size: 11px; color: #a0a0aa;")
        self.lbl_preview_info.setAlignment(Qt.AlignCenter)
        lay_preview.addWidget(self.lbl_preview_info)
        layout.addWidget(grp_preview)

        layout.addStretch(1)
        scroll.setWidget(content)
        main_layout.addWidget(scroll)

    # ---- Connection & Workflow Handling ----

    def _on_server_url_changed(self, text: str) -> None:
        url = text.strip()
        self.client.set_server_url(url)
        QSettings("IngeTrazo", "ComfyUIRenderer").setValue("server_url", url)

    def _test_connection(self) -> None:
        self.lbl_server_status.setText("Checking…")
        online, msg, _ = self.client.check_connection()
        if online:
            self.lbl_server_status.setText(f"🟢 {msg}")
            self.lbl_server_status.setStyleSheet("font-size: 11px; color: #4ade80;")
        else:
            self.lbl_server_status.setText(f"🔴 {msg}")
            self.lbl_server_status.setStyleSheet("font-size: 11px; color: #f87171;")

    def _choose_workflow_folder(self) -> None:
        """Let user select a custom directory containing workflow API JSONs."""
        settings = QSettings("IngeTrazo", "ComfyUIRenderer")
        current_dir = settings.value("workflow_dir", "")
        start_dir = str(current_dir) if current_dir and Path(current_dir).is_dir() else str(get_default_workflow_dir())
        folder = QFileDialog.getExistingDirectory(
            self, "Select ComfyUI Workflows Folder", start_dir
        )
        if folder:
            settings.setValue("workflow_dir", folder)
            self._refresh_workflows()

    def _refresh_workflows(self) -> None:
        """Scan bundled directory and user-configured folder for API workflows."""
        settings = QSettings("IngeTrazo", "ComfyUIRenderer")
        custom_dir = settings.value("workflow_dir", "")
        custom_path = Path(custom_dir) if custom_dir and Path(custom_dir).is_dir() else None

        self.combo_workflows.blockSignals(True)
        self.combo_workflows.clear()

        wfs = discover_workflows(custom_path)
        for disp_name, file_path in wfs:
            self.combo_workflows.addItem(disp_name, str(file_path))

        self.combo_workflows.blockSignals(False)
        if self.combo_workflows.count() > 0:
            self._load_workflow_by_index(0)
        else:
            self.lbl_wf_info.setText("No workflows found. Click 📁 to choose a workflow folder.")
            self.lbl_wf_info.setStyleSheet("font-size: 11px; color: #f87171;")

    def _browse_workflow_file(self) -> None:
        settings = QSettings("IngeTrazo", "ComfyUIRenderer")
        last_dir = settings.value("workflow_dir", "")
        start_dir = str(last_dir) if last_dir and Path(last_dir).is_dir() else str(get_default_workflow_dir())
        path, _ = QFileDialog.getOpenFileName(
            self, "Select ComfyUI Workflow API JSON", start_dir, "JSON files (*.json)"
        )
        if path:
            p = Path(path)
            disp_name = f"{p.stem} [Custom]"
            self.combo_workflows.addItem(disp_name, str(p))
            self.combo_workflows.setCurrentIndex(self.combo_workflows.count() - 1)

    def _on_workflow_selected(self, index: int) -> None:
        self._load_workflow_by_index(index)

    def _load_workflow_by_index(self, index: int) -> None:
        if index < 0 or index >= self.combo_workflows.count():
            return
        file_path_str = self.combo_workflows.itemData(index)
        if not file_path_str:
            return

        p = Path(file_path_str)
        try:
            with open(p, "r", encoding="utf-8") as f:
                wf_dict = json.load(f)

            self.current_workflow_path = p
            self.current_workflow_dict = wf_dict
            self.current_analysis = analyze_workflow(wf_dict)

            # Auto-populate UI fields from workflow defaults
            pos_text = self.current_analysis.get("positive_prompt_text", "")
            if pos_text:
                self.txt_positive_prompt.setPlainText(pos_text)

            neg_text = self.current_analysis.get("negative_prompt_text", "")
            if neg_text:
                self.txt_negative_prompt.setPlainText(neg_text)

            if "steps" in self.current_analysis:
                self.spin_steps.setValue(self.current_analysis["steps"])
            if "denoise" in self.current_analysis:
                self.spin_denoise.setValue(self.current_analysis["denoise"])
            if "cfg" in self.current_analysis:
                self.spin_cfg.setValue(self.current_analysis["cfg"])

            # Info label
            img_n = self.current_analysis.get("image_node", "Auto")
            pos_n = self.current_analysis.get("positive_prompt_node", "Auto")
            smp_n = self.current_analysis.get("sampler_node", "Auto")
            self.lbl_wf_info.setText(f"✓ Nodes: LoadImage #{img_n} · Prompt #{pos_n} · Sampler #{smp_n}")
            self.lbl_wf_info.setStyleSheet("font-size: 11px; color: #38bdf8;")

        except Exception as e:
            self.lbl_wf_info.setText(f"Error loading workflow: {e}")
            self.lbl_wf_info.setStyleSheet("font-size: 11px; color: #f87171;")

    def _restore_default_prompt(self) -> None:
        pos_text = self.current_analysis.get("positive_prompt_text", "")
        if pos_text:
            self.txt_positive_prompt.setPlainText(pos_text)

    # ---- Overlay Settings ----

    def _on_overlay_toggled(self, checked: bool) -> None:
        self.overlay.enabled = checked
        self._redraw_viewport()

    def _on_opacity_changed(self, value: int) -> None:
        self.overlay.opacity = value / 100.0
        self.lbl_opacity.setText(f"{value}%")
        self._redraw_viewport()

    def _on_fit_mode_changed(self, index: int) -> None:
        modes = ["Fit", "Fill", "Stretch"]
        if 0 <= index < len(modes):
            self.overlay.fit_mode = modes[index]
            self._redraw_viewport()

    def _on_clear_cam_toggled(self, checked: bool) -> None:
        self.overlay.clear_on_cam_change = checked
        if checked and self.overlay.pixmap:
            vp = getattr(self.app, "viewport", None)
            cam = getattr(vp, "camera", None) if vp else None
            if cam:
                self.overlay.capture_cam_key(cam)

    def _on_overlay_cleared_by_cam(self) -> None:
        self.lbl_status.setText("Overlay cleared (camera moved)")
        self._redraw_viewport()

    def _redraw_viewport(self) -> None:
        vp = getattr(self.app, "viewport", None)
        if vp:
            vp.update()

    def draw_viewport_overlay(self, viewport, painter) -> None:
        """Called by IngeTrazo viewport overlay delegate."""
        self.overlay.draw(viewport, painter)

    def clear_overlay(self) -> None:
        self.overlay.clear()
        self._redraw_viewport()
        self.lbl_status.setText("Overlay cleared")

    # ---- Viewport Capture & Rendering ----

    def _capture_viewport_image(self) -> tuple[Optional[bytes], str]:
        vp = getattr(self.app, "viewport", None)
        if not vp:
            return None, "Viewport not available"

        res_str = self.combo_res.currentText()
        if "1024" in res_str:
            tw, th = 1024, 768
        elif "1280" in res_str:
            tw, th = 1280, 720
        elif "1920" in res_str:
            tw, th = 1920, 1080
        elif "512" in res_str:
            tw, th = 512, 512
        else:
            tw, th = vp.width(), vp.height()

        # Ensure dimensions are multiples of 8 for VAE compatibility
        tw = max(64, (tw // 8) * 8)
        th = max(64, (th // 8) * 8)

        qimg = None
        if hasattr(vp, "render_image"):
            try:
                qimg = vp.render_image(tw, th)
            except Exception as e:
                log.warning(f"render_image failed: {e}")

        if qimg is None or qimg.isNull():
            if hasattr(vp, "grabFramebuffer"):
                try:
                    qimg = vp.grabFramebuffer().scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)
                except Exception:
                    pass

        if qimg is None or qimg.isNull():
            pix = vp.grab()
            qimg = pix.toImage().scaled(tw, th, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        buf = QBuffer()
        buf.open(QIODevice.WriteOnly)
        qimg.save(buf, "PNG")
        return bytes(buf.data()), ""

    def start_render(self) -> None:
        if not self.current_workflow_dict:
            QMessageBox.warning(self, "No Workflow", "Please select a ComfyUI workflow API JSON first.")
            return

        # 1. Capture viewport
        img_bytes, err = self._capture_viewport_image()
        if not img_bytes:
            QMessageBox.warning(self, "Capture Error", f"Failed to capture viewport: {err}")
            return

        # 2. Prepare parameters
        pos_prompt = self.txt_positive_prompt.toPlainText().strip()
        neg_prompt = self.txt_negative_prompt.toPlainText().strip()
        steps = self.spin_steps.value()
        denoise = self.spin_denoise.value()
        cfg = self.spin_cfg.value()

        if self.chk_rand_seed.isChecked():
            seed = random.randint(1, 10**15)
        else:
            seed = self.current_analysis.get("seed", 42)

        filename = f"ingetrazo_{int(time.time())}.png"

        # 3. Setup UI for rendering
        self.btn_render.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.progress_bar.setValue(5)
        self.lbl_status.setText("Initiating render…")

        # 4. Start Worker Thread
        self.active_worker = RenderWorker(
            client=self.client,
            workflow=self.current_workflow_dict,
            image_bytes=img_bytes,
            filename=filename,
            positive_prompt=pos_prompt,
            negative_prompt=neg_prompt,
            steps=steps,
            denoise=denoise,
            cfg=cfg,
            seed=seed,
            analysis=self.current_analysis,
            parent=self,
        )

        self.active_worker.sig_status.connect(self._on_worker_status)
        self.active_worker.sig_progress.connect(self._on_worker_progress)
        self.active_worker.sig_finished.connect(self._on_worker_finished)
        self.active_worker.sig_error.connect(self._on_worker_error)
        self.active_worker.sig_cancelled.connect(self._on_worker_cancelled)

        self.active_worker.start()

    def stop_render(self) -> None:
        if self.active_worker and self.active_worker.isRunning():
            self.lbl_status.setText("Stopping…")
            self.active_worker.cancel()
            self.btn_stop.setEnabled(False)

    def _on_worker_status(self, text: str) -> None:
        self.lbl_status.setText(text)

    def _on_worker_progress(self, val: int, text: str) -> None:
        self.progress_bar.setValue(val)
        self.lbl_status.setText(text)

    def _on_worker_finished(self, img_bytes: bytes, meta: dict) -> None:
        self.latest_rendered_bytes = img_bytes

        # Load pixmap
        pix = QPixmap()
        pix.loadFromData(img_bytes)
        self.latest_rendered_pixmap = pix

        # Record camera signature for view change detection
        vp = getattr(self.app, "viewport", None)
        cam = getattr(vp, "camera", None) if vp else None

        # Update overlay
        self.overlay.set_image(pix, cam=cam, note=f"Rendered in {meta.get('duration')}s")
        self._redraw_viewport()

        # Update preview card
        preview_pix = pix.scaled(280, 160, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.lbl_preview_img.setPixmap(preview_pix)
        self.lbl_preview_info.setText(
            f"{pix.width()}×{pix.height()} px · {meta.get('duration')}s · Seed: {meta.get('seed')}"
        )

        self.btn_save.setEnabled(True)
        self.btn_render.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(100)
        self.lbl_status.setText(f"Render completed in {meta.get('duration')}s")

    def _on_worker_error(self, err_msg: str) -> None:
        self.btn_render.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Failed")
        QMessageBox.critical(self, "ComfyUI Render Error", err_msg)

    def _on_worker_cancelled(self) -> None:
        self.btn_render.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.progress_bar.setValue(0)
        self.lbl_status.setText("Render cancelled")

    def save_image(self) -> None:
        if not self.latest_rendered_bytes:
            return
        default_name = f"comfyui_render_{int(time.time())}.png"
        path, _ = QFileDialog.getSaveFileName(
            self, "Save ComfyUI Render", default_name, "PNG Images (*.png);;JPEG Images (*.jpg *.jpeg)"
        )
        if path:
            try:
                with open(path, "wb") as f:
                    f.write(self.latest_rendered_bytes)
                self.lbl_status.setText(f"Saved: {Path(path).name}")
            except Exception as e:
                QMessageBox.warning(self, "Save Error", f"Failed to save image: {e}")
