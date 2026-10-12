"""Resolve model file references from workflow nodes to source file paths.

Model references are recorded regardless of whether the file currently
exists on disk. Earlier versions of this tool only added a reference to the
models dict once find_model_in_folders() had already located it — meaning a
model that's missing on the source machine (deleted, never downloaded,
shared from another install) was never even considered a reference, so it
silently vanished from the pack with no warning at all. Now every detected
reference is recorded with a best-effort folder_type (schema hint > broad
filesystem search > "unknown"), so find_all_model_files() always gets a
chance to report it as missing instead of dropping it outright.
"""

import os
from collections import defaultdict

from .constants import MODEL_INPUT_KEYS, INPUT_KEY_TO_FOLDER, MODEL_FILE_EXTENSIONS
from .node_schema import get_model_hints

UNKNOWN_FOLDER = "unknown"


def extract_model_references(nodes, env):
    """Extract all model file references from workflow nodes.

    Returns (models, metadata) where models is folder_type -> set of
    filenames (as before), and metadata is filename -> {"method": str,
    "node_ids": [...]} for manifest reporting.
    """
    models = defaultdict(set)  # folder_type -> set of filenames
    metadata = {}

    def record(filename, folder, method, node_id):
        models[folder].add(filename)
        entry = metadata.setdefault(filename, {"method": method, "node_ids": []})
        if node_id is not None:
            entry["node_ids"].append(str(node_id))

    for node in nodes:
        node_id = node.get("id")
        class_type = node.get("class_type", "")
        inputs = node.get("inputs", {})
        for key, value in inputs.items():
            if not isinstance(value, str):
                continue
            if key in INPUT_KEY_TO_FOLDER:
                # Some keys list multiple legacy-alias folders (e.g.
                # "unet_name" -> ["diffusion_models", "unet"]). Registering
                # the same filename under every alias caused it to resolve
                # and get copied once per alias — a real bug that silently
                # duplicated multi-GB files. Pick exactly one: whichever
                # alias actually has the file, else the first (modern) alias.
                candidates = INPUT_KEY_TO_FOLDER[key]
                chosen = next(
                    (folder for folder in candidates
                     if os.path.isfile(os.path.join(env.models_dir, folder, value))),
                    candidates[0],
                )
                record(value, chosen, "api_input_key", node_id)
            elif key in MODEL_INPUT_KEYS:
                found = find_model_in_folders(value, env)
                folder = found[0] if found else UNKNOWN_FOLDER
                record(value, folder, "api_input_key_broad_search" if found else "api_input_key_missing", node_id)

        widgets = node.get("widgets_values", [])
        if not widgets:
            continue

        schema_hints = get_model_hints(class_type)
        schema_covered_indices = {idx for idx, _ in schema_hints}
        for idx, folder in schema_hints:
            if idx < len(widgets) and isinstance(widgets[idx], str) and widgets[idx]:
                record(widgets[idx], folder, "schema_hint", node_id)

        for i, val in enumerate(widgets):
            if i in schema_covered_indices:
                continue  # already handled by the schema hint above
            if isinstance(val, str) and looks_like_model_filename(val):
                found = find_model_in_folders(val, env)
                folder = found[0] if found else UNKNOWN_FOLDER
                record(val, folder, "ui_extension_heuristic" if found else "ui_extension_heuristic_missing", node_id)

    return models, metadata


def looks_like_model_filename(value):
    """Check if a string looks like a model filename."""
    if not value or len(value) < 3:
        return False
    ext = os.path.splitext(value)[-1].lower()
    return ext in MODEL_FILE_EXTENSIONS


def find_model_in_folders(filename, env):
    """Find which model folder contains the given filename."""
    for folder in os.listdir(env.models_dir):
        folder_path = os.path.join(env.models_dir, folder)
        if os.path.isdir(folder_path):
            full_path = os.path.join(folder_path, filename)
            if os.path.exists(full_path):
                return (folder, full_path)
    return None


def find_all_model_files(models_dict, env):
    """Resolve model references to actual file paths. Returns (file_list, missing_files).

    Deduped by the *resolved absolute source path*, not by the raw filename
    string — when packing multiple workflows together, the same model can
    be referenced with different path-separator spelling between files
    (e.g. "Qwen\\file.safetensors" vs "Qwen/file.safetensors"), which a
    set-based string dedup upstream can't catch since they're different
    string objects that just happen to resolve to the same file on disk.
    Without this, the same multi-GB model could be listed and copied twice.
    """
    file_list = []
    missing_files = []
    seen_src = set()
    seen_missing = set()

    for folder_name, filenames in models_dict.items():
        for filename in filenames:
            search_dirs = [os.path.join(env.models_dir, folder_name)]
            if folder_name == "text_encoders":
                search_dirs.append(os.path.join(env.models_dir, "clip"))
            elif folder_name == "diffusion_models":
                search_dirs.append(os.path.join(env.models_dir, "unet"))

            found = False
            for search_dir in search_dirs:
                src = os.path.join(search_dir, filename)
                if os.path.exists(src):
                    src_key = os.path.normcase(os.path.abspath(src))
                    if src_key in seen_src:
                        found = True
                        break
                    seen_src.add(src_key)
                    rel_folder = os.path.basename(search_dir)
                    file_list.append((src, os.path.join("models", rel_folder, filename)))
                    found = True
                    break

            if not found:
                result = find_model_in_folders(filename, env)
                if result:
                    folder, full_path = result
                    src_key = os.path.normcase(os.path.abspath(full_path))
                    if src_key not in seen_src:
                        seen_src.add(src_key)
                        file_list.append((full_path, os.path.join("models", folder, filename)))
                else:
                    missing_key = os.path.normcase(filename)
                    if missing_key not in seen_missing:
                        seen_missing.add(missing_key)
                        rel_dest = os.path.join("models", folder_name, filename)
                        missing_files.append((filename, rel_dest))
                        print(f"  ⚠ Warning: Model not found locally: {filename}")

    return file_list, missing_files


def scan_custom_node_model_deps(required_folders, env):
    """
    Some custom nodes store models in their own folders or in
    non-standard model directories. Scan for these.
    """
    from .constants import STANDARD_MODEL_FOLDERS

    extra_model_dirs = []

    for folder_name in required_folders:
        folder_path = os.path.join(env.custom_nodes_dir, folder_name)
        if not os.path.isdir(folder_path):
            continue

        for sub in os.listdir(folder_path):
            sub_path = os.path.join(folder_path, sub)
            if os.path.isdir(sub_path) and sub.lower() in ('models', 'weights', 'pretrained', 'checkpoints'):
                if any(f.endswith(('.safetensors', '.pt', '.pth', '.onnx', '.bin')) for f in os.listdir(sub_path)):
                    extra_model_dirs.append((sub_path, os.path.join("custom_nodes", folder_name, sub)))

    non_standard = []
    for folder in os.listdir(env.models_dir):
        if folder not in STANDARD_MODEL_FOLDERS:
            folder_path = os.path.join(env.models_dir, folder)
            if os.path.isdir(folder_path):
                non_standard.append(folder)

    return extra_model_dirs, non_standard
