"""Resolve workflow node class_types to required custom_nodes folders.

Resolution tiers, highest confidence first (manual override cache is added
in a later milestone and will sit above all of these):
  1. Runtime introspection — actually import each custom_nodes folder inside
     the *source* ComfyUI's own python_embeded, in an isolated subprocess,
     and read the real NODE_CLASS_MAPPINGS dict. Handles custom nodes that
     assemble their mapping dynamically (loops, .update(), multi-file
     merges) which static regex scanning cannot see.
  2. extension-node-map.json + regex scan of NODE_CLASS_MAPPINGS literals
     (ported from the original monolith).
  3. Brute-force grep for the literal class_type string across every .py
     file in every custom_nodes folder (last resort, scoped to whatever is
     still unresolved after tiers 1-2).
"""

import ast
import concurrent.futures
import json
import os
import re
import subprocess

from .constants import BUILTIN_NODE_PREFIXES

_HARNESS_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_introspect_node_folder.py")


def scan_builtin_nodes(env):
    """Scan comfy_extras and comfy_api_nodes directories for built-in node types."""
    builtin_set = set(BUILTIN_NODE_PREFIXES)
    extras_dirs = [
        os.path.join(env.comfyui_dir, "comfy_extras"),
        os.path.join(env.comfyui_dir, "comfy_api_nodes"),
    ]
    for extras_dir in extras_dirs:
        if not os.path.isdir(extras_dir):
            continue
        for f in os.listdir(extras_dir):
            if f.endswith('.py'):
                filepath = os.path.join(extras_dir, f)
                try:
                    with open(filepath, 'r', encoding='utf-8', errors='ignore') as fh:
                        content = fh.read()
                    mappings = re.findall(
                        r'NODE_CLASS_MAPPINGS\s*[\[=].*?\{([^}]*)\}',
                        content, re.DOTALL
                    )
                    for match in mappings:
                        names = re.findall(r'["\']([^"\']+)["\']', match)
                        builtin_set.update(names)
                    node_ids = re.findall(r'node_id\s*=\s*["\']([^"\']+)["\']', content)
                    builtin_set.update(node_ids)
                except Exception:
                    pass
    nodes_py = os.path.join(env.comfyui_dir, "nodes.py")
    if os.path.isfile(nodes_py):
        try:
            with open(nodes_py, 'r', encoding='utf-8', errors='ignore') as fh:
                content = fh.read()
            mappings = re.findall(
                r'NODE_CLASS_MAPPINGS\s*=\s*\{([^}]*)\}',
                content, re.DOTALL
            )
            for match in mappings:
                names = re.findall(r'["\']([^"\']+)["\']', match)
                builtin_set.update(names)
        except Exception:
            pass
    return builtin_set


def build_node_to_folder_map(env):
    """
    Build a mapping from node class_type -> custom_node folder name.
    Uses multiple strategies:
    1. ComfyUI-Manager's extension-node-map.json
    2. Scanning local custom_nodes folders for NODE_CLASS_MAPPINGS (AST-based)

    Returns (node_map, dynamic_folders) where dynamic_folders is the set of
    folder names whose mapping is assembled from a non-literal expression
    (detected by the AST scan) — static analysis under-reports these, so
    they should lean on introspection or a manual override instead.
    """
    node_map = {}  # class_type -> folder_name

    url_to_nodes = {}
    if os.path.exists(env.extension_node_map):
        with open(env.extension_node_map, 'r', encoding='utf-8') as f:
            ext_map = json.load(f)
        for url, info in ext_map.items():
            if isinstance(info, list) and len(info) >= 1:
                node_list = info[0]
                meta = info[1] if len(info) > 1 else {}
                url_to_nodes[url] = {
                    "nodes": node_list,
                    "title": meta.get("title_aux", ""),
                }

    local_folders = []
    if os.path.isdir(env.custom_nodes_dir):
        for item in os.listdir(env.custom_nodes_dir):
            item_path = os.path.join(env.custom_nodes_dir, item)
            if os.path.isdir(item_path) and not item.startswith('.') and item != "__pycache__":
                local_folders.append(item)

    for url, info in url_to_nodes.items():
        repo_name = url.rstrip('/').split('/')[-1]
        if repo_name.endswith('.py'):
            continue

        matched_folder = None
        for folder in local_folders:
            if folder.lower() == repo_name.lower():
                matched_folder = folder
                break
            if info["title"] and folder.lower() == info["title"].lower().replace(" ", "-"):
                matched_folder = folder
                break

        if matched_folder:
            for node_type in info["nodes"]:
                node_map[node_type] = matched_folder

    dynamic_folders = set()
    for folder in local_folders:
        folder_path = os.path.join(env.custom_nodes_dir, folder)
        found_nodes, is_dynamic = scan_folder_for_nodes(folder_path)
        if is_dynamic:
            dynamic_folders.add(folder)
        for node_type in found_nodes:
            if node_type not in node_map:
                node_map[node_type] = folder

    return node_map, dynamic_folders


_SKIP_SUBDIRS = {'__pycache__', '.git', '.github', 'node_modules', 'venv', '.venv', 'tests', 'test'}


def _is_node_class_mappings_target(node):
    """True if an AST node is a bare Name or Attribute ending in
    NODE_CLASS_MAPPINGS (covers `NODE_CLASS_MAPPINGS = ...` and
    `module.NODE_CLASS_MAPPINGS = ...`)."""
    if isinstance(node, ast.Name):
        return node.id == "NODE_CLASS_MAPPINGS"
    if isinstance(node, ast.Attribute):
        return node.attr == "NODE_CLASS_MAPPINGS"
    return False


def _target_mentions_node_class_mappings(node):
    """Like _is_node_class_mappings_target, but also true when the name
    appears anywhere inside a tuple/list unpacking target, e.g.
    `NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS = generate_mappings(...)`
    — a very common pattern that a bare Name/Attribute check misses."""
    if _is_node_class_mappings_target(node):
        return True
    if isinstance(node, (ast.Tuple, ast.List)):
        return any(_target_mentions_node_class_mappings(e) for e in node.elts)
    return False


def _extract_dict_string_keys(dict_node):
    keys = []
    for k in dict_node.keys:
        if isinstance(k, ast.Constant) and isinstance(k.value, str):
            keys.append(k.value)
    return keys


def _scan_file_ast(content, found_nodes, dynamic_found):
    """Walk a single file's AST for NODE_CLASS_MAPPINGS assignments/.update()
    calls. Appends discovered class_type strings to found_nodes; sets
    dynamic_found[0]=True if an .update() call's argument isn't a literal
    dict (i.e. the mapping is assembled from another module/expression that
    static analysis can't resolve — introspection or manual override is
    needed for these)."""
    tree = ast.parse(content)
    for node in ast.walk(tree):
        # NODE_CLASS_MAPPINGS = {...}  or  NODE_CLASS_MAPPINGS: dict = {...}
        # or NODE_CLASS_MAPPINGS, OTHER = some_call(...) (tuple-unpack assembly)
        if isinstance(node, (ast.Assign, ast.AnnAssign)):
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if any(_target_mentions_node_class_mappings(t) for t in targets) and node.value is not None:
                if any(_is_node_class_mappings_target(t) for t in targets) and isinstance(node.value, ast.Dict):
                    found_nodes.extend(_extract_dict_string_keys(node.value))
                else:
                    # Either not a literal dict, or NODE_CLASS_MAPPINGS is one
                    # half of a tuple-unpack whose RHS we can't statically
                    # attribute to the right name — needs introspection.
                    dynamic_found[0] = True

        # NODE_CLASS_MAPPINGS.update({...}) or NODE_CLASS_MAPPINGS.update(other_dict)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "update":
            if _is_node_class_mappings_target(node.func.value):
                if node.args and isinstance(node.args[0], ast.Dict):
                    found_nodes.extend(_extract_dict_string_keys(node.args[0]))
                else:
                    dynamic_found[0] = True


def scan_folder_for_nodes(folder_path):
    """Scan a custom node folder (recursively) for NODE_CLASS_MAPPINGS to
    find registered node types.

    Prefers AST-based parsing (handles NODE_CLASS_MAPPINGS.update(dict) and
    annotated assignments correctly regardless of formatting); falls back to
    the original regex scan for files that fail to parse (e.g. Python 2
    syntax in an abandoned node pack). When a folder assembles its mapping
    from a non-literal expression (`.update(other_module.MAPPINGS)`, a loop,
    etc.), that's recorded as "dynamic" rather than silently producing an
    empty result — such folders should rely on runtime introspection or a
    manual override instead of static analysis.

    Returns (found_nodes, is_dynamic).
    """
    found_nodes = []
    dynamic_found = [False]

    py_files = []
    for root, dirs, files in os.walk(folder_path):
        dirs[:] = [d for d in dirs if d not in _SKIP_SUBDIRS and not d.startswith('.')]
        for f in files:
            if f.endswith('.py'):
                py_files.append(os.path.join(root, f))

    for py_file in py_files:
        try:
            with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
        except Exception:
            continue

        try:
            _scan_file_ast(content, found_nodes, dynamic_found)
            continue
        except SyntaxError:
            pass  # fall through to regex below

        try:
            mappings_match = re.findall(
                r'NODE_CLASS_MAPPINGS\s*[\[=].*?\{([^}]*)\}',
                content, re.DOTALL
            )
            for match in mappings_match:
                names = re.findall(r'["\']([^"\']+)["\']', match)
                found_nodes.extend(names)

            update_matches = re.findall(
                r'NODE_CLASS_MAPPINGS\.update\s*\(\s*\{([^}]*)\}\s*\)',
                content, re.DOTALL
            )
            for match in update_matches:
                names = re.findall(r'["\']([^"\']+)["\']', match)
                found_nodes.extend(names)
        except Exception:
            pass

    return found_nodes, dynamic_found[0]


def find_source_python_exe(env):
    """The python_embeded interpreter belonging to the *source* ComfyUI
    install — needed so introspection runs with the same deps (torch,
    comfy, etc.) the custom nodes actually expect at import time."""
    candidate = os.path.join(env.source_root, "python_embeded", "python.exe")
    return candidate if os.path.isfile(candidate) else None


def introspect_node_folder(python_exe, comfyui_dir, folder_path, timeout_s=25):
    """Run the introspection harness for a single custom_nodes folder in an
    isolated subprocess. Never raises — a crash/timeout in one folder must
    not affect resolution of any other folder."""
    folder_name = os.path.basename(os.path.normpath(folder_path))
    try:
        proc = subprocess.run(
            [python_exe, _HARNESS_PATH, folder_path, comfyui_dir],
            capture_output=True, text=True, encoding='utf-8', errors='replace',
            timeout=timeout_s, cwd=folder_path,
        )
    except subprocess.TimeoutExpired:
        return {"folder": folder_name, "ok": False, "node_names": [], "error": "timeout"}
    except Exception as e:
        return {"folder": folder_name, "ok": False, "node_names": [], "error": str(e)}

    # Custom node imports can print arbitrary noise to stdout; only the last
    # valid JSON line (written by the harness itself) is trusted.
    for line in reversed(proc.stdout.splitlines()):
        line = line.strip()
        if not line:
            continue
        try:
            return json.loads(line)
        except (json.JSONDecodeError, ValueError):
            continue

    err = (proc.stderr or "").strip()[-500:] or "no JSON output from harness"
    return {"folder": folder_name, "ok": False, "node_names": [], "error": err}


def introspect_folders(env, folder_names, timeout_s=25, max_workers=8, on_progress=None):
    """Introspect many custom_nodes folders in parallel (subprocess launches
    are I/O-bound, so a thread pool is sufficient — no GIL contention).

    Returns {folder_name: introspection_result_dict}. If the source
    python_embeded can't be found, every folder is reported as failed so
    callers fall through to the regex/brute-grep tiers.
    """
    python_exe = find_source_python_exe(env)
    results = {}

    if not python_exe:
        for f in folder_names:
            results[f] = {"folder": f, "ok": False, "node_names": [], "error": "source python_embeded not found"}
        return results

    total = len(folder_names)
    done = 0
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_folder = {
            executor.submit(introspect_node_folder, python_exe, env.comfyui_dir,
                             os.path.join(env.custom_nodes_dir, f), timeout_s): f
            for f in folder_names
        }
        for future in concurrent.futures.as_completed(future_to_folder):
            folder = future_to_folder[future]
            results[folder] = future.result()
            done += 1
            if on_progress:
                on_progress(done, total, results[folder])

    return results


def build_introspection_node_map(introspection_results):
    """Fold successful introspection results into class_type -> folder."""
    node_map = {}
    for folder, res in introspection_results.items():
        if res.get("ok"):
            for node_name in res.get("node_names", []):
                node_map[node_name] = folder
    return node_map


def identify_required_custom_nodes(nodes, node_map, env, introspection_map=None, override_map=None):
    """Given workflow nodes, identify which custom node folders are needed.

    Resolution priority per class_type: override_map (a user's own past
    manual decision, see node_overrides.py) > introspection_map (the real
    runtime NODE_CLASS_MAPPINGS dict) > node_map (extension-map/regex/AST
    static scan) > builtin > brute-force grep.

    Returns (required_folders, unresolved_nodes, builtin_nodes, resolution_details)
    where resolution_details maps class_type -> {"folder": str|None,
    "method": str, "node_ids": [...]} so callers (the manifest writer) can
    report *how* each node type was resolved, not just the final folder set.
    """
    introspection_map = introspection_map or {}
    override_map = override_map or {}
    required_folders = set()
    unresolved_nodes = []
    builtin_nodes = []
    resolution_details = {}

    builtin_set = scan_builtin_nodes(env)

    node_ids_by_type = {}
    all_class_types = set()
    for node in nodes:
        ct = node["class_type"]
        if ct:
            all_class_types.add(ct)
            node_ids_by_type.setdefault(ct, []).append(str(node.get("id")))

    for class_type in sorted(all_class_types):
        node_ids = node_ids_by_type.get(class_type, [])

        if class_type in override_map:
            folder = override_map[class_type]
            required_folders.add(folder)
            resolution_details[class_type] = {"folder": folder, "method": "manual_override", "node_ids": node_ids}
        elif class_type in introspection_map:
            folder = introspection_map[class_type]
            required_folders.add(folder)
            resolution_details[class_type] = {"folder": folder, "method": "introspection", "node_ids": node_ids}
        elif class_type in node_map:
            folder = node_map[class_type]
            required_folders.add(folder)
            resolution_details[class_type] = {"folder": folder, "method": "known_map", "node_ids": node_ids}
        elif class_type in builtin_set or any(class_type.startswith(p) for p in BUILTIN_NODE_PREFIXES):
            builtin_nodes.append(class_type)
            resolution_details[class_type] = {"folder": None, "method": "builtin", "node_ids": node_ids}
        else:
            matched = False
            for folder in os.listdir(env.custom_nodes_dir):
                folder_path = os.path.join(env.custom_nodes_dir, folder)
                if os.path.isdir(folder_path):
                    for root, dirs, files in os.walk(folder_path):
                        dirs[:] = [d for d in dirs if d not in ('__pycache__', '.git', 'node_modules')]
                        for f in files:
                            if f.endswith('.py'):
                                try:
                                    with open(os.path.join(root, f), 'r', encoding='utf-8', errors='ignore') as fh:
                                        content = fh.read()
                                    if f'"{class_type}"' in content or f"'{class_type}'" in content:
                                        required_folders.add(folder)
                                        matched = True
                                        break
                                except Exception:
                                    pass
                        if matched:
                            break
                if matched:
                    break

            if matched:
                resolution_details[class_type] = {"folder": folder, "method": "brute_grep", "node_ids": node_ids}
            else:
                unresolved_nodes.append(class_type)
                resolution_details[class_type] = {"folder": None, "method": None, "node_ids": node_ids}

    return required_folders, unresolved_nodes, builtin_nodes, resolution_details
