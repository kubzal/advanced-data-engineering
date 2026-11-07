"""Zapis danych: Parquet / CSV / JSON Lines / Avro, lokalnie lub do GCS (``gs://bucket/prefiks``).

Zapis do GCS używa wbudowanego w pyarrow klienta (``pyarrow.fs.GcsFileSystem``) i Application
Default Credentials. Nie trzeba instalować dodatkowych bibliotek.
"""

from __future__ import annotations

import base64
import json
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import pyarrow as pa
import pyarrow.csv as pacsv
import pyarrow.fs as pafs
import pyarrow.parquet as pq

FORMATS = ("parquet", "csv", "jsonl", "avro")
EXTENSIONS = {"parquet": ".parquet", "csv": ".csv", "jsonl": ".jsonl", "avro": ".avro"}


def json_default(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, bytes):
        return base64.b64encode(value).decode()
    raise TypeError(f"Nie umiem zserializować {type(value)}")


class Sink:
    """Miejsce docelowe: katalog lokalny albo ``gs://bucket/prefiks``."""

    def __init__(self, root: str, fmt: str = "parquet", compression: str | None = None):
        if fmt not in FORMATS:
            raise ValueError(f"Nieznany format {fmt!r}. Dostępne: {', '.join(FORMATS)}")
        self.root = root.rstrip("/")
        self.fmt = fmt
        self.compression = compression
        if "://" in root:
            self.fs, self.base = pafs.FileSystem.from_uri(root)
        else:
            self.fs, self.base = pafs.LocalFileSystem(), root
        self.is_local = isinstance(self.fs, pafs.LocalFileSystem)

    # -- ścieżki ------------------------------------------------------------------------------

    def _path(self, relpath: str) -> str:
        path = f"{self.base.rstrip('/')}/{relpath}"
        if self.is_local:
            parent = path.rsplit("/", 1)[0]
            self.fs.create_dir(parent, recursive=True)
        return path

    def uri(self, relpath: str = "") -> str:
        return f"{self.root}/{relpath}" if relpath else self.root

    # -- zapis ----------------------------------------------------------------------------------

    def write_bytes(self, relpath: str, data: bytes) -> None:
        with self.fs.open_output_stream(self._path(relpath), compression=None) as out:
            out.write(data)

    def write_table(self, relpath_stem: str, table: pa.Table, fmt: str | None = None) -> str:
        """Zapisuje tabelę; rozszerzenie pliku dobierane jest do formatu. Zwraca ścieżkę względną."""
        fmt = fmt or self.fmt
        ext = EXTENSIONS[fmt]
        comp = self.compression
        if fmt in ("csv", "jsonl") and comp == "gzip":
            ext += ".gz"
        relpath = relpath_stem + ext
        path = self._path(relpath)
        if fmt == "parquet":
            pq.write_table(
                table,
                path,
                filesystem=self.fs,
                compression=comp or "zstd",
                row_group_size=min(max(table.num_rows, 1), 1_000_000),
            )
        elif fmt == "csv":
            with self.fs.open_output_stream(path, compression="gzip" if comp == "gzip" else None) as out:
                pacsv.write_csv(table, out)
        elif fmt == "jsonl":
            with self.fs.open_output_stream(path, compression="gzip" if comp == "gzip" else None) as out:
                for batch in table.to_batches(max_chunksize=20_000):
                    lines = (
                        json.dumps(r, default=json_default, ensure_ascii=False) for r in batch.to_pylist()
                    )
                    out.write(("\n".join(lines) + "\n").encode("utf-8"))
        elif fmt == "avro":
            self._write_avro(path, table, comp)
        return relpath

    def _write_avro(self, path: str, table: pa.Table, comp: str | None) -> None:
        try:
            import fastavro
        except ImportError as exc:  # pragma: no cover - zależy od środowiska
            raise SystemExit("Format avro wymaga pakietu fastavro: uv sync --extra avro") from exc
        from .schemas import SCHEMAS, avro_schema

        name = next((n for n, s in SCHEMAS.items() if s.names == table.schema.names), None)
        if name is None:
            raise ValueError("Zapis Avro obsługuje tylko tabele o kanonicznym schemacie")
        schema = fastavro.parse_schema(avro_schema(name))
        with self.fs.open_output_stream(path, compression=None) as out:
            fastavro.writer(
                out,
                schema,
                (r for b in table.to_batches(50_000) for r in b.to_pylist()),
                codec="deflate" if comp in (None, "deflate", "gzip") else "null",
            )


def is_empty_destination(root: str) -> bool:
    if "://" in root:
        return True  # dla GCS nie sprawdzamy (listowanie może być kosztowne)
    fs = pafs.LocalFileSystem()
    info = fs.get_file_info(root)
    if info.type == pafs.FileType.NotFound:
        return True
    return not fs.get_file_info(pafs.FileSelector(root, recursive=False))
