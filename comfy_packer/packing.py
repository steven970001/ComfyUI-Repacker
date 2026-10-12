"""File-copy execution and the main full-pack orchestration.

M1: ported as-is from the original monolith (full-pack mode only),
re-plumbed through SourceEnv and the split-out resolver modules.
Packing-mode variants (custom-nodes-only / models-only / custom combination)
and the ignore-pattern exclusions are added in later milestones.
"""

import os
import shutil
import time

from . import node_resolver, model_resolver, node_overrides, workflow as workflow_mod
from .constants import STANDARD_MODEL_FOLDERS, COPY_IGNORE_PATTERNS
from .context import setup_source_env
from .downloader import interactive_download
from .manifest import ManifestBuilder, write_manifest, render_human_summary
from .ui import print_header, print_step, format_size, get_dir_size

_IGNORE_DIR_CONTENTS = shutil.ignore_patterns(*COPY_IGNORE_PATTERNS)
_IGNORE_DIR_CONTENTS_KEEP_GIT = shutil.ignore_patterns(*(p for p in COPY_IGNORE_PATTERNS if p != ".git"))

UPDATE_POLICIES = ("none", "core", "core_and_nodes")
REQUIRED_UPDATE_FILES = ("update.py", "update_comfyui.bat", "update_comfyui_stable.bat")


def _legacy_keep_git_to_update_policy(keep_git):
    if keep_git is None:
        return None
    return "core_and_nodes" if keep_git else "none"


def _default_update_policy(layout, include_comfyui_base, include_custom_nodes, include_python_embeded):
    if layout == "full_skeleton" and include_comfyui_base and include_python_embeded:
        return "core_and_nodes" if include_custom_nodes else "core"
    return "none"


def _prompt_update_policy(default_policy):
    if default_policy == "none":
        return "none"

    print("\n  Update support")
    print("     Make this portable updatable on another computer?")
    print("     This copies update/ and keeps the Git metadata needed by the official updater.")
    ans = input("  Enable update support? (Y/n): ").strip().lower()
    if ans == "n":
        return "none"
    return default_policy


def _inspect_update_support(env, update_policy):
    update_dir = os.path.join(env.source_root, "update")
    update_enabled = update_policy != "none"
    scripts = [
        name for name in REQUIRED_UPDATE_FILES
        if update_enabled and os.path.isfile(os.path.join(update_dir, name))
    ]
    missing = [
        os.path.join("update", name)
        for name in REQUIRED_UPDATE_FILES
        if update_enabled and not os.path.isfile(os.path.join(update_dir, name))
    ]

    python_exe = os.path.join(env.source_root, "python_embeded", "python.exe")
    comfyui_git = os.path.join(env.comfyui_dir, ".git")
    if update_enabled and not os.path.isfile(python_exe):
        missing.append(os.path.join("python_embeded", "python.exe"))
    if update_enabled and not os.path.isdir(comfyui_git):
        missing.append(os.path.join("ComfyUI", ".git"))

    return {
        "enabled": update_enabled,
        "policy": update_policy,
        "source_update_dir": update_dir,
        "required_scripts": scripts,
        "missing_requirements": missing,
        "update_folder_copied": False,
        "comfyui_git_present": os.path.isdir(comfyui_git),
        "python_embeded_present": os.path.isfile(python_exe),
        "custom_nodes_git_kept": [],
        "custom_nodes_without_git": [],
    }


def _validate_or_disable_update_support(update_policy, update_info, skip_confirm, explicit_update_policy):
    if update_policy == "none" or not update_info["missing_requirements"]:
        return update_policy

    print("\n  Update support cannot be enabled because the source portable is missing:")
    for item in update_info["missing_requirements"]:
        print(f"    - {item}")

    if skip_confirm or explicit_update_policy:
        raise RuntimeError(
            "Update support was requested, but required portable update files are missing: "
            + ", ".join(update_info["missing_requirements"])
        )

    ans = input("  Continue without update support? (y/N): ").strip().lower()
    if ans == "y":
        update_info["enabled"] = False
        update_info["policy"] = "none"
        return "none"
    return "cancelled"


def _prompt_manual_node_resolution(unresolved_class_types, env, resolution_details):
    """Let the user manually map still-unresolved class_types to a local
    custom_nodes folder (or skip). Choices are persisted to the override
    cache immediately so they're never asked twice for the same node type
    on this ComfyUI install."""
    resolved = {}
    if not os.path.isdir(env.custom_nodes_dir):
        return resolved
    local_folders = sorted(
        f for f in os.listdir(env.custom_nodes_dir)
        if os.path.isdir(os.path.join(env.custom_nodes_dir, f))
    )
    if not local_folders:
        return resolved

    print("\n  🔧 手動解析未知節點 (Manually resolve unresolved node types)")
    print("     以下是本機 custom_nodes 資料夾清單，供你判斷每個未知節點屬於哪一個:")
    for i, folder in enumerate(local_folders):
        print(f"      [{i+1}] {folder}")

    for class_type in sorted(unresolved_class_types):
        node_ids = resolution_details.get(class_type, {}).get("node_ids", [])
        prompt = f"\n    ❓ {class_type}"
        if node_ids:
            prompt += f"  (node id: {', '.join(node_ids)})"
        print(prompt)
        sel = input(f"    請輸入對應資料夾編號 (1-{len(local_folders)}，Enter 跳過): ").strip()
        if sel.isdigit() and 1 <= int(sel) <= len(local_folders):
            folder = local_folders[int(sel) - 1]
            resolved[class_type] = folder
            node_overrides.set_override(class_type, folder, env.source_root)
            print(f"    ✅ 已記錄: {class_type} -> {folder}（下次打包會自動套用）")

    return resolved


def _copy_file_with_retry(src, dst, attempts=3, backoff_seconds=5):
    """Multi-GB model files copied to a slow/external/network drive can hit
    transient OSErrors partway through (e.g. Windows WinError 121, "The
    semaphore timeout period has expired") that succeed on retry. A single
    such failure shouldn't abort an otherwise-successful multi-hour pack."""
    last_err = None
    for attempt in range(1, attempts + 1):
        try:
            shutil.copy2(src, dst)
            return
        except OSError as e:
            last_err = e
            if os.path.exists(dst):
                try:
                    os.remove(dst)  # don't leave a truncated partial file behind
                except OSError:
                    pass
            if attempt < attempts:
                print(f"    ⚠ Copy failed (attempt {attempt}/{attempts}): {e} — retrying in {backoff_seconds}s...")
                time.sleep(backoff_seconds)
    raise last_err


def copy_with_progress(src, dst, description="", keep_git=False):
    """Copy a file or directory with progress display, skipping dev cruft
    (.git, __pycache__, tests, venvs, ...) via COPY_IGNORE_PATTERNS. Pass
    keep_git=True to keep .git (needed for the copied folder to stay
    updatable via `git pull` / official update scripts / ComfyUI-Manager)."""
    if os.path.isdir(src):
        dir_size = get_dir_size(src)
        print(f"    📁 {description} ({format_size(dir_size)})")
        ignore = _IGNORE_DIR_CONTENTS_KEEP_GIT if keep_git else _IGNORE_DIR_CONTENTS
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore)
    else:
        size = os.path.getsize(src)
        print(f"    📄 {description} ({format_size(size)})")
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        _copy_file_with_retry(src, dst)


def _write_drop_in_readme(output_dir, mode, include_custom_nodes, include_models, wf_basenames):
    """A drop-in pack (custom-nodes-only / models-only / a "custom"
    combination without the ComfyUI base) has no runnable ComfyUI of its
    own — write a short README explaining what to merge and where."""
    lines = [
        "ComfyUI Workflow Packer — Drop-in Package",
        "=" * 50,
        "",
        f"Mode: {mode}",
        "",
        "This package does NOT contain a runnable ComfyUI install. It is meant",
        "to be merged into an existing ComfyUI installation on the target machine:",
        "",
    ]
    if include_custom_nodes:
        lines.append("  - Copy the folders under custom_nodes/ into your ComfyUI/custom_nodes/ directory.")
    if include_models:
        lines.append("  - Copy the folders under models/ into your ComfyUI/models/ directory (merge, don't overwrite).")
    lines += [
        "",
        "Then restart ComfyUI and load the included workflow:",
    ]
    for wf in wf_basenames:
        lines.append(f"  - {wf}")
    lines += [
        "",
        "See manifest.json / manifest.txt in this folder for exactly what was",
        "included, skipped, or missing.",
    ]
    with open(os.path.join(output_dir, "README_INSTALL.txt"), 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))


_MODE_DEFAULTS = {
    # mode -> (include_comfyui_base, include_custom_nodes, include_models)
    # include_python_embeded is handled separately (only ever relevant
    # alongside comfyui_base, and only asked interactively for "full").
    "full": (True, True, True),
    "custom_nodes": (False, True, False),
    "models": (False, False, True),
}


def resolve_output_layout(include_comfyui_base, include_custom_nodes, include_models):
    """"drop_in" (a flat custom_nodes/ and/or models/ folder meant to be
    merged into an existing ComfyUI install) vs "full_skeleton" (the
    complete portable ComfyUI/ tree). Any combination missing the ComfyUI
    base but keeping nodes/models collapses to the same drop-in shape as
    the dedicated custom-nodes-only/models-only modes — one code path for
    all four menu options instead of four divergent ones."""
    if not include_comfyui_base and (include_custom_nodes or include_models):
        return "drop_in"
    return "full_skeleton"


def pack_comfyui(workflow_paths, output_dir, skip_confirm=False, explicit_source=None,
                  use_introspection=True, introspect_timeout=25,
                  mode="full", include_python_embeded=None, include_comfyui_base=None,
                  include_custom_nodes=None, include_models=None, keep_git=None,
                  update_policy=None):
    """Main packing function supporting multiple workflows and packing modes.

    mode: "full" | "custom_nodes" | "models" | "custom". For "custom", the
    include_* toggles are required (explicit selection); for the other three
    modes any include_* left as None falls back to that mode's defaults.

    update_policy: "none" | "core" | "core_and_nodes". The legacy keep_git
    flag is still accepted and maps to core_and_nodes/none when
    update_policy is not provided.
    """
    print_header()

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

    defaults = _MODE_DEFAULTS.get(mode, (True, True, True))
    if include_comfyui_base is None:
        include_comfyui_base = defaults[0]
    if include_custom_nodes is None:
        include_custom_nodes = defaults[1]
    if include_models is None:
        include_models = defaults[2]
    if include_python_embeded is None:
        include_python_embeded = include_comfyui_base and mode == "full"

    layout = resolve_output_layout(include_comfyui_base, include_custom_nodes, include_models)
    if layout == "drop_in":
        include_python_embeded = False  # meaningless without a ComfyUI base to run it against

    explicit_update_policy = update_policy is not None or keep_git is not None
    if update_policy is None:
        update_policy = _legacy_keep_git_to_update_policy(keep_git)
    if update_policy is not None and update_policy not in UPDATE_POLICIES:
        raise ValueError(f"Unknown update_policy: {update_policy}")
    if update_policy is None:
        default_policy = _default_update_policy(
            layout, include_comfyui_base, include_custom_nodes, include_python_embeded
        )
        update_policy = default_policy if skip_confirm else _prompt_update_policy(default_policy)

    if update_policy != "none":
        if layout != "full_skeleton" or not include_comfyui_base:
            if explicit_update_policy or skip_confirm:
                raise RuntimeError("Update support requires a full portable package with the ComfyUI base.")
            print("\n  Update support is only available for full portable packages; disabling it for this drop-in pack.")
            update_policy = "none"
        elif not include_python_embeded:
            print("\n  Update support requires python_embeded; including it automatically.")
            include_python_embeded = True

    env = setup_source_env(workflow_paths[0], explicit_source)
    update_info = _inspect_update_support(env, update_policy)
    update_policy = _validate_or_disable_update_support(
        update_policy, update_info, skip_confirm, explicit_update_policy
    )
    if update_policy == "cancelled":
        print("\n  Packing cancelled.")
        return False
    manifest_builder = ManifestBuilder(mode, env.source_root, output_dir, workflow_paths)

    print(f"\n  📋 Source:    {env.source_root}")
    for i, wf in enumerate(workflow_paths):
        print(f"  📋 Workflow {i+1}: {wf}")
    print(f"  📋 Output:    {output_dir}")
    print(f"  📋 Mode:      {mode}  (layout: {layout})")
    print(f"  📋 Include:   python_embeded={include_python_embeded} comfyui_base={include_comfyui_base} custom_nodes={include_custom_nodes} models={include_models}")
    print(f"  📋 Update:    {update_policy}")

    # ── Step 1: Parse workflow ──
    print_step(1, "解析工作流 JSON (Parsing workflow JSON)")
    all_nodes = []
    for wf in workflow_paths:
        nodes = workflow_mod.load_workflow(wf)
        all_nodes.extend(nodes)

    print(f"  ✅ Found {len(all_nodes)} total nodes in {len(workflow_paths)} workflow(s)")

    class_types = set(n["class_type"] for n in all_nodes if n["class_type"])
    print(f"  ✅ Found {len(class_types)} unique node types")

    # ── Step 2: Identify custom nodes ──
    required_folders = set()
    unresolved, builtin = [], []
    resolution_details = {}
    dynamic_folders = set()
    introspection_results = {}

    if include_custom_nodes:
        print_step(2, "識別所需的自訂節點 (Identifying required custom nodes)")
        node_map, dynamic_folders = node_resolver.build_node_to_folder_map(env)
        print(f"  📊 Node map contains {len(node_map)} known node types")
        if dynamic_folders:
            print(f"  ℹ {len(dynamic_folders)} folder(s) assemble NODE_CLASS_MAPPINGS dynamically (relying on introspection/manual override): {', '.join(sorted(dynamic_folders))}")

        introspection_map = {}
        if use_introspection:
            local_folders = [
                f for f in os.listdir(env.custom_nodes_dir)
                if os.path.isdir(os.path.join(env.custom_nodes_dir, f)) and not f.startswith('.') and f != "__pycache__"
            ]
            python_exe = node_resolver.find_source_python_exe(env)
            if python_exe:
                print(f"  🔬 Introspecting {len(local_folders)} custom_nodes folder(s) via {python_exe}...")

                def _on_progress(done, total, result):
                    status = "ok" if result.get("ok") else f"failed ({result.get('error', '?')[:60]})"
                    print(f"      [{done}/{total}] {result.get('folder')}: {status}")

                introspection_results = node_resolver.introspect_folders(
                    env, local_folders, timeout_s=introspect_timeout, on_progress=_on_progress
                )
                introspection_map = node_resolver.build_introspection_node_map(introspection_results)
                succeeded = sum(1 for r in introspection_results.values() if r.get("ok"))
                print(f"  ✅ Introspection succeeded for {succeeded}/{len(local_folders)} folder(s)")
            else:
                print("  ⚠ source python_embeded not found — skipping introspection, falling back to regex/grep detection")

        override_map = node_overrides.build_override_map(class_types, env.source_root)
        if override_map:
            print(f"  📌 Applying {len(override_map)} cached manual override(s) from a previous run")

        required_folders, unresolved, builtin, resolution_details = node_resolver.identify_required_custom_nodes(
            all_nodes, node_map, env, introspection_map=introspection_map, override_map=override_map
        )

        required_folders.add("ComfyUI-Manager")
        resolution_details.setdefault("ComfyUI-Manager", {"folder": "ComfyUI-Manager", "method": "always_included", "node_ids": []})

        print(f"\n  ✅ Built-in nodes: {len(builtin)}")
        print(f"  ✅ Required custom node folders: {len(required_folders)}")
        for f in sorted(required_folders):
            folder_path = os.path.join(env.custom_nodes_dir, f)
            exists = "✅" if os.path.isdir(folder_path) else "❌"
            print(f"      {exists} {f}")

        if unresolved:
            print(f"\n  ⚠ Unresolved node types ({len(unresolved)}):")
            for n in sorted(unresolved):
                print(f"      ❓ {n}")
            print("  (These may be built-in nodes or from unrecognized custom nodes)")

            if not skip_confirm:
                resolved_via_manual = _prompt_manual_node_resolution(unresolved, env, resolution_details)
                for class_type, folder in resolved_via_manual.items():
                    required_folders.add(folder)
                    unresolved.remove(class_type)
                    node_ids = resolution_details.get(class_type, {}).get("node_ids", [])
                    resolution_details[class_type] = {"folder": folder, "method": "manual_override", "node_ids": node_ids}
    else:
        print_step(2, "略過自訂節點識別 (Skipping custom node identification — not included in this mode)")

    # ── Step 3: Identify required models ──
    model_files, missing_files = [], []
    model_metadata = {}
    extra_model_dirs, selected_nonstandard = [], []
    total_model_size = 0

    if include_models:
        print_step(3, "識別所需的模型檔案 (Identifying required models)")
        models_dict, model_metadata = model_resolver.extract_model_references(all_nodes, env)
        model_files, missing_files = model_resolver.find_all_model_files(models_dict, env)

        extra_model_dirs, non_standard_folders = model_resolver.scan_custom_node_model_deps(required_folders, env)

        if non_standard_folders:
            print(f"\n  📦 Found non-standard model folders in models/:")
            for i, f in enumerate(non_standard_folders):
                folder_path = os.path.join(env.models_dir, f)
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
    else:
        print_step(3, "略過模型識別 (Skipping model identification — not included in this mode)")

    # ── Estimate total size ──
    print_step(4, "估算打包大小 (Estimating pack size)")
    python_size = get_dir_size(os.path.join(env.source_root, "python_embeded")) if include_python_embeded else 0
    comfyui_base_size = 0
    if include_comfyui_base:
        comfyui_base_size = sum(
            os.path.getsize(os.path.join(env.comfyui_dir, f))
            for f in os.listdir(env.comfyui_dir)
            if os.path.isfile(os.path.join(env.comfyui_dir, f))
        )
    custom_nodes_size = 0
    if include_custom_nodes:
        custom_nodes_size = sum(
            get_dir_size(os.path.join(env.custom_nodes_dir, f))
            for f in required_folders
            if os.path.isdir(os.path.join(env.custom_nodes_dir, f))
        )
    nonstandard_size = sum(
        get_dir_size(os.path.join(env.models_dir, f))
        for f in selected_nonstandard
    ) if include_models else 0

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
    keep_comfyui_git = update_policy in ("core", "core_and_nodes")
    keep_custom_node_git = update_policy == "core_and_nodes"
    keep_git = keep_custom_node_git
    pack_python = include_python_embeded
    if keep_git is None:
        keep_git = False
        if not skip_confirm and (include_comfyui_base or include_custom_nodes):
            print("\n  💡 提示: 保留 .git 版本資訊（以及來源的 update/ 資料夾）可以讓拿到這份打包的人")
            print("     之後用官方 update_comfyui.bat 或 ComfyUI-Manager 的「Update」按鈕更新 ComfyUI / 節點。")
            print("     不保留的話，這份打包會缺少更新機制所需的版本資料（也不含 update/ 資料夾），但體積較小。")
            ans_git = input("  是否保留 Git 版本資訊以便未來更新？ (y/N，預設 N): ").strip().lower()
            keep_git = ans_git == 'y'
    print(f"  📋 Update policy: {update_policy}")
    print(f"  📋 Keep ComfyUI .git: {keep_comfyui_git}")
    print(f"  📋 Keep custom node .git: {keep_custom_node_git}")

    if not skip_confirm:
        if pack_python and update_policy == "none":
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

    if update_policy == "core_and_nodes":
        for folder in sorted(required_folders):
            src_folder = os.path.join(env.custom_nodes_dir, folder)
            if os.path.isdir(os.path.join(src_folder, ".git")):
                update_info["custom_nodes_git_kept"].append(folder)
            elif os.path.isdir(src_folder):
                update_info["custom_nodes_without_git"].append(folder)

    manifest_builder.set_included(
        python_embeded=pack_python, comfyui_base=include_comfyui_base,
        custom_nodes=include_custom_nodes, models=include_models, keep_git=keep_git,
    )
    manifest_builder.set_update_support(update_info)
    manifest_builder.set_node_resolution(required_folders, resolution_details, unresolved, builtin)
    manifest_builder.set_introspection_results(introspection_results)
    manifest_builder.set_dynamic_folders(dynamic_folders)
    manifest_builder.set_model_resolution(model_files, missing_files, model_metadata, selected_nonstandard, extra_model_dirs)
    manifest_builder.set_sizes({
        "python_embeded": python_size if pack_python else 0,
        "comfyui_base": comfyui_base_size,
        "custom_nodes": custom_nodes_size,
        "models": total_model_size,
        "nonstandard_models": nonstandard_size,
        "total_estimated": total_est,
    })

    # ── Step 5: Copy files ──
    print_step(5, "開始打包複製 (Copying files)")
    start_time = time.time()
    wf_basenames = []

    # full_skeleton nests custom_nodes/models under an "ComfyUI/" dir meant
    # to run standalone; drop_in places them directly under output_dir as a
    # folder meant to be merged into an existing install.
    content_root = os.path.join(output_dir, "ComfyUI") if layout == "full_skeleton" else output_dir
    dst_comfyui = content_root if layout == "full_skeleton" else None

    try:
        if include_python_embeded and pack_python:
            print("\n  Copying python_embeded...")
            src_python = os.path.join(env.source_root, "python_embeded")
            dst_python = os.path.join(output_dir, "python_embeded")
            if os.path.isdir(src_python):
                copy_with_progress(src_python, dst_python, "python_embeded")

        if include_comfyui_base and layout == "full_skeleton":
            print("\n  Copying ComfyUI base files...")
            os.makedirs(dst_comfyui, exist_ok=True)

            skip_dirs = {'custom_nodes', 'models', 'output', 'temp', 'input', '__pycache__', 'user'}
            if not keep_comfyui_git:
                skip_dirs.add('.git')
            for item in os.listdir(env.comfyui_dir):
                src_item = os.path.join(env.comfyui_dir, item)
                dst_item = os.path.join(dst_comfyui, item)
                if item in skip_dirs:
                    continue
                if os.path.isfile(src_item):
                    copy_with_progress(src_item, dst_item, item)
                elif os.path.isdir(src_item):
                    copy_with_progress(src_item, dst_item, item, keep_git=keep_comfyui_git)

            for d in ['output', 'temp', 'input']:
                os.makedirs(os.path.join(dst_comfyui, d), exist_ok=True)

        if include_custom_nodes:
            print("\n  Copying custom nodes...")
            dst_custom_nodes = os.path.join(content_root, "custom_nodes")
            os.makedirs(dst_custom_nodes, exist_ok=True)

            for folder in sorted(required_folders):
                src_folder = os.path.join(env.custom_nodes_dir, folder)
                dst_folder = os.path.join(dst_custom_nodes, folder)
                if os.path.isdir(src_folder):
                    copy_with_progress(src_folder, dst_folder, folder, keep_git=keep_custom_node_git)
                else:
                    print(f"    ⚠ Custom node folder not found: {folder}")

            for src_dir, rel_path in extra_model_dirs:
                # rel_path is "custom_nodes/<folder>/<sub>" — always lands
                # under content_root regardless of layout.
                dst_dir = os.path.join(content_root, rel_path)
                copy_with_progress(src_dir, dst_dir, rel_path)

        if include_models:
            print("\n  Copying models...")
            dst_models = os.path.join(content_root, "models")
            os.makedirs(dst_models, exist_ok=True)

            for folder in STANDARD_MODEL_FOLDERS:
                os.makedirs(os.path.join(dst_models, folder), exist_ok=True)

            for src, rel_path in model_files:
                dst = os.path.join(content_root, rel_path)
                if os.path.exists(src):
                    copy_with_progress(src, dst, os.path.basename(rel_path))

            for folder in selected_nonstandard:
                src_folder = os.path.join(env.models_dir, folder)
                dst_folder = os.path.join(dst_models, folder)
                if os.path.isdir(src_folder):
                    copy_with_progress(src_folder, dst_folder, f"models/{folder}")

        if layout == "full_skeleton" and include_comfyui_base:
            print("\n  Copying launch scripts...")
            for bat in ['run_nvidia_gpu.bat', 'run_cpu.bat']:
                src_bat = os.path.join(env.source_root, bat)
                dst_bat = os.path.join(output_dir, bat)
                if os.path.isfile(src_bat):
                    copy_with_progress(src_bat, dst_bat, bat)

            if update_policy != "none":
                src_update = os.path.join(env.source_root, "update")
                if os.path.isdir(src_update):
                    print("\n  Copying update/ folder (官方更新腳本)...")
                    copy_with_progress(src_update, os.path.join(output_dir, "update"), "update", keep_git=True)
                    update_info["update_folder_copied"] = True

        print("\n  Copying workflow JSON(s)...")
        if layout == "full_skeleton" and include_comfyui_base:
            dst_workflow_dir = os.path.join(dst_comfyui, "user", "default", "workflows")
            os.makedirs(dst_workflow_dir, exist_ok=True)
        else:
            dst_workflow_dir = None

        for wf_path in workflow_paths:
            wf_basename = os.path.basename(wf_path)
            wf_basenames.append(wf_basename)
            if dst_workflow_dir:
                shutil.copy2(wf_path, os.path.join(dst_workflow_dir, wf_basename))
            shutil.copy2(wf_path, os.path.join(output_dir, wf_basename))
            print(f"    📄 {wf_basename}")

        if layout == "drop_in":
            _write_drop_in_readme(output_dir, mode, include_custom_nodes, include_models, wf_basenames)

        # ── Missing Models Interactive Download ──
        if missing_files:
            interactive_download(missing_files, content_root if layout == "full_skeleton" else output_dir)
    except Exception as e:
        elapsed = time.time() - start_time
        manifest_builder.data["warnings"].append(f"Pack aborted with exception: {e}")
        manifest = manifest_builder.finalize("aborted", elapsed_seconds=elapsed)
        write_manifest(manifest, output_dir)
        print(f"\n  ❌ 打包過程發生錯誤 (Packing failed): {e}")
        print(f"  已寫入部分 manifest 供除錯: {os.path.join(output_dir, 'manifest.json')}")
        raise

    elapsed = time.time() - start_time
    final_size = get_dir_size(output_dir)

    manifest = manifest_builder.finalize("success", elapsed_seconds=elapsed)
    manifest["size_bytes"]["total_actual"] = final_size
    write_manifest(manifest, output_dir)

    print(f"\n{'=' * 70}")
    print(f"  ✅ 打包完成! (Packing complete!)")
    print(f"  📁 Output: {output_dir}")
    print(f"  📊 Size:   {format_size(final_size)}")
    print(f"  ⏱  Time:   {elapsed:.1f}s")
    for wf_basename in wf_basenames:
        print(f"  📋 Workflow: {wf_basename}")
    if layout == "full_skeleton" and include_comfyui_base:
        print(f"\n  使用方式: 在目標電腦上執行 run_nvidia_gpu.bat 啟動 ComfyUI")
        print(f"  然後載入工作流: {', '.join(wf_basenames)}")
    else:
        print(f"\n  使用方式: 請參閱 README_INSTALL.txt，將內容合併到目標的 ComfyUI 安裝目錄")
    if update_policy != "none":
        print(f"\n  💡 已建立可更新 portable，可在目標電腦用 update\\update_comfyui.bat 更新 ComfyUI")
        if update_policy == "core_and_nodes":
            print(f"     已保留 custom_nodes 的 Git 資訊；有 Git repo 的節點可透過 ComfyUI-Manager 更新")
    elif include_comfyui_base or include_custom_nodes:
        print(f"\n  ⚠ 未保留 Git 版本資訊，這份打包無法用官方 update 機制或 ComfyUI-Manager 更新")
    print(f"  📄 Manifest: {os.path.join(output_dir, 'manifest.json')}")
    print(f"{'=' * 70}\n")

    return True
