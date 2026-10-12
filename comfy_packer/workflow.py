"""Load and normalize ComfyUI workflow JSON (both UI-export and API formats)."""

import json


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
