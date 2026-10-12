"""Source ComfyUI environment resolution.

Replaces the previous module-global state (SOURCE_ROOT, COMFYUI_DIR, ...)
with an explicit, passable object so downstream modules don't rely on
hidden mutable globals.
"""

import os
from dataclasses import dataclass


@dataclass
class SourceEnv:
    source_root: str
    comfyui_dir: str
    custom_nodes_dir: str
    models_dir: str
    extension_node_map: str


def setup_source_env(workflow_path=None, explicit_source=None):
    """Resolve which ComfyUI_windows_portable install to pack from.

    Priority: explicit --source override > auto-detect by walking up from
    the workflow path looking for sibling python_embeded/ComfyUI dirs >
    hardcoded fallback.
    """
    source_root = r"C:\ComfyUI_windows_portable"  # Hardcoded fallback

    if explicit_source and os.path.isdir(explicit_source):
        source_root = os.path.abspath(explicit_source)
    elif workflow_path:
        current_dir = os.path.dirname(os.path.abspath(workflow_path))
        while current_dir and current_dir != os.path.dirname(current_dir):
            if os.path.isdir(os.path.join(current_dir, "python_embeded")) and os.path.isdir(os.path.join(current_dir, "ComfyUI")):
                source_root = current_dir
                break
            current_dir = os.path.dirname(current_dir)

    comfyui_dir = os.path.join(source_root, "ComfyUI")
    custom_nodes_dir = os.path.join(comfyui_dir, "custom_nodes")
    models_dir = os.path.join(comfyui_dir, "models")
    extension_node_map = os.path.join(custom_nodes_dir, "ComfyUI-Manager", "extension-node-map.json")

    return SourceEnv(
        source_root=source_root,
        comfyui_dir=comfyui_dir,
        custom_nodes_dir=custom_nodes_dir,
        models_dir=models_dir,
        extension_node_map=extension_node_map,
    )
