# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 seghier and IngeTrazo ComfyUI Renderer contributors.
"""Background worker thread for asynchronous ComfyUI rendering without blocking the Qt GUI."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, Optional

from PySide6.QtCore import QThread, Signal

from .comfy_client import ComfyClient
from .workflow_utils import patch_workflow

log = logging.getLogger("ingetrazo.plugins.comfyui_renderer.worker")


class RenderWorker(QThread):
    """Executes the render pipeline in background: upload -> patch -> queue -> poll -> download."""

    sig_status = Signal(str)
    sig_progress = Signal(int, str)
    sig_finished = Signal(bytes, dict)
    sig_error = Signal(str)
    sig_cancelled = Signal()

    def __init__(
        self,
        client: ComfyClient,
        workflow: Dict[str, Any],
        image_bytes: bytes,
        filename: str,
        positive_prompt: str,
        negative_prompt: str,
        steps: int,
        denoise: float,
        cfg: float,
        seed: int,
        analysis: Optional[Dict[str, Any]] = None,
        parent=None,
    ):
        super().__init__(parent)
        self.client = client
        self.workflow = workflow
        self.image_bytes = image_bytes
        self.filename = filename
        self.positive_prompt = positive_prompt
        self.negative_prompt = negative_prompt
        self.steps = steps
        self.denoise = denoise
        self.cfg = cfg
        self.seed = seed
        self.analysis = analysis
        self._is_cancelled = False

    def cancel(self) -> None:
        """Request immediate cancellation of the active render job."""
        self._is_cancelled = True
        self.client.interrupt()

    def run(self) -> None:
        start_time = time.time()
        try:
            # 1. Connection check
            self.sig_status.emit("Connecting to ComfyUI…")
            self.sig_progress.emit(10, "Connecting…")
            online, msg, _ = self.client.check_connection()
            if not online:
                self.sig_error.emit(f"ComfyUI is offline: {msg}")
                return

            if self._is_cancelled:
                self.sig_cancelled.emit()
                return

            # 2. Upload viewport image
            self.sig_status.emit("Uploading viewport capture…")
            self.sig_progress.emit(25, "Uploading viewport…")
            ok, upload_res, err = self.client.upload_image(self.image_bytes, self.filename)
            if not ok:
                self.sig_error.emit(f"Image upload failed: {err}")
                return

            uploaded_name = upload_res.get("name", self.filename)
            if self._is_cancelled:
                self.sig_cancelled.emit()
                return

            # 3. Patch workflow with parameters
            self.sig_status.emit("Configuring workflow parameters…")
            self.sig_progress.emit(40, "Configuring workflow…")
            patched_wf = patch_workflow(
                self.workflow,
                uploaded_image_name=uploaded_name,
                positive_prompt=self.positive_prompt,
                negative_prompt=self.negative_prompt,
                steps=self.steps,
                denoise=self.denoise,
                cfg=self.cfg,
                seed=self.seed,
                analysis=self.analysis,
            )

            if self._is_cancelled:
                self.sig_cancelled.emit()
                return

            # 4. Queue prompt
            self.sig_status.emit("Submitting to ComfyUI queue…")
            self.sig_progress.emit(55, "Queuing prompt…")
            ok, prompt_id, err = self.client.queue_prompt(patched_wf)
            if not ok:
                self.sig_error.emit(f"Queue failed: {err}")
                return

            if self._is_cancelled:
                self.client.interrupt()
                self.sig_cancelled.emit()
                return

            # 5. Poll history for completion
            self.sig_status.emit(f"Sampling in ComfyUI (ID: {prompt_id[:8]})…")
            self.sig_progress.emit(70, "Sampling…")

            def on_progress(pct: Optional[int], text: str):
                if pct is not None:
                    self.sig_progress.emit(max(0, min(100, int(pct))), text)
                self.sig_status.emit(text)

            ok, images, err = self.client.poll_history(
                prompt_id,
                timeout_sec=600.0,
                cancel_check=lambda: self._is_cancelled,
                progress_callback=on_progress,
            )

            if not ok:
                if self._is_cancelled:
                    self.sig_cancelled.emit()
                else:
                    self.sig_error.emit(f"Sampling failed: {err}")
                return

            if not images:
                self.sig_error.emit("No output images returned by ComfyUI workflow.")
                return

            # 6. Download rendered image
            self.sig_status.emit("Downloading rendered image…")
            self.sig_progress.emit(90, "Downloading…")
            target_img = images[-1]  # Latest image
            ok, img_bytes, err = self.client.download_image(target_img)
            if not ok:
                self.sig_error.emit(f"Failed to download image: {err}")
                return

            elapsed = round(time.time() - start_time, 2)
            meta = {
                "duration": elapsed,
                "prompt_id": prompt_id,
                "filename": target_img.get("filename", ""),
                "seed": self.seed,
                "steps": self.steps,
            }

            self.sig_progress.emit(100, f"Done in {elapsed}s")
            self.sig_status.emit(f"Render completed in {elapsed}s")
            self.sig_finished.emit(img_bytes, meta)

        except Exception as e:
            log.error(f"RenderWorker crashed: {e}", exc_info=True)
            self.sig_error.emit(f"Unexpected error: {e}")
