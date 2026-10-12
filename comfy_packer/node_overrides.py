"""Persisted manual class_type -> custom_nodes folder mapping.

A user's own past decision (made when no automated tier could resolve a
node type) should always win over automated re-detection on future runs —
this is tier 1, checked before introspection/regex/brute-grep.
"""

import json
import os
from datetime import datetime

_CACHE_DIR = os.path.join(os.environ.get("LOCALAPPDATA", os.path.expanduser("~")), "ComfyUIPacker")
_CACHE_PATH = os.path.join(_CACHE_DIR, "node_overrides.json")


def get_override_path():
    return _CACHE_PATH


def load_overrides():
    if not os.path.isfile(_CACHE_PATH):
        return {"version": 1, "overrides": {}}
    try:
        with open(_CACHE_PATH, 'r', encoding='utf-8') as f:
            data = json.load(f)
        if not isinstance(data, dict) or "overrides" not in data:
            return {"version": 1, "overrides": {}}
        return data
    except Exception:
        return {"version": 1, "overrides": {}}


def save_overrides(data):
    os.makedirs(_CACHE_DIR, exist_ok=True)
    with open(_CACHE_PATH, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def set_override(class_type, folder, source_root):
    data = load_overrides()
    data["overrides"][class_type] = {
        "folder": folder,
        "source_root": source_root,
        "set_at": datetime.now().astimezone().isoformat(),
    }
    save_overrides(data)


def build_override_map(class_types, source_root, overrides=None):
    """Return {class_type: folder} for every class_type that has a cached
    override scoped to this source_root (or with no source_root recorded,
    e.g. from an older cache entry)."""
    overrides = overrides if overrides is not None else load_overrides()
    entries = overrides.get("overrides", {})
    result = {}
    for class_type in class_types:
        entry = entries.get(class_type)
        if not entry:
            continue
        entry_root = entry.get("source_root")
        if entry_root and entry_root != source_root:
            continue  # scoped to a different ComfyUI install, don't cross-apply
        result[class_type] = entry["folder"]
    return result
