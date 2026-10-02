# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 seghier and IngeTrazo ComfyUI Renderer contributors.
"""ComfyUI HTTP and WebSocket API client using standard library modules."""

from __future__ import annotations

import base64
import json
import logging
import os
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

log = logging.getLogger("ingetrazo.plugins.comfyui_renderer.client")


class PureWebSocket:
    """Minimal pure-Python RFC 6455 WebSocket client using standard sockets."""

    def __init__(self, host: str, port: int, path: str):
        self.host = host
        self.port = port
        self.path = path
        self.sock: Optional[socket.socket] = None

    def connect(self, timeout: float = 4.0) -> bool:
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.settimeout(timeout)
            self.sock.connect((self.host, self.port))

            key = base64.b64encode(os.urandom(16)).decode("ascii")
            handshake = (
                f"GET {self.path} HTTP/1.1\r\n"
                f"Host: {self.host}:{self.port}\r\n"
                f"Upgrade: websocket\r\n"
                f"Connection: Upgrade\r\n"
                f"Sec-WebSocket-Key: {key}\r\n"
                f"Sec-WebSocket-Version: 13\r\n\r\n"
            )
            self.sock.sendall(handshake.encode("ascii"))
            resp = self.sock.recv(4096).decode("utf-8", errors="replace")
            if "101" not in resp:
                self.close()
                return False
            return True
        except Exception as e:
            log.debug(f"WebSocket connect failed: {e}")
            self.close()
            return False

    def recv(self, timeout: float = 0.5) -> Optional[Tuple[int, bytes]]:
        if not self.sock:
            return None
        self.sock.settimeout(timeout)
        try:
            head = self.sock.recv(2)
            if not head or len(head) < 2:
                return None
            b1, b2 = head[0], head[1]
            opcode = b1 & 0x0F
            is_masked = (b2 & 0x80) != 0
            length = b2 & 0x7F

            if length == 126:
                ext = self.sock.recv(2)
                length = int.from_bytes(ext, "big")
            elif length == 127:
                ext = self.sock.recv(8)
                length = int.from_bytes(ext, "big")

            mask = self.sock.recv(4) if is_masked else None
            payload = bytearray()
            while len(payload) < length:
                chunk = self.sock.recv(min(4096, length - len(payload)))
                if not chunk:
                    break
                payload.extend(chunk)

            if is_masked and mask:
                for i in range(len(payload)):
                    payload[i] ^= mask[i % 4]

            return opcode, bytes(payload)
        except (socket.timeout, BlockingIOError):
            return None
        except Exception as e:
            log.debug(f"WebSocket recv exception: {e}")
            return None

    def close(self) -> None:
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None


class ComfyClient:
    """Client for interacting with the ComfyUI REST and WebSocket API."""

    def __init__(self, server_url: str = "http://127.0.0.1:8000"):
        self.server_url = server_url.rstrip("/")
        self.client_id = str(uuid.uuid4())

    def set_server_url(self, server_url: str) -> None:
        self.server_url = server_url.rstrip("/")

    def _parse_host_port(self) -> Tuple[str, int]:
        parsed = urllib.parse.urlparse(self.server_url)
        host = parsed.hostname or "127.0.0.1"
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        return host, port

    def check_connection(self) -> Tuple[bool, str, Dict[str, Any]]:
        """Test connection to ComfyUI server and get system info."""
        url = f"{self.server_url}/system_stats"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IngeTrazo-ComfyUI/1.0"})
            with urllib.request.urlopen(req, timeout=3.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                version = data.get("system", {}).get("comfyui_version", "unknown")
                devices = data.get("devices", [])
                dev_name = devices[0].get("name", "GPU") if devices else "Default"
                if ":" in dev_name:
                    dev_name = dev_name.split(":")[0].strip()
                return True, f"Online (v{version} · {dev_name})", data
        except urllib.error.URLError as e:
            return False, f"Offline ({e.reason})", {}
        except Exception as e:
            return False, f"Error: {e}", {}

    def upload_image(self, image_bytes: bytes, filename: str = "viewport.png") -> Tuple[bool, Dict[str, Any], str]:
        """Upload an image to ComfyUI via multipart/form-data."""
        url = f"{self.server_url}/upload/image"
        boundary = f"----WebKitFormBoundary{uuid.uuid4().hex}"

        parts = []
        # overwrite = true
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(b'Content-Disposition: form-data; name="overwrite"\r\n\r\n')
        parts.append(b"true\r\n")

        # image file
        parts.append(f"--{boundary}\r\n".encode("utf-8"))
        parts.append(
            f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode("utf-8")
        )
        parts.append(b"Content-Type: image/png\r\n\r\n")
        parts.append(image_bytes)
        parts.append(b"\r\n")

        # closing boundary
        parts.append(f"--{boundary}--\r\n".encode("utf-8"))

        body = b"".join(parts)
        req = urllib.request.Request(
            url,
            data=body,
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "User-Agent": "IngeTrazo-ComfyUI/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                result = json.loads(resp.read().decode("utf-8"))
                log.info(f"Uploaded image successfully: {result}")
                return True, result, ""
        except Exception as e:
            msg = f"Upload error: {e}"
            log.error(msg)
            return False, {}, msg

    def queue_prompt(self, workflow_prompt: dict) -> Tuple[bool, str, str]:
        """Submit a prompt workflow dictionary to ComfyUI queue."""
        url = f"{self.server_url}/prompt"
        payload = json.dumps({"prompt": workflow_prompt, "client_id": self.client_id}).encode("utf-8")

        req = urllib.request.Request(
            url,
            data=payload,
            headers={
                "Content-Type": "application/json",
                "User-Agent": "IngeTrazo-ComfyUI/1.0",
            },
            method="POST",
        )

        try:
            with urllib.request.urlopen(req, timeout=15.0) as resp:
                data = json.loads(resp.read().decode("utf-8"))
                prompt_id = data.get("prompt_id")
                if not prompt_id:
                    error_msg = data.get("error", {}).get("message", "Unknown queue error")
                    return False, "", error_msg
                log.info(f"Prompt queued with ID: {prompt_id}")
                return True, prompt_id, ""
        except urllib.error.HTTPError as he:
            err_body = he.read().decode("utf-8", errors="replace")
            try:
                err_json = json.loads(err_body)
                node_errors = err_json.get("node_errors", {})
                if node_errors:
                    err_msg = json.dumps(node_errors)
                else:
                    err_msg = err_json.get("error", {}).get("message", err_body)
            except Exception:
                err_msg = err_body
            return False, "", f"HTTP {he.code}: {err_msg}"
        except Exception as e:
            return False, "", f"Queue error: {e}"

    def interrupt(self) -> bool:
        """Interrupt the currently running prompt execution."""
        url = f"{self.server_url}/interrupt"
        try:
            req = urllib.request.Request(
                url,
                data=b"{}",
                headers={"Content-Type": "application/json", "User-Agent": "IngeTrazo-ComfyUI/1.0"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=5.0) as resp:
                return resp.status == 200
        except Exception as e:
            log.warning(f"Interrupt failed: {e}")
            return False

    def poll_history(
        self,
        prompt_id: str,
        timeout_sec: float = 600.0,
        cancel_check: Optional[Callable[[], bool]] = None,
        progress_callback: Optional[Callable[[Optional[int], str], None]] = None,
    ) -> Tuple[bool, List[Dict[str, Any]], str]:
        """Listen to live WebSocket progress frames and poll history until generation completes.

        Provides live step-by-step progress: e.g. "Sampling: 14/20 (70%)".
        """
        host, port = self._parse_host_port()
        ws_path = f"/ws?clientId={self.client_id}"
        ws = PureWebSocket(host, port, ws_path)
        ws_connected = ws.connect(timeout=3.0)

        start_time = time.time()
        last_http_check = 0.0
        cached_images: List[Dict[str, Any]] = []

        try:
            while True:
                if cancel_check and cancel_check():
                    self.interrupt()
                    return False, [], "Generation cancelled by user"

                elapsed = time.time() - start_time
                if elapsed > timeout_sec:
                    return False, [], f"Timed out after {int(elapsed)}s"

                # 1. Read WebSocket frames if connected
                if ws_connected:
                    frame = ws.recv(timeout=0.25)
                    if frame:
                        opcode, payload = frame
                        if opcode == 1:  # Text JSON frame
                            try:
                                msg = json.loads(payload.decode("utf-8"))
                                m_type = msg.get("type")
                                data = msg.get("data", {})

                                if m_type == "progress":
                                    val = data.get("value", 0)
                                    max_val = data.get("max", 1)
                                    if max_val > 0:
                                        pct = int((val / max_val) * 100)
                                        if progress_callback:
                                            progress_callback(pct, f"Sampling: {val}/{max_val} steps ({pct}%)")

                                elif m_type == "executing":
                                    node_id = data.get("node")
                                    if node_id is None:
                                        # Generation finished
                                        if progress_callback:
                                            progress_callback(100, "Finalizing render…")
                                        # Allow brief time for history to write
                                        time.sleep(0.3)
                                        break
                                    else:
                                        if progress_callback:
                                            progress_callback(None, f"Executing node #{node_id}…")

                                elif m_type == "execution_error":
                                    err_msg = data.get("exception_message", "ComfyUI error")
                                    return False, [], f"ComfyUI execution error: {err_msg}"

                                elif m_type == "executed":
                                    node_out = data.get("output", {})
                                    if "images" in node_out:
                                        cached_images.extend(node_out["images"])

                            except Exception as ex:
                                log.debug(f"JSON frame parse error: {ex}")

                # 2. Periodic HTTP check every 1.5 seconds as reliable fallback
                now = time.time()
                if now - last_http_check >= 1.5:
                    last_http_check = now
                    try:
                        url = f"{self.server_url}/history/{prompt_id}"
                        req = urllib.request.Request(url, headers={"User-Agent": "IngeTrazo-ComfyUI/1.0"})
                        with urllib.request.urlopen(req, timeout=3.0) as resp:
                            history = json.loads(resp.read().decode("utf-8"))

                        if prompt_id in history:
                            p_data = history[prompt_id]
                            status = p_data.get("status", {})
                            if status.get("status_str") == "error":
                                messages = status.get("messages", [])
                                return False, [], f"ComfyUI error: {messages}"

                            outputs = p_data.get("outputs", {})
                            images = []
                            for _, node_out in outputs.items():
                                if "images" in node_out:
                                    images.extend(node_out["images"])

                            if images:
                                return True, images, ""

                    except Exception as e:
                        log.debug(f"HTTP check exception: {e}")

                if not ws_connected:
                    time.sleep(0.5)

            # Final fetch from history
            try:
                url = f"{self.server_url}/history/{prompt_id}"
                req = urllib.request.Request(url, headers={"User-Agent": "IngeTrazo-ComfyUI/1.0"})
                with urllib.request.urlopen(req, timeout=5.0) as resp:
                    history = json.loads(resp.read().decode("utf-8"))

                if prompt_id in history:
                    outputs = history[prompt_id].get("outputs", {})
                    images = []
                    for _, node_out in outputs.items():
                        if "images" in node_out:
                            images.extend(node_out["images"])
                    if images:
                        return True, images, ""
            except Exception as e:
                log.debug(f"Final history fetch failed: {e}")

            if cached_images:
                return True, cached_images, ""

            return False, [], "No output images retrieved from ComfyUI."

        finally:
            ws.close()

    def download_image(self, img_info: dict) -> Tuple[bool, bytes, str]:
        """Download output image from ComfyUI /view."""
        filename = img_info.get("filename", "")
        subfolder = img_info.get("subfolder", "")
        img_type = img_info.get("type", "output")

        query = urllib.parse.urlencode({
            "filename": filename,
            "subfolder": subfolder,
            "type": img_type,
        })
        url = f"{self.server_url}/view?{query}"

        try:
            req = urllib.request.Request(url, headers={"User-Agent": "IngeTrazo-ComfyUI/1.0"})
            with urllib.request.urlopen(req, timeout=30.0) as resp:
                data = resp.read()
                return True, data, ""
        except Exception as e:
            return False, b"", f"Download error: {e}"
