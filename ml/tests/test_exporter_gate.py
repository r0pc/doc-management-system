"""Double-gate tests: real-text mode needs flag AND env var, refusing in both orders."""

import csv
import os
import subprocess
import sys
from pathlib import Path

from docx import Document

from generate_synthetic_corpus import generate_corpus

ML_DIR = Path(__file__).resolve().parents[1]
CONFIRM_ENV = "DMS_EXPORT_REAL_TEXT_CONFIRM"


def _run_export(
    manifest: Path, out: Path, extra: list[str], env_overrides: dict[str, str]
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.pop(CONFIRM_ENV, None)
    env.update(env_overrides)
    return subprocess.run(
        [sys.executable, "-m", "export_training_data", str(manifest), "--out", str(out), *extra],
        cwd=ML_DIR,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def _synthetic_manifest(tmp_path: Path) -> Path:
    generate_corpus(count=2, out_dir=tmp_path / "corpus", seed=7)
    return tmp_path / "corpus" / "manifest.csv"


def _real_store(tmp_path: Path) -> Path:
    store = tmp_path / "real_store"
    store.mkdir()
    doc = Document()
    doc.add_paragraph("Quarterly access review minutes for the records department.")
    doc.save(store / "real_doc.docx")
    (store / "labels.csv").write_text(
        "file_name,label_doc_type,label_level\nreal_doc.docx,policy_memo,internal\n",
        encoding="utf-8",
    )
    return store


def test_synthetic_default_mode_exports_rows_without_any_gate(tmp_path: Path):
    manifest = _synthetic_manifest(tmp_path)
    dataset = tmp_path / "dataset.csv"

    proc = _run_export(manifest, dataset, [], {})

    assert proc.returncode == 0, proc.stderr
    with dataset.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 2
    assert {r["source"] for r in rows} == {"synthetic"}
    assert all(0 < len(r["text_excerpt"]) <= 4000 for r in rows)
    assert all(r["label_doc_type"] and r["label_level"] for r in rows)


def test_flag_without_env_refuses(tmp_path: Path):
    manifest = _synthetic_manifest(tmp_path)
    dataset = tmp_path / "dataset.csv"

    proc = _run_export(manifest, dataset, ["--allow-real-text", str(_real_store(tmp_path))], {})

    assert proc.returncode == 2
    assert not dataset.exists()
    combined = proc.stdout + proc.stderr
    assert "must not leave" in combined.lower() or "self-hosting invariant" in combined.lower()


def test_env_without_flag_refuses(tmp_path: Path):
    manifest = _synthetic_manifest(tmp_path)
    dataset = tmp_path / "dataset.csv"

    proc = _run_export(manifest, dataset, [], {CONFIRM_ENV: "yes"})

    assert proc.returncode == 2
    assert not dataset.exists()


def test_env_set_to_other_value_with_flag_refuses(tmp_path: Path):
    manifest = _synthetic_manifest(tmp_path)
    dataset = tmp_path / "dataset.csv"

    proc = _run_export(
        manifest, dataset, ["--allow-real-text", str(_real_store(tmp_path))], {CONFIRM_ENV: "YES"}
    )

    assert proc.returncode == 2
    assert not dataset.exists()


def test_both_gate_inputs_set_proceeds_and_writes_real_rows(tmp_path: Path):
    manifest = _synthetic_manifest(tmp_path)
    dataset = tmp_path / "dataset.csv"

    proc = _run_export(
        manifest,
        dataset,
        ["--allow-real-text", str(_real_store(tmp_path))],
        {CONFIRM_ENV: "yes"},
    )

    assert proc.returncode == 0, proc.stderr
    with dataset.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    sources = {r["source"] for r in rows}
    assert sources == {"synthetic", "real"}
    real_rows = [r for r in rows if r["source"] == "real"]
    assert len(real_rows) == 1
    assert real_rows[0]["label_doc_type"] == "policy_memo"
