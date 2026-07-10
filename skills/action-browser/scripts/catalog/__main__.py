from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

from .core import CURRENT_SITES, build_catalog, envelope, read_json, render_markdown, validate_catalog, write_json


def main() -> int:
    parser = argparse.ArgumentParser(prog="catalog")
    sub = parser.add_subparsers(dest="command", required=True)
    capture = sub.add_parser("capture-reference")
    capture.add_argument("--repo", type=Path, required=True)
    capture.add_argument("--commit", required=True)
    capture.add_argument("--output", type=Path, required=True)
    inventory = sub.add_parser("inventory-target")
    inventory.add_argument("--execution-baseline", required=True)
    inventory.add_argument("--output", type=Path, required=True)
    diff = sub.add_parser("diff")
    diff.add_argument("--reference", type=Path, required=True)
    diff.add_argument("--target", type=Path, required=True)
    diff.add_argument("--output", type=Path, required=True)
    diff.add_argument("--reference-baseline", required=True)
    diff.add_argument("--execution-baseline", required=True)
    validate = sub.add_parser("validate")
    validate.add_argument("--source", type=Path, required=True)
    render = sub.add_parser("render")
    render.add_argument("--source", type=Path, required=True)
    render.add_argument("--output", type=Path, required=True)
    render.add_argument("--format", choices=["markdown"], required=True)
    maintenance = sub.add_parser("maintenance-check")
    maintenance.add_argument("--previous", type=Path, required=True)
    maintenance.add_argument("--current", type=Path, required=True)
    maintenance.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.command == "capture-reference":
            manifest = subprocess.check_output(["git", "-C", str(args.repo), "show", f"{args.commit}:cli-manifest.json"], text=True)
            write_json(args.output, json.loads(manifest))
            result = envelope("capture", "completed", artifact_refs=[str(args.output)])
        elif args.command == "inventory-target":
            root = Path.cwd()
            head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root, text=True).strip()
            sites = sorted(path.name.removesuffix("_workflow.py") for path in (root / "scripts" / "adapters").glob("*_workflow.py"))
            references = sorted(path.stem for path in (root / "references" / "adapters").glob("*.md"))
            if head != args.execution_baseline:
                result = envelope("inventory", "failed", failure={"reason_code": "native_conflict", "message": "current HEAD differs from execution baseline", "retryable": False})
            elif sites != references or sites != sorted(CURRENT_SITES):
                result = envelope("inventory", "failed", failure={"reason_code": "native_conflict", "message": "site inventory does not match current sites", "retryable": False})
            else:
                write_json(args.output, {"execution_baseline": args.execution_baseline, "sites": sites, "evidence": {site: {"script": f"scripts/adapters/{site}_workflow.py", "reference": f"references/adapters/{site}.md"} for site in sites}})
                result = envelope("inventory", "completed", artifact_refs=[str(args.output)])
        elif args.command == "diff":
            write_json(args.output, build_catalog(read_json(args.reference), read_json(args.target), reference_baseline=args.reference_baseline, execution_baseline=args.execution_baseline))
            result = envelope("diff", "completed", artifact_refs=[str(args.output)])
        elif args.command == "validate":
            errors = validate_catalog(read_json(args.source))
            result = envelope("validate", "completed" if not errors else "failed", failure=None if not errors else errors[0])
        else:
            if args.command == "render":
                args.output.write_text(render_markdown(read_json(args.source)), encoding="utf-8")
                result = envelope("render", "completed", artifact_refs=[str(args.output)])
            else:
                def item_id(item: dict[str, object]) -> str:
                    return str(item.get("id") or f"{item.get('site', '')}.{item.get('name', '')}")
                previous = {item_id(item) for item in read_json(args.previous)}
                current = {item_id(item) for item in read_json(args.current)}
                write_json(args.output, {"added": sorted(current - previous), "removed": sorted(previous - current)})
                result = envelope("maintenance-check", "completed", artifact_refs=[str(args.output)])
    except (OSError, ValueError, TypeError, KeyError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        operation = {"capture-reference": "capture", "inventory-target": "inventory"}.get(args.command, args.command)
        result = envelope(operation, "failed", failure={"reason_code": "schema_mismatch", "message": str(error), "retryable": False})
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
