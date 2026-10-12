"""Known widget-index -> model-folder hints for specific node class_types.

UI-format workflows store widget values positionally with no field-name
context, so the only way to know "this widget is a model filename" without
running the node's own INPUT_TYPES is either (a) a recognizable file
extension, or (b) prior knowledge of that node's widget layout. This table
covers (b) for nodes seen in practice — most importantly it lets a model
reference resolve correctly even when the file doesn't exist locally (a
missing/deleted model has no extension-heuristic anchor problem, but without
a schema hint the tool has no idea which models/ subfolder it belongs in
either, so it could only be silently dropped instead of reported missing).

Extend this table opportunistically as new gaps are found; nodes absent from
it still fall back to the extension-based heuristic in model_resolver.py.
"""

# class_type -> [(widget_index, model_folder_name), ...]
MODEL_WIDGET_SCHEMA = {
    # Built-in ComfyUI loaders (widgets_values order matches INPUT_TYPES)
    "CheckpointLoaderSimple": [(0, "checkpoints")],
    "LoraLoader": [(0, "loras")],
    "LoraLoaderModelOnly": [(0, "loras")],
    "VAELoader": [(0, "vae")],
    "ControlNetLoader": [(0, "controlnet")],
    "DiffControlNetLoader": [(0, "controlnet")],
    "CLIPLoader": [(0, "text_encoders")],
    "DualCLIPLoader": [(0, "text_encoders"), (1, "text_encoders")],
    "TripleCLIPLoader": [(0, "text_encoders"), (1, "text_encoders"), (2, "text_encoders")],
    "UNETLoader": [(0, "diffusion_models")],
    "UpscaleModelLoader": [(0, "upscale_models")],
    "CLIPVisionLoader": [(0, "clip_vision")],
    "StyleModelLoader": [(0, "style_models")],
    "GLIGENLoader": [(0, "gligen")],
    "PhotoMakerLoader": [(0, "photomaker")],
    "unCLIPCheckpointLoader": [(0, "checkpoints")],
    "ImageOnlyCheckpointLoader": [(0, "checkpoints")],

    # ComfyUI-GGUF (custom_nodes/ComfyUI-GGUF) — real gap found in testing:
    # .gguf files loaded here have no chance of resolving without a hint
    # when the file is missing locally, since the extension heuristic alone
    # can't tell diffusion_models from text_encoders.
    "CLIPLoaderGGUF": [(0, "text_encoders")],
    "DualCLIPLoaderGGUF": [(0, "text_encoders"), (1, "text_encoders")],
    "TripleCLIPLoaderGGUF": [(0, "text_encoders"), (1, "text_encoders"), (2, "text_encoders")],
    "QuadrupleCLIPLoaderGGUF": [(0, "text_encoders"), (1, "text_encoders"), (2, "text_encoders"), (3, "text_encoders")],
    "UnetLoaderGGUF": [(0, "diffusion_models")],
    "UnetLoaderGGUFAdvanced": [(0, "diffusion_models")],

    # comfyui-kjnodes
    "GGUFLoaderKJ": [(0, "diffusion_models"), (1, "diffusion_models")],
    "CheckpointLoaderKJ": [(0, "checkpoints")],
    "DiffusionModelLoaderKJ": [(0, "diffusion_models")],
    "VAELoaderKJ": [(0, "vae")],
}


def get_model_hints(class_type):
    return MODEL_WIDGET_SCHEMA.get(class_type, [])
