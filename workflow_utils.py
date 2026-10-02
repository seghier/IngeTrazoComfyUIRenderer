# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2026 seghier and IngeTrazo ComfyUI Renderer contributors.
"""Workflow discovery, analysis, and parameter patching for ComfyUI API JSONs."""

from __future__ import annotations

import copy
import json
import logging
import random
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

log = logging.getLogger("ingetrazo.plugins.comfyui_renderer.workflow")


def get_default_workflow_dir() -> Path:
    """Return the bundled workflows directory inside the plugin folder."""
    return Path(__file__).parent / "workflows"


def discover_workflows(custom_dir: Optional[Path] = None) -> List[Tuple[str, Path]]:
    """Find all valid ComfyUI API JSON files.

    Search order:
    1. Plugin's bundled workflows: `plugin_folder/workflows`
    2. User-configured custom workflow directory (if set)
    3. Local developer folder (if present on the current machine)
    """
    dirs: List[Path] = []

    # 1. Bundled plugin directory (primary, always works out of the box)
    bundled = get_default_workflow_dir()
    if bundled.is_dir():
        dirs.append(bundled)

    # 2. User custom directory (e.g. from QSettings or Folder Picker)
    if custom_dir and Path(custom_dir).is_dir():
        p_cust = Path(custom_dir)
        if p_cust.resolve() not in [d.resolve() for d in dirs]:
            dirs.append(p_cust)

    found: List[Tuple[str, Path]] = []
    seen_paths = set()

    for d in dirs:
        if not d.is_dir():
            continue
        for p in sorted(d.glob("*.json")):
            # Skip nanobanana workflows as explicitly requested by user
            if "nano banana" in p.name.lower() or "nanobanana" in p.name.lower():
                continue
            if p.resolve() in seen_paths:
                continue
            seen_paths.add(p.resolve())

            try:
                with open(p, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, dict) and any("class_type" in v for v in data.values() if isinstance(v, dict)):
                    # Show parent folder label if multiple directories
                    category = "Bundled" if d == bundled else d.name
                    display_name = f"{p.stem} [{category}]"
                    found.append((display_name, p))
            except Exception:
                continue

    return found


def analyze_workflow(workflow: Dict[str, Any]) -> Dict[str, Any]:
    """Analyze workflow to discover LoadImage, CLIPTextEncode, and KSampler nodes."""
    info: Dict[str, Any] = {
        "image_node": None,
        "positive_prompt_node": None,
        "negative_prompt_node": None,
        "sampler_node": None,
        "positive_prompt_text": "",
        "negative_prompt_text": "",
        "steps": 20,
        "denoise": 1.0,
        "cfg": 6.0,
        "seed": 0,
    }

    text_nodes = []
    sampler_nodes = []
    image_nodes = []

    for nid, node in workflow.items():
        if not isinstance(node, dict):
            continue
        ctype = node.get("class_type", "")
        title = node.get("_meta", {}).get("title", "")
        inputs = node.get("inputs", {})

        if ctype == "LoadImage":
            image_nodes.append((nid, title, node))
        elif ctype in ("CLIPTextEncode", "PrimitiveString", "TextEncode", "CLIPTextEncodeSDXL"):
            text_nodes.append((nid, title, node))
        elif "KSampler" in ctype or ctype in ("SamplerCustom", "KSamplerAdvanced"):
            sampler_nodes.append((nid, title, node))

    # 1. Pick LoadImage node
    if image_nodes:
        info["image_node"] = image_nodes[0][0]

    # 2. Pick Sampler node
    if sampler_nodes:
        s_nid, _, s_node = sampler_nodes[0]
        info["sampler_node"] = s_nid
        s_inputs = s_node.get("inputs", {})
        if "steps" in s_inputs and isinstance(s_inputs["steps"], (int, float)):
            info["steps"] = int(s_inputs["steps"])
        if "denoise" in s_inputs and isinstance(s_inputs["denoise"], (int, float)):
            info["denoise"] = float(s_inputs["denoise"])
        if "cfg" in s_inputs and isinstance(s_inputs["cfg"], (int, float)):
            info["cfg"] = float(s_inputs["cfg"])
        if "seed" in s_inputs and isinstance(s_inputs["seed"], int):
            info["seed"] = s_inputs["seed"]

    # 3. Pick Positive vs Negative prompt nodes
    for nid, title, node in text_nodes:
        t_lower = title.lower()
        inp_text = node.get("inputs", {}).get("text") or node.get("inputs", {}).get("value") or ""

        is_neg = False
        if "negative" in t_lower:
            is_neg = True
        elif any(w in inp_text.lower() for w in ("blurry", "bad quality", "low quality", "cartoon", "deformed")):
            is_neg = True

        if is_neg:
            if info["negative_prompt_node"] is None:
                info["negative_prompt_node"] = nid
                info["negative_prompt_text"] = inp_text
        else:
            if info["positive_prompt_node"] is None:
                info["positive_prompt_node"] = nid
                info["positive_prompt_text"] = inp_text

    # Fallback if text nodes exist
    if info["positive_prompt_node"] is None and text_nodes:
        info["positive_prompt_node"] = text_nodes[0][0]
        info["positive_prompt_text"] = text_nodes[0][2].get("inputs", {}).get("text", "")
    if info["negative_prompt_node"] is None and len(text_nodes) > 1:
        if text_nodes[1][0] != info["positive_prompt_node"]:
            info["negative_prompt_node"] = text_nodes[1][0]
            info["negative_prompt_text"] = text_nodes[1][2].get("inputs", {}).get("text", "")

    return info


def patch_workflow(
    workflow: Dict[str, Any],
    uploaded_image_name: str,
    positive_prompt: Optional[str] = None,
    negative_prompt: Optional[str] = None,
    steps: Optional[int] = None,
    denoise: Optional[float] = None,
    cfg: Optional[float] = None,
    seed: Optional[int] = None,
    analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Return a modified deep copy of the workflow with runtime parameters injected."""
    patched = copy.deepcopy(workflow)
    if analysis is None:
        analysis = analyze_workflow(patched)

    # 1. Inject image into LoadImage node
    img_nid = analysis.get("image_node")
    if img_nid and img_nid in patched:
        patched[img_nid].setdefault("inputs", {})["image"] = uploaded_image_name
    else:
        for _, node in patched.items():
            if isinstance(node, dict) and node.get("class_type") == "LoadImage":
                node.setdefault("inputs", {})["image"] = uploaded_image_name
                break

    # 2. Inject positive prompt
    pos_nid = analysis.get("positive_prompt_node")
    if pos_nid and pos_nid in patched and positive_prompt is not None and positive_prompt.strip():
        node_inputs = patched[pos_nid].setdefault("inputs", {})
        if "text" in node_inputs or "value" not in node_inputs:
            node_inputs["text"] = positive_prompt.strip()
        else:
            node_inputs["value"] = positive_prompt.strip()

    # 3. Inject negative prompt
    neg_nid = analysis.get("negative_prompt_node")
    if neg_nid and neg_nid in patched and negative_prompt is not None and negative_prompt.strip():
        node_inputs = patched[neg_nid].setdefault("inputs", {})
        if "text" in node_inputs or "value" not in node_inputs:
            node_inputs["text"] = negative_prompt.strip()
        else:
            node_inputs["value"] = negative_prompt.strip()

    # 4. Inject Sampler parameters (steps, denoise, cfg, seed)
    sampler_nid = analysis.get("sampler_node")
    target_nodes = []
    if sampler_nid and sampler_nid in patched:
        target_nodes.append(patched[sampler_nid])
    else:
        for _, node in patched.items():
            if isinstance(node, dict) and ("KSampler" in node.get("class_type", "") or "Sampler" in node.get("class_type", "")):
                target_nodes.append(node)

    new_seed = seed if seed is not None and seed > 0 else random.randint(1, 10**15)

    for node in target_nodes:
        inputs = node.setdefault("inputs", {})
        if "seed" in inputs:
            inputs["seed"] = new_seed
        if steps is not None and "steps" in inputs:
            inputs["steps"] = int(steps)
        if denoise is not None and "denoise" in inputs:
            inputs["denoise"] = float(denoise)
        if cfg is not None and "cfg" in inputs:
            inputs["cfg"] = float(cfg)

    return patched
