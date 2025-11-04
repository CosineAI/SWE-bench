#!/usr/bin/env python3
"""
CLI to extract commands for one or more SWE-bench instance IDs.

By default, prints only the test commands (the lines between START_TEST_OUTPUT and END_TEST_OUTPUT)
for each instance. You can choose other sections with --section.

Instance IDs can be provided directly with -i/--instance_ids, or via a JSON file containing
an array of string IDs using --instance_ids_file.

Usage:
    # Direct IDs
    python -m swebench.harness.get_instance_commands -i django__django-15180 pytest-dev__pytest-10482

    # From a JSON file: ["django__django-15180", "pytest-dev__pytest-10482"]
    python -m swebench.harness.get_instance_commands --instance_ids_file ids.json

    # Change section and output format
    python -m swebench.harness.get_instance_commands --instance_ids_file ids.json --section eval
    python -m swebench.harness.get_instance_commands --instance_ids_file ids.json --format json --output commands.json
"""

from __future__ import annotations

import json
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter
from typing import Dict, List

from swebench.harness.constants import START_TEST_OUTPUT, END_TEST_OUTPUT, MAP_REPO_VERSION_TO_SPECS
from swebench.harness.test_spec.test_spec import make_test_spec
from swebench.harness.utils import load_swebench_dataset


def _extract_test_commands(eval_script_list: List[str]) -> List[str]:
    """Return only the test commands between START_TEST_OUTPUT and END_TEST_OUTPUT."""
    try:
        start = eval_script_list.index(f": '{START_TEST_OUTPUT}'") + 1
        end = eval_script_list.index(f": '{END_TEST_OUTPUT}'")
        return eval_script_list[start:end]
    except ValueError:
        # Markers not found; return empty list
        return []


def _get_install_cmds(instance: Dict) -> List[str]:
    """Return the install command(s) defined in the specs for this instance."""
    specs = MAP_REPO_VERSION_TO_SPECS[instance["repo"]][instance["version"]]
    install = specs.get("install")
    if install is None:
        return []
    if isinstance(install, list):
        return install
    return [install]


def get_instance_commands(instance: Dict, section: str = "test") -> Dict[str, List[str]] | List[str]:
    """
    Build the TestSpec for the instance and return commands for the requested section.

    section:
      - "test" -> only the test commands (between markers)
      - "eval" -> full eval script list
      - "repo" -> repository setup commands
      - "env"  -> environment setup commands
      - "install" -> install command(s) from specs
      - "all"  -> dict with keys: env, repo, eval, test, install
    """
    ts = make_test_spec(instance)
    if section == "test":
        return _extract_test_commands(ts.eval_script_list)
    elif section == "eval":
        return ts.eval_script_list
    elif section == "repo":
        return ts.repo_script_list
    elif section == "env":
        return ts.env_script_list
    elif section == "install":
        return _get_install_cmds(instance)
    elif section == "all":
        return {
            "env": ts.env_script_list,
            "repo": ts.repo_script_list,
            "eval": ts.eval_script_list,
            "test": _extract_test_commands(ts.eval_script_list),
            "install": _get_install_cmds(instance),
        }
    else:
        raise ValueError(f"Unknown section: {section}")


def _load_ids(instance_ids: List[str] | None, instance_ids_file: str | None) -> List[str]:
    """
    Combine IDs provided directly with IDs loaded from a JSON file.

    The JSON file must contain an array of strings: ["repo__repo-123", "..."]
    """
    ids: List[str] = list(instance_ids or [])
    if instance_ids_file:
        with open(instance_ids_file, "r") as f:
            data = json.load(f)
        if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
            raise ValueError("instance_ids_file must be a JSON array of strings")
        ids.extend(data)
    # de-duplicate while preserving order
    seen = set()
    unique_ids: List[str] = []
    for x in ids:
        if x not in seen:
            unique_ids.append(x)
            seen.add(x)
    return unique_ids


def main(
    dataset_name: str,
    split: str,
    instance_ids: List[str] | None,
    instance_ids_file: str | None,
    section: str,
    fmt: str,
    output: str | None,
) -> None:
    # load IDs from CLI and JSON file
    ids = _load_ids(instance_ids, instance_ids_file)
    if not ids:
        print("No instance IDs provided. Use -i/--instance_ids or --instance_ids_file.")
        return

    dataset = load_swebench_dataset(dataset_name, split, ids)
    if not dataset:
        print("No instances found for the given IDs.")
        return

    results: Dict[str, Dict[str, List[str]] | List[str]] = {}
    for instance in dataset:
        instance_id = instance["instance_id"]
        results[instance_id] = get_instance_commands(instance, section)

    if fmt == "json":
        payload = json.dumps(results, indent=2)
        if output:
            with open(output, "w") as f:
                f.write(payload)
        else:
            print(payload)
    else:
        # human-readable text
        for iid, cmds in results.items():
            print(f"Instance: {iid}")
            if section == "all":
                assert isinstance(cmds, dict)
                for key in ["env", "repo", "eval", "test", "install"]:
                    print(f"  {key} commands:")
                    for c in cmds[key]:
                        print(f"    {c}")
                print()
            else:
                assert isinstance(cmds, list)
                for c in cmds:
                    print(f"  {c}")
                print()


if __name__ == "__main__":
    parser = ArgumentParser(
        description="Extract commands for SWE-bench instance IDs.",
        formatter_class=ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "-d",
        "--dataset_name",
        default="SWE-bench/SWE-bench_Lite",
        type=str,
        help="Dataset name or path to JSON/JSONL file.",
    )
    parser.add_argument(
        "-s", "--split", type=str, default="test", help="Dataset split."
    )
    parser.add_argument(
        "-i",
        "--instance_ids",
        nargs="+",
        required=False,
        help="Instance IDs to process (space separated).",
    )
    parser.add_argument(
        "--instance_ids_file",
        type=str,
        help="Path to JSON file containing an array of instance IDs.",
    )
    parser.add_argument(
        "--section",
        choices=["test", "eval", "repo", "env", "install", "all"],
        default="test",
        help="Which commands to extract.",
    )
    parser.add_argument(
        "--format",
        dest="fmt",
        choices=["text", "json"],
        default="text",
        help="Output format.",
    )
    parser.add_argument(
        "--output",
        type=str,
        default=None,
        help="Optional path to write JSON output.",
    )

    args = parser.parse_args()
    main(**vars(args))