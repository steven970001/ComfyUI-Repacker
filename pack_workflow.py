"""
ComfyUI Workflow Packer
=======================
Parses a ComfyUI workflow JSON, identifies all required custom nodes and models,
then packages a clean, minimal ComfyUI portable instance to the specified output directory.

Usage:
    python pack_workflow.py
    (Interactive prompts for workflow JSON path and output directory)

    python pack_workflow.py --workflow wf1.json wf2.json --output D:\\packed_comfyui

Implementation lives in the comfy_packer/ package; this file is kept as the
stable entry point that pack_workflow.bat invokes.
"""

import io
import os
import sys

# Some ComfyUI portable installs ship a python_embeded whose ._pth file
# overrides sys.path with a fixed list that doesn't include the running
# script's own directory (normal python.exe always adds it; the embeddable
# distribution's ._pth mode can override that). Since this script is packed
# to run under whichever ComfyUI's python_embeded the user points at, make
# the comfy_packer/ package importable regardless of that quirk.
_SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if _SCRIPT_DIR not in sys.path:
    sys.path.insert(0, _SCRIPT_DIR)

# Fix Windows console encoding for emoji/unicode output
if sys.platform == 'win32':
    try:
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        sys.stderr.reconfigure(encoding='utf-8', errors='replace')
    except Exception:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

from comfy_packer.cli import main

if __name__ == "__main__":
    main()
