"""Introspection harness — runs INSIDE the *source* ComfyUI's own
python_embeded interpreter (spawned as a subprocess by node_resolver.py,
never imported directly by the packer's own process).

Imports a single custom_nodes folder in isolation and reports the real,
fully-assembled NODE_CLASS_MAPPINGS dict as one JSON line on stdout. This is
what correctly handles custom nodes that build their mapping dynamically
across multiple files/loops/`.update()` calls, which static regex scanning
cannot see.

Usage: python.exe _introspect_node_folder.py <folder_path> <comfyui_dir>
"""

import importlib.util
import json
import os
import sys
import traceback


def main():
    if len(sys.argv) < 3:
        print(json.dumps({"folder": "", "ok": False, "node_names": [], "error": "missing arguments"}))
        return

    folder_path = sys.argv[1]
    comfyui_dir = sys.argv[2]
    folder_name = os.path.basename(os.path.normpath(folder_path))
    result = {"folder": folder_name, "ok": False, "node_names": [], "error": None}

    try:
        # Most custom nodes import ComfyUI internals (folder_paths, comfy.*,
        # server) and sometimes sibling custom_node packages by folder name.
        sys.path.insert(0, comfyui_dir)
        sys.path.insert(0, os.path.join(comfyui_dir, "custom_nodes"))
        sys.path.insert(0, os.path.dirname(folder_path))

        init_py = os.path.join(folder_path, "__init__.py")
        if not os.path.isfile(init_py):
            result["error"] = "no __init__.py"
            print(json.dumps(result))
            return

        spec = importlib.util.spec_from_file_location(
            folder_name, init_py, submodule_search_locations=[folder_path],
        )
        module = importlib.util.module_from_spec(spec)
        sys.modules[folder_name] = module
        spec.loader.exec_module(module)

        mapping = getattr(module, "NODE_CLASS_MAPPINGS", {}) or {}
        result["node_names"] = list(mapping.keys())
        result["ok"] = True
    except SystemExit as e:
        result["error"] = f"SystemExit({e.code})"
    except BaseException:
        result["error"] = traceback.format_exc(limit=8)

    # Last stdout line is authoritative; the parent process only trusts the
    # final valid JSON line, tolerant of noisy prints during import.
    print(json.dumps(result))


if __name__ == "__main__":
    main()
