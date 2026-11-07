"""Minimalny „table format” na plikach: log transakcji + atomowy commit (put-if-absent).

Lekcja 01.05 (era lakehouse). Pokazuje, dlaczego sam katalog plików Parquet nie jest tabelą
i co dokładnie dodają Delta Lake / Iceberg / Hudi:

  1. naiwny „katalog plików”: czytelnik widzi stan pośredni, awaria zostawia śmieci;
  2. tabela z logiem: pliki danych są niewidoczne, dopóki commit nie trafi do logu;
  3. optimistic concurrency: dwa procesy dopisują równolegle, konflikty → retry;
  4. konflikt logiczny: dwa nadpisania tej samej partycji → jeden musi przegrać;
  5. time travel: odczyt dowolnej wcześniejszej wersji.

Atomowość commitu zapewnia os.link (put-if-absent): plik wersji N tworzy tylko jeden writer. W chmurze to samo daje put-if-absent: GCS `ifGenerationMatch=0`, S3 `If-None-Match: *`.

Uruchomienie: cd examples && uv run python 06_toy_table_format.py
"""

from __future__ import annotations

import json
import multiprocessing as mp
import os
import shutil
import tempfile
import time
import uuid
from pathlib import Path

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

DATA = Path(os.environ.get("NOVACART_DATA", Path(__file__).resolve().parents[3] / "data" / "s"))


class CommitConflict(Exception):
    """Ktoś inny zmienił pliki, które ten commit chciał usunąć (konflikt logiczny)."""


class ToyTable:
    """Tabela = katalog `data/` z plikami Parquet + katalog `_log/` z commitami JSON."""

    def __init__(self, root: Path):
        self.root = root
        self.log = root / "_log"
        (root / "data").mkdir(parents=True, exist_ok=True)
        self.log.mkdir(exist_ok=True)

    # --- odczyt -------------------------------------------------------------------------------
    def latest_version(self) -> int:
        versions = [int(p.stem) for p in self.log.glob("*.json")]
        return max(versions, default=-1)

    def snapshot(self, version: int | None = None) -> dict[str, dict]:
        """Odtwarza listę aktywnych plików, „odgrywając” log od wersji 0 do `version`."""
        version = self.latest_version() if version is None else version
        files: dict[str, dict] = {}
        for v in range(version + 1):
            for action in json.loads((self.log / f"{v:020d}.json").read_text())["actions"]:
                if "add" in action:
                    files[action["add"]["path"]] = action["add"]
                else:
                    files.pop(action["remove"]["path"], None)
        return files

    def read(self, version: int | None = None) -> pa.Table:
        files = self.snapshot(version)
        tables = [pq.read_table(self.root / "data" / p) for p in sorted(files)]
        return pa.concat_tables(tables) if tables else pa.table({})

    # --- zapis --------------------------------------------------------------------------------
    def _write_file(self, table: pa.Table, partition: str) -> dict:
        name = f"{partition}-{uuid.uuid4().hex[:12]}.parquet"
        pq.write_table(table, self.root / "data" / name)
        return {"path": name, "partition": partition, "rows": table.num_rows}

    def commit(self, adds: list[dict], removes: list[str], read_version: int, op: str) -> tuple[int, int]:
        """Próbuje zapisać commit jako wersję read_version+1; przy kolizji ponawia.

        Zwraca (wersja, liczba ponowień). Rzuca CommitConflict, gdy pliki do usunięcia
        zniknęły w międzyczasie (ktoś inny już je nadpisał).
        """
        actions = [{"remove": {"path": p}} for p in removes] + [{"add": a} for a in adds]
        payload = json.dumps({"op": op, "pid": os.getpid(), "actions": actions}).encode()
        attempt, version = 0, read_version + 1
        while True:
            # Walidacja: czy wszystkie pliki, które usuwamy, nadal są aktywne w wersji version-1?
            if removes and not set(removes) <= set(self.snapshot(version - 1)):
                raise CommitConflict(f"{op}: pliki do usunięcia zmieniły się przed wersją {version}")
            # Put-if-absent: najpierw pełna treść w pliku tymczasowym, potem os.link, który
            # (jak O_EXCL) kończy się błędem, gdy wersja już istnieje. Czytelnik nigdy nie
            # zobaczy pół-zapisanego commitu.
            tmp = self.log / f".tmp-{uuid.uuid4().hex}"
            tmp.write_bytes(payload)
            try:
                os.link(tmp, self.log / f"{version:020d}.json")
            except FileExistsError:  # ktoś był szybszy → sprawdź jego zmiany i spróbuj kolejny numer
                attempt, version = attempt + 1, version + 1
                continue
            finally:
                tmp.unlink()
            return version, attempt

    def append(self, table: pa.Table, partition: str) -> tuple[int, int]:
        read_version = self.latest_version()
        return self.commit([self._write_file(table, partition)], [], read_version, "append")

    def overwrite_partition(self, table: pa.Table, partition: str, pause: float = 0.0) -> tuple[int, int]:
        read_version = self.latest_version()
        old = [p for p, a in self.snapshot(read_version).items() if a["partition"] == partition]
        new = [self._write_file(table, partition)]  # pliki niewidoczne, dopóki nie ma commitu
        time.sleep(pause)
        return self.commit(new, old, read_version, f"overwrite {partition}")


# --- scenariusze ------------------------------------------------------------------------------
def load_day(day: str) -> pa.Table:
    t = pq.read_table(DATA / "orders" / f"dt={day}")
    return t.select(["order_id", "customer_id", "status", "total_amount", "created_at"])


def naive_directory(tmp: Path, day: pa.Table) -> None:
    print("\n[1] Naiwny „katalog plików” — przepisanie partycji dt=2025-11-28 trzema plikami")
    root = tmp / "naive" / "dt=2025-11-28"
    root.mkdir(parents=True)
    pq.write_table(day, root / "part-0.parquet")

    def reader() -> int:  # „czytelnik” listuje katalog i czyta wszystko, co znajdzie
        return pq.read_table(root).num_rows if any(root.iterdir()) else 0

    print(f"    stan początkowy:                   czytelnik widzi {reader():>5} wierszy")
    (root / "part-0.parquet").unlink()
    print(f"    po usunięciu starego pliku:        czytelnik widzi {reader():>5} wierszy")
    chunk = -(-day.num_rows // 3)
    for i in range(3):
        pq.write_table(day.slice(i * chunk, chunk), root / f"part-new-{i}.parquet")
        if i == 1:
            print(
                f"    po zapisie 2 z 3 nowych plików:    czytelnik widzi {reader():>5} wierszy"
                "   ← AWARIA tutaj = trwale zła tabela"
            )
    print(f"    po zakończeniu:                    czytelnik widzi {reader():>5} wierszy")


def logged_table(tmp: Path, days: dict[str, pa.Table]) -> ToyTable:
    print("\n[2] Tabela z logiem — te same operacje")
    t = ToyTable(tmp / "orders_tbl")
    for d, tbl in days.items():
        t.append(tbl, f"dt={d}")
    bf = days["2025-11-28"]
    v0 = t.latest_version()
    print(f"    wersja {v0}: {t.read().num_rows} wierszy, {len(t.snapshot())} aktywnych plików")
    # „Awaria” w połowie: plik danych zapisany, commit nie powstał.
    t._write_file(bf.slice(0, 100), "dt=2025-11-28")
    on_disk = len(list((t.root / "data").glob("*.parquet")))
    print(
        f"    po awarii writera (plik bez commitu): czytelnik widzi {t.read().num_rows} wierszy;"
        f" na dysku {on_disk} plików, aktywnych {len(t.snapshot())} (sierota czeka na VACUUM)"
    )
    fixed = bf.filter(pc.not_equal(bf["status"], "cancelled"))
    v, _ = t.overwrite_partition(fixed, "dt=2025-11-28")
    print(
        f"    wersja {v}: overwrite dt=2025-11-28 bez anulowanych → {t.read().num_rows} wierszy"
        " (stara i nowa wersja nigdy nie są widoczne jednocześnie)"
    )
    return t


def _appender(root: str, day: str, n: int, q: mp.Queue) -> None:
    t, tbl, retries = ToyTable(Path(root)), load_day(day), 0
    for i in range(n):
        _, r = t.append(tbl.slice(i * 10, 10), f"dt={day}")
        retries += r
    q.put((os.getpid(), retries))


def concurrent_appends(t: ToyTable, n: int = 40) -> None:
    print(f"\n[3] Dwa procesy dopisują równolegle po {n} małych commitów (optimistic concurrency)")
    before, rows_before = t.latest_version(), t.read().num_rows
    q: mp.Queue = mp.Queue()
    procs = [mp.Process(target=_appender, args=(str(t.root), d, n, q)) for d in ("2025-12-01", "2025-12-02")]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    retries = sum(q.get()[1] for _ in procs)
    after = t.latest_version()
    print(
        f"    wersje {before} → {after} (+{after - before}), ponowień po kolizji: {retries}"
        " (liczba zależy od przeplotu procesów)"
    )
    print(
        f"    wiersze: {rows_before} → {t.read().num_rows} (+{t.read().num_rows - rows_before},"
        f" oczekiwano +{2 * n * 10}); żaden commit nie zginął"
    )


def _overwriter(root: str, label: str, keep_status: str, q: mp.Queue) -> None:
    t = ToyTable(Path(root))
    tbl = load_day("2025-11-28")
    tbl = tbl.filter(pc.equal(tbl["status"], keep_status))
    try:
        v, _ = t.overwrite_partition(tbl, "dt=2025-11-28", pause=0.3)
        q.put((label, f"commit OK → wersja {v}"))
    except CommitConflict as e:
        q.put((label, f"ODRZUCONY: {e}"))


def conflicting_overwrites(t: ToyTable) -> None:
    print("\n[4] Dwa nadpisania tej samej partycji jednocześnie (konflikt logiczny)")
    q: mp.Queue = mp.Queue()
    procs = [
        mp.Process(target=_overwriter, args=(str(t.root), lab, st, q))
        for lab, st in (
            ("writer A (tylko delivered)", "delivered"),
            ("writer B (tylko returned)", "returned"),
        )
    ]
    for p in procs:
        p.start()
    for p in procs:
        p.join()
    for label, msg in sorted(q.get() for _ in procs):
        print(f"    {label:<28} {msg}")


def time_travel(t: ToyTable) -> None:
    print("\n[5] Time travel — liczba wierszy partycji dt=2025-11-28 w kolejnych wersjach")
    print(f"    {'wersja':>6}  {'operacja':<28} {'wiersze dt=2025-11-28':>22}")
    skipped = 0
    for v in range(t.latest_version() + 1):
        op = json.loads((t.log / f"{v:020d}.json").read_text())["op"]
        if op == "append" and v > 2:  # commity z kroku [3] nie dotyczą tej partycji
            skipped += 1
            continue
        if skipped:
            print(f"    {'…':>6}  {f'{skipped} × append (krok 3)':<28} {'bez zmian':>22}")
            skipped = 0
        files = t.snapshot(v)
        rows = sum(a["rows"] for a in files.values() if a["partition"] == "dt=2025-11-28")
        print(f"    {v:>6}  {op:<28} {rows:>22}")


def main() -> None:
    tmp = Path(tempfile.mkdtemp(prefix="toy_table_"))
    try:
        days = {d: load_day(d) for d in ("2025-11-27", "2025-11-28", "2025-11-29")}
        naive_directory(tmp, days["2025-11-28"])
        t = logged_table(tmp, days)
        concurrent_appends(t)
        conflicting_overwrites(t)
        time_travel(t)
        log_bytes = sum(p.stat().st_size for p in t.log.glob("*.json"))
        print(
            f"\nLog: {t.latest_version() + 1} commitów, {log_bytes / 1024:.1f} KiB;"
            f" pliki danych: {len(list((t.root / 'data').glob('*.parquet')))}"
        )
        # Antywzorzec: czytanie katalogu tabeli „zwykłym” czytnikiem Parquet, z pominięciem logu.
        raw = pq.read_table(t.root / "data").num_rows
        print(
            f"Czytnik ignorujący log widzi {raw} wierszy zamiast {t.read().num_rows}"
            " (usunięte wersje, sieroty po awarii i dane sprzed nadpisań)"
        )
    finally:
        shutil.rmtree(tmp)


if __name__ == "__main__":
    main()
