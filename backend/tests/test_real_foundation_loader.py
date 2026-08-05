from __future__ import annotations

from pathlib import Path

import pytest

from app.load_real_foundation import (
    FOUNDATION_SOURCES,
    _sqlalchemy_database_url,
    source_manifest_checksum,
    source_paths,
)


def _write_source_files(data_dir: Path) -> None:
    for index, source in enumerate(FOUNDATION_SOURCES):
        (data_dir / source.filename).write_bytes(f"source-{index}".encode("utf-8"))


def test_real_foundation_source_mapping_is_explicit() -> None:
    assert [(source.schema, source.table, source.filename) for source in FOUNDATION_SOURCES] == [
        (
            "canonical_network",
            "canonical_corridors",
            "canonical_corridors.geoparquet",
        ),
        (
            "canonical_network",
            "official_segment_links",
            "official_segment_links.parquet",
        ),
        (
            "accident_attribution",
            "accident_attributions",
            "accident_attributions.geoparquet",
        ),
        (
            "accident_attribution",
            "accident_attribution_summary",
            "accident_attribution_summary.parquet",
        ),
    ]


def test_source_manifest_checksum_is_deterministic_and_detects_changes(tmp_path: Path) -> None:
    _write_source_files(tmp_path)

    first = source_manifest_checksum(tmp_path)
    second = source_manifest_checksum(tmp_path)

    assert first == second
    assert len(first) == 64

    (tmp_path / FOUNDATION_SOURCES[0].filename).write_bytes(b"changed")
    assert source_manifest_checksum(tmp_path) != first


def test_source_paths_reject_missing_files(tmp_path: Path) -> None:
    _write_source_files(tmp_path)
    missing = tmp_path / FOUNDATION_SOURCES[-1].filename
    missing.unlink()

    with pytest.raises(FileNotFoundError, match="accident_attribution_summary.parquet"):
        source_paths(tmp_path)


def test_loader_uses_the_installed_psycopg_sqlalchemy_driver() -> None:
    assert _sqlalchemy_database_url(
        "postgresql://road_user:secret@postgres:5432/road_risk"
    ) == "postgresql+psycopg://road_user:secret@postgres:5432/road_risk"


def test_nested_columns_are_json_encoded() -> None:
    pandas = pytest.importorskip("pandas")
    from app.load_real_foundation import _stringify_nested_columns

    frame = pandas.DataFrame(
        {"status_breakdown": [{"assigned": 1}], "total": [1]}
    )

    converted = _stringify_nested_columns(frame)

    assert converted.loc[0, "status_breakdown"] == '{"assigned": 1}'
    assert converted.loc[0, "total"] == 1
