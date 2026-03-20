"""
ComfyUI Workflow Packer
=======================
Parses a ComfyUI workflow JSON, identifies all required custom nodes and models,
then packages a clean, minimal ComfyUI portable instance to the specified output directory.

Usage:
    python pack_workflow.py
    (Interactive prompts for workflow JSON path and output directory)

    python pack_workflow.py --workflow wf1.json wf2.json --output D:\\packed_comfyui
"""

import json
import os
import sys
import shutil
import argparse
import re
import time
import io
from pathlib import Path
from collections import defaultdict

# Fix Windows console encoding for emoji/unicode output
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')


# ─── Configuration Variables (Populated at Runtime) ───────────────────────────
SOURCE_ROOT = ""
COMFYUI_DIR = ""
CUSTOM_NODES_DIR = ""
MODELS_DIR = ""
EXTENSION_NODE_MAP = ""

def setup_paths(workflow_path=None, explicit_source=None):
    global SOURCE_ROOT, COMFYUI_DIR, CUSTOM_NODES_DIR, MODELS_DIR, EXTENSION_NODE_MAP
    
    SOURCE_ROOT = r"C:\ComfyUI_windows_portable"  # Hardcoded fallback
    
    if explicit_source and os.path.isdir(explicit_source):
        SOURCE_ROOT = os.path.abspath(explicit_source)
    elif workflow_path:
        # Try to auto-detect from workflow path
        current_dir = os.path.dirname(os.path.abspath(workflow_path))
        while current_dir and current_dir != os.path.dirname(current_dir):
            if os.path.isdir(os.path.join(current_dir, "python_embeded")) and os.path.isdir(os.path.join(current_dir, "ComfyUI")):
                SOURCE_ROOT = current_dir
                break
            current_dir = os.path.dirname(current_dir)
            
    COMFYUI_DIR = os.path.join(SOURCE_ROOT, "ComfyUI")
    CUSTOM_NODES_DIR = os.path.join(COMFYUI_DIR, "custom_nodes")
    MODELS_DIR = os.path.join(COMFYUI_DIR, "models")
    EXTENSION_NODE_MAP = os.path.join(CUSTOM_NODES_DIR, "ComfyUI-Manager", "extension-node-map.json")
    
    return SOURCE_ROOT

# Standard model folder names used by ComfyUI (from folder_paths.py)
STANDARD_MODEL_FOLDERS = [
    "checkpoints", "configs", "loras", "vae", "text_encoders", "clip",
    "diffusion_models", "unet", "clip_vision", "style_models", "embeddings",
    "diffusers", "vae_approx", "controlnet", "gligen", "upscale_models",
    "latent_upscale_models", "hypernetworks", "photomaker", "model_patches",
    "audio_encoders",
]

# Node class_types that are built-in to ComfyUI (no custom node needed)
# We build this dynamically but also have a fallback
BUILTIN_NODE_PREFIXES = [
    "KSampler", "CheckpointLoader", "CLIPTextEncode", "VAEDecode", "VAEEncode",
    "EmptyLatentImage", "SaveImage", "LoadImage", "LoraLoader", "CLIPSetLastLayer",
    "ConditioningCombine", "ConditioningAverage", "ConditioningConcat",
    "ConditioningSetArea", "ConditioningSetMask", "ConditioningZeroOut",
    "VAELoader", "ControlNetLoader", "ControlNetApply",
    "ImageScale", "ImageScaleBy", "ImageInvert", "ImageBatch", "ImagePadForOutpaint",
    "LatentUpscale", "LatentUpscaleBy", "LatentComposite",
    "CLIPVisionLoader", "CLIPVisionEncode", "StyleModelLoader", "StyleModelApply",
    "unCLIPCheckpointLoader", "GLIGENLoader", "GLIGENTextBoxApply",
    "DiffusersLoader", "LoadLatent", "SaveLatent",
    "LoraLoaderModelOnly", "CheckpointLoaderSimple",
    "VAEDecodeTiled", "VAEEncodeTiled", "VAEEncodeForInpaint",
    "InpaintModelConditioning", "ConditioningSetTimestepRange",
    "ConditioningSetAreaPercentage", "ConditioningSetAreaStrength",
    "DualCLIPLoader", "TripleCLIPLoader", "UNETLoader",
    "DualCFGGuider", "BasicGuider", "BasicScheduler", "RandomNoise",
    "SamplerCustomAdvanced", "SamplerCustom", "FlipSigmas", "SplitSigmas",
    "KSamplerSelect", "SDTurboScheduler",
    "ModelSamplingSD3", "ModelSamplingFlux", "ModelSamplingAuraFlow",
    "ModelSamplingContinuousV", "ModelSamplingContinuousEDM",
    "RebatchLatents", "EmptySD3LatentImage",
    "PhotoMakerLoader", "PhotoMakerEncode",
    "PreviewImage", "LoadImageMask",
    "ImageCrop", "RepeatImageBatch", "RebatchImages",
    "PatchModelAddDownscale",
    "ModelMergeSimple", "ModelMergeBlocks", "ModelMergeSubtract", "ModelMergeAdd",
    "CLIPMergeSimple", "CLIPMergeSubtract", "CLIPMergeAdd",
    "Note", "Reroute", "PrimitiveNode",
    # Frontend-only nodes
    "SetNode", "GetNode",
    # comfy_extras nodes (common)
    "MaskToImage", "ImageToMask", "SolidMask", "InvertMask",
    "CropMask", "MaskComposite", "FeatherMask", "GrowMask",
    "ThresholdMask", "ImageCompositeMasked",
]


def scan_builtin_nodes():
    """Scan comfy_extras and comfy_api_nodes directories for built-in node types."""
    builtin_set = set(BUILTIN_NODE_PREFIXES)
    extras_dirs = [
        os.path.join(COMFYUI_DIR, "comfy_extras"),
        os.path.join(COMFYUI_DIR, "comfy_api_nodes"),
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
                    # Extract node names from NODE_CLASS_MAPPINGS
                    mappings = re.findall(
                        r'NODE_CLASS_MAPPINGS\s*[\[=].*?\{([^}]*)\}',
                        content, re.DOTALL
                    )
                    for match in mappings:
                        names = re.findall(r'["\']([^"\']+)["\']', match)
                        builtin_set.update(names)
                    # Also check node_id= patterns (new API style)
                    node_ids = re.findall(r'node_id\s*=\s*["\']([^"\']+)["\']', content)
                    builtin_set.update(node_ids)
                except Exception:
                    pass
    # Also scan nodes.py itself
    nodes_py = os.path.join(COMFYUI_DIR, "nodes.py")
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


def print_header():
    print("\n" + "=" * 70)
    print("  ComfyUI Workflow Packer")
    print("  打包 ComfyUI 工作流到可攜帶版本")
    print("=" * 70)


def print_step(step_num, message):
    print(f"\n{'─' * 60}")
    print(f"  Step {step_num}: {message}")
    print(f"{'─' * 60}")


def format_size(size_bytes):
    """Format bytes to human-readable size."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if size_bytes < 1024.0:
            return f"{size_bytes:.1f} {unit}"
        size_bytes /= 1024.0
    return f"{size_bytes:.1f} PB"


def get_dir_size(path):
    """Get total size of a directory."""
    total = 0
    for dirpath, dirnames, filenames in os.walk(path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            try:
                total += os.path.getsize(fp)
            except OSError:
                pass
    return total


# ─── Step 1: Parse Workflow JSON ─────────────────────────────────────────────

def load_workflow(workflow_path):
    """Load and parse a ComfyUI workflow JSON file. Handles both API and UI formats."""
    with open(workflow_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # Detect format: API format has nodes as top-level dict with class_type
    # UI format has a "nodes" array and "links" array
    if isinstance(data, dict):
        if "nodes" in data and isinstance(data["nodes"], list):
            # UI format (exported from ComfyUI frontend)
            nodes = parse_ui_format(data)
            
            # Extract nested subgraph nodes (new ComfyUI feature)
            if "definitions" in data and isinstance(data["definitions"], dict):
                subgraphs = data["definitions"].get("subgraphs", [])
                for sg in subgraphs:
                    if "nodes" in sg and isinstance(sg["nodes"], list):
                        nodes.extend(parse_ui_format(sg))
            
            return nodes
        else:
            # API format (dict of node_id -> node_config)
            return parse_api_format(data)
    else:
        raise ValueError("Unrecognized workflow format")


def parse_api_format(data):
    """Parse API format workflow: {node_id: {class_type, inputs, ...}}"""
    nodes = []
    for node_id, node_data in data.items():
        if isinstance(node_data, dict) and "class_type" in node_data:
            nodes.append({
                "id": node_id,
                "class_type": node_data["class_type"],
                "inputs": node_data.get("inputs", {}),
                "widgets_values": []  # API format puts values in inputs directly
            })
    return nodes


def parse_ui_format(data):
    """Parse UI format workflow: {nodes: [...], links: [...]}"""
    nodes = []
    for node in data.get("nodes", []):
        nodes.append({
            "id": node.get("id"),
            "class_type": node.get("type", ""),
            "inputs": {},  # UI format uses widgets_values
            "widgets_values": node.get("widgets_values", []),
            "properties": node.get("properties", {}),
        })
    return nodes


# ─── Step 2: Extract Required Custom Nodes ───────────────────────────────────

def build_node_to_folder_map():
    """
    Build a mapping from node class_type -> custom_node folder name.
    Uses multiple strategies:
    1. ComfyUI-Manager's extension-node-map.json
    2. Scanning local custom_nodes folders for NODE_CLASS_MAPPINGS
    """
    node_map = {}  # class_type -> folder_name

    # Strategy 1: extension-node-map.json (maps URL -> node list)
    # We need to also figure out which URL corresponds to which local folder
    url_to_nodes = {}
    if os.path.exists(EXTENSION_NODE_MAP):
        with open(EXTENSION_NODE_MAP, 'r', encoding='utf-8') as f:
            ext_map = json.load(f)
        for url, info in ext_map.items():
            if isinstance(info, list) and len(info) >= 1:
                node_list = info[0]
                meta = info[1] if len(info) > 1 else {}
                url_to_nodes[url] = {
                    "nodes": node_list,
                    "title": meta.get("title_aux", ""),
                }

    # Strategy 2: Scan local custom_nodes folders
    # For each folder, try to find what nodes it registers
    local_folders = []
    if os.path.isdir(CUSTOM_NODES_DIR):
        for item in os.listdir(CUSTOM_NODES_DIR):
            item_path = os.path.join(CUSTOM_NODES_DIR, item)
            if os.path.isdir(item_path) and not item.startswith('.') and item != "__pycache__":
                local_folders.append(item)

    # Match extension-node-map URLs to local folder names
    for url, info in url_to_nodes.items():
        # Extract repo name from github URL
        repo_name = url.rstrip('/').split('/')[-1]
        if repo_name.endswith('.py'):
            continue  # Skip single-file nodes

        # Try to match to a local folder
        matched_folder = None
        for folder in local_folders:
            if folder.lower() == repo_name.lower():
                matched_folder = folder
                break
            # Also try matching title_aux
            if info["title"] and folder.lower() == info["title"].lower().replace(" ", "-"):
                matched_folder = folder
                break

        if matched_folder:
            for node_type in info["nodes"]:
                node_map[node_type] = matched_folder

    # Strategy 3: Scan __init__.py or *.py files for NODE_CLASS_MAPPINGS
    for folder in local_folders:
        folder_path = os.path.join(CUSTOM_NODES_DIR, folder)
        found_nodes = scan_folder_for_nodes(folder_path)
        for node_type in found_nodes:
            if node_type not in node_map:  # Don't override existing mappings
                node_map[node_type] = folder

    return node_map


def scan_folder_for_nodes(folder_path):
    """Scan a custom node folder for NODE_CLASS_MAPPINGS to find registered node types."""
    found_nodes = []

    # Check __init__.py first
    init_py = os.path.join(folder_path, "__init__.py")
    py_files = [init_py] if os.path.exists(init_py) else []

    # Also check top-level .py files
    if os.path.isdir(folder_path):
        for f in os.listdir(folder_path):
            if f.endswith('.py') and f != "__init__.py":
                py_files.append(os.path.join(folder_path, f))

    for py_file in py_files:
        try:
            with open(py_file, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
            # Look for NODE_CLASS_MAPPINGS = { "NodeName": ClassName, ... }
            # Use regex to find quoted strings in NODE_CLASS_MAPPINGS
            mappings_match = re.findall(
                r'NODE_CLASS_MAPPINGS\s*[\[=].*?\{([^}]*)\}',
                content, re.DOTALL
            )
            for match in mappings_match:
                # Extract quoted node names
                names = re.findall(r'["\']([^"\']+)["\']', match)
                found_nodes.extend(names)

            # Also check for NODE_CLASS_MAPPINGS.update(...)
            update_matches = re.findall(
                r'NODE_CLASS_MAPPINGS\.update\s*\(\s*\{([^}]*)\}\s*\)',
                content, re.DOTALL
            )
            for match in update_matches:
                names = re.findall(r'["\']([^"\']+)["\']', match)
                found_nodes.extend(names)

        except Exception:
            pass

    return found_nodes


def identify_required_custom_nodes(nodes, node_map):
    """Given workflow nodes, identify which custom node folders are needed."""
    required_folders = set()
    unresolved_nodes = []
    builtin_nodes = []

    # Build comprehensive built-in node set
    builtin_set = scan_builtin_nodes()

    all_class_types = set()
    for node in nodes:
        ct = node["class_type"]
        if ct:
            all_class_types.add(ct)

    for class_type in sorted(all_class_types):
        if class_type in node_map:
            required_folders.add(node_map[class_type])
        elif class_type in builtin_set or any(class_type.startswith(p) for p in BUILTIN_NODE_PREFIXES):
            builtin_nodes.append(class_type)
        else:
            # Try fuzzy match with local folders
            matched = False
            for folder in os.listdir(CUSTOM_NODES_DIR):
                folder_path = os.path.join(CUSTOM_NODES_DIR, folder)
                if os.path.isdir(folder_path):
                    # Check if class_type appears in any .py file in this folder
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

            if not matched:
                unresolved_nodes.append(class_type)

    return required_folders, unresolved_nodes, builtin_nodes


# ─── Step 3: Extract Required Models ─────────────────────────────────────────

# Known widget field names that reference model files
MODEL_INPUT_KEYS = [
    "ckpt_name", "config_name", "lora_name", "vae_name",
    "control_net_name", "clip_name", "unet_name",
    "model_name", "upscale_model", "style_model_name",
    "gligen_name", "hypernetwork_name", "embedding_name",
    "clip_vision", "model_path", "diffusion_model",
    "weight_name", "clip_name1", "clip_name2", "clip_name3",
]

# Map from input key -> model folder name(s) to search
INPUT_KEY_TO_FOLDER = {
    "ckpt_name": ["checkpoints"],
    "config_name": ["configs"],
    "lora_name": ["loras"],
    "vae_name": ["vae"],
    "control_net_name": ["controlnet"],
    "clip_name": ["text_encoders", "clip"],
    "clip_name1": ["text_encoders", "clip"],
    "clip_name2": ["text_encoders", "clip"],
    "clip_name3": ["text_encoders", "clip"],
    "unet_name": ["diffusion_models", "unet"],
    "diffusion_model": ["diffusion_models", "unet"],
    "model_name": ["upscale_models", "checkpoints"],
    "upscale_model": ["upscale_models"],
    "style_model_name": ["style_models"],
    "gligen_name": ["gligen"],
    "hypernetwork_name": ["hypernetworks"],
    "clip_vision": ["clip_vision"],
}


def extract_model_references(nodes):
    """Extract all model file references from workflow nodes."""
    models = defaultdict(set)  # folder_type -> set of filenames

    for node in nodes:
        class_type = node["class_type"]

        # From API format inputs
        inputs = node.get("inputs", {})
        for key, value in inputs.items():
            if isinstance(value, str) and key in INPUT_KEY_TO_FOLDER:
                for folder in INPUT_KEY_TO_FOLDER[key]:
                    models[folder].add(value)
            elif isinstance(value, str) and key in MODEL_INPUT_KEYS:
                # Try to find which folder this model lives in
                found = find_model_in_folders(value)
                if found:
                    models[found[0]].add(value)

        # From UI format widgets_values (positional values)
        widgets = node.get("widgets_values", [])
        if widgets:
            for val in widgets:
                if isinstance(val, str) and looks_like_model_filename(val):
                    found = find_model_in_folders(val)
                    if found:
                        models[found[0]].add(val)

    return models


def looks_like_model_filename(value):
    """Check if a string looks like a model filename."""
    if not value or len(value) < 3:
        return False
    model_extensions = {'.safetensors', '.ckpt', '.pt', '.pth', '.bin', '.onnx', '.pkl', '.sft'}
    ext = os.path.splitext(value)[-1].lower()
    return ext in model_extensions


def find_model_in_folders(filename):
    """Find which model folder contains the given filename."""
    for folder in os.listdir(MODELS_DIR):
        folder_path = os.path.join(MODELS_DIR, folder)
        if os.path.isdir(folder_path):
            full_path = os.path.join(folder_path, filename)
            if os.path.exists(full_path):
                return (folder, full_path)
    return None


def find_all_model_files(models_dict):
    """Resolve model references to actual file paths. Returns (file_list, missing_files)."""
    file_list = []
    missing_files = []

    for folder_name, filenames in models_dict.items():
        for filename in filenames:
            # Search in models dir
            search_dirs = [os.path.join(MODELS_DIR, folder_name)]
            # Also check legacy paths
            if folder_name == "text_encoders":
                search_dirs.append(os.path.join(MODELS_DIR, "clip"))
            elif folder_name == "diffusion_models":
                search_dirs.append(os.path.join(MODELS_DIR, "unet"))

            found = False
            for search_dir in search_dirs:
                src = os.path.join(search_dir, filename)
                if os.path.exists(src):
                    rel_folder = os.path.basename(search_dir)
                    file_list.append((src, os.path.join("models", rel_folder, filename)))
                    found = True
                    break

            if not found:
                # Broad search across all model folders
                result = find_model_in_folders(filename)
                if result:
                    folder, full_path = result
                    file_list.append((full_path, os.path.join("models", folder, filename)))
                else:
                    rel_dest = os.path.join("models", folder_name, filename)
                    missing_files.append((filename, rel_dest))
                    print(f"  ⚠ Warning: Model not found locally: {filename}")

    return file_list, missing_files


# ─── Step 4: Scan custom nodes for additional model dependencies ─────────────

def scan_custom_node_model_deps(required_folders):
    """
    Some custom nodes store models in their own folders or in
    non-standard model directories. Scan for these.
    """
    extra_model_dirs = []

    for folder_name in required_folders:
        folder_path = os.path.join(CUSTOM_NODES_DIR, folder_name)
        if not os.path.isdir(folder_path):
            continue

        # Check if the custom node has its own models subfolder
        for sub in os.listdir(folder_path):
            sub_path = os.path.join(folder_path, sub)
            if os.path.isdir(sub_path) and sub.lower() in ('models', 'weights', 'pretrained', 'checkpoints'):
                if any(f.endswith(('.safetensors', '.pt', '.pth', '.onnx', '.bin')) for f in os.listdir(sub_path)):
                    extra_model_dirs.append((sub_path, os.path.join("custom_nodes", folder_name, sub)))

    # Also check for non-standard model folders in models/
    non_standard = []
    for folder in os.listdir(MODELS_DIR):
        if folder not in STANDARD_MODEL_FOLDERS:
            folder_path = os.path.join(MODELS_DIR, folder)
            if os.path.isdir(folder_path):
                non_standard.append(folder)

    return extra_model_dirs, non_standard


# ─── Step 5: Copy files ──────────────────────────────────────────────────────

def copy_with_progress(src, dst, description=""):
    """Copy a file or directory with progress display."""
    if os.path.isdir(src):
        dir_size = get_dir_size(src)
        print(f"    📁 {description} ({format_size(dir_size)})")
        shutil.copytree(src, dst, dirs_exist_ok=True)
    else:
        size = os.path.getsize(src)
        print(f"    📄 {description} ({format_size(size)})")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)

def interactive_download(missing_files, dest_dir):
    """Interactively help the user download missing models into the packaged output."""
    if not missing_files:
        return
        
    import urllib.request
    import urllib.parse
    
    def download_file(url, out_path):
        print(f"    ⬇️  Downloading from {url}...")
        try:
            req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
            with urllib.request.urlopen(req) as response:
                total_size = int(response.info().get('Content-Length', 0))
                with open(out_path, 'wb') as f:
                    downloaded = 0
                    block_size = 8192
                    while True:
                        buffer = response.read(block_size)
                        if not buffer:
                            break
                        downloaded += len(buffer)
                        f.write(buffer)
                        if total_size > 0:
                            percent = min(100, int(downloaded * 100 / total_size))
                            sys.stdout.write(f"\r    [{percent:3d}%] \t{format_size(downloaded)} / {format_size(total_size)}")
                            sys.stdout.flush()
            print("\n    ✅ 下載完成!")
            return True
        except Exception as e:
            print(f"\n    ❌ 下載失敗: {e}")
            if os.path.exists(out_path):
                os.remove(out_path)
            return False

    print("\n" + "─" * 60)
    print("  Step 6: 補齊缺失模型 (Downloading Missing Models)")
    print("─" * 60)
    
    for filename, rel_path in missing_files:
        print(f"\n  缺少模型: {filename}\n  內部預期路徑: {rel_path}")
        while True:
            print("    [1] 跳過 (Skip, 自己去下載)")
            print("    [2] 輸入直接下載網址 (Direct URL)")
            print("    [3] 輸入 HuggingFace Repo ID (例如: Kijai/flux-fp8)")
            print("    [4] 嘗試讓程式在 HuggingFace 自動搜尋")
            choice = input("    請選擇操作 [1-4]: ").strip()
            
            out_path = os.path.join(dest_dir, rel_path)
            
            if choice == "1":
                break
            elif choice == "2":
                url = input("    網址URL: ").strip()
                if url:
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    if download_file(url, out_path):
                        break
            elif choice == "3":
                repo = input("    Repo ID: ").strip()
                if repo:
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    url = f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(filename)}"
                    print("    嘗試下載主目錄...")
                    if download_file(url, out_path):
                        break
                    else:
                        print("    嘗試猜測子目錄 (例如 /unet, /vae, /lora)...")
                        found = False
                        for sub in ["unet", "vae", "loras", "checkpoints", "text_encoder", "diffusion_models"]:
                            sub_url = f"https://huggingface.co/{repo}/resolve/main/{sub}/{urllib.parse.quote(filename)}"
                            if download_file(sub_url, out_path):
                                found = True
                                break
                        if found: break
            elif choice == "4":
                print("    正在搜尋 HuggingFace...")
                query = os.path.splitext(filename)[0][:20]
                url = f"https://huggingface.co/api/models?search={urllib.parse.quote(query)}&limit=5"
                try:
                    req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                    with urllib.request.urlopen(req) as resp:
                        import json
                        results = json.loads(resp.read().decode())
                except Exception as e:
                    print(f"    搜尋失敗: {e}")
                    continue
                
                if not results:
                    print("    搜尋不到相關 Repo。")
                    continue
                    
                print("    找到以下候選 Repo:")
                for i, r in enumerate(results):
                    print(f"      [{i+1}] {r['id']}")
                r_c = input("    請選擇 Repo [1-5] 或直接按 Enter 取消: ").strip()
                if r_c.isdigit() and 1 <= int(r_c) <= len(results):
                    repo = results[int(r_c)-1]['id']
                    os.makedirs(os.path.dirname(out_path), exist_ok=True)
                    dl_url = f"https://huggingface.co/{repo}/resolve/main/{urllib.parse.quote(filename)}"
                    if download_file(dl_url, out_path):
                        break
                    else:
                        print("    下載失敗，該 Repo 中似乎沒有直接與此檔名一樣的檔案。")



def pack_comfyui(workflow_paths, output_dir, skip_confirm=False):
    """Main packing function supporting multiple workflows."""
    print_header()

    # ── Validate inputs ──
    valid_paths = []
    for wf in workflow_paths:
        path = os.path.abspath(wf)
        if not os.path.isfile(path):
            print(f"\n❌ Error: Workflow file not found: {path}")
        else:
            valid_paths.append(path)
            
    if not valid_paths:
        return False
        
    workflow_paths = valid_paths
    output_dir = os.path.abspath(output_dir)

    print(f"\n  📋 Source:    {SOURCE_ROOT}")
    for i, wf in enumerate(workflow_paths):
        print(f"  📋 Workflow {i+1}: {wf}")
    print(f"  📋 Output:    {output_dir}")

    # ── Step 1: Parse workflow ──
    print_step(1, "解析工作流 JSON (Parsing workflow JSON)")
    all_nodes = []
    for wf in workflow_paths:
        nodes = load_workflow(wf)
        all_nodes.extend(nodes)
        
    print(f"  ✅ Found {len(all_nodes)} total nodes in {len(workflow_paths)} workflow(s)")

    class_types = set(n["class_type"] for n in all_nodes if n["class_type"])
    print(f"  ✅ Found {len(class_types)} unique node types")

    # ── Step 2: Identify custom nodes ──
    print_step(2, "識別所需的自訂節點 (Identifying required custom nodes)")
    node_map = build_node_to_folder_map()
    print(f"  📊 Node map contains {len(node_map)} known node types")

    required_folders, unresolved, builtin = identify_required_custom_nodes(all_nodes, node_map)

    # Always include ComfyUI-Manager
    required_folders.add("ComfyUI-Manager")

    print(f"\n  ✅ Built-in nodes: {len(builtin)}")
    print(f"  ✅ Required custom node folders: {len(required_folders)}")
    for f in sorted(required_folders):
        folder_path = os.path.join(CUSTOM_NODES_DIR, f)
        exists = "✅" if os.path.isdir(folder_path) else "❌"
        print(f"      {exists} {f}")

    if unresolved:
        print(f"\n  ⚠ Unresolved node types ({len(unresolved)}):")
        for n in sorted(unresolved):
            print(f"      ❓ {n}")
        print("  (These may be built-in nodes or from unrecognized custom nodes)")

    # ── Step 3: Identify required models ──
    print_step(3, "識別所需的模型檔案 (Identifying required models)")
    models_dict = extract_model_references(all_nodes)
    model_files, missing_files = find_all_model_files(models_dict)

    # Check for non-standard model folders used by custom nodes
    extra_model_dirs, non_standard_folders = scan_custom_node_model_deps(required_folders)

    # Ask user about non-standard model folders
    selected_nonstandard = []
    if non_standard_folders:
        print(f"\n  📦 Found non-standard model folders in models/:")
        for i, f in enumerate(non_standard_folders):
            folder_path = os.path.join(MODELS_DIR, f)
            size = get_dir_size(folder_path)
            print(f"      [{i+1}] {f} ({format_size(size)})")
        print(f"\n  These may be required by custom nodes.")
        if not skip_confirm:
            sel = input("  Enter folder numbers to include (comma-separated, 'a' for all, Enter to skip): ").strip()
            if sel.lower() == 'a':
                selected_nonstandard = non_standard_folders
            elif sel:
                try:
                    indices = [int(x.strip()) - 1 for x in sel.split(',')]
                    selected_nonstandard = [non_standard_folders[i] for i in indices if 0 <= i < len(non_standard_folders)]
                except (ValueError, IndexError):
                    print("  ⚠ Invalid input, skipping non-standard folders")

    total_model_size = sum(os.path.getsize(src) for src, _ in model_files if os.path.isfile(src))
    print(f"\n  ✅ Required model files: {len(model_files)} ({format_size(total_model_size)})")
    for src, rel in model_files:
        size = os.path.getsize(src) if os.path.isfile(src) else 0
        print(f"      📄 {rel} ({format_size(size)})")
        
    if missing_files:
        print(f"\n  ⚠ 缺失的模型 (Missing Models): {len(missing_files)}")
        for fn, rp in missing_files:
            print(f"      ❌ {fn} (預期: {rp})")

    # ── Estimate total size ──
    print_step(4, "估算打包大小 (Estimating pack size)")
    python_size = get_dir_size(os.path.join(SOURCE_ROOT, "python_embeded"))
    comfyui_base_size = sum(
        os.path.getsize(os.path.join(COMFYUI_DIR, f))
        for f in os.listdir(COMFYUI_DIR)
        if os.path.isfile(os.path.join(COMFYUI_DIR, f))
    )
    custom_nodes_size = sum(
        get_dir_size(os.path.join(CUSTOM_NODES_DIR, f))
        for f in required_folders
        if os.path.isdir(os.path.join(CUSTOM_NODES_DIR, f))
    )
    nonstandard_size = sum(
        get_dir_size(os.path.join(MODELS_DIR, f))
        for f in selected_nonstandard
    )

    total_est = python_size + comfyui_base_size + custom_nodes_size + total_model_size + nonstandard_size
    print(f"  📊 python_embeded:    {format_size(python_size)}")
    print(f"  📊 ComfyUI base:      {format_size(comfyui_base_size)}")
    print(f"  📊 Custom nodes:      {format_size(custom_nodes_size)}")
    print(f"  📊 Models:            {format_size(total_model_size)}")
    if nonstandard_size:
        print(f"  📊 Extra model dirs:  {format_size(nonstandard_size)}")
    print(f"  {'─' * 40}")
    print(f"  📊 Estimated total:   {format_size(total_est)}")

    # ── Confirm ──
    pack_python = True
    if not skip_confirm:
        print(f"\n  💡 提示: 目前的 python_embeded 環境比較龐大 ({format_size(python_size)})。")
        print("     它包含了完整的 PyTorch 深度學習套件，是讓隨身碟可以「隨插即用」的關鍵。")
        print("     但如果對方電腦已經有裝好 ComfyUI 的環境，你可以選擇不打包它以節省空間。")
        ans_py = input("  是否要包含 python_embeded？ (Y/N，預設 Y): ").strip().lower()
        if ans_py == 'n':
            pack_python = False
            total_est -= python_size
            print(f"  📊 扣除 python_embeded 後的新預估大小: {format_size(total_est)}")

        confirm = input(f"\n  準備好打包到 {output_dir} 了嗎? (y/n): ").strip().lower()
        if confirm != 'y':
            print("\n  ❌ Packing cancelled.")
            return False

    # ── Step 5: Copy files ──
    print_step(5, "開始打包複製 (Copying files)")
    start_time = time.time()

    # 5a: Copy python_embeded
    if pack_python:
        print("\n  [1/6] Copying python_embeded...")
        src_python = os.path.join(SOURCE_ROOT, "python_embeded")
        dst_python = os.path.join(output_dir, "python_embeded")
        if os.path.isdir(src_python):
            copy_with_progress(src_python, dst_python, "python_embeded")
    else:
        print("\n  [1/6] Skipping python_embeded...")

    # 5b: Copy ComfyUI base files (not custom_nodes, not models, not output/temp)
    print("\n  [2/6] Copying ComfyUI base files...")
    dst_comfyui = os.path.join(output_dir, "ComfyUI")
    os.makedirs(dst_comfyui, exist_ok=True)

    skip_dirs = {'custom_nodes', 'models', 'output', 'temp', 'input', '.git', '__pycache__', 'user'}
    for item in os.listdir(COMFYUI_DIR):
        src_item = os.path.join(COMFYUI_DIR, item)
        dst_item = os.path.join(dst_comfyui, item)
        if item in skip_dirs:
            continue
        if os.path.isfile(src_item):
            copy_with_progress(src_item, dst_item, item)
        elif os.path.isdir(src_item):
            copy_with_progress(src_item, dst_item, item)

    # Create empty output/temp/input dirs
    for d in ['output', 'temp', 'input']:
        os.makedirs(os.path.join(dst_comfyui, d), exist_ok=True)

    # 5c: Copy required custom nodes
    print("\n  [3/6] Copying custom nodes...")
    dst_custom_nodes = os.path.join(dst_comfyui, "custom_nodes")
    os.makedirs(dst_custom_nodes, exist_ok=True)

    for folder in sorted(required_folders):
        src_folder = os.path.join(CUSTOM_NODES_DIR, folder)
        dst_folder = os.path.join(dst_custom_nodes, folder)
        if os.path.isdir(src_folder):
            copy_with_progress(src_folder, dst_folder, folder)
        else:
            print(f"    ⚠ Custom node folder not found: {folder}")

    # 5d: Copy required models
    print("\n  [4/6] Copying models...")
    dst_models = os.path.join(dst_comfyui, "models")
    os.makedirs(dst_models, exist_ok=True)

    # Create all standard model folders (empty)
    for folder in STANDARD_MODEL_FOLDERS:
        os.makedirs(os.path.join(dst_models, folder), exist_ok=True)

    for src, rel_path in model_files:
        dst = os.path.join(dst_comfyui, rel_path)
        if os.path.exists(src):
            copy_with_progress(src, dst, os.path.basename(rel_path))

    # Copy non-standard model folders if selected
    for folder in selected_nonstandard:
        src_folder = os.path.join(MODELS_DIR, folder)
        dst_folder = os.path.join(dst_models, folder)
        if os.path.isdir(src_folder):
            copy_with_progress(src_folder, dst_folder, f"models/{folder}")

    # Copy extra model dirs from custom nodes
    for src_dir, rel_path in extra_model_dirs:
        dst_dir = os.path.join(dst_comfyui, rel_path)
        copy_with_progress(src_dir, dst_dir, rel_path)

    # 5e: Copy batch files
    print("\n  [5/6] Copying launch scripts...")
    for bat in ['run_nvidia_gpu.bat', 'run_cpu.bat']:
        src_bat = os.path.join(SOURCE_ROOT, bat)
        dst_bat = os.path.join(output_dir, bat)
        if os.path.isfile(src_bat):
            copy_with_progress(src_bat, dst_bat, bat)

    # 5f: Copy workflow JSONs
    print("\n  [6/6] Copying workflow JSON(s)...")
    dst_workflow_dir = os.path.join(dst_comfyui, "user", "default", "workflows")
    os.makedirs(dst_workflow_dir, exist_ok=True)
    
    for wf_path in workflow_paths:
        wf_basename = os.path.basename(wf_path)
        shutil.copy2(wf_path, os.path.join(dst_workflow_dir, wf_basename))
        shutil.copy2(wf_path, os.path.join(output_dir, wf_basename))
        print(f"    📄 {wf_basename}")

    # ── Step 6: Missing Models Interactive Download ──
    if missing_files:
        interactive_download(missing_files, dst_comfyui)

    elapsed = time.time() - start_time
    final_size = get_dir_size(output_dir)

    print(f"\n{'=' * 70}")
    print(f"  ✅ 打包完成! (Packing complete!)")
    print(f"  📁 Output: {output_dir}")
    print(f"  📊 Size:   {format_size(final_size)}")
    print(f"  ⏱  Time:   {elapsed:.1f}s")
    print(f"  📋 Workflow: {wf_basename}")
    print(f"\n  使用方式: 在目標電腦上執行 run_nvidia_gpu.bat 啟動 ComfyUI")
    print(f"  然後載入工作流: {wf_basename}")
    print(f"{'=' * 70}\n")

    return True


# ─── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="ComfyUI Workflow Packer - 打包工作流到可攜帶版本"
    )
    parser.add_argument('--workflow', '-w', nargs='+', type=str, help='Path to workflow JSON file(s)')
    parser.add_argument('--output', '-o', type=str, help='Output directory for packed ComfyUI')
    parser.add_argument('--source', '-s', type=str, help='(Optional) Explicit ComfyUI source folder. Will auto-detect from workflow by default.')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompts')

    args = parser.parse_args()

    workflow_paths = args.workflow
    output_dir = args.output
    explicit_source = args.source

    if not workflow_paths:
        print_header()
        print("\n  請輸入工作流 JSON 檔案路徑 (Please enter workflow JSON path):")
        print("  💡 支援同時輸入多個檔案 (用空白分隔，或加上雙引號，若檔案路徑無空格可直接拖曳多個檔案)")
        raw_input_wf = input("  > ").strip()
        
        import shlex
        try:
            workflow_paths = shlex.split(raw_input_wf)
        except Exception:
            workflow_paths = [w.strip() for w in raw_input_wf.replace('"', '').replace("'", "").split(" ") if w.strip()]

    # Validate and setup paths dynamically based on the first JSON location
    if workflow_paths:
        setup_paths(workflow_paths[0], explicit_source)

    if not output_dir:
        print("\n  請輸入打包目標路徑 (Please enter output directory path):")
        print("  (例如: D:\\ComfyUI_packed 或 E:\\comfyui_for_client)")
        output_dir = input("  > ").strip().strip('"').strip("'")

    if not workflow_paths or not output_dir:
        print("\n❌ Error: Both workflow path and output directory are required.")
        sys.exit(1)

    # Automatically create a subfolder
    if len(workflow_paths) == 1:
        wf_name = os.path.splitext(os.path.basename(workflow_paths[0]))[0]
        folder_name = f"ComfyUI_windows_portable_{wf_name}"
    else:
        folder_name = f"ComfyUI_windows_portable_Multi_Workflows"
        
    final_output_dir = os.path.join(os.path.abspath(output_dir), folder_name)

    success = pack_comfyui(workflow_paths, final_output_dir, skip_confirm=args.yes)
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
