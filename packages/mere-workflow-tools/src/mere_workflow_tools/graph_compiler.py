from __future__ import annotations

import argparse
import copy
import hashlib
import json
import pathlib
import re
import sys
from typing import cast

from .graph_sdk import GraphProviderError, JsonMap, as_list, as_map

PROGRAM_KIND = "mere.run/workflow-program"
MODULE_KIND = "mere.run/workflow-module"
GRAPH_KIND = "mere.run/workflow-graph"
REPORT_CONTRACT_VERSION = "mere.run/workflow-compile-report.v1"
ID_PATTERN = re.compile(r"^[a-z][a-z0-9-]{0,63}$")
REFERENCE_PATTERN = re.compile(r"^nodes\.([a-z][a-z0-9-]{0,63})\.outputs\.([a-z][a-z0-9_]{0,63})$")


def load_json(path: pathlib.Path, label: str) -> JsonMap:
    try:
        return as_map(json.loads(path.read_text()), label)
    except json.JSONDecodeError as exc:
        raise GraphProviderError(f"invalid {label} JSON: {exc}") from None


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()
    return hashlib.sha256(encoded).hexdigest()


def write_json(path: pathlib.Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")
    temporary.replace(path)


class WorkflowCompiler:
    def __init__(
        self,
        source: JsonMap,
        source_path: pathlib.Path,
        variable_overrides: JsonMap | None = None,
    ) -> None:
        self.source = source
        self.source_path = source_path.resolve()
        self.root = self.source_path.parent
        self.variables = copy.deepcopy(as_map(source.get("variables", {}), "variables"))
        if variable_overrides:
            self.variables.update(copy.deepcopy(variable_overrides))
        self.modules: dict[str, JsonMap] = {}
        self.step_outputs: dict[str, list[JsonMap]] = {}
        self.step_nodes: dict[str, list[str]] = {}
        self.nodes: list[JsonMap] = []
        self.compiled_node_ids: set[str] = set()
        self.step_reports: list[JsonMap] = []

    def compile(self) -> tuple[JsonMap, JsonMap]:
        self._validate_program()
        self._load_modules()
        for raw_step in as_list(self.source.get("steps"), "steps"):
            self._compile_step(as_map(raw_step, "step"))
        outputs = as_map(self._rewrite_value(self.source.get("outputs"), {}, {}), "outputs")
        for name, value in outputs.items():
            self._require_id(name, "graph output")
            mapped = as_map(value, f"output {name}")
            reference = mapped.get("$ref")
            if not isinstance(reference, str) or REFERENCE_PATTERN.fullmatch(reference) is None:
                raise GraphProviderError(f"graph output {name} must resolve to one compiled node output reference")
        graph: JsonMap = {
            "schema_version": 1,
            "kind": GRAPH_KIND,
            "name": cast(str, self.source["name"]),
            "inputs": copy.deepcopy(as_map(self.source.get("inputs", {}), "inputs")),
            "nodes": self.nodes,
            "outputs": outputs,
        }
        if "execution" in self.source:
            graph["execution"] = copy.deepcopy(as_map(self.source["execution"], "execution"))
        if "metadata" in self.source:
            graph["metadata"] = self._resolve_compile_values(copy.deepcopy(self.source["metadata"]), {}, {})
        report: JsonMap = {
            "contract_version": REPORT_CONTRACT_VERSION,
            "source": self.source_path.name,
            "source_sha256": canonical_digest(self.source),
            "graph_sha256": canonical_digest(graph),
            "module_ids": sorted(self.modules),
            "steps": self.step_reports,
            "node_count": len(self.nodes),
            "max_parallel_nodes": as_map(graph.get("execution", {}), "execution").get("max_parallel_nodes", 1),
        }
        return graph, report

    def _validate_program(self) -> None:
        if self.source.get("schema_version") != 1 or self.source.get("kind") != PROGRAM_KIND:
            raise GraphProviderError(f"workflow program must use schema_version 1 and kind {PROGRAM_KIND}")
        name = self.source.get("name")
        if not isinstance(name, str) or not name.strip():
            raise GraphProviderError("workflow program name must be a non-empty string")
        if not isinstance(self.source.get("steps"), list) or not self.source["steps"]:
            raise GraphProviderError("workflow program must contain at least one step")
        as_map(self.source.get("outputs"), "outputs")
        step_ids: set[str] = set()
        for raw_step in as_list(self.source["steps"], "steps"):
            step = as_map(raw_step, "step")
            step_id = step.get("id")
            if not isinstance(step_id, str):
                raise GraphProviderError("step id must be a string")
            self._require_id(step_id, "step")
            if step_id in step_ids:
                raise GraphProviderError(f"duplicate step id: {step_id}")
            step_ids.add(step_id)

    def _load_modules(self) -> None:
        for module_id, raw_module in as_map(self.source.get("modules", {}), "modules").items():
            self._require_id(module_id, "module")
            self.modules[module_id] = self._validate_module(module_id, as_map(raw_module, f"module {module_id}"))
        for module_id, raw_path in as_map(self.source.get("imports", {}), "imports").items():
            self._require_id(module_id, "module import")
            if module_id in self.modules:
                raise GraphProviderError(f"duplicate module id: {module_id}")
            if not isinstance(raw_path, str):
                raise GraphProviderError(f"module import {module_id} path must be a string")
            relative = pathlib.PurePosixPath(raw_path)
            if relative.is_absolute() or not relative.parts or ".." in relative.parts:
                raise GraphProviderError(f"module import path is not confined: {raw_path}")
            path = (self.root / pathlib.Path(*relative.parts)).resolve()
            if path != self.root and self.root not in path.parents:
                raise GraphProviderError(f"module import escapes the program directory: {raw_path}")
            module = load_json(path, f"module import {module_id}")
            if module.get("schema_version") != 1 or module.get("kind") != MODULE_KIND:
                raise GraphProviderError(f"module import {module_id} must use schema_version 1 and kind {MODULE_KIND}")
            self.modules[module_id] = self._validate_module(module_id, module)
        if not self.modules:
            raise GraphProviderError("workflow program must define or import at least one module")

    def _validate_module(self, module_id: str, module: JsonMap) -> JsonMap:
        parameters = as_list(module.get("parameters", []), f"module {module_id}.parameters")
        seen: set[str] = set()
        for raw_parameter in parameters:
            if not isinstance(raw_parameter, str):
                raise GraphProviderError(f"module {module_id} parameter must be a string")
            self._require_id(raw_parameter, f"module {module_id} parameter")
            if raw_parameter in seen:
                raise GraphProviderError(f"module {module_id} has duplicate parameter: {raw_parameter}")
            seen.add(raw_parameter)
        nodes = as_list(module.get("nodes"), f"module {module_id}.nodes")
        if not nodes:
            raise GraphProviderError(f"module {module_id} must contain at least one node")
        node_ids: set[str] = set()
        for raw_node in nodes:
            node = as_map(raw_node, f"module {module_id} node")
            node_id = node.get("id")
            if not isinstance(node_id, str):
                raise GraphProviderError(f"module {module_id} node id must be a string")
            self._require_id(node_id, f"module {module_id} node")
            if node_id in node_ids:
                raise GraphProviderError(f"module {module_id} has duplicate node id: {node_id}")
            node_ids.add(node_id)
        as_map(module.get("outputs"), f"module {module_id}.outputs")
        return module

    def _compile_step(self, step: JsonMap) -> None:
        step_id = cast(str, step["id"])
        module_id = step.get("module")
        if not isinstance(module_id, str) or module_id not in self.modules:
            raise GraphProviderError(f"step {step_id} uses unknown module: {module_id}")
        include = self._evaluate_condition(step.get("when", True))
        map_value = step.get("map")
        instances: list[dict[str, object]] = [{}]
        if map_value is not None:
            mapping = as_map(map_value, f"step {step_id}.map")
            item_name = mapping.get("item")
            if not isinstance(item_name, str):
                raise GraphProviderError(f"step {step_id} map item must be a string")
            self._require_id(item_name, f"step {step_id} map item")
            values = self._resolve_compile_values(mapping.get("values"), {}, {})
            if not isinstance(values, list):
                raise GraphProviderError(f"step {step_id} map values must resolve to an array")
            if len(values) > 1000:
                raise GraphProviderError(f"step {step_id} map exceeds the 1000-instance limit")
            instances = [{item_name: value} for value in values]
        if not include:
            instances = []
        outputs: list[JsonMap] = []
        node_ids: list[str] = []
        for index, items in enumerate(instances):
            instance_outputs, instance_nodes = self._expand_module(step, module_id, index, items, map_value is not None)
            outputs.append(instance_outputs)
            node_ids.extend(instance_nodes)
        self.step_outputs[step_id] = outputs
        self.step_nodes[step_id] = node_ids
        self.step_reports.append(
            {
                "id": step_id,
                "module": module_id,
                "included": include,
                "instances": len(instances),
                "node_ids": node_ids,
            }
        )

    def _expand_module(
        self,
        step: JsonMap,
        module_id: str,
        index: int,
        items: dict[str, object],
        mapped: bool,
    ) -> tuple[JsonMap, list[str]]:
        module = self.modules[module_id]
        bindings = as_map(copy.deepcopy(step.get("arguments", {})), f"step {step['id']}.arguments")
        parameters = cast(list[object], module.get("parameters", []))
        expected = {cast(str, item) for item in parameters}
        supplied = set(bindings)
        if supplied != expected:
            missing = sorted(expected - supplied)
            extra = sorted(supplied - expected)
            raise GraphProviderError(f"step {step['id']} parameter mismatch; missing={missing}, extra={extra}")
        bindings = as_map(self._resolve_compile_values(bindings, {}, items), f"step {step['id']}.arguments")
        prefix = f"{step['id']}-{index:03d}" if mapped else cast(str, step["id"])
        local_nodes = [as_map(raw, f"module {module_id} node") for raw in as_list(module["nodes"], "nodes")]
        local_to_compiled: dict[str, str] = {}
        for node in local_nodes:
            local_id = cast(str, node["id"])
            compiled_id = f"{prefix}-{local_id}"
            self._require_id(compiled_id, f"compiled node for step {step['id']}")
            if compiled_id in self.compiled_node_ids:
                raise GraphProviderError(f"compiled node id collision: {compiled_id}")
            local_to_compiled[local_id] = compiled_id
            self.compiled_node_ids.add(compiled_id)
        compiled_ids: list[str] = []
        for node in local_nodes:
            compiled = copy.deepcopy(node)
            local_id = cast(str, compiled["id"])
            compiled["id"] = local_to_compiled[local_id]
            compiled["arguments"] = self._rewrite_value(compiled.get("arguments", {}), bindings, items, local_to_compiled)
            if "depends_on" in compiled:
                dependencies: list[str] = []
                for raw_dependency in as_list(compiled["depends_on"], f"node {local_id}.depends_on"):
                    if not isinstance(raw_dependency, str):
                        raise GraphProviderError(f"node {local_id} dependency must be a string")
                    if raw_dependency in local_to_compiled:
                        dependencies.append(local_to_compiled[raw_dependency])
                    elif raw_dependency.startswith("steps."):
                        dependency_step = raw_dependency.removeprefix("steps.")
                        if dependency_step not in self.step_nodes:
                            raise GraphProviderError(f"node {local_id} depends on unavailable step: {dependency_step}")
                        dependencies.extend(self.step_nodes[dependency_step])
                    else:
                        raise GraphProviderError(f"node {local_id} depends on unknown local node: {raw_dependency}")
                compiled["depends_on"] = list(dict.fromkeys(dependencies))
            self.nodes.append(compiled)
            compiled_ids.append(cast(str, compiled["id"]))
        raw_outputs = as_map(module["outputs"], f"module {module_id}.outputs")
        compiled_outputs = as_map(
            self._rewrite_value(copy.deepcopy(raw_outputs), bindings, items, local_to_compiled),
            f"module {module_id}.outputs",
        )
        return compiled_outputs, compiled_ids

    def _resolve_compile_values(
        self,
        value: object,
        bindings: JsonMap,
        items: dict[str, object],
    ) -> object:
        if isinstance(value, list):
            return [self._resolve_compile_values(item, bindings, items) for item in value]
        if not isinstance(value, dict):
            return value
        mapped = cast(JsonMap, value)
        if set(mapped) in ({"$var"}, {"$param"}, {"$item"}):
            key, raw_name = next(iter(mapped.items()))
            if not isinstance(raw_name, str):
                raise GraphProviderError(f"{key} name must be a string")
            source: dict[str, object] = self.variables if key == "$var" else bindings if key == "$param" else items
            if raw_name not in source:
                raise GraphProviderError(f"unknown {key} binding: {raw_name}")
            return copy.deepcopy(source[raw_name])
        return {key: self._resolve_compile_values(item, bindings, items) for key, item in mapped.items()}

    def _rewrite_value(
        self,
        value: object,
        bindings: JsonMap,
        items: dict[str, object],
        local_nodes: dict[str, str] | None = None,
    ) -> object:
        resolved = self._resolve_compile_values(value, bindings, items)
        return self._rewrite_references(resolved, local_nodes or {})

    def _rewrite_references(self, value: object, local_nodes: dict[str, str]) -> object:
        if isinstance(value, list):
            return [self._rewrite_references(item, local_nodes) for item in value]
        if not isinstance(value, dict):
            return value
        mapped = cast(JsonMap, value)
        if set(mapped) == {"$ref"}:
            raw_reference = mapped["$ref"]
            if not isinstance(raw_reference, str):
                raise GraphProviderError("$ref must be a string")
            return {"$ref": self._rewrite_reference(raw_reference, local_nodes)}
        return {key: self._rewrite_references(item, local_nodes) for key, item in mapped.items()}

    def _rewrite_reference(self, reference: str, local_nodes: dict[str, str]) -> str:
        match = REFERENCE_PATTERN.fullmatch(reference)
        if match:
            node_id, output = match.groups()
            return f"nodes.{local_nodes.get(node_id, node_id)}.outputs.{output}"
        parts = reference.split(".")
        if len(parts) == 4 and parts[0] == "steps" and parts[2] == "outputs":
            step_id, output = parts[1], parts[3]
            instances = self.step_outputs.get(step_id)
            if instances is None:
                raise GraphProviderError(f"reference uses unavailable step: {step_id}")
            if len(instances) != 1:
                raise GraphProviderError(f"mapped step reference requires an instance index: {reference}")
            return self._extract_step_reference(step_id, 0, output)
        if len(parts) == 5 and parts[0] == "steps" and parts[3] == "outputs" and parts[2].isdigit():
            return self._extract_step_reference(parts[1], int(parts[2]), parts[4])
        if reference.startswith("inputs."):
            return reference
        raise GraphProviderError(f"unsupported workflow program reference: {reference}")

    def _extract_step_reference(self, step_id: str, index: int, output: str) -> str:
        instances = self.step_outputs.get(step_id)
        if instances is None or index >= len(instances):
            raise GraphProviderError(f"step output instance is unavailable: {step_id}.{index}")
        value = as_map(instances[index].get(output), f"step {step_id} output {output}")
        reference = value.get("$ref")
        if not isinstance(reference, str) or REFERENCE_PATTERN.fullmatch(reference) is None:
            raise GraphProviderError(f"step {step_id} output {output} is not a node output reference")
        return reference

    def _evaluate_condition(self, value: object) -> bool:
        resolved = self._resolve_compile_values(value, {}, {})
        if isinstance(resolved, bool):
            return resolved
        condition = as_map(resolved, "step condition")
        if set(condition) == {"equals"}:
            values = as_list(condition["equals"], "equals")
            if len(values) != 2:
                raise GraphProviderError("equals condition requires exactly two values")
            return values[0] == values[1]
        if set(condition) == {"not"}:
            return not self._evaluate_condition(condition["not"])
        if set(condition) in ({"and"}, {"or"}):
            operator, raw_values = next(iter(condition.items()))
            values = as_list(raw_values, operator)
            results = [self._evaluate_condition(item) for item in values]
            return all(results) if operator == "and" else any(results)
        raise GraphProviderError(f"unsupported step condition: {condition}")

    @staticmethod
    def _require_id(value: str, label: str) -> None:
        if ID_PATTERN.fullmatch(value) is None:
            raise GraphProviderError(f"{label} id is invalid: {value}")


def compile_file(
    source_path: pathlib.Path,
    variable_overrides: JsonMap | None = None,
) -> tuple[JsonMap, JsonMap]:
    source = load_json(source_path, "workflow program")
    return WorkflowCompiler(source, source_path, variable_overrides).compile()


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description="Compile reusable modules, maps, and branches into a mere.run graph.")
    value.add_argument("source", type=pathlib.Path)
    value.add_argument("--output", required=True, type=pathlib.Path)
    value.add_argument("--report-output", type=pathlib.Path)
    value.add_argument("--variables-json", type=pathlib.Path)
    value.add_argument("--json", action="store_true")
    return value


def run(args: argparse.Namespace) -> JsonMap:
    overrides = load_json(args.variables_json, "variable overrides") if args.variables_json else None
    graph, report = compile_file(args.source, overrides)
    write_json(args.output, graph)
    if args.report_output:
        write_json(args.report_output, report)
    return {
        "contract_version": REPORT_CONTRACT_VERSION,
        "status": "compiled",
        "output": str(args.output),
        "report_output": str(args.report_output) if args.report_output else None,
        "result": report,
    }


def main() -> int:
    args = parser().parse_args()
    try:
        result = run(args)
    except (GraphProviderError, OSError) as exc:
        sys.stderr.write(str(exc) + "\n")
        return 2
    if args.json:
        sys.stdout.write(json.dumps(result, sort_keys=True) + "\n")
    else:
        sys.stdout.write(f"Compiled {result['output']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
