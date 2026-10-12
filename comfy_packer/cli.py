"""Argument parsing, interactive prompts, and orchestration entry point."""

import argparse
import os
import re
import sys

from .packing import pack_comfyui
from .ui import print_header

_MODE_CHOICES = ["full", "custom_nodes", "models", "custom"]
_UPDATE_POLICY_CHOICES = ["none", "core", "core_and_nodes"]
_MODE_FOLDER_SUFFIX = {
    "full": "",
    "custom_nodes": "_custom_nodes",
    "models": "_models",
    "custom": "_custom",
}

_MODE_MENU = """
  請選擇打包模式 (Choose a packing mode):
    [1] 完整打包 (Full pack) — python_embeded + ComfyUI 本體 + custom_nodes + models
    [2] 只打包 Custom Nodes — 給已有 ComfyUI 環境的人補齊節點 (drop-in 資料夾)
    [3] 只打包 Models — 給已有節點、缺模型的人 (drop-in 資料夾)
    [4] 自訂組合 — 自行勾選要包含的項目
"""


def _prompt_mode():
    print(_MODE_MENU)
    choice = input("  請選擇 [1-4，預設 1]: ").strip()
    return {"1": "full", "2": "custom_nodes", "3": "models", "4": "custom"}.get(choice, "full")


def _prompt_custom_toggles():
    def ask(label, default_yes):
        default_str = "Y/n" if default_yes else "y/N"
        ans = input(f"    包含 {label}？ ({default_str}): ").strip().lower()
        if not ans:
            return default_yes
        return ans == 'y'

    print("\n  🔧 自訂組合 (Custom combination) — 請選擇要包含的項目:")
    include_comfyui_base = ask("ComfyUI 本體 (base files)", True)
    include_custom_nodes = ask("Custom Nodes", True)
    include_models = ask("Models", True)
    include_python_embeded = False
    if include_comfyui_base:
        include_python_embeded = ask("python_embeded (較大，約數GB~十幾GB)", False)
    return include_python_embeded, include_comfyui_base, include_custom_nodes, include_models


def main():
    parser = argparse.ArgumentParser(
        description="ComfyUI Workflow Packer - 打包工作流到可攜帶版本"
    )
    parser.add_argument('--workflow', '-w', nargs='+', type=str, help='Path to workflow JSON file(s)')
    parser.add_argument('--output', '-o', type=str, help='Output directory for packed ComfyUI')
    parser.add_argument('--source', '-s', type=str, help='(Optional) Explicit ComfyUI source folder. Will auto-detect from workflow by default.')
    parser.add_argument('--yes', '-y', action='store_true', help='Skip confirmation prompts')
    parser.add_argument('--no-introspect', action='store_true',
                         help='Skip runtime import-based node introspection (faster, less reliable); use regex/grep detection only')
    parser.add_argument('--introspect-timeout', type=int, default=25,
                         help='Per-folder timeout in seconds for node introspection (default: 25)')
    parser.add_argument('--mode', choices=_MODE_CHOICES, default=None,
                         help='Packing mode: full (default) | custom_nodes | models | custom. '
                              'Skips the interactive mode menu. With --yes and no --mode, defaults to "full".')
    parser.add_argument('--include-python-embeded', action=argparse.BooleanOptionalAction, default=None,
                         help='(mode=custom only) include python_embeded')
    parser.add_argument('--include-comfyui-base', action=argparse.BooleanOptionalAction, default=None,
                         help='(mode=custom only) include ComfyUI base files')
    parser.add_argument('--include-custom-nodes', action=argparse.BooleanOptionalAction, default=None,
                         help='(mode=custom only) include required custom_nodes')
    parser.add_argument('--include-models', action=argparse.BooleanOptionalAction, default=None,
                         help='(mode=custom only) include required models')
    update_group = parser.add_mutually_exclusive_group()
    update_group.add_argument('--update-policy', choices=_UPDATE_POLICY_CHOICES, default=None,
                              help='Update support for full portable packs: none | core | core_and_nodes. '
                                   'core copies update/ and keeps ComfyUI/.git; core_and_nodes also keeps '
                                   'custom_nodes .git folders for ComfyUI-Manager updates. Default: '
                                   'core_and_nodes for full packs with python_embeded, none for drop-in packs.')
    update_group.add_argument('--updatable', action='store_true',
                              help='Shortcut for --update-policy core_and_nodes')
    update_group.add_argument('--no-updatable', action='store_true',
                              help='Shortcut for --update-policy none')
    parser.add_argument('--keep-git', action=argparse.BooleanOptionalAction, default=None,
                         help='Keep .git in the ComfyUI base and each custom_nodes folder, and copy the '
                              'update/ folder, so the packed output can be updated later via the official '
                              'update_comfyui.bat or ComfyUI-Manager\'s Update button. Legacy alias for '
                              '--update-policy core_and_nodes / --update-policy none.')

    args = parser.parse_args()

    workflow_paths = args.workflow
    output_dir = args.output
    explicit_source = args.source

    if not workflow_paths:
        print_header()
        print("\n  請輸入工作流 JSON 檔案路徑 (Please enter workflow JSON path):")
        print("  💡 支援同時輸入多個檔案 (用空白分隔，或加上雙引號，若檔案路徑無空格可直接拖曳多個檔案)")
        raw_input_wf = input("  > ").strip()

        # Windows-safe parser for drag-and-drop paths:
        # keep backslashes intact while still supporting quoted paths.
        tokens = re.findall(r'"([^"]+)"|\'([^\']+)\'|(\S+)', raw_input_wf)
        workflow_paths = [a or b or c for a, b, c in tokens if (a or b or c)]

    if not output_dir:
        print("\n  請輸入打包目標路徑 (Please enter output directory path):")
        print("  (例如: D:\\ComfyUI_packed 或 E:\\comfyui_for_client)")
        output_dir = input("  > ").strip().strip('"').strip("'")

    if not workflow_paths or not output_dir:
        print("\n❌ Error: Both workflow path and output directory are required.")
        sys.exit(1)

    mode = args.mode
    include_python_embeded = args.include_python_embeded
    include_comfyui_base = args.include_comfyui_base
    include_custom_nodes = args.include_custom_nodes
    include_models = args.include_models
    update_policy = args.update_policy
    if args.updatable:
        update_policy = "core_and_nodes"
    elif args.no_updatable:
        update_policy = "none"

    if mode is None:
        if args.yes:
            mode = "full"  # preserve historical non-interactive default behavior
        else:
            mode = _prompt_mode()

    if mode == "custom" and include_comfyui_base is None and not args.yes:
        include_python_embeded, include_comfyui_base, include_custom_nodes, include_models = _prompt_custom_toggles()

    if len(workflow_paths) == 1:
        wf_name = os.path.splitext(os.path.basename(workflow_paths[0]))[0]
        folder_name = f"ComfyUI_windows_portable_{wf_name}{_MODE_FOLDER_SUFFIX[mode]}"
    else:
        folder_name = f"ComfyUI_windows_portable_Multi_Workflows{_MODE_FOLDER_SUFFIX[mode]}"

    final_output_dir = os.path.join(os.path.abspath(output_dir), folder_name)

    success = pack_comfyui(
        workflow_paths, final_output_dir, skip_confirm=args.yes, explicit_source=explicit_source,
        use_introspection=not args.no_introspect, introspect_timeout=args.introspect_timeout,
        mode=mode, include_python_embeded=include_python_embeded, include_comfyui_base=include_comfyui_base,
        include_custom_nodes=include_custom_nodes, include_models=include_models, keep_git=args.keep_git,
        update_policy=update_policy,
    )
    sys.exit(0 if success else 1)
