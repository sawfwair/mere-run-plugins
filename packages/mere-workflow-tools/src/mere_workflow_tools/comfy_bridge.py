from __future__ import annotations

import collections
import json
import pathlib
from typing import cast

from .graph_sdk import JsonMap, as_list, as_map

BRIDGE_CONTRACT_VERSION = "mere.run/comfy-bridge.v1"
SUPPORTED_API_CLASSES = {
    "CheckpointLoaderSimple",
    "CLIPTextEncode",
    "EmptyLatentImage",
    "KSampler",
    "LoadImage",
    "LoraLoader",
    "SaveImage",
    "VAEDecode",
    "VAEEncode",
}


class ComfyBridgeError(RuntimeError):
    pass


def load_workflow(path: pathlib.Path) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), "workflow")
    except json.JSONDecodeError as exc:
        raise ComfyBridgeError(f"invalid ComfyUI workflow JSON: {exc}") from None


def inspect_workflow(workflow: JsonMap) -> JsonMap:
    workflow_format, nodes = workflow_nodes(workflow)
    class_types = class_type_counts(workflow_format, nodes)
    unsupported = sorted(name for name in class_types if name not in SUPPORTED_API_CLASSES)
    diagnostics: list[JsonMap] = []
    if workflow_format == "ui":
        diagnostics.append(
            {
                "code": "ui_export_requires_api_format",
                "severity": "blocker",
                "message": "UI workflow JSON can be inspected but import requires ComfyUI API prompt format.",
            }
        )
    if unsupported:
        diagnostics.append(
            {
                "code": "unsupported_node_classes",
                "severity": "blocker",
                "message": f"Unsupported ComfyUI classes: {', '.join(unsupported)}",
            }
        )
    if workflow_format == "api" and class_types.get("KSampler", 0) != 1:
        diagnostics.append(
            {
                "code": "sampler_count_unsupported",
                "severity": "blocker",
                "message": "Import currently requires exactly one KSampler node.",
            }
        )
    return {
        "contract_version": BRIDGE_CONTRACT_VERSION,
        "format": workflow_format,
        "node_count": sum(class_types.values()),
        "class_types": dict(sorted(class_types.items())),
        "supported_class_types": sorted(name for name in class_types if name in SUPPORTED_API_CLASSES),
        "unsupported_class_types": unsupported,
        "importable": not any(item["severity"] == "blocker" for item in diagnostics),
        "diagnostics": diagnostics,
    }


def import_workflow(
    workflow: JsonMap,
    model_id: str,
    source_name: str,
    asset_root: pathlib.Path | None,
) -> tuple[JsonMap, JsonMap, JsonMap]:
    report = inspect_workflow(workflow)
    if report["format"] != "api" or not report["importable"]:
        messages = [str(item["message"]) for item in cast(list[JsonMap], report["diagnostics"])]
        raise ComfyBridgeError(" ".join(messages))
    nodes = api_nodes(workflow)
    sampler_id, sampler = single_node(nodes, "KSampler")
    sampler_inputs = as_map(sampler.get("inputs"), f"nodes.{sampler_id}.inputs")
    positive = text_condition(nodes, sampler_inputs.get("positive"), "positive")
    negative = text_condition(nodes, sampler_inputs.get("negative"), "negative")
    latent_id = reference_node_id(sampler_inputs.get("latent_image"), "KSampler.latent_image")
    latent = node(nodes, latent_id)
    latent_class = latent.get("class_type")
    graph_inputs: JsonMap = {"prompt": {"type": "string"}}
    input_values: JsonMap = {"prompt": positive}
    arguments: JsonMap = {
        "prompt": {"$ref": "inputs.prompt"},
        "model": model_id,
    }
    if negative:
        graph_inputs["negative_prompt"] = {"type": "string"}
        input_values["negative_prompt"] = negative
        arguments["negative_prompt"] = {"$ref": "inputs.negative_prompt"}
    copy_numeric(sampler_inputs, arguments, "seed", int)
    copy_numeric(sampler_inputs, arguments, "steps", int)
    copy_numeric(sampler_inputs, arguments, "cfg", float, target_name="cfg_scale")
    warnings = omitted_sampler_warnings(sampler_inputs)

    if latent_class == "EmptyLatentImage":
        latent_inputs = as_map(latent.get("inputs"), f"nodes.{latent_id}.inputs")
        copy_numeric(latent_inputs, arguments, "width", int)
        copy_numeric(latent_inputs, arguments, "height", int)
        batch_size = latent_inputs.get("batch_size", 1)
        if batch_size != 1:
            raise ComfyBridgeError("ComfyUI batch_size must be 1 for graph import.")
    elif latent_class == "VAEEncode":
        latent_inputs = as_map(latent.get("inputs"), f"nodes.{latent_id}.inputs")
        image_id = reference_node_id(latent_inputs.get("pixels"), "VAEEncode.pixels")
        image_node = node(nodes, image_id)
        if image_node.get("class_type") != "LoadImage":
            raise ComfyBridgeError("VAEEncode.pixels must reference LoadImage.")
        image_inputs = as_map(image_node.get("inputs"), f"nodes.{image_id}.inputs")
        image_name = image_inputs.get("image")
        if not isinstance(image_name, str) or asset_root is None:
            raise ComfyBridgeError("Image-to-image import requires --asset-root containing the LoadImage asset.")
        image_path = confined_asset(asset_root, image_name)
        graph_inputs["image"] = {"type": "asset"}
        input_values["image"] = str(image_path)
        arguments["input"] = {"$ref": "inputs.image"}
        copy_numeric(sampler_inputs, arguments, "denoise", float, target_name="strength")
    else:
        raise ComfyBridgeError(f"Unsupported KSampler latent source: {latent_class}")

    checkpoint_name, lora = model_chain(nodes, sampler_inputs.get("model"), asset_root)
    if lora is not None:
        graph_inputs["lora"] = {"type": "asset"}
        input_values["lora"] = str(lora["path"])
        arguments["lora"] = {"$ref": "inputs.lora"}
        arguments["lora_scale"] = lora["scale"]

    graph: JsonMap = {
        "schema_version": 1,
        "kind": "mere.run/workflow-graph",
        "name": normalized_graph_name(source_name),
        "inputs": graph_inputs,
        "nodes": [
            {
                "id": "generate",
                "kind": "image.generate",
                "arguments": arguments,
            }
        ],
        "outputs": {"image": {"$ref": "nodes.generate.outputs.image"}},
        "metadata": {
            "imported_from": "comfyui-api",
            "comfy_checkpoint": checkpoint_name,
            "bridge_contract": BRIDGE_CONTRACT_VERSION,
        },
    }
    import_report: JsonMap = {
        **report,
        "managed_model_id": model_id,
        "source_checkpoint": checkpoint_name,
        "warnings": warnings,
    }
    return graph, input_values, import_report


def workflow_nodes(workflow: JsonMap) -> tuple[str, object]:
    prompt = workflow.get("prompt")
    if isinstance(prompt, dict):
        return "api", prompt
    if workflow and all(isinstance(value, dict) and "class_type" in value for value in workflow.values()):
        return "api", workflow
    nodes = workflow.get("nodes")
    if isinstance(nodes, list):
        return "ui", nodes
    raise ComfyBridgeError("Unrecognized ComfyUI workflow shape.")


def class_type_counts(workflow_format: str, raw_nodes: object) -> collections.Counter[str]:
    result: collections.Counter[str] = collections.Counter()
    values = as_map(raw_nodes, "nodes").values() if workflow_format == "api" else as_list(raw_nodes, "nodes")
    for raw_node in values:
        item = as_map(raw_node, "node")
        class_type = item.get("class_type") if workflow_format == "api" else item.get("type")
        if isinstance(class_type, str):
            result[class_type] += 1
    return result


def api_nodes(workflow: JsonMap) -> JsonMap:
    raw = workflow.get("prompt", workflow)
    return as_map(raw, "prompt")


def node(nodes: JsonMap, node_id: str) -> JsonMap:
    return as_map(nodes.get(node_id), f"nodes.{node_id}")


def single_node(nodes: JsonMap, class_type: str) -> tuple[str, JsonMap]:
    matches = [(node_id, as_map(raw, f"nodes.{node_id}")) for node_id, raw in nodes.items() if as_map(raw, f"nodes.{node_id}").get("class_type") == class_type]
    if len(matches) != 1:
        raise ComfyBridgeError(f"Expected exactly one {class_type} node.")
    return matches[0]


def reference_node_id(value: object, label: str) -> str:
    if not isinstance(value, list) or len(value) != 2 or not isinstance(value[0], str):
        raise ComfyBridgeError(f"{label} must be a ComfyUI node reference.")
    return value[0]


def text_condition(nodes: JsonMap, value: object, label: str) -> str:
    node_id = reference_node_id(value, f"KSampler.{label}")
    condition = node(nodes, node_id)
    if condition.get("class_type") != "CLIPTextEncode":
        raise ComfyBridgeError(f"KSampler.{label} must reference CLIPTextEncode.")
    text = as_map(condition.get("inputs"), f"nodes.{node_id}.inputs").get("text")
    if not isinstance(text, str):
        raise ComfyBridgeError(f"nodes.{node_id}.inputs.text must be a string.")
    return text


def model_chain(
    nodes: JsonMap,
    value: object,
    asset_root: pathlib.Path | None,
) -> tuple[str, JsonMap | None]:
    model_id = reference_node_id(value, "KSampler.model")
    model_node = node(nodes, model_id)
    if model_node.get("class_type") == "LoraLoader":
        inputs = as_map(model_node.get("inputs"), f"nodes.{model_id}.inputs")
        lora_name = inputs.get("lora_name")
        scale = inputs.get("strength_model", 1.0)
        if not isinstance(lora_name, str) or asset_root is None:
            raise ComfyBridgeError("LoraLoader import requires --asset-root containing the LoRA file.")
        if not isinstance(scale, (int, float)) or isinstance(scale, bool):
            raise ComfyBridgeError("LoraLoader.strength_model must be numeric.")
        checkpoint, _ = model_chain(nodes, inputs.get("model"), asset_root)
        return checkpoint, {"path": confined_asset(asset_root, lora_name), "scale": float(scale)}
    if model_node.get("class_type") != "CheckpointLoaderSimple":
        raise ComfyBridgeError("KSampler.model must reference CheckpointLoaderSimple or LoraLoader.")
    checkpoint_value = as_map(model_node.get("inputs"), f"nodes.{model_id}.inputs").get("ckpt_name")
    if not isinstance(checkpoint_value, str):
        raise ComfyBridgeError("CheckpointLoaderSimple.ckpt_name must be a string.")
    return checkpoint_value, None


def copy_numeric(
    source: JsonMap,
    destination: JsonMap,
    name: str,
    conversion: type[int] | type[float],
    target_name: str | None = None,
) -> None:
    target = target_name or name
    value = source.get(name)
    if value is None:
        return
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise ComfyBridgeError(f"KSampler.{name} must be numeric.")
    destination[target] = conversion(value)


def omitted_sampler_warnings(inputs: JsonMap) -> list[str]:
    warnings: list[str] = []
    for name in ["sampler_name", "scheduler"]:
        if name in inputs:
            warnings.append(f"ComfyUI {name}={inputs[name]} is not represented by image.generate and was omitted.")
    return warnings


def confined_asset(root: pathlib.Path, relative: str) -> pathlib.Path:
    resolved_root = root.expanduser().resolve()
    candidate = (resolved_root / relative).resolve()
    if resolved_root not in candidate.parents or not candidate.is_file():
        raise ComfyBridgeError(f"ComfyUI asset is missing or escapes --asset-root: {relative}")
    return candidate


def normalized_graph_name(source_name: str) -> str:
    stem = pathlib.Path(source_name).stem.lower()
    normalized = "".join(character if character.isalnum() else "-" for character in stem).strip("-")
    return normalized or "comfy-import"


def write_json(path: pathlib.Path, value: JsonMap) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)
