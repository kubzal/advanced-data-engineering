"""Mini MapReduce od zera: map → partition → sort/spill → shuffle → merge → reduce.

Liczymy zdarzenia clickstream NovaCart per (event_type, country), dokładnie tak, jak zrobiłby to
klasyczny Hadoop MapReduce:

- input split = jeden plik partycji dziennej (`clickstream/dt=…/part-00000.parquet`),
- map task czyta split i emituje pary (klucz, 1),
- partitioner przydziela klucz do reducera: hash(klucz) mod R,
- map task sortuje swoje wyjście i zapisuje je na dysk (spill) — osobny plik na każdy reducer,
- shuffle: reducer r pobiera „swoje” pliki od WSZYSTKICH map tasków,
- merge: reducer scala posortowane pliki (merge sort) i wywołuje reduce dla każdego klucza.

Uruchamiamy zadanie dwa razy: bez combinera i z combinerem (lokalna agregacja po stronie mapa)
i porównujemy, ile bajtów przeszło przez shuffle. Wynik sprawdzamy w DuckDB.

Uruchomienie (z katalogu examples/):
    env -u VIRTUAL_ENV uv run python 03_mapreduce_from_scratch.py
    env -u VIRTUAL_ENV uv run python 03_mapreduce_from_scratch.py --reducers 8 --workers 8
"""

from __future__ import annotations

import argparse
import heapq
import os
import shutil
import tempfile
import time
import zlib
from collections import Counter
from collections.abc import Iterator
from itertools import groupby
from multiprocessing import Pool
from pathlib import Path

import duckdb
import pyarrow.parquet as pq

DATA = Path(os.environ.get("NOVACART_DATA", Path(__file__).resolve().parents[3] / "data" / "s"))


# ---------------------------------------------------------------------------------------------
# Funkcje użytkownika — to jedyne, co pisał programista Hadoopa. Reszta to „framework”.
# ---------------------------------------------------------------------------------------------
def map_fn(record: dict) -> Iterator[tuple[str, int]]:
    event_type = record["event_type"] or "<pusty>"
    yield f"{event_type}|{record['country']}", 1


def reduce_fn(key: str, values: Iterator[int]) -> tuple[str, int]:
    return key, sum(values)


# ---------------------------------------------------------------------------------------------
# Framework
# ---------------------------------------------------------------------------------------------
def partition(key: str, reducers: int) -> int:
    """Domyślny partitioner Hadoopa: hash(klucz) mod liczba reducerów."""
    return zlib.crc32(key.encode()) % reducers


def map_task(args: tuple[int, Path, Path, int, bool]) -> dict:
    task_id, split, workdir, reducers, use_combiner = args
    t0 = time.perf_counter()
    table = pq.read_table(split, columns=["event_type", "country"])
    buffers: list[list[tuple[str, int]]] = [[] for _ in range(reducers)]
    emitted = 0
    if use_combiner:
        # Combiner = reduce wykonany lokalnie na wyjściu jednego mapa, PRZED zapisem na dysk.
        local = Counter()
        for record in table.to_pylist():
            for key, value in map_fn(record):
                local[key] += value
                emitted += 1
        pairs = local.items()
    else:
        pairs = (kv for record in table.to_pylist() for kv in map_fn(record))
    written = 0
    spilled = 0
    for key, value in pairs:
        spilled += 1
        if not use_combiner:
            emitted += 1
        buffers[partition(key, reducers)].append((key, value))
    # Sort + spill: jeden posortowany plik na każdy reducer.
    for r, buf in enumerate(buffers):
        buf.sort()
        path = workdir / f"map-{task_id:04d}-r{r:02d}.tsv"
        with path.open("w") as f:
            for key, value in buf:
                f.write(f"{key}\t{value}\n")
        written += path.stat().st_size
    return {
        "emitted": emitted,
        "spilled": spilled,
        "records": table.num_rows,
        "spill_bytes": written,
        "seconds": time.perf_counter() - t0,
    }


def read_spill(path: Path) -> Iterator[tuple[str, int]]:
    with path.open() as f:
        for line in f:
            key, value = line.rstrip("\n").split("\t")
            yield key, int(value)


def reduce_task(args: tuple[int, Path]) -> dict:
    r, workdir = args
    t0 = time.perf_counter()
    # Shuffle: pobieramy pliki od wszystkich mapów (w Hadoopie — przez HTTP z innych maszyn).
    files = sorted(workdir.glob(f"map-*-r{r:02d}.tsv"))
    fetched = sum(f.stat().st_size for f in files)
    # Merge: scalanie posortowanych strumieni, potem grupowanie po kluczu.
    merged = heapq.merge(*(read_spill(f) for f in files))
    out = [reduce_fn(key, (v for _, v in group)) for key, group in groupby(merged, key=lambda kv: kv[0])]
    return {
        "reducer": r,
        "files": len(files),
        "fetched_bytes": fetched,
        "keys": len(out),
        "result": out,
        "seconds": time.perf_counter() - t0,
    }


def run_job(splits: list[Path], reducers: int, workers: int, use_combiner: bool) -> tuple[dict, list]:
    workdir = Path(tempfile.mkdtemp(prefix="mr-"))
    try:
        t0 = time.perf_counter()
        with Pool(workers) as pool:
            maps = pool.map(map_task, [(i, s, workdir, reducers, use_combiner) for i, s in enumerate(splits)])
            t_map = time.perf_counter() - t0
            reds = pool.map(reduce_task, [(r, workdir) for r in range(reducers)])
        total = time.perf_counter() - t0
    finally:
        shutil.rmtree(workdir)
    stats = {
        "records": sum(m["records"] for m in maps),
        "emitted": sum(m["emitted"] for m in maps),
        "spilled": sum(m["spilled"] for m in maps),
        "spill_files": len(maps) * reducers,
        "shuffle_bytes": sum(m["spill_bytes"] for m in maps),
        "map_s": t_map,
        "total_s": total,
        "reducer_keys": [r["keys"] for r in reds],
        "reducer_bytes": [r["fetched_bytes"] for r in reds],
    }
    result = sorted(kv for r in reds for kv in r["result"])
    return stats, result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--reducers", type=int, default=4)
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()

    splits = sorted((DATA / "clickstream").glob("dt=*/*.parquet"))
    print(f"Wejście: {len(splits)} splitów (plików), reducery: {args.reducers}, procesy: {args.workers}\n")

    runs = {}
    for use_combiner in (False, True):
        stats, result = run_job(splits, args.reducers, args.workers, use_combiner)
        runs[use_combiner] = (stats, result)

    # Weryfikacja wyniku niezależnym silnikiem (DuckDB).
    expected = duckdb.sql(f"""
        SELECT coalesce(nullif(event_type, ''), '<pusty>') || '|' || country AS key, count(*) AS n
        FROM read_parquet('{DATA}/clickstream/*/*.parquet') GROUP BY 1 ORDER BY 1
    """).fetchall()
    for _stats, result in runs.values():
        assert dict(result) == dict(expected), "wynik MapReduce różni się od DuckDB!"

    print(f"{'Metryka':40s} {'bez combinera':>16s} {'z combinerem':>16s}")
    a, b = runs[False][0], runs[True][0]
    rows = [
        ("rekordy wejściowe", f"{a['records']:,}", f"{b['records']:,}"),
        ("pary emitowane przez map", f"{a['emitted']:,}", f"{b['emitted']:,}"),
        ("pary zapisane na dysk (spill)", f"{a['spilled']:,}", f"{b['spilled']:,}"),
        ("pliki pośrednie (map × reduce)", f"{a['spill_files']:,}", f"{b['spill_files']:,}"),
        ("bajty przez shuffle", f"{a['shuffle_bytes'] / 1e6:,.1f} MB", f"{b['shuffle_bytes'] / 1e3:,.1f} KB"),
        ("czas fazy map", f"{a['map_s']:.2f} s", f"{b['map_s']:.2f} s"),
        ("czas całkowity", f"{a['total_s']:.2f} s", f"{b['total_s']:.2f} s"),
    ]
    for name, x, y in rows:
        print(f"{name:40s} {x:>16s} {y:>16s}")
    print(f"\nRedukcja shuffle dzięki combinerowi: ×{a['shuffle_bytes'] / b['shuffle_bytes']:,.0f}")
    print(f"Klucze per reducer: {a['reducer_keys']} (rozkład zależy od hash(klucz) mod R)")
    mb = [f"{x / 1e6:.1f}" for x in a["reducer_bytes"]]
    print(f"MB pobrane przez reducery bez combinera: {mb}  ← skew: klucze mają różną liczność")

    print("\nTop 5 kluczy (event_type|country):")
    for key, n in sorted(runs[True][1], key=lambda kv: -kv[1])[:5]:
        print(f"  {key:30s} {n:>10,}")
    print(f"\nWynik zgodny z DuckDB: {len(expected)} kluczy ✓")


if __name__ == "__main__":
    main()
