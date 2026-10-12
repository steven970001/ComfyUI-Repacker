"""Build and persist a durable record of what a pack run included/excluded.

Written unconditionally at the end of every run (success or aborted) so the
user has an audit trail for "what actually got left out and why" instead of
only scrollback console output.
"""

import json
import os
from datetime import datetime


class ManifestBuilder:
    """Accumulates pack-run facts incrementally; safe to render partially
    if the run aborts partway through (see cli.py's finally block)."""

    def __init__(self, mode, source_root, output_dir, workflow_paths):
        self.data = {
            "manifest_version": 1,
            "generated_at": datetime.now().astimezone().isoformat(),
            "status": "in_progress",
            "mode": mode,
            "source_root": source_root,
            "output_dir": output_dir,
            "workflows": [os.path.basename(w) for w in workflow_paths],
            "included": {},
            "custom_nodes": {
                "builtin_node_types": [],
                "required_folders": [],
                "unresolved_class_types": [],
                "manual_overrides_applied": [],
                "introspection": {"attempted": 0, "succeeded": 0, "failed": []},
                "dynamic_mapping_folders": [],
            },
            "models": {
                "included": [],
                "missing": [],
                "nonstandard_model_dirs_included": [],
                "extra_model_dirs_from_custom_nodes": [],
            },
            "update": {
                "enabled": False,
                "policy": "none",
                "source_update_dir": None,
                "required_scripts": [],
                "missing_requirements": [],
                "update_folder_copied": False,
                "comfyui_git_present": False,
                "python_embeded_present": False,
                "custom_nodes_git_kept": [],
                "custom_nodes_without_git": [],
            },
            "size_bytes": {},
            "warnings": [],
            "elapsed_seconds": None,
        }

    def set_included(self, python_embeded=False, comfyui_base=False, custom_nodes=False, models=False, keep_git=False):
        self.data["included"] = {
            "python_embeded": python_embeded,
            "comfyui_base": comfyui_base,
            "custom_nodes": custom_nodes,
            "models": models,
            "keep_git": keep_git,
        }

    def set_update_support(self, update_info):
        self.data["update"] = update_info
        if update_info.get("enabled") and update_info.get("custom_nodes_without_git"):
            self.data["warnings"].append(
                f"{len(update_info['custom_nodes_without_git'])} copied custom node folder(s) do not have .git and cannot be updated by Git"
            )

    def set_node_resolution(self, required_folders, resolution_details, unresolved_nodes, builtin_nodes, copied_folders=None):
        copied_folders = copied_folders or set(required_folders)
        self.data["custom_nodes"]["builtin_node_types"] = sorted(builtin_nodes)

        folder_class_types = {}
        folder_methods = {}
        for class_type, info in resolution_details.items():
            folder = info.get("folder")
            if folder:
                folder_class_types.setdefault(folder, []).append(class_type)
                folder_methods.setdefault(folder, set()).add(info.get("method") or "unknown")

        self.data["custom_nodes"]["required_folders"] = [
            {
                "folder": folder,
                "resolved_class_types": sorted(folder_class_types.get(folder, [])),
                "resolution_methods": sorted(folder_methods.get(folder, set())),
                "copied": folder in copied_folders,
            }
            for folder in sorted(required_folders)
        ]

        self.data["custom_nodes"]["unresolved_class_types"] = [
            {"class_type": ct, "node_ids": info.get("node_ids", [])}
            for ct, info in sorted(resolution_details.items())
            if ct in unresolved_nodes
        ]

        self.data["custom_nodes"]["manual_overrides_applied"] = [
            {"class_type": ct, "folder": info.get("folder")}
            for ct, info in sorted(resolution_details.items())
            if info.get("method") == "manual_override"
        ]

        if unresolved_nodes:
            self.data["warnings"].append(
                f"{len(unresolved_nodes)} node class_type(s) unresolved and not copied — see custom_nodes.unresolved_class_types"
            )

    def set_dynamic_folders(self, dynamic_folders):
        self.data["custom_nodes"]["dynamic_mapping_folders"] = sorted(dynamic_folders)

    def set_introspection_results(self, introspection_results):
        if not introspection_results:
            return
        succeeded = [r for r in introspection_results.values() if r.get("ok")]
        failed = [r for r in introspection_results.values() if not r.get("ok")]
        self.data["custom_nodes"]["introspection"] = {
            "attempted": len(introspection_results),
            "succeeded": len(succeeded),
            "failed": [{"folder": r.get("folder"), "error": r.get("error")} for r in failed],
        }
        if failed:
            self.data["warnings"].append(
                f"{len(failed)}/{len(introspection_results)} custom_nodes folder(s) failed runtime introspection — fell back to regex/grep detection for those"
            )

    def set_model_resolution(self, model_files, missing_files, model_metadata, nonstandard_included, extra_model_dirs):
        # Model filenames may carry either slash style depending on how they
        # were authored in the workflow JSON; normalize both sides to match.
        normalized_metadata = {k.replace("\\", "/"): v for k, v in model_metadata.items()}

        included = []
        for src, rel_path in model_files:
            # rel_path is "models/<folder_type>/<original filename, possibly with subfolders>"
            parts = rel_path.replace("\\", "/").split("/")
            folder_type = parts[1] if len(parts) > 1 else ""
            original_filename = "/".join(parts[2:]) if len(parts) > 2 else parts[-1]
            meta = normalized_metadata.get(original_filename, {})
            size_bytes = os.path.getsize(src) if os.path.isfile(src) else 0
            included.append({
                "filename": original_filename,
                "folder_type": folder_type,
                "resolution_method": meta.get("method"),
                "node_ids": meta.get("node_ids", []),
                "size_bytes": size_bytes,
            })
        self.data["models"]["included"] = included

        missing = []
        for filename, rel_path in missing_files:
            missing.append({
                "filename": filename,
                "expected_rel_path": rel_path.replace("\\", "/"),
            })
        self.data["models"]["missing"] = missing

        self.data["models"]["nonstandard_model_dirs_included"] = list(nonstandard_included)
        self.data["models"]["extra_model_dirs_from_custom_nodes"] = [
            {"src": src, "dest": dest} for src, dest in extra_model_dirs
        ]

        if missing_files:
            self.data["warnings"].append(
                f"{len(missing_files)} model file(s) missing locally and not included — see models.missing"
            )

    def set_sizes(self, size_dict):
        self.data["size_bytes"] = size_dict

    def finalize(self, status, elapsed_seconds=None):
        self.data["status"] = status
        self.data["elapsed_seconds"] = elapsed_seconds
        return self.data


def render_human_summary(manifest):
    lines = []
    lines.append("=" * 70)
    lines.append("  ComfyUI Workflow Packer — Manifest Summary")
    lines.append("=" * 70)
    lines.append(f"  Status:      {manifest['status']}")
    lines.append(f"  Mode:        {manifest['mode']}")
    lines.append(f"  Generated:   {manifest['generated_at']}")
    lines.append(f"  Source:      {manifest['source_root']}")
    lines.append(f"  Output:      {manifest['output_dir']}")
    lines.append(f"  Workflows:   {', '.join(manifest['workflows'])}")
    lines.append("")
    lines.append("  Included:")
    for k, v in manifest["included"].items():
        lines.append(f"    {'✅' if v else '⬜'} {k}")

    update = manifest.get("update", {})
    if update:
        lines.append("")
        lines.append("  Update:")
        lines.append(f"    {'✅' if update.get('enabled') else '⬜'} enabled")
        lines.append(f"    policy: {update.get('policy', 'none')}")
        if update.get("required_scripts"):
            lines.append(f"    scripts: {', '.join(update['required_scripts'])}")
        if update.get("missing_requirements"):
            lines.append("    missing requirements:")
            for item in update["missing_requirements"]:
                lines.append(f"      - {item}")
        if update.get("custom_nodes_git_kept"):
            lines.append(f"    custom node git repos kept: {len(update['custom_nodes_git_kept'])}")
        if update.get("custom_nodes_without_git"):
            lines.append(f"    custom node folders without git: {len(update['custom_nodes_without_git'])}")

    nodes = manifest["custom_nodes"]
    intro = nodes.get("introspection", {})
    if intro.get("attempted"):
        lines.append("")
        lines.append(f"  Introspection: {intro['succeeded']}/{intro['attempted']} folder(s) succeeded")
        for f in intro.get("failed", []):
            err = (f.get("error") or "").splitlines()[-1][:80] if f.get("error") else ""
            lines.append(f"    ⚠ {f['folder']}: {err}")

    lines.append("")
    lines.append(f"  Custom node folders ({len(nodes['required_folders'])}):")
    for f in nodes["required_folders"]:
        methods = ",".join(f["resolution_methods"])
        lines.append(f"    ✅ {f['folder']}  [{methods}]  ({len(f['resolved_class_types'])} node type(s))")
    if nodes["unresolved_class_types"]:
        lines.append(f"  ⚠ Unresolved node types ({len(nodes['unresolved_class_types'])}):")
        for u in nodes["unresolved_class_types"]:
            lines.append(f"    ❓ {u['class_type']}")

    models = manifest["models"]
    lines.append("")
    lines.append(f"  Models included ({len(models['included'])}):")
    for m in models["included"]:
        lines.append(f"    📄 {m['folder_type']}/{m['filename']} [{m['resolution_method']}]")
    if models["missing"]:
        lines.append(f"  ⚠ Models missing ({len(models['missing'])}):")
        for m in models["missing"]:
            lines.append(f"    ❌ {m['filename']} (expected: {m['expected_rel_path']})")

    if manifest["warnings"]:
        lines.append("")
        lines.append("  Warnings:")
        for w in manifest["warnings"]:
            lines.append(f"    - {w}")

    if manifest.get("elapsed_seconds") is not None:
        lines.append("")
        lines.append(f"  Elapsed: {manifest['elapsed_seconds']:.1f}s")
    lines.append("=" * 70)
    return "\n".join(lines)


def write_manifest(manifest, output_dir):
    os.makedirs(output_dir, exist_ok=True)
    json_path = os.path.join(output_dir, "manifest.json")
    txt_path = os.path.join(output_dir, "manifest.txt")

    with open(json_path, 'w', encoding='utf-8') as f:
        json.dump(manifest, f, ensure_ascii=False, indent=2)

    with open(txt_path, 'w', encoding='utf-8') as f:
        f.write(render_human_summary(manifest))

    return json_path, txt_path
