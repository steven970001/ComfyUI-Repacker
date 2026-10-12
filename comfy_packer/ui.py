"""Shared console-output helpers."""

import os


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
