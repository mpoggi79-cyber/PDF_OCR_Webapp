"""Runner dei test OCR ufficiali basato sulle API HTTP reali del backend.

Questo script legge i casi in tests/official, esegue upload, avvio OCR, polling del job,
esportazione markdown e salvataggio dei risultati in actual/.
"""

from __future__ import annotations

import argparse
import json
import mimetypes
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

SUPPORTED_INPUT_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg"}
TERMINAL_JOB_STATUSES = {"done", "error", "partial"}
DEFAULT_BASE_URL = "http://localhost:8080"
DEFAULT_DATASET_ROOT = Path(__file__).resolve().parent / "official"


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def milliseconds_to_seconds(value_ms: int | None) -> float | None:
    if value_ms is None:
        return None
    return round(value_ms / 1000, 3)


def duration_map_ms_to_seconds(duration_map: dict[str, Any] | None) -> dict[str, float] | None:
    if not duration_map:
        return None

    converted: dict[str, float] = {}
    for key, value in duration_map.items():
        if isinstance(value, int):
            converted[str(key)] = round(value / 1000, 3)
    return converted or None


def load_cases(dataset_root: Path) -> list[dict[str, Any]]:
    metadata = read_json(dataset_root / "metadata.json")
    cases: list[dict[str, Any]] = []

    for item in metadata.get("cases", []):
        relative_case_dir = item["relative_case_dir"]
        case_dir = dataset_root / relative_case_dir
        case_metadata = read_json(case_dir / "case.json")
        merged = dict(item)
        merged.update(case_metadata)
        merged["relative_case_dir"] = relative_case_dir
        merged["case_dir"] = case_dir
        cases.append(merged)

    return cases


def filter_cases(
    cases: list[dict[str, Any]],
    case_id: str | None,
    *,
    exact: bool = False,
) -> list[dict[str, Any]]:
    if not case_id:
        return cases

    if exact:
        filtered = [case for case in cases if case.get("id") == case_id]
        if filtered:
            return filtered
        raise SystemExit(f"Caso non trovato: {case_id}")

    filtered: list[dict[str, Any]] = []
    for case in cases:
        if case.get("id") == case_id or case.get("group") == case_id:
            filtered.append(case)

    if filtered:
        seen_ids: set[str] = set()
        unique_filtered: list[dict[str, Any]] = []
        for case in filtered:
            case_id_value = str(case.get("id"))
            if case_id_value in seen_ids:
                continue
            seen_ids.add(case_id_value)
            unique_filtered.append(case)
        return unique_filtered

    filtered = [case for case in cases if case.get("group") == case_id]
    if filtered:
        return filtered

    raise SystemExit(f"Caso non trovato: {case_id}")


def resolve_input_file(case_dir: Path) -> Path | None:
    input_dir = case_dir / "input"
    if not input_dir.exists():
        return None

    candidates = sorted(
        path
        for path in input_dir.iterdir()
        if path.is_file() and path.suffix.lower() in SUPPORTED_INPUT_EXTENSIONS
    )
    if not candidates:
        return None
    if len(candidates) > 1:
        raise RuntimeError(f"Trovati piu' file input in {input_dir}")
    return candidates[0]


def resolve_expected_file(case_dir: Path, input_file: Path | None) -> Path | None:
    if input_file is None:
        return None

    expected_file = case_dir / "expected" / f"{input_file.stem}.md"
    return expected_file if expected_file.exists() else None


def compare_actual_with_expected(
    actual_file: Path,
    expected_file: Path | None,
) -> dict[str, str | None]:
    if expected_file is None:
        return {"status": "not_available", "warning": None}

    if not actual_file.exists():
        return {
            "status": "missing_actual",
            "warning": f"ATTENZIONE: actual non trovato per {expected_file.name}.",
        }

    actual = actual_file.read_text(encoding="utf-8")
    expected = expected_file.read_text(encoding="utf-8")
    if actual == expected:
        return {"status": "match", "warning": None}

    return {
        "status": "different",
        "warning": (
            f"ATTENZIONE: actual differisce da expected per {expected_file.name}. "
            "Eseguire una verifica visiva prima di aggiornare expected."
        ),
    }


def build_structure_report(cases: list[dict[str, Any]]) -> dict[str, Any]:
    missing: list[dict[str, str]] = []

    for case in cases:
        case_dir = Path(case["case_dir"])
        for relative_path in ("case.json", "input", "expected", "actual"):
            target = case_dir / relative_path
            if not target.exists():
                missing.append({"case_id": case["id"], "missing": str(target)})

    return {
        "checked_at": utc_now_iso(),
        "cases_checked": len(cases),
        "ok": not missing,
        "missing": missing,
    }


def print_case_list(cases: list[dict[str, Any]]) -> None:
    for case in cases:
        group = case.get("group")
        group_label = f" | gruppo {group}" if group else ""
        print(f"{case['id']}{group_label} | {case['label']} | {case['relative_case_dir']}")


def build_case_report(
    case: dict[str, Any],
    *,
    input_file: Path | None,
    expected_file: Path | None,
    actual_file: Path,
    result_status: str,
    job_payload: dict[str, Any] | None,
    runner_elapsed_ms: int | None,
    detail: str | None = None,
    doc_id: str | None = None,
) -> dict[str, Any]:
    comparison = compare_actual_with_expected(actual_file, expected_file)
    payload = {
        "case_id": case["id"],
        "group": case.get("group"),
        "label": case.get("label"),
        "prompt_profile": case.get("prompt_profile"),
        "source_type": case.get("source_type"),
        "status": result_status,
        "detail": detail,
        "doc_id": doc_id,
        "input_file": input_file.name if input_file else None,
        "expected_file": expected_file.name if expected_file else None,
        "expected_present": expected_file is not None,
        "expected_comparison": comparison["status"],
        "comparison_warning": comparison["warning"],
        "actual_file": str(actual_file),
        "job_status": (job_payload or {}).get("status"),
        "runner_elapsed_seconds": milliseconds_to_seconds(runner_elapsed_ms),
        "ocr_total_duration_seconds": milliseconds_to_seconds((job_payload or {}).get("total_duration_ms")),
        "pages_duration_seconds": duration_map_ms_to_seconds((job_payload or {}).get("pages_duration_ms")),
        "started_at": (job_payload or {}).get("started_at"),
        "finished_at": (job_payload or {}).get("finished_at"),
        "updated_at": (job_payload or {}).get("updated_at"),
        "generated_at": utc_now_iso(),
    }
    return payload


def refresh_case_comparison(case: dict[str, Any]) -> dict[str, Any]:
    case_dir = Path(case["case_dir"])
    input_file = resolve_input_file(case_dir)
    expected_file = resolve_expected_file(case_dir, input_file)
    actual_file = case_dir / "actual" / ((input_file.stem + ".md") if input_file else "missing-input.md")
    report_path = case_dir / "actual" / "last_run.json"

    if report_path.exists():
        report = read_json(report_path)
    else:
        report = build_case_report(
            case,
            input_file=input_file,
            expected_file=expected_file,
            actual_file=actual_file,
            result_status="not_run",
            job_payload=None,
            runner_elapsed_ms=None,
            detail="Confronto eseguito senza un run OCR precedente.",
        )

    comparison = compare_actual_with_expected(actual_file, expected_file)
    report.update(
        {
            "expected_file": expected_file.name if expected_file else None,
            "expected_present": expected_file is not None,
            "expected_comparison": comparison["status"],
            "comparison_warning": comparison["warning"],
            "comparison_checked_at": utc_now_iso(),
        }
    )
    write_json(report_path, report)
    return report


def render_markdown_summary(summary: dict[str, Any]) -> str:
    lines = [
        "# Report test OCR ufficiali",
        "",
        f"- Generato: {summary['generated_at']}",
        f"- Base URL: {summary['base_url']}",
        f"- Casi considerati: {summary['cases_considered']}",
        f"- {summary.get('cases_label', 'Casi eseguiti')}: {summary['cases_executed']}",
        "",
        "| Caso | Stato | Confronto | Input | Tempo runner s | Tempo OCR s | Job |",
        "|------|-------|-----------|-------|----------------|-------------|-----|",
    ]

    for result in summary["results"]:
        lines.append(
            f"| {result['case_id']} | {result['status']} | {result.get('expected_comparison') or '-'} | "
            f"{result.get('input_file') or '-'} | "
            f"{result.get('runner_elapsed_seconds') or '-'} | {result.get('ocr_total_duration_seconds') or '-'} | "
            f"{result.get('job_status') or '-'} |"
        )

    warnings = [result["comparison_warning"] for result in summary["results"] if result.get("comparison_warning")]
    if warnings:
        lines.extend(["", "## Avvisi confronto actual/expected", ""])
        lines.extend(f"- {warning}" for warning in warnings)

    return "\n".join(lines) + "\n"


def execute_case(
    client: httpx.Client,
    case: dict[str, Any],
    *,
    poll_interval: float,
    timeout_seconds: float,
) -> dict[str, Any]:
    case_dir = Path(case["case_dir"])
    actual_dir = case_dir / "actual"
    input_file = resolve_input_file(case_dir)
    expected_file = resolve_expected_file(case_dir, input_file)
    actual_file = actual_dir / ((input_file.stem + ".md") if input_file else "missing-input.md")

    if input_file is None:
        report = build_case_report(
            case,
            input_file=None,
            expected_file=None,
            actual_file=actual_file,
            result_status="missing_input",
            job_payload=None,
            runner_elapsed_ms=None,
            detail="Nessun file input trovato nella cartella input/.",
        )
        write_json(actual_dir / "last_run.json", report)
        return report

    mime_type = mimetypes.guess_type(input_file.name)[0] or "application/octet-stream"
    params = {}
    if case.get("prompt_profile"):
        params["prompt_profile"] = case["prompt_profile"]
    if case.get("page_rotation") is not None:
        params["page_rotation"] = case["page_rotation"]

    with input_file.open("rb") as file_stream:
        upload_response = client.post(
            "/api/upload",
            params=params,
            files={"file": (input_file.name, file_stream, mime_type)},
        )
    upload_response.raise_for_status()
    upload_payload = upload_response.json()
    doc_id = upload_payload["doc_id"]

    start_response = client.post(f"/api/ocr-job/{doc_id}", params=params)
    start_response.raise_for_status()

    runner_start = time.perf_counter()
    final_job: dict[str, Any] | None = None

    while True:
        job_response = client.get(f"/api/ocr-job/{doc_id}")
        job_response.raise_for_status()
        final_job = job_response.json()
        if final_job.get("status") in TERMINAL_JOB_STATUSES:
            break
        if time.perf_counter() - runner_start > timeout_seconds:
            report = build_case_report(
                case,
                input_file=input_file,
                expected_file=expected_file,
                actual_file=actual_file,
                result_status="timeout",
                job_payload=final_job,
                runner_elapsed_ms=int((time.perf_counter() - runner_start) * 1000),
                detail=f"Timeout dopo {timeout_seconds} secondi.",
                doc_id=doc_id,
            )
            write_json(actual_dir / "last_run.json", report)
            return report
        time.sleep(poll_interval)

    export_response = client.get(f"/api/export/{doc_id}")
    export_response.raise_for_status()
    export_payload = export_response.json()
    write_text(actual_file, export_payload.get("content") or "")

    report = build_case_report(
        case,
        input_file=input_file,
        expected_file=expected_file,
        actual_file=actual_file,
        result_status="generated",
        job_payload=final_job,
        runner_elapsed_ms=int((time.perf_counter() - runner_start) * 1000),
        detail="Markdown generato con successo.",
        doc_id=doc_id,
    )
    write_json(actual_dir / "last_run.json", report)
    return report


def save_summary(
    dataset_root: Path,
    base_url: str,
    results: list[dict[str, Any]],
    *,
    cases_label: str = "Casi eseguiti",
) -> Path:
    results_dir = dataset_root / "results"
    results_dir.mkdir(parents=True, exist_ok=True)

    summary = {
        "generated_at": utc_now_iso(),
        "base_url": base_url,
        "cases_considered": len(results),
        "cases_executed": sum(1 for item in results if item["status"] != "missing_input"),
        "cases_label": cases_label,
        "results": results,
    }
    json_path = results_dir / "latest.json"
    markdown_path = results_dir / "latest.md"
    write_json(json_path, summary)
    write_text(markdown_path, render_markdown_summary(summary))
    return json_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Esegue i test OCR ufficiali via API HTTP.")
    parser.add_argument("--dataset-root", default=str(DEFAULT_DATASET_ROOT), help="Cartella dataset test ufficiali.")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Base URL del backend FastAPI.")
    parser.add_argument("--case", dest="case_id", help="Esegue un solo caso, per esempio T001.")
    parser.add_argument(
        "--exact-case",
        action="store_true",
        help="Con --case esegue solo l'ID esatto, senza includere eventuali varianti dello stesso gruppo.",
    )
    parser.add_argument("--list", action="store_true", help="Mostra i casi disponibili e termina.")
    parser.add_argument(
        "--check-structure",
        action="store_true",
        help="Controlla che esistano metadata e cartelle standard dei casi.",
    )
    parser.add_argument(
        "--compare-only",
        action="store_true",
        help="Confronta actual ed expected dei report esistenti senza eseguire nuovo OCR.",
    )
    parser.add_argument("--poll-interval", type=float, default=1.0, help="Intervallo polling job in secondi.")
    parser.add_argument("--timeout-seconds", type=float, default=300.0, help="Timeout per singolo caso.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    dataset_root = Path(args.dataset_root)
    cases = filter_cases(load_cases(dataset_root), args.case_id, exact=args.exact_case)

    if args.list:
        print_case_list(cases)
        return 0

    if args.check_structure:
        structure_report = build_structure_report(cases)
        print(json.dumps(structure_report, ensure_ascii=False, indent=2))
        return 0 if structure_report["ok"] else 1

    if args.compare_only:
        results = [refresh_case_comparison(case) for case in cases]
        report_path = save_summary(
            dataset_root,
            args.base_url,
            results,
            cases_label="Casi confrontati",
        )
        for result in results:
            if result.get("comparison_warning"):
                print(result["comparison_warning"])
        print(f"Report confronto salvato in {report_path}")
        return 0

    timeout = httpx.Timeout(args.timeout_seconds + 10.0, connect=10.0)
    results: list[dict[str, Any]] = []
    execution_failed = False

    with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=timeout) as client:
        for case in cases:
            try:
                result = execute_case(
                    client,
                    case,
                    poll_interval=args.poll_interval,
                    timeout_seconds=args.timeout_seconds,
                )
            except Exception as exc:
                case_dir = Path(case["case_dir"])
                actual_dir = case_dir / "actual"
                result = build_case_report(
                    case,
                    input_file=resolve_input_file(case_dir),
                    expected_file=None,
                    actual_file=actual_dir / "last_failure.md",
                    result_status="failed",
                    job_payload=None,
                    runner_elapsed_ms=None,
                    detail=str(exc),
                )
                write_json(actual_dir / "last_run.json", result)
                execution_failed = True
            else:
                if result["status"] in {"timeout", "failed"}:
                    execution_failed = True
                if result.get("comparison_warning"):
                    print(result["comparison_warning"])
            results.append(result)

    report_path = save_summary(dataset_root, args.base_url, results)
    print(f"Report salvato in {report_path}")
    return 1 if execution_failed else 0


if __name__ == "__main__":
    sys.exit(main())
