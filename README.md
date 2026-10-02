# IngeTrazo ComfyUI Viewport Renderer

A lightweight, high-performance extension for **[IngeTrazo](https://github.com/ingelibre/ingetrazo)** (Python + PySide6 / Qt) that captures the 3D viewport, sends it to **ComfyUI** using standard API workflows, and renders the AI output directly as an interactive real-time viewport overlay.

https://github.com/user-attachments/assets/ing_comfyui.mp4

<p align="center">
  <video src="video/ing_comfyui.mp4" controls width="100%"></video>
</p>

---

## 🚀 Features

- **Direct Viewport AI Rendering:**
  - One-click capture of IngeTrazo's active 3D OpenGL viewport (with automatic dimension rounding for SDXL/Flux VAE compatibility).
  - Sends capture to local or remote ComfyUI server (`http://127.0.0.1:8000` or custom port).
- **Real-Time Viewport Overlay:**
  - View the generated AI render projected directly over the 3D viewport canvas.
  - Interactive **Opacity Slider (0% - 100%)** for smooth real-time cross-fading between your 3D CAD model and the photorealistic AI render.
  - Scaling modes: **Fit** (aspect-ratio preserved), **Fill** (crop/cover), or **Stretch**.
  - Optional subtle HUD badge indicator showing active overlay status and opacity.
- **Flexible Workflow System (Bundled & Custom Folders):**
  - Includes ready-to-use bundled API JSON workflows (`flux_canny_api.json`, `sdxl_controlnet_api.json`).
  - **📁 Custom Folder Picker**: Choose any directory of ComfyUI API JSON workflows on your computer; paths persist across sessions.
  - **📄 Single File Browse**: Quickly load and test any standalone ComfyUI API JSON workflow.
  - Intelligently detects and maps `LoadImage`, positive/negative `CLIPTextEncode`, and `KSampler` nodes.
  - Pre-populates prompt and sampling parameters directly from workflow defaults.
- **Live Sampling Progress (WebSocket):**
  - Real-time step-by-step progress and percentage display matching the ComfyUI console (e.g., `Sampling: 14/20 steps (70%)`) using pure standard-library WebSockets.
- **Auto-Clear on Camera Movement:**
  - Optional "Clear when camera moves" checkbox instantly dismisses the overlay when you orbit, pan, or zoom the 3D camera.
- **Clean & Focused Controls:**
  - **Prompt Editors:** Positive & Negative prompts with "Default" reset button.
  - **Sampling Overrides:** Steps, Denoise, CFG scale, and Seed (Randomize or Fixed).
  - **Resolution Selector:** Native Viewport, 1024×768, 1280×720 (HD), 1920×1080 (FHD), 512×512 (Fast).
  - **Actions:** ⚡ Render Viewport, ⏹️ Stop / Interrupt, 🧹 Clear Viewport, 💾 Save Image.
- **Asynchronous & Non-Blocking:**
  - All network I/O, prompt queuing, and history polling execute inside a dedicated background `QThread`.
  - IngeTrazo's 3D viewport and UI remain 100% responsive with live progress updates.
- **Zero External Dependencies:**
  - Pure Python standard library (`urllib.request`, `json`, `uuid`, `time`, `pathlib`) + `PySide6`. No bloat, no third-party package requirements.

---

## 📥 Installation

IngeTrazo automatically discovers plugins in your user plugins directory:

```
%APPDATA%\ingetrazo\plugins\
```

1. Copy the `comfyui_renderer` directory to:
   ```
   C:\Users\<YourUser>\AppData\Roaming\ingetrazo\plugins\comfyui_renderer
   ```
2. Start or restart **IngeTrazo**.
3. Access the plugin:
   - Via the **ComfyUI** tab in the side tray alongside *Properties*, *BIM*, *Levels*.
   - Or through the menu: **Extensions** ▸ **ComfyUI Viewport Renderer…**

---

## 🎮 How to Use

1. Ensure **ComfyUI** is running (default: `http://127.0.0.1:8000`).
2. Open the **ComfyUI** tab in IngeTrazo's side tray.
3. Select an API JSON workflow from the dropdown (e.g. `image to render api` or `flux_canny_model_api`).
4. Enter or refine your **Positive Prompt** (e.g., *"modern glass facade office buildings, golden hour sunlight, architectural photography"*).
5. Click **⚡ Render Viewport**.
6. Watch the progress bar as ComfyUI generates the image.
7. Once finished, the rendered image appears seamlessly as an overlay directly in the 3D viewport!
8. Drag the **Opacity** slider to blend between the 3D model and the AI rendering, or click **💾 Save Image…** to save it.

---

## 📄 License

Licensed under the [GNU General Public License v3.0 (GPL-3.0)](LICENSE), matching IngeTrazo's GPL-3.0 license.
