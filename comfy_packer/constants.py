"""Static lookup tables shared across node/model resolution."""

# Standard model folder names used by ComfyUI (from folder_paths.py)
STANDARD_MODEL_FOLDERS = [
    "checkpoints", "configs", "loras", "vae", "text_encoders", "clip",
    "diffusion_models", "unet", "clip_vision", "style_models", "embeddings",
    "diffusers", "vae_approx", "controlnet", "gligen", "upscale_models",
    "latent_upscale_models", "hypernetworks", "photomaker", "model_patches",
    "audio_encoders",
]

# Node class_types that are built-in to ComfyUI (no custom node needed).
# Scanned dynamically at runtime too, but kept as a fallback baseline.
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

MODEL_FILE_EXTENSIONS = {
    '.safetensors', '.ckpt', '.pt', '.pth', '.bin', '.onnx', '.pkl', '.sft',
    '.gguf',  # quantized models (e.g. ComfyUI-GGUF UNETLoader/CLIPLoader) — real gap found in testing
    '.engine',  # TensorRT
    '.pte',  # ExecuTorch
    '.npz',
}

# Directory/file name patterns excluded when copying ComfyUI base dirs and
# custom_nodes folders — dev cruft that bloats the package but is never
# needed at runtime.
COPY_IGNORE_PATTERNS = [
    ".git", ".github", "__pycache__", "*.pyc", "*.pyo",
    "tests", "test", ".pytest_cache",
    "venv", ".venv", "env", ".env",
    ".mypy_cache", ".ruff_cache",
]
