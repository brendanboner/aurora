# Aurora Production Evaluation Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a one-shot evaluation report on the Aurora production system, using existing telemetry plus a small LLM-as-judge supplement, delivered as a markdown report + a reproducible Jupyter notebook.

**Architecture:** A small Python package `eval/aurora_eval/` exports prod data (Postgres `oracle_query_history`, Neo4j corpus snapshot, Prometheus scrape, Loki tail) to local parquet/JSON. A separate runner stratified-samples ~100 queries and scores them with an LLM-as-judge. A notebook reads the snapshot + judgements and renders all charts/tables. A final markdown report pulls everything together with exec summary + technical appendices.

**Tech Stack:** Python 3.12, pandas, pyarrow, psycopg2-binary, neo4j (driver), requests (Prometheus/Loki HTTP APIs), anthropic SDK (LLM judge), matplotlib + seaborn (charts), pytest, jupyter.

**Spec:** `docs/superpowers/specs/2026-06-02-aurora-production-evaluation-report-design.md`

---

## File Structure

| Path | Purpose |
|---|---|
| `eval/aurora_eval/__init__.py` | Package marker |
| `eval/aurora_eval/config.py` | Env-driven config: DB URLs, paths, report window, judge model |
| `eval/aurora_eval/scout.py` | Quick prod scan: row counts, date range, feedback volume — informs window choice |
| `eval/aurora_eval/dump_postgres.py` | Dump `oracle_query_history`, `chat_messages`, `user_feedback` to parquet |
| `eval/aurora_eval/dump_neo4j.py` | Read-only Cypher batch → JSON snapshot of node/edge counts |
| `eval/aurora_eval/dump_prometheus.py` | Snapshot of `/metrics` from oracle service |
| `eval/aurora_eval/dump_loki.py` | LogQL tail for digester + LLM logs over the window |
| `eval/aurora_eval/loaders.py` | Read parquet/JSON snapshots into DataFrames |
| `eval/aurora_eval/sampling.py` | Stratified sampling for judge input |
| `eval/aurora_eval/judge.py` | Build judge prompt, call Anthropic API, parse response |
| `eval/aurora_eval/judge_runner.py` | Iterate sample, call `judge`, save results to parquet |
| `eval/aurora_eval/charts.py` | Helpers for the recurring chart types |
| `eval/aurora_eval/cli.py` | Argparse entry points: `scout`, `dump`, `judge` |
| `eval/aurora_eval/analyze.ipynb` | Notebook producing all report charts/tables |
| `eval/tests/test_config.py` | Unit tests for config |
| `eval/tests/test_dump_postgres.py` | Unit tests for Postgres dump SQL + transforms |
| `eval/tests/test_dump_neo4j.py` | Unit tests for Cypher batch |
| `eval/tests/test_loaders.py` | Unit tests for snapshot loaders |
| `eval/tests/test_sampling.py` | Unit tests for stratified sampling |
| `eval/tests/test_judge.py` | Unit tests for prompt build + response parsing |
| `eval/tests/fixtures/` | Fixture parquets, sample judge responses |
| `eval/data/` | Output dir for dumps + judgements (gitignored) |
| `eval/charts/` | Output dir for rendered SVG/PNG (gitignored) |
| `eval/requirements.txt` | Pinned deps |
| `eval/pytest.ini` | pytest config |
| `eval/README.md` | How to scout/dump/judge/analyze |
| `eval/.gitignore` | Ignores `data/`, `charts/`, `.venv/`, `__pycache__/` |
| `docs/aurora-production-evaluation-2026-06-02.md` | Final report |

Output dirs `eval/data/` and `eval/charts/` are gitignored — snapshot data may contain user content and must not be committed.

---

## Task 1: Package skeleton + dependencies

**Files:**
- Create: `eval/requirements.txt`
- Create: `eval/pytest.ini`
- Create: `eval/.gitignore`
- Create: `eval/aurora_eval/__init__.py`
- Create: `eval/tests/__init__.py`
- Create: `eval/tests/test_smoke.py`
- Create: `eval/README.md`

- [ ] **Step 1: Create directory layout**

```bash
mkdir -p eval/aurora_eval eval/tests/fixtures eval/data eval/charts
```

- [ ] **Step 2: Write `eval/requirements.txt`**

```
pandas==2.2.*
pyarrow==16.*
psycopg2-binary==2.9.*
neo4j==5.*
requests==2.32.*
anthropic==0.39.*
matplotlib==3.9.*
seaborn==0.13.*
jupyter==1.*
pytest==8.*
pytest-mock==3.*
python-dateutil==2.9.*
tabulate==0.9.*
```

- [ ] **Step 3: Write `eval/pytest.ini`**

```ini
[pytest]
testpaths = tests
python_files = test_*.py
addopts = -ra -q
```

- [ ] **Step 4: Write `eval/.gitignore`**

```
.venv/
__pycache__/
*.pyc
data/
charts/
.ipynb_checkpoints/
```

- [ ] **Step 5: Write `eval/aurora_eval/__init__.py`**

```python
"""Aurora production evaluation toolkit."""

__version__ = "0.1.0"
```

- [ ] **Step 6: Write `eval/tests/__init__.py`**

Empty file.

- [ ] **Step 7: Write a smoke test**

`eval/tests/test_smoke.py`:

```python
def test_package_importable():
    import aurora_eval

    assert aurora_eval.__version__ == "0.1.0"
```

- [ ] **Step 8: Create a venv and install deps**

```bash
cd eval
python3.12 -m venv .venv
.venv/bin/pip install --upgrade pip
.venv/bin/pip install -r requirements.txt
```

Expected: install completes without errors.

- [ ] **Step 9: Run the smoke test**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_smoke.py -v
```

Expected: 1 passed.

- [ ] **Step 10: Write `eval/README.md`**

```markdown
# Aurora Evaluation Toolkit

Reproducible analysis package for the production evaluation report.

## Setup

```bash
cd eval
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Usage

```bash
# 1. Scout — confirm prod row counts and date range, choose window
PYTHONPATH=. .venv/bin/python -m aurora_eval.cli scout

# 2. Dump — snapshot prod data to ./data/
PYTHONPATH=. .venv/bin/python -m aurora_eval.cli dump --since 2026-01-01

# 3. Judge — run LLM-as-judge on a stratified sample
PYTHONPATH=. .venv/bin/python -m aurora_eval.cli judge --sample-size 100

# 4. Analyze — open the notebook
.venv/bin/jupyter notebook aurora_eval/analyze.ipynb
```

## Re-running against a fresh dump

`data/` and `charts/` are gitignored. Delete them and re-run the scout/dump/judge sequence.
```

- [ ] **Step 11: Commit**

```bash
git add eval/
git commit -m "feat(eval): package skeleton for production evaluation toolkit"
```

---

## Task 2: Config module

**Files:**
- Create: `eval/aurora_eval/config.py`
- Create: `eval/tests/test_config.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_config.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pytest

from aurora_eval import config


def test_config_reads_from_env(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_POSTGRES_URL", "postgresql://user:pw@localhost:5432/aurora")
    monkeypatch.setenv("EVAL_NEO4J_URL", "bolt://localhost:7687")
    monkeypatch.setenv("EVAL_NEO4J_USER", "neo4j")
    monkeypatch.setenv("EVAL_NEO4J_PASSWORD", "secret")
    monkeypatch.setenv("EVAL_PROMETHEUS_URL", "http://localhost:9090")
    monkeypatch.setenv("EVAL_LOKI_URL", "http://localhost:3100")
    monkeypatch.setenv("EVAL_ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("EVAL_DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("EVAL_CHARTS_DIR", str(tmp_path / "charts"))
    monkeypatch.setenv("EVAL_SINCE", "2026-01-01T00:00:00+00:00")
    monkeypatch.setenv("EVAL_UNTIL", "2026-06-02T00:00:00+00:00")

    cfg = config.load()

    assert cfg.postgres_url == "postgresql://user:pw@localhost:5432/aurora"
    assert cfg.neo4j_url == "bolt://localhost:7687"
    assert cfg.neo4j_user == "neo4j"
    assert cfg.neo4j_password == "secret"
    assert cfg.prometheus_url == "http://localhost:9090"
    assert cfg.loki_url == "http://localhost:3100"
    assert cfg.anthropic_api_key == "sk-ant-test"
    assert cfg.data_dir == tmp_path / "data"
    assert cfg.charts_dir == tmp_path / "charts"
    assert cfg.since == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert cfg.until == datetime(2026, 6, 2, tzinfo=timezone.utc)
    assert cfg.judge_model == "claude-opus-4-7"  # default
    assert cfg.judge_sample_size == 100  # default


def test_config_missing_required_var_raises(monkeypatch):
    monkeypatch.delenv("EVAL_POSTGRES_URL", raising=False)
    with pytest.raises(config.ConfigError, match="EVAL_POSTGRES_URL"):
        config.load()


def test_config_ensure_dirs_creates_them(monkeypatch, tmp_path):
    monkeypatch.setenv("EVAL_POSTGRES_URL", "postgresql://x")
    monkeypatch.setenv("EVAL_NEO4J_URL", "bolt://x")
    monkeypatch.setenv("EVAL_NEO4J_USER", "x")
    monkeypatch.setenv("EVAL_NEO4J_PASSWORD", "x")
    monkeypatch.setenv("EVAL_PROMETHEUS_URL", "http://x")
    monkeypatch.setenv("EVAL_LOKI_URL", "http://x")
    monkeypatch.setenv("EVAL_ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("EVAL_DATA_DIR", str(tmp_path / "d"))
    monkeypatch.setenv("EVAL_CHARTS_DIR", str(tmp_path / "c"))
    monkeypatch.setenv("EVAL_SINCE", "2026-01-01T00:00:00+00:00")
    monkeypatch.setenv("EVAL_UNTIL", "2026-06-02T00:00:00+00:00")

    cfg = config.load()
    cfg.ensure_dirs()

    assert (tmp_path / "d").is_dir()
    assert (tmp_path / "c").is_dir()
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_config.py -v
```

Expected: 3 failed (`aurora_eval.config` does not exist).

- [ ] **Step 3: Write `eval/aurora_eval/config.py`**

```python
"""Environment-driven configuration for the evaluation toolkit."""
from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


class ConfigError(Exception):
    pass


_REQUIRED = [
    "EVAL_POSTGRES_URL",
    "EVAL_NEO4J_URL",
    "EVAL_NEO4J_USER",
    "EVAL_NEO4J_PASSWORD",
    "EVAL_PROMETHEUS_URL",
    "EVAL_LOKI_URL",
    "EVAL_ANTHROPIC_API_KEY",
    "EVAL_DATA_DIR",
    "EVAL_CHARTS_DIR",
    "EVAL_SINCE",
    "EVAL_UNTIL",
]


@dataclass(frozen=True)
class Config:
    postgres_url: str
    neo4j_url: str
    neo4j_user: str
    neo4j_password: str
    prometheus_url: str
    loki_url: str
    anthropic_api_key: str
    data_dir: Path
    charts_dir: Path
    since: datetime
    until: datetime
    judge_model: str = "claude-opus-4-7"
    judge_sample_size: int = 100

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.charts_dir.mkdir(parents=True, exist_ok=True)


def load() -> Config:
    missing = [k for k in _REQUIRED if not os.environ.get(k)]
    if missing:
        raise ConfigError(f"Missing required env vars: {', '.join(missing)}")

    return Config(
        postgres_url=os.environ["EVAL_POSTGRES_URL"],
        neo4j_url=os.environ["EVAL_NEO4J_URL"],
        neo4j_user=os.environ["EVAL_NEO4J_USER"],
        neo4j_password=os.environ["EVAL_NEO4J_PASSWORD"],
        prometheus_url=os.environ["EVAL_PROMETHEUS_URL"],
        loki_url=os.environ["EVAL_LOKI_URL"],
        anthropic_api_key=os.environ["EVAL_ANTHROPIC_API_KEY"],
        data_dir=Path(os.environ["EVAL_DATA_DIR"]),
        charts_dir=Path(os.environ["EVAL_CHARTS_DIR"]),
        since=datetime.fromisoformat(os.environ["EVAL_SINCE"]),
        until=datetime.fromisoformat(os.environ["EVAL_UNTIL"]),
        judge_model=os.environ.get("EVAL_JUDGE_MODEL", "claude-opus-4-7"),
        judge_sample_size=int(os.environ.get("EVAL_JUDGE_SAMPLE_SIZE", "100")),
    )
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_config.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/config.py eval/tests/test_config.py
git commit -m "feat(eval): env-driven config module"
```

---

## Task 3: Postgres dump module

**Files:**
- Create: `eval/aurora_eval/dump_postgres.py`
- Create: `eval/tests/test_dump_postgres.py`
- Create: `eval/tests/conftest.py`

- [ ] **Step 1: Write `eval/tests/conftest.py` with a shared sqlite/in-memory fixture**

```python
"""Shared pytest fixtures."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone, timedelta

import pytest


@pytest.fixture
def sqlite_with_query_history(tmp_path):
    """In-file sqlite seeded with a minimal oracle_query_history."""
    db = tmp_path / "test.db"
    conn = sqlite3.connect(db)
    conn.execute(
        """
        CREATE TABLE oracle_query_history (
            query_id TEXT PRIMARY KEY,
            created_at TEXT,
            user_id TEXT,
            question TEXT,
            mode TEXT,
            answer TEXT,
            citations TEXT,
            documents TEXT,
            intent TEXT,
            confidence_score REAL,
            documents_count INTEGER,
            processing_time_ms INTEGER,
            llm_tokens_used INTEGER,
            cache_hit INTEGER,
            strategies_used TEXT,
            feedback_type TEXT,
            feedback_comment TEXT,
            error INTEGER,
            error_message TEXT,
            request_options TEXT
        )
        """
    )
    base = datetime(2026, 5, 1, 12, 0, 0, tzinfo=timezone.utc)
    rows = []
    for i in range(50):
        rows.append(
            (
                f"q{i}",
                (base + timedelta(hours=i)).isoformat(),
                f"u{i % 5}",
                f"question {i}",
                "fast" if i % 2 == 0 else "baseline",
                f"answer {i}",
                "[]",
                "[]",
                "FACTUAL" if i % 3 == 0 else "ANALYTICAL",
                0.5 + (i % 5) * 0.1,
                3,
                100 + i * 10,
                500 + i * 50,
                1 if i % 4 == 0 else 0,
                '["keyword", "vector"]',
                "positive" if i % 7 == 0 else None,
                None,
                0,
                None,
                '{"pipeline": "fast", "cache": {"overall_hit": false}}',
            )
        )
    conn.executemany(
        "INSERT INTO oracle_query_history VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        rows,
    )
    conn.commit()
    conn.close()
    return f"sqlite:///{db}"
```

- [ ] **Step 2: Write the failing test**

`eval/tests/test_dump_postgres.py`:

```python
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

from aurora_eval import dump_postgres


def test_query_history_sql_uses_window():
    sql, params = dump_postgres.query_history_sql(
        since=datetime(2026, 1, 1, tzinfo=timezone.utc),
        until=datetime(2026, 6, 1, tzinfo=timezone.utc),
    )
    assert "FROM oracle_query_history" in sql
    assert "created_at >= %s" in sql
    assert "created_at <  %s" in sql
    assert params == (
        datetime(2026, 1, 1, tzinfo=timezone.utc),
        datetime(2026, 6, 1, tzinfo=timezone.utc),
    )


def test_dump_to_parquet_writes_file(tmp_path, sqlite_with_query_history):
    out = tmp_path / "query_history.parquet"
    n = dump_postgres.dump_query_history_sqlite(
        sqlite_url=sqlite_with_query_history,
        out_path=out,
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 3, tzinfo=timezone.utc),
    )
    assert out.exists()
    df = pd.read_parquet(out)
    assert n == len(df)
    assert n > 0
    assert "query_id" in df.columns
    assert "question" in df.columns
    assert "answer" in df.columns


def test_dump_normalizes_json_columns(tmp_path, sqlite_with_query_history):
    out = tmp_path / "query_history.parquet"
    dump_postgres.dump_query_history_sqlite(
        sqlite_url=sqlite_with_query_history,
        out_path=out,
        since=datetime(2026, 5, 1, tzinfo=timezone.utc),
        until=datetime(2026, 5, 3, tzinfo=timezone.utc),
    )
    df = pd.read_parquet(out)
    # strategies_used and request_options should be parsed dicts/lists, not raw strings
    first = df.iloc[0]
    assert isinstance(first["strategies_used"], (list, type(None)))
    assert isinstance(first["request_options"], (dict, type(None)))
```

- [ ] **Step 3: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_dump_postgres.py -v
```

Expected: 3 failed (module not found).

- [ ] **Step 4: Write `eval/aurora_eval/dump_postgres.py`**

```python
"""Snapshot Postgres tables to local parquet files."""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Iterable, Tuple

import pandas as pd

QUERY_HISTORY_COLS = [
    "query_id", "created_at", "user_id", "question", "mode",
    "answer", "citations", "documents", "intent", "confidence_score",
    "documents_count", "processing_time_ms", "llm_tokens_used", "cache_hit",
    "strategies_used", "feedback_type", "feedback_comment",
    "error", "error_message", "request_options",
]

CHAT_MESSAGES_COLS = [
    "id", "conversation_id", "user_id", "role", "content", "metadata", "created_at",
]

USER_FEEDBACK_COLS = [
    "id", "user_id", "feedback_text", "category", "status",
    "priority", "submitted_at", "updated_at",
]

_JSON_COLUMNS = {
    "oracle_query_history": ["citations", "documents", "strategies_used", "request_options"],
    "chat_messages": ["metadata"],
}


def query_history_sql(since: datetime, until: datetime) -> Tuple[str, tuple]:
    cols = ", ".join(QUERY_HISTORY_COLS)
    sql = (
        f"SELECT {cols} FROM oracle_query_history "
        f"WHERE created_at >= %s AND created_at <  %s "
        f"ORDER BY created_at"
    )
    return sql, (since, until)


def chat_messages_sql(since: datetime, until: datetime) -> Tuple[str, tuple]:
    cols = ", ".join(CHAT_MESSAGES_COLS)
    sql = (
        f"SELECT {cols} FROM chat_messages "
        f"WHERE created_at >= %s AND created_at <  %s "
        f"ORDER BY created_at"
    )
    return sql, (since, until)


def user_feedback_sql(since: datetime, until: datetime) -> Tuple[str, tuple]:
    cols = ", ".join(USER_FEEDBACK_COLS)
    sql = (
        f"SELECT {cols} FROM user_feedback "
        f"WHERE submitted_at >= %s AND submitted_at <  %s "
        f"ORDER BY submitted_at"
    )
    return sql, (since, until)


def _parse_json_columns(df: pd.DataFrame, columns: Iterable[str]) -> pd.DataFrame:
    for col in columns:
        if col in df.columns:
            df[col] = df[col].apply(lambda v: json.loads(v) if isinstance(v, str) and v else None)
    return df


def dump_query_history(
    *, postgres_url: str, out_path: Path, since: datetime, until: datetime
) -> int:
    """Production path — connects via psycopg2."""
    import psycopg2  # local import to keep tests dependency-light

    sql, params = query_history_sql(since, until)
    with psycopg2.connect(postgres_url) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    df = _parse_json_columns(df, _JSON_COLUMNS["oracle_query_history"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return len(df)


def dump_query_history_sqlite(
    *, sqlite_url: str, out_path: Path, since: datetime, until: datetime
) -> int:
    """Test path — sqlite uses ? placeholders and ISO-string timestamps."""
    assert sqlite_url.startswith("sqlite:///")
    db_path = sqlite_url[len("sqlite:///"):]
    sql, _ = query_history_sql(since, until)
    sql = sql.replace("%s", "?")
    conn = sqlite3.connect(db_path)
    try:
        df = pd.read_sql_query(sql, conn, params=(since.isoformat(), until.isoformat()))
    finally:
        conn.close()
    df = _parse_json_columns(df, _JSON_COLUMNS["oracle_query_history"])
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return len(df)


def dump_all(*, postgres_url: str, out_dir: Path, since: datetime, until: datetime) -> dict:
    """Production: dump all relevant tables. Returns row counts per table."""
    out_dir.mkdir(parents=True, exist_ok=True)
    counts = {}
    counts["oracle_query_history"] = dump_query_history(
        postgres_url=postgres_url,
        out_path=out_dir / "query_history.parquet",
        since=since,
        until=until,
    )
    counts["chat_messages"] = _dump_with_sql(
        postgres_url, out_dir / "chat_messages.parquet",
        *chat_messages_sql(since, until),
        json_columns=_JSON_COLUMNS["chat_messages"],
    )
    counts["user_feedback"] = _dump_with_sql(
        postgres_url, out_dir / "user_feedback.parquet",
        *user_feedback_sql(since, until),
        json_columns=[],
    )
    return counts


def _dump_with_sql(
    postgres_url: str, out_path: Path, sql: str, params: tuple, *, json_columns: list
) -> int:
    import psycopg2

    with psycopg2.connect(postgres_url) as conn:
        df = pd.read_sql_query(sql, conn, params=params)
    df = _parse_json_columns(df, json_columns)
    df.to_parquet(out_path, index=False)
    return len(df)
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_dump_postgres.py -v
```

Expected: 3 passed.

- [ ] **Step 6: Commit**

```bash
git add eval/aurora_eval/dump_postgres.py eval/tests/test_dump_postgres.py eval/tests/conftest.py
git commit -m "feat(eval): Postgres dump with sqlite test path"
```

---

## Task 4: Neo4j dump module

**Files:**
- Create: `eval/aurora_eval/dump_neo4j.py`
- Create: `eval/tests/test_dump_neo4j.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_dump_neo4j.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock

from aurora_eval import dump_neo4j


def test_corpus_snapshot_queries_returns_all_keys():
    queries = dump_neo4j.CORPUS_SNAPSHOT_QUERIES
    assert set(queries.keys()) == {
        "total_nodes",
        "total_relationships",
        "nodes_by_label",
        "relationships_by_type",
        "datasources_count",
        "documents_count",
        "orphan_nodes_count",
        "topics_count",
        "people_count",
        "organizations_count",
        "events_count",
    }


def test_snapshot_runs_each_query_and_writes_json(tmp_path):
    fake_session = MagicMock()
    fake_session.run.side_effect = lambda q: _fake_records_for(q)
    fake_driver = MagicMock()
    fake_driver.session.return_value.__enter__.return_value = fake_session

    out = tmp_path / "neo4j_snapshot.json"
    snapshot = dump_neo4j.snapshot(driver=fake_driver, out_path=out)

    assert out.exists()
    written = json.loads(out.read_text())
    assert written["total_nodes"] == 42
    assert "captured_at" in written
    assert written == snapshot


def _fake_records_for(query):
    """Mimic neo4j Result.data() shape for our queries."""
    if "COUNT(n)" in query and "MATCH (n)" in query and "WHERE" not in query and "labels" not in query:
        return _result([{"value": 42}])
    if "COUNT(r)" in query:
        return _result([{"value": 17}])
    if "labels(n)" in query:
        return _result([
            {"label": "Document", "count": 10},
            {"label": "Topic", "count": 5},
        ])
    if "type(r)" in query:
        return _result([{"type": "MENTIONS", "count": 8}])
    if "DataSource" in query and "COUNT" in query:
        return _result([{"value": 3}])
    if "Document" in query and "COUNT" in query:
        return _result([{"value": 10}])
    if "orphan" in query.lower() or "NOT (n)--()" in query:
        return _result([{"value": 0}])
    if "Topic" in query and "COUNT" in query:
        return _result([{"value": 5}])
    if "Person" in query and "COUNT" in query:
        return _result([{"value": 2}])
    if "Organization" in query and "COUNT" in query:
        return _result([{"value": 1}])
    if "Event" in query and "COUNT" in query:
        return _result([{"value": 0}])
    return _result([])


def _result(records):
    mock = MagicMock()
    mock.data.return_value = records
    return mock
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_dump_neo4j.py -v
```

Expected: 2 failed (module not found).

- [ ] **Step 3: Write `eval/aurora_eval/dump_neo4j.py`**

```python
"""Read-only Neo4j corpus snapshot."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

CORPUS_SNAPSHOT_QUERIES = {
    "total_nodes": "MATCH (n) RETURN COUNT(n) AS value",
    "total_relationships": "MATCH ()-[r]->() RETURN COUNT(r) AS value",
    "nodes_by_label": (
        "MATCH (n) UNWIND labels(n) AS label "
        "RETURN label, COUNT(*) AS count ORDER BY count DESC"
    ),
    "relationships_by_type": (
        "MATCH ()-[r]->() RETURN type(r) AS type, COUNT(*) AS count ORDER BY count DESC"
    ),
    "datasources_count": "MATCH (n:DataSource) RETURN COUNT(n) AS value",
    "documents_count": "MATCH (n:Document) RETURN COUNT(n) AS value",
    "orphan_nodes_count": "MATCH (n) WHERE NOT (n)--() RETURN COUNT(n) AS value",
    "topics_count": "MATCH (n:Topic) RETURN COUNT(n) AS value",
    "people_count": "MATCH (n:Person) RETURN COUNT(n) AS value",
    "organizations_count": "MATCH (n:Organization) RETURN COUNT(n) AS value",
    "events_count": "MATCH (n:Event) RETURN COUNT(n) AS value",
}


def snapshot(*, driver, out_path: Path) -> dict[str, Any]:
    """Run every query in CORPUS_SNAPSHOT_QUERIES and write a single JSON file."""
    result: dict[str, Any] = {
        "captured_at": datetime.now(timezone.utc).isoformat(),
    }
    with driver.session() as session:
        for key, query in CORPUS_SNAPSHOT_QUERIES.items():
            rows = session.run(query).data()
            if not rows:
                result[key] = None
                continue
            if len(rows) == 1 and "value" in rows[0]:
                result[key] = rows[0]["value"]
            else:
                result[key] = rows

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(result, indent=2, default=str))
    return result


def open_driver(url: str, user: str, password: str):
    """Production helper; imported lazily so tests don't need the neo4j driver."""
    from neo4j import GraphDatabase

    return GraphDatabase.driver(url, auth=(user, password))
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_dump_neo4j.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/dump_neo4j.py eval/tests/test_dump_neo4j.py
git commit -m "feat(eval): Neo4j corpus snapshot"
```

---

## Task 5: Prometheus + Loki snapshot modules

**Files:**
- Create: `eval/aurora_eval/dump_prometheus.py`
- Create: `eval/aurora_eval/dump_loki.py`
- Create: `eval/tests/test_dump_prometheus.py`
- Create: `eval/tests/test_dump_loki.py`

- [ ] **Step 1: Write the Prometheus test**

`eval/tests/test_dump_prometheus.py`:

```python
from pathlib import Path
from unittest.mock import patch

from aurora_eval import dump_prometheus


def test_snapshot_writes_raw_text(tmp_path):
    out = tmp_path / "metrics.txt"
    sample_body = "# HELP oracle_query_total\n# TYPE oracle_query_total counter\noracle_query_total{intent=\"FACTUAL\"} 42\n"

    with patch("aurora_eval.dump_prometheus.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.text = sample_body
        dump_prometheus.snapshot(
            prometheus_url="http://localhost:9090",
            target_metrics_url="http://oracle:8000/metrics",
            out_path=out,
        )

    assert out.exists()
    assert out.read_text() == sample_body
```

- [ ] **Step 2: Write the Loki test**

`eval/tests/test_dump_loki.py`:

```python
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from aurora_eval import dump_loki


def test_query_range_builds_request():
    with patch("aurora_eval.dump_loki.requests.get") as mock_get:
        mock_get.return_value.status_code = 200
        mock_get.return_value.json.return_value = {
            "data": {"result": [{"stream": {"service": "digester"}, "values": [["1717286400000000000", "msg"]]}]}
        }
        rows = dump_loki.query_range(
            loki_url="http://localhost:3100",
            logql='{service="digester"}',
            since=datetime(2026, 6, 1, tzinfo=timezone.utc),
            until=datetime(2026, 6, 2, tzinfo=timezone.utc),
            limit=1000,
        )
    assert rows == [{
        "service": "digester",
        "ts_ns": "1717286400000000000",
        "line": "msg",
    }]
    args, kwargs = mock_get.call_args
    assert args[0] == "http://localhost:3100/loki/api/v1/query_range"
    assert kwargs["params"]["query"] == '{service="digester"}'
    assert kwargs["params"]["limit"] == 1000
    assert kwargs["params"]["start"] == int(datetime(2026, 6, 1, tzinfo=timezone.utc).timestamp() * 1e9)
    assert kwargs["params"]["end"] == int(datetime(2026, 6, 2, tzinfo=timezone.utc).timestamp() * 1e9)


def test_snapshot_writes_jsonl(tmp_path):
    out = tmp_path / "loki.jsonl"
    rows = [{"service": "digester", "ts_ns": "1", "line": "a"}]
    dump_loki.write_jsonl(out, rows)
    written = [json.loads(l) for l in out.read_text().splitlines()]
    assert written == rows
```

- [ ] **Step 3: Run tests, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_dump_prometheus.py tests/test_dump_loki.py -v
```

Expected: 3 failed (modules not found).

- [ ] **Step 4: Write `eval/aurora_eval/dump_prometheus.py`**

```python
"""Snapshot the /metrics endpoint of a target service (raw text)."""
from __future__ import annotations

from pathlib import Path

import requests


def snapshot(*, prometheus_url: str, target_metrics_url: str, out_path: Path) -> None:
    """Fetch the target's /metrics body directly (cheap, no Prometheus query needed).

    The `prometheus_url` is kept on the signature so callers carry context, but
    we hit the target's /metrics endpoint to capture the exact point-in-time view
    the report references. Saves the raw Prometheus exposition format.
    """
    resp = requests.get(target_metrics_url, timeout=30)
    resp.raise_for_status()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(resp.text)
```

- [ ] **Step 5: Write `eval/aurora_eval/dump_loki.py`**

```python
"""Snapshot Loki logs via the LogQL range API."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Iterable

import requests


def query_range(
    *, loki_url: str, logql: str, since: datetime, until: datetime, limit: int = 5000
) -> list[dict]:
    start_ns = int(since.timestamp() * 1e9)
    end_ns = int(until.timestamp() * 1e9)
    resp = requests.get(
        f"{loki_url}/loki/api/v1/query_range",
        params={
            "query": logql,
            "start": start_ns,
            "end": end_ns,
            "limit": limit,
            "direction": "forward",
        },
        timeout=60,
    )
    resp.raise_for_status()
    body = resp.json()
    rows: list[dict] = []
    for stream in body.get("data", {}).get("result", []):
        service = stream.get("stream", {}).get("service", "")
        for ts_ns, line in stream.get("values", []):
            rows.append({"service": service, "ts_ns": ts_ns, "line": line})
    return rows


def write_jsonl(out_path: Path, rows: Iterable[dict]) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def snapshot(
    *,
    loki_url: str,
    out_path: Path,
    since: datetime,
    until: datetime,
    queries: dict[str, str],
) -> dict[str, int]:
    """Run multiple LogQL queries and concatenate the resulting rows into one jsonl.

    `queries` is a dict of {label: logql_query}. The label is added to each row
    so downstream analysis can filter by it.
    """
    all_rows: list[dict] = []
    counts: dict[str, int] = {}
    for label, q in queries.items():
        rows = query_range(loki_url=loki_url, logql=q, since=since, until=until)
        for row in rows:
            row["_query_label"] = label
        all_rows.extend(rows)
        counts[label] = len(rows)
    write_jsonl(out_path, all_rows)
    return counts
```

- [ ] **Step 6: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_dump_prometheus.py tests/test_dump_loki.py -v
```

Expected: 3 passed.

- [ ] **Step 7: Commit**

```bash
git add eval/aurora_eval/dump_prometheus.py eval/aurora_eval/dump_loki.py \
        eval/tests/test_dump_prometheus.py eval/tests/test_dump_loki.py
git commit -m "feat(eval): Prometheus and Loki snapshot helpers"
```

---

## Task 6: Snapshot loaders

**Files:**
- Create: `eval/aurora_eval/loaders.py`
- Create: `eval/tests/test_loaders.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_loaders.py`:

```python
import json
from pathlib import Path

import pandas as pd

from aurora_eval import loaders


def test_load_query_history_returns_dataframe(tmp_path):
    df_in = pd.DataFrame({
        "query_id": ["q1", "q2"],
        "question": ["a", "b"],
        "mode": ["fast", "baseline"],
        "confidence_score": [0.7, 0.8],
        "processing_time_ms": [100, 200],
    })
    df_in.to_parquet(tmp_path / "query_history.parquet")
    df = loaders.load_query_history(tmp_path)
    assert len(df) == 2
    assert list(df["mode"]) == ["fast", "baseline"]


def test_load_neo4j_snapshot(tmp_path):
    snap = {"total_nodes": 100, "documents_count": 50, "captured_at": "2026-06-02T12:00:00Z"}
    (tmp_path / "neo4j_snapshot.json").write_text(json.dumps(snap))
    loaded = loaders.load_neo4j_snapshot(tmp_path)
    assert loaded == snap


def test_load_judgements(tmp_path):
    df_in = pd.DataFrame({
        "query_id": ["q1"],
        "faithfulness": [4],
        "relevance": [5],
        "hallucination": [False],
        "citation_usefulness": [3],
    })
    df_in.to_parquet(tmp_path / "judgements.parquet")
    df = loaders.load_judgements(tmp_path)
    assert len(df) == 1
    assert df.iloc[0]["faithfulness"] == 4
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_loaders.py -v
```

Expected: 3 failed (module not found).

- [ ] **Step 3: Write `eval/aurora_eval/loaders.py`**

```python
"""Read snapshot files into pandas DataFrames."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd


def load_query_history(data_dir: Path) -> pd.DataFrame:
    return pd.read_parquet(data_dir / "query_history.parquet")


def load_chat_messages(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "chat_messages.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_user_feedback(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "user_feedback.parquet"
    if not path.exists():
        return pd.DataFrame()
    return pd.read_parquet(path)


def load_neo4j_snapshot(data_dir: Path) -> dict:
    return json.loads((data_dir / "neo4j_snapshot.json").read_text())


def load_judgements(data_dir: Path) -> pd.DataFrame:
    return pd.read_parquet(data_dir / "judgements.parquet")


def load_prometheus(data_dir: Path) -> str:
    return (data_dir / "metrics.txt").read_text()


def load_loki(data_dir: Path) -> pd.DataFrame:
    path = data_dir / "loki.jsonl"
    if not path.exists():
        return pd.DataFrame()
    rows = [json.loads(l) for l in path.read_text().splitlines() if l.strip()]
    return pd.DataFrame(rows)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_loaders.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/loaders.py eval/tests/test_loaders.py
git commit -m "feat(eval): snapshot loaders"
```

---

## Task 7: Stratified sampling for judge input

**Files:**
- Create: `eval/aurora_eval/sampling.py`
- Create: `eval/tests/test_sampling.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_sampling.py`:

```python
import pandas as pd

from aurora_eval import sampling


def _make_df(n_per_combo: int) -> pd.DataFrame:
    rows = []
    pid = 0
    for mode in ["fast", "baseline"]:
        for intent in ["FACTUAL", "ANALYTICAL", "COMPARATIVE", "TEMPORAL", "ENTITY"]:
            for i in range(n_per_combo):
                rows.append({
                    "query_id": f"q{pid}",
                    "mode": mode,
                    "intent": intent,
                    "answer": f"answer {pid}",
                    "error": 0,
                })
                pid += 1
    return pd.DataFrame(rows)


def test_stratified_sample_returns_target_size():
    df = _make_df(100)
    sample = sampling.stratified_sample(df, target=100, by=("mode", "intent"), random_state=42)
    assert len(sample) == 100


def test_stratified_sample_balances_strata():
    df = _make_df(100)
    sample = sampling.stratified_sample(df, target=100, by=("mode", "intent"), random_state=42)
    counts = sample.groupby(["mode", "intent"]).size()
    # 2 modes * 5 intents = 10 strata; target=100 => 10 per stratum
    assert counts.min() >= 9 and counts.max() <= 11


def test_stratified_sample_skips_errors_and_empty_answers():
    df = pd.DataFrame({
        "query_id": ["q1", "q2", "q3", "q4"],
        "mode": ["fast"] * 4,
        "intent": ["FACTUAL"] * 4,
        "answer": ["good", "", "good", "good"],
        "error": [0, 0, 1, 0],
    })
    sample = sampling.stratified_sample(df, target=10, by=("mode", "intent"), random_state=42)
    # q2 (empty answer) and q3 (error) excluded → 2 rows max
    assert set(sample["query_id"]) <= {"q1", "q4"}


def test_stratified_sample_handles_undersized_strata():
    df = _make_df(2)  # only 2 per stratum, total 20
    sample = sampling.stratified_sample(df, target=100, by=("mode", "intent"), random_state=42)
    assert len(sample) == 20
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_sampling.py -v
```

Expected: 4 failed.

- [ ] **Step 3: Write `eval/aurora_eval/sampling.py`**

```python
"""Stratified sampling for LLM-as-judge input."""
from __future__ import annotations

from typing import Tuple

import pandas as pd


def stratified_sample(
    df: pd.DataFrame, *, target: int, by: Tuple[str, ...], random_state: int = 42
) -> pd.DataFrame:
    """Return a stratified sample of ~target rows, balanced across `by` groups.

    Rows with `error == 1` or empty `answer` are excluded before sampling.
    If a stratum has fewer rows than its quota, it contributes everything it has
    and the total may fall below `target`.
    """
    eligible = df[(df["error"] == 0) & df["answer"].astype(str).str.strip().ne("")].copy()
    groups = eligible.groupby(list(by))
    n_strata = len(groups)
    if n_strata == 0:
        return eligible.head(0)
    per_stratum = max(1, target // n_strata)
    picked = pd.concat(
        [g.sample(min(len(g), per_stratum), random_state=random_state) for _, g in groups]
    ).reset_index(drop=True)
    return picked
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_sampling.py -v
```

Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/sampling.py eval/tests/test_sampling.py
git commit -m "feat(eval): stratified sampling for judge input"
```

---

## Task 8: LLM-as-judge prompt + response parser

**Files:**
- Create: `eval/aurora_eval/judge.py`
- Create: `eval/tests/test_judge.py`
- Create: `eval/tests/fixtures/judge_response_good.json`
- Create: `eval/tests/fixtures/judge_response_bad.json`

- [ ] **Step 1: Write the fixture files**

`eval/tests/fixtures/judge_response_good.json`:

```json
{
  "faithfulness": 5,
  "faithfulness_rationale": "Every claim is supported by the cited Wi-Fi Alliance spec section.",
  "relevance": 4,
  "relevance_rationale": "Answer addresses the question with one minor tangent.",
  "hallucination": false,
  "hallucination_rationale": "No unsupported claims detected.",
  "citation_usefulness": 4,
  "citation_usefulness_rationale": "Citations point to the exact section a reader would need."
}
```

`eval/tests/fixtures/judge_response_bad.json`:

```json
{
  "faithfulness": 2,
  "faithfulness_rationale": "Claim about Wi-Fi 8 throughput is not in the cited document.",
  "relevance": 3,
  "relevance_rationale": "Partially addresses the question.",
  "hallucination": true,
  "hallucination_rationale": "Throughput figure of 100 Gbps appears fabricated.",
  "citation_usefulness": 2,
  "citation_usefulness_rationale": "Cited document does not contain the figure being claimed."
}
```

- [ ] **Step 2: Write the failing test**

`eval/tests/test_judge.py`:

```python
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from aurora_eval import judge

FIXTURES = Path(__file__).parent / "fixtures"


def test_build_prompt_includes_question_answer_citations():
    prompt = judge.build_prompt(
        question="What is Wi-Fi 8?",
        answer="Wi-Fi 8 is the upcoming IEEE 802.11bn standard.",
        citations=[
            {"title": "WFA Whitepaper 2025", "url": "https://example.com/wp", "snippet": "Wi-Fi 8 is..."}
        ],
    )
    assert "What is Wi-Fi 8?" in prompt
    assert "Wi-Fi 8 is the upcoming IEEE 802.11bn standard." in prompt
    assert "WFA Whitepaper 2025" in prompt
    assert "faithfulness" in prompt.lower()
    assert "relevance" in prompt.lower()
    assert "hallucination" in prompt.lower()


def test_parse_response_good_fixture():
    raw = (FIXTURES / "judge_response_good.json").read_text()
    parsed = judge.parse_response(raw)
    assert parsed["faithfulness"] == 5
    assert parsed["relevance"] == 4
    assert parsed["hallucination"] is False
    assert parsed["citation_usefulness"] == 4


def test_parse_response_handles_text_around_json():
    raw = "Here is my evaluation:\n\n" + (FIXTURES / "judge_response_good.json").read_text() + "\n\nLet me know if you need more."
    parsed = judge.parse_response(raw)
    assert parsed["faithfulness"] == 5


def test_parse_response_raises_on_missing_field():
    bad = json.dumps({"faithfulness": 5})  # missing other required fields
    with pytest.raises(judge.JudgeParseError):
        judge.parse_response(bad)


def test_score_calls_anthropic_and_returns_parsed():
    fake_client = MagicMock()
    fake_message = MagicMock()
    fake_message.content = [MagicMock(text=(FIXTURES / "judge_response_good.json").read_text())]
    fake_client.messages.create.return_value = fake_message

    result = judge.score(
        client=fake_client,
        model="claude-opus-4-7",
        question="q",
        answer="a",
        citations=[],
    )
    assert result["faithfulness"] == 5
    fake_client.messages.create.assert_called_once()
    kwargs = fake_client.messages.create.call_args.kwargs
    assert kwargs["model"] == "claude-opus-4-7"
```

- [ ] **Step 3: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_judge.py -v
```

Expected: 5 failed.

- [ ] **Step 4: Write `eval/aurora_eval/judge.py`**

```python
"""LLM-as-judge: build prompt, parse response, run a single judgement."""
from __future__ import annotations

import json
import re
from typing import Any


class JudgeParseError(ValueError):
    pass


REQUIRED_FIELDS = (
    "faithfulness",
    "relevance",
    "hallucination",
    "citation_usefulness",
)

SYSTEM_PROMPT = """You are evaluating a retrieval-augmented question-answering system for Wi-Fi Alliance content.

For each (question, answer, citations) you receive, score the answer on four dimensions and return a JSON object only. Do not include any other text in your final response.

Scoring rubric (0-5 except where noted):

- faithfulness (0-5): Are the answer's specific claims supported by the cited documents? 5 = every claim supported; 0 = nothing supported.
- relevance (0-5): Does the answer address the user's question? 5 = directly answers; 0 = off-topic.
- hallucination (boolean): Does the answer contain at least one specific factual claim not supported by the citations? true/false.
- citation_usefulness (0-5): Would the cited documents actually help a reader verify the answer? 5 = exact source; 0 = unhelpful or irrelevant.

For each score include a brief one-sentence rationale.

Return JSON of exactly this shape (no extra fields, no surrounding markdown):
{
  "faithfulness": 0-5,
  "faithfulness_rationale": "string",
  "relevance": 0-5,
  "relevance_rationale": "string",
  "hallucination": true|false,
  "hallucination_rationale": "string",
  "citation_usefulness": 0-5,
  "citation_usefulness_rationale": "string"
}
"""


def build_prompt(*, question: str, answer: str, citations: list[dict]) -> str:
    citation_block = "\n\n".join(
        f"[{i+1}] {c.get('title', '(no title)')}\nURL: {c.get('url', '(no url)')}\nSnippet: {c.get('snippet', '(no snippet)')}"
        for i, c in enumerate(citations)
    ) or "(no citations provided)"
    return (
        f"Question:\n{question}\n\n"
        f"Answer:\n{answer}\n\n"
        f"Citations:\n{citation_block}\n\n"
        f"Score this answer according to the rubric. Return JSON only."
    )


def parse_response(raw: str) -> dict[str, Any]:
    # Find the first JSON object in the response.
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise JudgeParseError(f"No JSON object found in response: {raw[:200]!r}")
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError as exc:
        raise JudgeParseError(f"Invalid JSON: {exc}") from exc

    missing = [f for f in REQUIRED_FIELDS if f not in parsed]
    if missing:
        raise JudgeParseError(f"Missing required fields: {missing}")
    return parsed


def score(
    *, client, model: str, question: str, answer: str, citations: list[dict], max_tokens: int = 1024
) -> dict[str, Any]:
    """Call the Anthropic API and return the parsed judgement."""
    prompt = build_prompt(question=question, answer=answer, citations=citations)
    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text
    return parse_response(raw)
```

- [ ] **Step 5: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_judge.py -v
```

Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add eval/aurora_eval/judge.py eval/tests/test_judge.py eval/tests/fixtures/
git commit -m "feat(eval): LLM-as-judge prompt + response parser"
```

---

## Task 9: Judge runner (iterates sample, saves results)

**Files:**
- Create: `eval/aurora_eval/judge_runner.py`
- Create: `eval/tests/test_judge_runner.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_judge_runner.py`:

```python
from unittest.mock import MagicMock

import pandas as pd

from aurora_eval import judge_runner


def test_run_iterates_sample_and_collects_scores(tmp_path):
    sample = pd.DataFrame({
        "query_id": ["q1", "q2"],
        "question": ["What is X?", "What is Y?"],
        "answer": ["X is a thing.", "Y is another thing."],
        "citations": [
            [{"title": "doc1", "url": "u1", "snippet": "X is..."}],
            [{"title": "doc2", "url": "u2", "snippet": "Y is..."}],
        ],
        "mode": ["fast", "baseline"],
        "intent": ["FACTUAL", "ANALYTICAL"],
    })

    fake_client = MagicMock()
    def fake_create(**kwargs):
        msg = MagicMock()
        msg.content = [MagicMock(text=(
            '{"faithfulness": 4, "faithfulness_rationale": "good",'
            ' "relevance": 5, "relevance_rationale": "good",'
            ' "hallucination": false, "hallucination_rationale": "none",'
            ' "citation_usefulness": 3, "citation_usefulness_rationale": "ok"}'
        ))]
        return msg
    fake_client.messages.create.side_effect = fake_create

    out = tmp_path / "judgements.parquet"
    df = judge_runner.run(
        client=fake_client,
        model="claude-opus-4-7",
        sample=sample,
        out_path=out,
    )
    assert len(df) == 2
    assert set(df.columns) >= {"query_id", "mode", "intent", "faithfulness", "relevance", "hallucination", "citation_usefulness"}
    assert df["faithfulness"].tolist() == [4, 4]
    assert out.exists()
    assert fake_client.messages.create.call_count == 2


def test_run_skips_rows_that_error_during_judging(tmp_path):
    sample = pd.DataFrame({
        "query_id": ["q1", "q2"],
        "question": ["q1", "q2"],
        "answer": ["a1", "a2"],
        "citations": [[], []],
        "mode": ["fast", "fast"],
        "intent": ["FACTUAL", "FACTUAL"],
    })

    fake_client = MagicMock()
    call = [0]
    def fake_create(**kwargs):
        call[0] += 1
        msg = MagicMock()
        if call[0] == 1:
            msg.content = [MagicMock(text="not valid json")]
        else:
            msg.content = [MagicMock(text=(
                '{"faithfulness": 3, "faithfulness_rationale": "",'
                ' "relevance": 3, "relevance_rationale": "",'
                ' "hallucination": false, "hallucination_rationale": "",'
                ' "citation_usefulness": 3, "citation_usefulness_rationale": ""}'
            ))]
        return msg
    fake_client.messages.create.side_effect = fake_create

    out = tmp_path / "judgements.parquet"
    df = judge_runner.run(
        client=fake_client, model="m", sample=sample, out_path=out
    )
    # First row parse fails → still saved with judge_error set, second succeeds
    assert len(df) == 2
    failed = df[df["query_id"] == "q1"].iloc[0]
    assert failed["judge_error"]
    assert pd.isna(failed["faithfulness"])
    succeeded = df[df["query_id"] == "q2"].iloc[0]
    assert succeeded["faithfulness"] == 3
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_judge_runner.py -v
```

Expected: 2 failed.

- [ ] **Step 3: Write `eval/aurora_eval/judge_runner.py`**

```python
"""Iterate a sample, score each row with the LLM judge, save to parquet."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import pandas as pd

from aurora_eval import judge

log = logging.getLogger(__name__)


def _row_record(row: pd.Series, scored: dict[str, Any] | None, error: str | None) -> dict:
    out = {
        "query_id": row["query_id"],
        "mode": row.get("mode"),
        "intent": row.get("intent"),
        "judge_error": error,
    }
    if scored:
        out.update({
            "faithfulness": scored["faithfulness"],
            "faithfulness_rationale": scored.get("faithfulness_rationale"),
            "relevance": scored["relevance"],
            "relevance_rationale": scored.get("relevance_rationale"),
            "hallucination": scored["hallucination"],
            "hallucination_rationale": scored.get("hallucination_rationale"),
            "citation_usefulness": scored["citation_usefulness"],
            "citation_usefulness_rationale": scored.get("citation_usefulness_rationale"),
        })
    else:
        out.update({
            "faithfulness": pd.NA,
            "faithfulness_rationale": None,
            "relevance": pd.NA,
            "relevance_rationale": None,
            "hallucination": pd.NA,
            "hallucination_rationale": None,
            "citation_usefulness": pd.NA,
            "citation_usefulness_rationale": None,
        })
    return out


def run(*, client, model: str, sample: pd.DataFrame, out_path: Path) -> pd.DataFrame:
    records: list[dict] = []
    for _, row in sample.iterrows():
        try:
            scored = judge.score(
                client=client,
                model=model,
                question=row["question"],
                answer=row["answer"],
                citations=row.get("citations", []) or [],
            )
            records.append(_row_record(row, scored, error=None))
        except Exception as exc:  # noqa: BLE001 — judge can fail in many ways; we record and continue
            log.warning("judge failed for query_id=%s: %s", row.get("query_id"), exc)
            records.append(_row_record(row, scored=None, error=str(exc)))
    df = pd.DataFrame(records)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out_path, index=False)
    return df


def open_client(api_key: str):
    """Production helper; imported lazily so tests don't need the anthropic SDK."""
    from anthropic import Anthropic

    return Anthropic(api_key=api_key)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_judge_runner.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/judge_runner.py eval/tests/test_judge_runner.py
git commit -m "feat(eval): judge runner with per-row error capture"
```

---

## Task 10: Scout module

**Files:**
- Create: `eval/aurora_eval/scout.py`
- Create: `eval/tests/test_scout.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_scout.py`:

```python
import sqlite3
from datetime import datetime, timezone, timedelta

from aurora_eval import scout


def test_scout_summary_sqlite(sqlite_with_query_history):
    summary = scout.summarize_sqlite(sqlite_with_query_history)
    assert summary["total_queries"] == 50
    assert summary["earliest"] is not None
    assert summary["latest"] is not None
    assert summary["distinct_users"] == 5
    assert summary["fast_count"] == 25
    assert summary["baseline_count"] == 25
    assert summary["with_feedback"] > 0
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_scout.py -v
```

Expected: 1 failed.

- [ ] **Step 3: Write `eval/aurora_eval/scout.py`**

```python
"""Lightweight production data scan, before committing to a dump window."""
from __future__ import annotations

import sqlite3
from typing import Any


_SCOUT_SQL = {
    "total_queries": "SELECT COUNT(*) FROM oracle_query_history",
    "earliest": "SELECT MIN(created_at) FROM oracle_query_history",
    "latest": "SELECT MAX(created_at) FROM oracle_query_history",
    "distinct_users": "SELECT COUNT(DISTINCT user_id) FROM oracle_query_history",
    "fast_count": "SELECT COUNT(*) FROM oracle_query_history WHERE mode = 'fast'",
    "baseline_count": "SELECT COUNT(*) FROM oracle_query_history WHERE mode = 'baseline'",
    "with_feedback": "SELECT COUNT(*) FROM oracle_query_history WHERE feedback_type IS NOT NULL",
    "error_count": "SELECT COUNT(*) FROM oracle_query_history WHERE error = 1",
}


def summarize(*, postgres_url: str) -> dict[str, Any]:
    import psycopg2

    out: dict[str, Any] = {}
    with psycopg2.connect(postgres_url) as conn:
        with conn.cursor() as cur:
            for key, sql in _SCOUT_SQL.items():
                cur.execute(sql)
                (v,) = cur.fetchone()
                out[key] = v
    return out


def summarize_sqlite(sqlite_url: str) -> dict[str, Any]:
    assert sqlite_url.startswith("sqlite:///")
    db_path = sqlite_url[len("sqlite:///"):]
    out: dict[str, Any] = {}
    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        for key, sql in _SCOUT_SQL.items():
            cur.execute(sql)
            (v,) = cur.fetchone()
            out[key] = v
    finally:
        conn.close()
    return out


def format_report(summary: dict[str, Any]) -> str:
    lines = ["Aurora prod scan", "================"]
    for k, v in summary.items():
        lines.append(f"  {k:<20} {v}")
    return "\n".join(lines)
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_scout.py -v
```

Expected: 1 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/scout.py eval/tests/test_scout.py
git commit -m "feat(eval): scout module for prod row counts"
```

---

## Task 11: Chart helpers

**Files:**
- Create: `eval/aurora_eval/charts.py`
- Create: `eval/tests/test_charts.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_charts.py`:

```python
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

from aurora_eval import charts


def test_latency_histogram_returns_figure():
    df = pd.DataFrame({
        "mode": ["fast"] * 50 + ["baseline"] * 50,
        "processing_time_ms": list(range(100, 600, 10)) * 2,
    })
    fig = charts.latency_histogram(df)
    assert isinstance(fig, plt.Figure)
    plt.close(fig)


def test_confidence_distribution_returns_figure():
    df = pd.DataFrame({
        "mode": ["fast", "fast", "baseline", "baseline"],
        "confidence_score": [0.6, 0.8, 0.4, 0.7],
    })
    fig = charts.confidence_distribution(df)
    assert isinstance(fig, plt.Figure)
    plt.close(fig)


def test_save_writes_svg(tmp_path):
    fig = plt.figure()
    plt.plot([1, 2, 3])
    out = tmp_path / "test.svg"
    charts.save(fig, out)
    assert out.exists()
    plt.close(fig)
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_charts.py -v
```

Expected: 3 failed.

- [ ] **Step 3: Write `eval/aurora_eval/charts.py`**

```python
"""Reusable chart helpers for the evaluation report."""
from __future__ import annotations

from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd
import seaborn as sns

sns.set_theme(style="whitegrid")


def latency_histogram(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8, 4))
    for mode, group in df.groupby("mode"):
        ax.hist(group["processing_time_ms"], bins=40, alpha=0.5, label=mode)
    ax.set_xlabel("Latency (ms)")
    ax.set_ylabel("Queries")
    ax.set_title("Query latency by pipeline")
    ax.legend()
    return fig


def confidence_distribution(df: pd.DataFrame) -> plt.Figure:
    fig, ax = plt.subplots(figsize=(8, 4))
    sns.violinplot(data=df, x="mode", y="confidence_score", ax=ax)
    ax.set_title("Confidence score distribution by pipeline")
    ax.set_ylim(0, 1)
    return fig


def tokens_by_prompt_type(df: pd.DataFrame, top_n: int = 10) -> plt.Figure:
    top = df.groupby("prompt_type")["total_tokens"].sum().sort_values(ascending=False).head(top_n)
    fig, ax = plt.subplots(figsize=(8, 4))
    top.plot.barh(ax=ax)
    ax.set_xlabel("Total tokens")
    ax.set_title(f"Token usage by prompt type (top {top_n})")
    fig.tight_layout()
    return fig


def cache_hit_rate(df: pd.DataFrame) -> plt.Figure:
    rates = df.groupby("mode")["cache_hit"].mean()
    fig, ax = plt.subplots(figsize=(6, 3))
    rates.plot.bar(ax=ax)
    ax.set_ylabel("Cache hit rate")
    ax.set_ylim(0, 1)
    ax.set_title("Cache hit rate by pipeline")
    fig.tight_layout()
    return fig


def save(fig: plt.Figure, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(out_path, bbox_inches="tight")
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_charts.py -v
```

Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/charts.py eval/tests/test_charts.py
git commit -m "feat(eval): chart helpers"
```

---

## Task 12: CLI entry point

**Files:**
- Create: `eval/aurora_eval/cli.py`
- Create: `eval/tests/test_cli.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_cli.py`:

```python
import sys
from unittest.mock import patch

from aurora_eval import cli


def test_cli_scout_invokes_scout(monkeypatch, capsys):
    monkeypatch.setenv("EVAL_POSTGRES_URL", "postgresql://x")
    monkeypatch.setenv("EVAL_NEO4J_URL", "bolt://x")
    monkeypatch.setenv("EVAL_NEO4J_USER", "x")
    monkeypatch.setenv("EVAL_NEO4J_PASSWORD", "x")
    monkeypatch.setenv("EVAL_PROMETHEUS_URL", "http://x")
    monkeypatch.setenv("EVAL_LOKI_URL", "http://x")
    monkeypatch.setenv("EVAL_ANTHROPIC_API_KEY", "x")
    monkeypatch.setenv("EVAL_DATA_DIR", "/tmp/eval-d")
    monkeypatch.setenv("EVAL_CHARTS_DIR", "/tmp/eval-c")
    monkeypatch.setenv("EVAL_SINCE", "2026-01-01T00:00:00+00:00")
    monkeypatch.setenv("EVAL_UNTIL", "2026-06-02T00:00:00+00:00")

    with patch("aurora_eval.cli.scout.summarize") as mock_summarize:
        mock_summarize.return_value = {"total_queries": 1234, "earliest": "x", "latest": "y"}
        rc = cli.main(["scout"])

    out = capsys.readouterr().out
    assert rc == 0
    assert "1234" in out
    mock_summarize.assert_called_once()


def test_cli_dump_calls_dumpers(monkeypatch):
    for var, val in [
        ("EVAL_POSTGRES_URL", "postgresql://x"),
        ("EVAL_NEO4J_URL", "bolt://x"),
        ("EVAL_NEO4J_USER", "x"),
        ("EVAL_NEO4J_PASSWORD", "x"),
        ("EVAL_PROMETHEUS_URL", "http://x"),
        ("EVAL_LOKI_URL", "http://x"),
        ("EVAL_ANTHROPIC_API_KEY", "x"),
        ("EVAL_DATA_DIR", "/tmp/eval-d"),
        ("EVAL_CHARTS_DIR", "/tmp/eval-c"),
        ("EVAL_SINCE", "2026-01-01T00:00:00+00:00"),
        ("EVAL_UNTIL", "2026-06-02T00:00:00+00:00"),
    ]:
        monkeypatch.setenv(var, val)

    with patch("aurora_eval.cli.dump_postgres.dump_all") as mock_pg, \
         patch("aurora_eval.cli.dump_neo4j.snapshot") as mock_neo, \
         patch("aurora_eval.cli.dump_neo4j.open_driver"), \
         patch("aurora_eval.cli.dump_prometheus.snapshot") as mock_prom, \
         patch("aurora_eval.cli.dump_loki.snapshot") as mock_loki:
        mock_pg.return_value = {"oracle_query_history": 100}
        mock_neo.return_value = {"total_nodes": 50}
        mock_loki.return_value = {"digester": 10}
        rc = cli.main(["dump", "--target-metrics-url", "http://oracle:8000/metrics"])
    assert rc == 0
    assert mock_pg.called
    assert mock_neo.called
    assert mock_prom.called
    assert mock_loki.called
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_cli.py -v
```

Expected: 2 failed.

- [ ] **Step 3: Write `eval/aurora_eval/cli.py`**

```python
"""Command-line entry point for the evaluation toolkit."""
from __future__ import annotations

import argparse
import logging
import sys

import pandas as pd

from aurora_eval import (
    config,
    dump_loki,
    dump_neo4j,
    dump_postgres,
    dump_prometheus,
    judge_runner,
    loaders,
    sampling,
    scout,
)

log = logging.getLogger(__name__)


DEFAULT_LOKI_QUERIES = {
    "llm_calls": '{job="oracle"} |= "llm.prompt_type"',
    "digester": '{service="digester"}',
}


def cmd_scout(cfg: config.Config) -> int:
    summary = scout.summarize(postgres_url=cfg.postgres_url)
    print(scout.format_report(summary))
    return 0


def cmd_dump(cfg: config.Config, args: argparse.Namespace) -> int:
    cfg.ensure_dirs()
    log.info("Postgres → %s", cfg.data_dir)
    counts = dump_postgres.dump_all(
        postgres_url=cfg.postgres_url,
        out_dir=cfg.data_dir,
        since=cfg.since,
        until=cfg.until,
    )
    log.info("Postgres counts: %s", counts)

    log.info("Neo4j snapshot")
    driver = dump_neo4j.open_driver(cfg.neo4j_url, cfg.neo4j_user, cfg.neo4j_password)
    dump_neo4j.snapshot(driver=driver, out_path=cfg.data_dir / "neo4j_snapshot.json")

    if args.target_metrics_url:
        log.info("Prometheus snapshot")
        dump_prometheus.snapshot(
            prometheus_url=cfg.prometheus_url,
            target_metrics_url=args.target_metrics_url,
            out_path=cfg.data_dir / "metrics.txt",
        )

    log.info("Loki snapshot")
    loki_counts = dump_loki.snapshot(
        loki_url=cfg.loki_url,
        out_path=cfg.data_dir / "loki.jsonl",
        since=cfg.since,
        until=cfg.until,
        queries=DEFAULT_LOKI_QUERIES,
    )
    log.info("Loki row counts: %s", loki_counts)
    return 0


def cmd_judge(cfg: config.Config, args: argparse.Namespace) -> int:
    cfg.ensure_dirs()
    df = loaders.load_query_history(cfg.data_dir)
    sample = sampling.stratified_sample(
        df, target=args.sample_size, by=("mode", "intent"), random_state=args.random_state
    )
    log.info("Sample size: %d", len(sample))
    sample.to_parquet(cfg.data_dir / "judge_sample.parquet", index=False)

    client = judge_runner.open_client(cfg.anthropic_api_key)
    result = judge_runner.run(
        client=client,
        model=cfg.judge_model,
        sample=sample,
        out_path=cfg.data_dir / "judgements.parquet",
    )
    log.info("Judged %d rows", len(result))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="aurora_eval")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("scout", help="Scan prod row counts and date range")

    p_dump = sub.add_parser("dump", help="Snapshot prod data locally")
    p_dump.add_argument("--target-metrics-url", default=None,
                        help="URL of the /metrics endpoint to scrape, e.g. http://oracle:8000/metrics")

    p_judge = sub.add_parser("judge", help="Run LLM-as-judge on a stratified sample")
    p_judge.add_argument("--sample-size", type=int, default=None)
    p_judge.add_argument("--random-state", type=int, default=42)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

    cfg = config.load()
    if args.cmd == "judge" and args.sample_size is None:
        args.sample_size = cfg.judge_sample_size

    if args.cmd == "scout":
        return cmd_scout(cfg)
    if args.cmd == "dump":
        return cmd_dump(cfg, args)
    if args.cmd == "judge":
        return cmd_judge(cfg, args)
    raise SystemExit(f"unknown command {args.cmd}")


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_cli.py -v
```

Expected: 2 passed.

- [ ] **Step 5: Run the full test suite to confirm nothing else broke**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest -v
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add eval/aurora_eval/cli.py eval/tests/test_cli.py
git commit -m "feat(eval): CLI entry point — scout, dump, judge subcommands"
```

---

## Task 13: Real prod scout run (manual)

This is a manual verification task — no automated test, but the output drives the report window.

**Files:** none modified.

- [ ] **Step 1: Set up prod connectivity**

If prod Postgres is reached via SSM, open the tunnel. Otherwise, populate the `.env` file with the prod credentials. The required env vars:

```
EVAL_POSTGRES_URL
EVAL_NEO4J_URL EVAL_NEO4J_USER EVAL_NEO4J_PASSWORD
EVAL_PROMETHEUS_URL EVAL_LOKI_URL
EVAL_ANTHROPIC_API_KEY
EVAL_DATA_DIR=./data EVAL_CHARTS_DIR=./charts
EVAL_SINCE=<temporary, e.g. 2020-01-01T00:00:00+00:00 — scout ignores window>
EVAL_UNTIL=<temporary, e.g. 2030-01-01T00:00:00+00:00>
```

- [ ] **Step 2: Run scout**

```bash
cd eval && PYTHONPATH=. .venv/bin/python -m aurora_eval.cli scout
```

Expected: a printout like:

```
Aurora prod scan
================
  total_queries        <N>
  earliest             <timestamp>
  latest               <timestamp>
  distinct_users       <N>
  fast_count           <N>
  baseline_count       <N>
  with_feedback        <N>
  error_count          <N>
```

- [ ] **Step 3: Choose the report window**

Based on the scout output:
- If `total_queries < 1000`: use the entire range (`EVAL_SINCE` = `earliest`, `EVAL_UNTIL` = `latest + 1 day`).
- If `total_queries >= 1000`: prefer the full range unless the earliest weeks show low/noisy volume; otherwise drop the first 7 days from `EVAL_SINCE`.
- Record the chosen window in a scratch note for the methodology appendix.

- [ ] **Step 4: Update `.env` with final window**

Set `EVAL_SINCE` and `EVAL_UNTIL` to the decided ISO timestamps.

- [ ] **Step 5: No commit needed** (no code change)

---

## Task 14: Real prod dump run (manual)

**Files:** writes only to `eval/data/` (gitignored).

- [ ] **Step 1: Run dump**

```bash
cd eval && PYTHONPATH=. .venv/bin/python -m aurora_eval.cli dump \
    --target-metrics-url http://oracle:8000/metrics
```

Expected: produces:
- `eval/data/query_history.parquet`
- `eval/data/chat_messages.parquet`
- `eval/data/user_feedback.parquet`
- `eval/data/neo4j_snapshot.json`
- `eval/data/metrics.txt`
- `eval/data/loki.jsonl`

- [ ] **Step 2: Sanity-check the dump**

Open a Python REPL with the venv:

```bash
cd eval && PYTHONPATH=. .venv/bin/python -c "
from pathlib import Path
from aurora_eval import loaders
d = Path('data')
q = loaders.load_query_history(d)
print('queries:', len(q))
print('mode counts:', q['mode'].value_counts().to_dict())
print('null answer:', q['answer'].isna().sum())
print('neo4j:', loaders.load_neo4j_snapshot(d))
"
```

Expected output should be consistent with the scout numbers. If row counts diverge significantly, investigate before continuing.

- [ ] **Step 3: No commit** — data is gitignored.

---

## Task 15: Real LLM-as-judge run (manual)

**Files:** writes only to `eval/data/` (gitignored).

- [ ] **Step 1: Run the judge**

```bash
cd eval && PYTHONPATH=. .venv/bin/python -m aurora_eval.cli judge --sample-size 100
```

Expected: produces `eval/data/judge_sample.parquet` and `eval/data/judgements.parquet`. Log output should show "Judged 100 rows" (or fewer if some strata were small).

- [ ] **Step 2: Spot-check the rationales**

```bash
cd eval && PYTHONPATH=. .venv/bin/python -c "
import pandas as pd
df = pd.read_parquet('data/judgements.parquet')
print(df[['mode','faithfulness','relevance','hallucination']].describe(include='all'))
print('errors:', df['judge_error'].notna().sum())
# Print 3 random rows with rationales
print(df.sample(3, random_state=1)[['query_id','mode','intent','faithfulness','faithfulness_rationale']])
"
```

Look for: any score that seems clearly wrong relative to the rationale, indicating prompt issues. If >5% of rows have `judge_error`, investigate the failures and re-run.

- [ ] **Step 3: No commit** — data is gitignored.

---

## Task 16: Notebook scaffold + Section 1 (Operational health)

**Files:**
- Create: `eval/aurora_eval/analyze.ipynb`

- [ ] **Step 1: Create the notebook with a header cell**

Open Jupyter:

```bash
cd eval && PYTHONPATH=. .venv/bin/jupyter notebook aurora_eval/analyze.ipynb
```

Add a markdown cell at the top:

```markdown
# Aurora Production Evaluation — Analysis Notebook

Generated 2026-06-02. Reads from `../data/` and writes charts to `../charts/`.

Window: `EVAL_SINCE` → `EVAL_UNTIL` (see config).
```

- [ ] **Step 2: Add a setup cell**

```python
%matplotlib inline
import sys
from pathlib import Path
sys.path.insert(0, str(Path.cwd().parent))  # so `aurora_eval` resolves

from aurora_eval import config, loaders, charts
import pandas as pd
import matplotlib.pyplot as plt

cfg = config.load()
data_dir = cfg.data_dir
charts_dir = cfg.charts_dir
charts_dir.mkdir(parents=True, exist_ok=True)

queries = loaders.load_query_history(data_dir)
neo4j = loaders.load_neo4j_snapshot(data_dir)
judgements = loaders.load_judgements(data_dir)

print(f"Loaded {len(queries):,} queries, {len(judgements):,} judgements")
```

- [ ] **Step 3: Add Section 1 — Operational health**

Markdown cell:

```markdown
## Section 1 — Operational health

Volume, latency, error rate, and cache effectiveness over the report window.
```

Code cell:

```python
# Volume per day
daily = queries.assign(day=pd.to_datetime(queries["created_at"]).dt.date).groupby("day").size()
fig, ax = plt.subplots(figsize=(10, 3))
daily.plot(ax=ax)
ax.set_title("Daily query volume")
ax.set_ylabel("Queries")
charts.save(fig, charts_dir / "01_daily_volume.svg")
fig
```

Code cell:

```python
# Latency
fig = charts.latency_histogram(queries)
charts.save(fig, charts_dir / "01_latency_histogram.svg")

latency_summary = queries.groupby("mode")["processing_time_ms"].describe(percentiles=[0.5, 0.95, 0.99])
print(latency_summary)
```

Code cell:

```python
# Error rate
err = queries.assign(is_err=queries["error"].astype(bool))
err_rate = err.groupby("mode")["is_err"].mean()
print("Error rate by mode:")
print(err_rate)

top_errors = err[err["is_err"]].groupby("error_message").size().sort_values(ascending=False).head(10)
print("\nTop error messages:")
print(top_errors)
```

Code cell:

```python
# Cache hit rate (3-tier breakdown)
def cache_tier(opts):
    if not isinstance(opts, dict):
        return {}
    return opts.get("cache", {}) or {}

cache_df = queries["request_options"].apply(cache_tier).apply(pd.Series)
for col in ["overall_hit", "route_hit", "result_hit", "answer_hit"]:
    if col not in cache_df.columns:
        cache_df[col] = False
cache_df["mode"] = queries["mode"].values
cache_summary = cache_df.groupby("mode")[["overall_hit", "route_hit", "result_hit", "answer_hit"]].mean()
print(cache_summary)

fig = charts.cache_hit_rate(queries.assign(cache_hit=cache_df["overall_hit"].astype(int)))
charts.save(fig, charts_dir / "01_cache_hit_rate.svg")
```

- [ ] **Step 4: Run the cells; confirm they execute end-to-end**

In Jupyter: Cell → Run All. Expected: no exceptions, charts render, summary tables print.

- [ ] **Step 5: Commit the notebook with outputs**

```bash
git add eval/aurora_eval/analyze.ipynb
git commit -m "feat(eval): notebook scaffold + Section 1 operational health"
```

---

## Task 17: Notebook Section 2 — KG vs RAG head-to-head

**Files:**
- Modify: `eval/aurora_eval/analyze.ipynb`

- [ ] **Step 1: Add markdown cell**

```markdown
## Section 2 — KG (fast) vs RAG (baseline) head-to-head

The system's central design bet: does the KG-first fast pipeline pay for itself?
```

- [ ] **Step 2: Add comparison cells**

Code cell (latency):

```python
from scipy import stats

latency_compare = queries.groupby("mode")["processing_time_ms"].agg(["count", "mean", "median", "std"])
print(latency_compare)

fast = queries[queries["mode"] == "fast"]["processing_time_ms"]
baseline = queries[queries["mode"] == "baseline"]["processing_time_ms"]
if len(fast) > 30 and len(baseline) > 30:
    u, p = stats.mannwhitneyu(fast, baseline, alternative="two-sided")
    print(f"Mann-Whitney U: {u:.0f}, p={p:.4f}")
    print(f"Effect size (median diff): {fast.median() - baseline.median():.0f} ms")
```

Add `scipy` to `eval/requirements.txt` if not already present:

```
scipy==1.13.*
```

Then install:

```bash
cd eval && .venv/bin/pip install scipy==1.13.*
```

Code cell (tokens):

```python
token_compare = queries.groupby("mode")["llm_tokens_used"].describe(percentiles=[0.5, 0.95])
print(token_compare)
fig, ax = plt.subplots(figsize=(8, 4))
import seaborn as sns
sns.boxplot(data=queries, x="mode", y="llm_tokens_used", showfliers=False, ax=ax)
ax.set_title("LLM tokens per query by pipeline")
charts.save(fig, charts_dir / "02_tokens_by_mode.svg")
```

Code cell (confidence):

```python
fig = charts.confidence_distribution(queries)
charts.save(fig, charts_dir / "02_confidence_by_mode.svg")
conf_compare = queries.groupby("mode")["confidence_score"].describe()
print(conf_compare)
```

Code cell (feedback ratio):

```python
fb = queries[queries["feedback_type"].notna()]
fb_summary = fb.groupby(["mode", "feedback_type"]).size().unstack(fill_value=0)
fb_summary["positive_ratio"] = fb_summary["positive"] / (fb_summary["positive"] + fb_summary["negative"])
print(fb_summary)
```

Code cell (judge correctness comparison):

```python
judge_compare = judgements.groupby("mode")[
    ["faithfulness", "relevance", "citation_usefulness"]
].agg(["mean", "std", "count"])
print(judge_compare)

hallu_rate = judgements.groupby("mode")["hallucination"].mean()
print("Hallucination rate by mode:")
print(hallu_rate)

fig, axes = plt.subplots(1, 3, figsize=(14, 4))
for ax, dim in zip(axes, ["faithfulness", "relevance", "citation_usefulness"]):
    sns.barplot(data=judgements, x="mode", y=dim, ax=ax, errorbar=("ci", 95))
    ax.set_ylim(0, 5)
    ax.set_title(dim)
fig.suptitle("LLM-as-judge scores by pipeline (95% CI)")
charts.save(fig, charts_dir / "02_judge_scores_by_mode.svg")
```

- [ ] **Step 3: Run all cells, confirm execution**

In Jupyter: Cell → Run All.

- [ ] **Step 4: Commit**

```bash
git add eval/aurora_eval/analyze.ipynb eval/requirements.txt
git commit -m "feat(eval): notebook Section 2 — KG vs RAG comparison"
```

---

## Task 18: Notebook Section 3 — LLM efficiency

**Files:**
- Modify: `eval/aurora_eval/analyze.ipynb`

- [ ] **Step 1: Add markdown cell**

```markdown
## Section 3 — LLM efficiency

Token usage broken down by prompt type and model, plus a cost estimate.
```

- [ ] **Step 2: Add cells parsing Loki LLM logs**

Code cell:

```python
import json

loki_df = loaders.load_loki(data_dir)
llm_rows = loki_df[loki_df["_query_label"] == "llm_calls"].copy()

def parse_llm(line):
    try:
        return json.loads(line)
    except Exception:
        return {}

llm_parsed = pd.json_normalize(llm_rows["line"].apply(parse_llm))
# Expected fields per common/telemetry.log_llm_request: llm.prompt_type, llm.model,
# llm.prompt_tokens, llm.completion_tokens, llm.total_tokens, llm.duration_ms, llm.status
for col in ["llm.prompt_type", "llm.model", "llm.prompt_tokens", "llm.completion_tokens", "llm.total_tokens"]:
    if col not in llm_parsed.columns:
        llm_parsed[col] = None

llm = llm_parsed.rename(columns=lambda c: c.replace("llm.", ""))
print("LLM calls captured in Loki:", len(llm))
print("By prompt_type:")
print(llm.groupby("prompt_type")["total_tokens"].agg(["count", "sum", "mean"]).sort_values("sum", ascending=False))
```

Code cell (chart + cost estimate):

```python
fig = charts.tokens_by_prompt_type(llm)
charts.save(fig, charts_dir / "03_tokens_by_prompt_type.svg")

# Cost estimate
# IMPORTANT: confirm current Azure OpenAI pricing for the deployed model.
# These rates are placeholders — replace with values from the Azure pricing page
# on the date the report is finalized. Default below assumes gpt-4o.
PRICE_PER_1K_INPUT = 0.005    # USD per 1K input tokens (PLACEHOLDER — verify)
PRICE_PER_1K_OUTPUT = 0.015   # USD per 1K output tokens (PLACEHOLDER — verify)

cost_in = llm["prompt_tokens"].fillna(0).sum() / 1000 * PRICE_PER_1K_INPUT
cost_out = llm["completion_tokens"].fillna(0).sum() / 1000 * PRICE_PER_1K_OUTPUT
print(f"Estimated LLM cost over window: input=${cost_in:.2f}, output=${cost_out:.2f}, total=${cost_in + cost_out:.2f}")
print(f"Per-query average cost: ${(cost_in + cost_out) / max(len(queries), 1):.4f}")
```

- [ ] **Step 3: Run all cells**

Confirm no exceptions. If `llm` is empty, the Loki query needs tuning — check Step 4.

- [ ] **Step 4: If Loki returns no LLM rows, fix the LogQL**

The default query `{job="oracle"} |= "llm.prompt_type"` assumes the oracle service has `job=oracle` label. If logs use a different label (`service`, `app`, `compose_service`), edit `DEFAULT_LOKI_QUERIES` in `cli.py`. Confirm by running a Loki query in Grafana first.

- [ ] **Step 5: Commit**

```bash
git add eval/aurora_eval/analyze.ipynb
git commit -m "feat(eval): notebook Section 3 — LLM efficiency and cost estimate"
```

---

## Task 19: Notebook Section 4 — Document processing efficiency

**Files:**
- Modify: `eval/aurora_eval/analyze.ipynb`

- [ ] **Step 1: Add markdown cell**

```markdown
## Section 4 — Document processing (Digester)

Throughput, DLQ rate, failure modes, and Neo4j corpus snapshot.
```

- [ ] **Step 2: Add cells**

Code cell:

```python
digester_df = loki_df[loki_df["_query_label"] == "digester"].copy()
print(f"Digester log lines: {len(digester_df)}")

digester_df["ts"] = pd.to_datetime(digester_df["ts_ns"].astype("int64"), unit="ns", utc=True)
digester_df["day"] = digester_df["ts"].dt.date
per_day = digester_df.groupby("day").size()
fig, ax = plt.subplots(figsize=(10, 3))
per_day.plot(ax=ax)
ax.set_title("Digester log volume per day")
ax.set_ylabel("Log lines")
charts.save(fig, charts_dir / "04_digester_throughput.svg")
```

Code cell:

```python
dlq_keywords = ["dlq", "timeout", "validation_error", "redelivery"]
dlq_counts = {}
for k in dlq_keywords:
    dlq_counts[k] = digester_df["line"].str.contains(k, case=False, na=False).sum()
print("Digester failure mode counts:")
for k, v in dlq_counts.items():
    print(f"  {k}: {v}")
```

Code cell:

```python
import json
print("Neo4j corpus snapshot:")
print(json.dumps(neo4j, indent=2, default=str)[:2000])

# Render nodes_by_label as a bar
if isinstance(neo4j.get("nodes_by_label"), list):
    nodes_df = pd.DataFrame(neo4j["nodes_by_label"])
    fig, ax = plt.subplots(figsize=(8, 4))
    nodes_df.set_index("label")["count"].sort_values().plot.barh(ax=ax)
    ax.set_xlabel("Node count")
    ax.set_title("Neo4j nodes by label")
    fig.tight_layout()
    charts.save(fig, charts_dir / "04_nodes_by_label.svg")
```

- [ ] **Step 3: Run all cells**

- [ ] **Step 4: Commit**

```bash
git add eval/aurora_eval/analyze.ipynb
git commit -m "feat(eval): notebook Section 4 — digester + Neo4j corpus"
```

---

## Task 20: Notebook Section 5 — KG utilization

**Files:**
- Modify: `eval/aurora_eval/analyze.ipynb`

- [ ] **Step 1: Add markdown cell**

```markdown
## Section 5 — Knowledge graph utilization

Which route templates fire, citation density, coverage gaps (fast → baseline fallbacks).
```

- [ ] **Step 2: Add cells**

Code cell (route_id distribution):

```python
def extract_route_id(opts):
    if isinstance(opts, dict):
        return opts.get("route_id") or opts.get("route_plan", {}).get("route_id")
    return None

queries["route_id"] = queries["request_options"].apply(extract_route_id)
route_hits = queries[queries["mode"] == "fast"].groupby("route_id").size().sort_values(ascending=False)
print(f"Distinct fast routes used: {route_hits.shape[0]}")
print("Top 15:")
print(route_hits.head(15))

fig, ax = plt.subplots(figsize=(8, 6))
route_hits.head(20).plot.barh(ax=ax)
ax.set_xlabel("Queries")
ax.set_title("Fast pipeline route_id hits (top 20)")
fig.tight_layout()
charts.save(fig, charts_dir / "05_route_hits.svg")
```

Code cell (citation density):

```python
def citation_count(cits):
    if isinstance(cits, list):
        return len(cits)
    return 0

queries["citation_count"] = queries["citations"].apply(citation_count)
cite_by_mode = queries.groupby("mode")["citation_count"].describe()
print(cite_by_mode)
```

Code cell (coverage gap — fast→baseline fallback proxy):

```python
def fallback_reason(opts):
    if isinstance(opts, dict):
        return opts.get("fallback_reason")
    return None

queries["fallback_reason"] = queries["request_options"].apply(fallback_reason)
fallbacks = queries[queries["fallback_reason"].notna()]
print(f"Fallback events: {len(fallbacks)}")
if len(fallbacks):
    print(fallbacks.groupby(["intent", "fallback_reason"]).size().sort_values(ascending=False).head(15))
```

- [ ] **Step 3: Run all cells**

If `route_id` extraction returns mostly None, inspect a few rows of `request_options` and adjust the extraction path:

```python
print(queries["request_options"].dropna().head(3).tolist())
```

- [ ] **Step 4: Commit**

```bash
git add eval/aurora_eval/analyze.ipynb
git commit -m "feat(eval): notebook Section 5 — KG utilization"
```

---

## Task 21: Notebook Section 6 — User satisfaction

**Files:**
- Modify: `eval/aurora_eval/analyze.ipynb`

- [ ] **Step 1: Add markdown cell**

```markdown
## Section 6 — User satisfaction

Feedback ratio, confidence-vs-feedback correlation, complaint themes.
```

- [ ] **Step 2: Add cells**

Code cell (feedback ratio over time):

```python
fb_over_time = (
    queries.assign(day=pd.to_datetime(queries["created_at"]).dt.date)
           .dropna(subset=["feedback_type"])
           .groupby(["day", "feedback_type"]).size().unstack(fill_value=0)
)
fb_over_time["ratio"] = fb_over_time.get("positive", 0) / (
    fb_over_time.get("positive", 0) + fb_over_time.get("negative", 0)
).replace(0, pd.NA)
print(fb_over_time.tail(20))

fig, ax = plt.subplots(figsize=(10, 3))
fb_over_time["ratio"].plot(ax=ax, marker="o")
ax.set_ylim(0, 1)
ax.set_title("Daily positive feedback ratio")
ax.set_ylabel("positive / (positive + negative)")
charts.save(fig, charts_dir / "06_feedback_ratio.svg")
```

Code cell (confidence-vs-feedback correlation):

```python
fb = queries.dropna(subset=["feedback_type", "confidence_score"])
fig, ax = plt.subplots(figsize=(6, 4))
sns.boxplot(data=fb, x="feedback_type", y="confidence_score", ax=ax)
ax.set_title("Confidence by feedback type")
charts.save(fig, charts_dir / "06_confidence_vs_feedback.svg")

corr = fb.assign(pos=(fb["feedback_type"] == "positive").astype(int))["confidence_score"].corr(
    fb.assign(pos=(fb["feedback_type"] == "positive").astype(int))["pos"]
)
print(f"Point-biserial correlation (confidence vs positive_feedback): {corr:.3f}")
```

Code cell (complaint themes — light NLP):

```python
import re
from collections import Counter

negative = queries[
    (queries["feedback_type"] == "negative") &
    queries["feedback_comment"].notna() &
    (queries["feedback_comment"].astype(str).str.strip() != "")
]
print(f"Negative comments: {len(negative)}")

# Top bigrams as a cheap theme proxy
def tokens(text):
    return re.findall(r"[a-z]{3,}", str(text).lower())

bigrams = Counter()
for c in negative["feedback_comment"]:
    toks = tokens(c)
    for i in range(len(toks) - 1):
        bigrams[(toks[i], toks[i+1])] += 1

print("Top 20 bigrams in negative feedback:")
for bg, n in bigrams.most_common(20):
    print(f"  {n:3d}  {' '.join(bg)}")
```

- [ ] **Step 3: Run all cells**

If `len(negative) < 20`, note in the report that theme extraction sample was too small for confident clustering.

- [ ] **Step 4: Commit**

```bash
git add eval/aurora_eval/analyze.ipynb
git commit -m "feat(eval): notebook Section 6 — user satisfaction"
```

---

## Task 22: Notebook Section 7 — LLM-as-judge results

**Files:**
- Modify: `eval/aurora_eval/analyze.ipynb`

- [ ] **Step 1: Add markdown cell**

```markdown
## Section 7 — Correctness (LLM-as-judge)

Faithfulness, relevance, hallucination rate, citation usefulness — scored by Claude on a stratified sample.
```

- [ ] **Step 2: Add cells**

Code cell (overall summary):

```python
print(f"Judged rows: {len(judgements)}")
print(f"Errors during judging: {judgements['judge_error'].notna().sum()}")
print("\nMean scores by dimension:")
print(judgements[["faithfulness", "relevance", "citation_usefulness"]].mean())
print(f"\nHallucination rate: {judgements['hallucination'].mean():.1%}")
```

Code cell (best/worst examples for report appendix):

```python
def attach_qa(j):
    merged = j.merge(
        queries[["query_id", "question", "answer", "mode", "intent"]],
        on="query_id", how="left", suffixes=("", "_q"),
    )
    return merged

merged = attach_qa(judgements)
worst = merged.sort_values("faithfulness").head(5)[
    ["query_id", "mode", "intent", "faithfulness", "faithfulness_rationale", "question", "answer"]
]
best = merged.sort_values("faithfulness", ascending=False).head(5)[
    ["query_id", "mode", "intent", "faithfulness", "faithfulness_rationale", "question", "answer"]
]
print("\n--- WORST 5 ---")
for _, r in worst.iterrows():
    print(f"\n[{r['query_id']}] mode={r['mode']} intent={r['intent']} faith={r['faithfulness']}")
    print(f"  Q: {r['question'][:200]}")
    print(f"  A: {str(r['answer'])[:200]}")
    print(f"  rationale: {r['faithfulness_rationale']}")

print("\n--- BEST 5 ---")
for _, r in best.iterrows():
    print(f"\n[{r['query_id']}] mode={r['mode']} intent={r['intent']} faith={r['faithfulness']}")
    print(f"  Q: {r['question'][:200]}")
    print(f"  A: {str(r['answer'])[:200]}")
    print(f"  rationale: {r['faithfulness_rationale']}")

# Save for report appendix
worst.to_csv(charts_dir / "07_worst_examples.csv", index=False)
best.to_csv(charts_dir / "07_best_examples.csv", index=False)
```

- [ ] **Step 3: Run all cells**

- [ ] **Step 4: Commit**

```bash
git add eval/aurora_eval/analyze.ipynb
git commit -m "feat(eval): notebook Section 7 — LLM-as-judge results + examples"
```

---

## Task 23: PII / sensitive content scan

Before writing the final markdown report, scan the example questions/answers and feedback comments for content that shouldn't be published.

**Files:**
- Create: `eval/aurora_eval/scrubber.py`
- Create: `eval/tests/test_scrubber.py`

- [ ] **Step 1: Write the failing test**

`eval/tests/test_scrubber.py`:

```python
from aurora_eval import scrubber


def test_scan_finds_emails():
    issues = scrubber.scan("Contact john.doe@example.com for details")
    assert any(i.kind == "email" for i in issues)


def test_scan_finds_phone_numbers():
    issues = scrubber.scan("Call 555-123-4567 if you have questions")
    assert any(i.kind == "phone" for i in issues)


def test_scan_finds_likely_secret():
    issues = scrubber.scan("token: sk-abcdef1234567890abcdef1234567890")
    assert any(i.kind == "secret" for i in issues)


def test_scan_clean_text():
    issues = scrubber.scan("What is Wi-Fi 8 throughput?")
    assert issues == []


def test_redact_replaces_emails():
    redacted = scrubber.redact("Contact john.doe@example.com please")
    assert "john.doe@example.com" not in redacted
    assert "[REDACTED-EMAIL]" in redacted
```

- [ ] **Step 2: Run test, verify failure**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_scrubber.py -v
```

Expected: 5 failed.

- [ ] **Step 3: Write `eval/aurora_eval/scrubber.py`**

```python
"""Detect and redact PII / secrets in text destined for the published report."""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable


_PATTERNS = {
    "email": re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    "secret": re.compile(r"\b(?:sk-|pk-|api[_-]?key[=:\s]*)[A-Za-z0-9_\-]{20,}\b", re.IGNORECASE),
    "ip": re.compile(r"\b(?:10\.|192\.168\.|172\.(?:1[6-9]|2\d|3[01])\.)\d{1,3}\.\d{1,3}\b"),
}

_REDACTIONS = {
    "email": "[REDACTED-EMAIL]",
    "phone": "[REDACTED-PHONE]",
    "secret": "[REDACTED-SECRET]",
    "ip": "[REDACTED-IP]",
}


@dataclass(frozen=True)
class Issue:
    kind: str
    match: str


def scan(text: str) -> list[Issue]:
    if not isinstance(text, str):
        return []
    found: list[Issue] = []
    for kind, pattern in _PATTERNS.items():
        for m in pattern.finditer(text):
            found.append(Issue(kind=kind, match=m.group(0)))
    return found


def redact(text: str) -> str:
    if not isinstance(text, str):
        return text
    out = text
    for kind, pattern in _PATTERNS.items():
        out = pattern.sub(_REDACTIONS[kind], out)
    return out


def scan_dataframe_column(df, column: str) -> list[tuple]:
    """Return list of (row_index, kind, match) for any issues in the column."""
    issues = []
    for idx, value in df[column].items():
        for issue in scan(value or ""):
            issues.append((idx, issue.kind, issue.match))
    return issues
```

- [ ] **Step 4: Run tests, verify pass**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest tests/test_scrubber.py -v
```

Expected: 5 passed.

- [ ] **Step 5: Manually scan the example exports**

```bash
cd eval && PYTHONPATH=. .venv/bin/python -c "
import pandas as pd
from aurora_eval import scrubber

for f in ['charts/07_worst_examples.csv', 'charts/07_best_examples.csv']:
    df = pd.read_csv(f)
    for col in ['question', 'answer', 'faithfulness_rationale']:
        for idx, kind, match in scrubber.scan_dataframe_column(df, col):
            print(f'{f}:{col}:row{idx} {kind}: {match}')
"
```

If anything is reported: redact the affected rows in the CSV before including them in the report, or drop those rows from the example set. Document the redaction in the methodology appendix.

- [ ] **Step 6: Commit**

```bash
git add eval/aurora_eval/scrubber.py eval/tests/test_scrubber.py
git commit -m "feat(eval): PII/secret scrubber for report content"
```

---

## Task 24: Write the final markdown report

**Files:**
- Create: `docs/aurora-production-evaluation-2026-06-02.md`

- [ ] **Step 1: Create the report file with skeleton**

`docs/aurora-production-evaluation-2026-06-02.md`:

```markdown
# Aurora Production Evaluation Report

**Reporting window:** `<EVAL_SINCE>` → `<EVAL_UNTIL>`
**Report generated:** 2026-06-02
**Reproducibility:** `eval/aurora_eval/analyze.ipynb` against the snapshot in `eval/data/`

## Executive summary

> This section is written **last**, after the technical sections are stable. Fill in:
> - Query volume + window
> - Headline latency (p95 fast vs baseline)
> - Cache hit rate
> - 👍/👎 ratio
> - Per-query LLM cost
> - Judge faithfulness (with CI)
> - KG corpus size (nodes + edges)
> - **Verdict paragraph** on the KG-vs-RAG tradeoff
> - **Limitations paragraph** — no ground truth, judge bias, snapshot timeframe

---

## 1. Operational health

[Embed: charts/01_daily_volume.svg]

Latency by pipeline:

| | count | mean | p50 | p95 | p99 |
|---|---|---|---|---|---|
| fast | … | … | … | … | … |
| baseline | … | … | … | … | … |

[Embed: charts/01_latency_histogram.svg]

Error rate: `<X%>` overall (`<Y%>` fast, `<Z%>` baseline). Top error messages:
1. …

Cache hit rate (3-tier):

| | overall | route | result | answer |
|---|---|---|---|---|
| fast | … | … | … | … |
| baseline | … | n/a | n/a | n/a |

[Embed: charts/01_cache_hit_rate.svg]

## 2. KG (fast) vs RAG (baseline)

Headline tradeoff: **fast pipeline is `<faster|slower>` by `<N>`ms median and uses `<more|fewer>` tokens per query, with `<higher|comparable|lower>` LLM-judge correctness.**

Latency: fast median = `<N>`ms, baseline = `<N>`ms (Mann-Whitney p=`<p>`).

Tokens per query: fast mean = `<N>`, baseline = `<N>`.

[Embed: charts/02_tokens_by_mode.svg]
[Embed: charts/02_confidence_by_mode.svg]
[Embed: charts/02_judge_scores_by_mode.svg]

Feedback ratio (positive / total) is `<X>` on fast vs `<Y>` on baseline.

## 3. LLM efficiency

Total tokens over window: `<N>` input, `<N>` output.
Estimated cost (placeholder rates — see methodology): `$<X>` total, `$<Y>` per query.

[Embed: charts/03_tokens_by_prompt_type.svg]

Top prompt types by token spend:

| prompt_type | calls | mean tokens | total tokens | est. $ |
|---|---|---|---|---|
| … | … | … | … | … |

## 4. Document processing

Digester volume: `<N>` log lines over window, peaking at `<N>`/day.

[Embed: charts/04_digester_throughput.svg]

Failure modes: `<N>` DLQ events (`<X>` timeouts, `<Y>` validation errors).

Neo4j corpus snapshot (as of `<captured_at>`):

| Label | Count |
|---|---|
| Document | … |
| Topic | … |
| Person | … |
| Organization | … |
| Event | … |
| Total nodes | … |
| Total relationships | … |
| Orphan nodes | … |

[Embed: charts/04_nodes_by_label.svg]

## 5. Knowledge graph utilization

Distinct fast-pipeline routes used: `<N>` out of `<total_defined>` registered (`<dead_count>` never fired).

[Embed: charts/05_route_hits.svg]

Citation density per answer:

| | count | mean | median |
|---|---|---|---|
| fast | … | … | … |
| baseline | … | … | … |

Coverage gaps (queries that fell back from fast to baseline): `<N>` (`<X%>` of fast attempts), by intent:
1. …

## 6. User satisfaction

Overall feedback: `<positive_n>` 👍 / `<negative_n>` 👎 over `<total_with_feedback>` queries with feedback (`<X%>` of all queries).

[Embed: charts/06_feedback_ratio.svg]

Confidence-vs-feedback: point-biserial correlation `<r>`, suggesting `<the model is|the model is not>` well-calibrated against user judgement.

[Embed: charts/06_confidence_vs_feedback.svg]

Top complaint themes (from negative feedback comments, n=`<n>`):
- …

## 7. Correctness — LLM-as-judge

Sample: `<N>` queries, stratified across pipeline × top intents.
Judge: `<model>`.

Scores (mean ± std):

| | fast | baseline | difference |
|---|---|---|---|
| Faithfulness (0-5) | … | … | … |
| Relevance (0-5) | … | … | … |
| Citation usefulness (0-5) | … | … | … |
| Hallucination rate (boolean) | … | … | … |

[Embed: charts/02_judge_scores_by_mode.svg]

Worst-scoring examples are in Appendix C. Best-scoring examples confirm the system can produce high-quality, well-cited answers in its core question types.

---

## Appendix A — Methodology

**Data sources:** `oracle_query_history` (Postgres), `chat_messages`, `user_feedback`, Neo4j corpus snapshot, Prometheus `/metrics` scrape, Loki structured logs over the window.

**Snapshot taken:** `<timestamp>`.

**LLM-as-judge:**
- Model: `<EVAL_JUDGE_MODEL>`.
- Sample size: `<N>` queries, stratified by (pipeline × top-5 intents).
- Rubric: 0–5 scores on faithfulness, relevance, citation usefulness; boolean hallucination flag. Full prompt in `eval/aurora_eval/judge.py`.
- Known biases: LLM judges tend to over-score verbose answers; we mitigate with explicit citation-grounding requirements in the rubric and report all rationales. Numbers should be treated as relative, not absolute.

**Cost estimate:** rates assumed from `<source URL>` as of `<date>`. Replace placeholders before publishing.

**What this report cannot tell you:** correctness against a domain-expert-authored ground truth (no such dataset exists). Faithfulness numbers measure consistency with cited documents, not whether the cited documents themselves are correct or complete.

## Appendix B — Glossary

- **Fast pipeline / KG-first**: query is routed through a Cypher template + Neo4j lookup before falling back to the broader baseline pipeline.
- **Baseline pipeline / RAG**: traditional retrieval-augmented generation using vector + keyword retrieval and LLM synthesis.
- **Route plan / route_id**: identifier of the Cypher template chosen for a fast-pipeline query.
- **Intent**: high-level classification of the user's question (FACTUAL, ANALYTICAL, COMPARATIVE, TEMPORAL, ENTITY).
- **Confidence score**: model-estimated confidence in its answer, 0.0–1.0.
- **Cache tiers**: plan cache (route plan), result cache (Neo4j results), answer cache (final answer). All keyed in Redis.

## Appendix C — Sample judged answers

### Worst-scoring (faithfulness)

> Imported from `eval/charts/07_worst_examples.csv` post-scrubber pass.

| query_id | mode | intent | faithfulness | question | rationale |
|---|---|---|---|---|---|
| … | … | … | … | … | … |

### Best-scoring (faithfulness)

| query_id | mode | intent | faithfulness | question | rationale |
|---|---|---|---|---|---|
| … | … | … | … | … | … |
```

- [ ] **Step 2: Fill in numbers and embeds from notebook outputs**

For each `[Embed: charts/...]` placeholder, replace with the markdown image syntax:

```markdown
![<title>](../eval/charts/01_daily_volume.svg)
```

For each `<N>` / `<X>` placeholder, copy the value from the notebook output.

For the appendix tables, paste rows from the worst/best CSVs after running them through the scrubber.

- [ ] **Step 3: Write the executive summary last**

Once all sections have numbers, write the executive summary at the top. Stick to:
- 1 paragraph: scope + window + headline numbers.
- 1 paragraph: KG-vs-RAG verdict (what's the system actually buying us?).
- 1 paragraph: limitations (no ground truth, judge bias, single-snapshot timeframe).

- [ ] **Step 4: Render-check**

```bash
# Confirm GitHub-style markdown renders the embedded SVGs
ls docs/aurora-production-evaluation-2026-06-02.md
# Open in a markdown previewer of your choice
```

- [ ] **Step 5: Commit**

```bash
git add docs/aurora-production-evaluation-2026-06-02.md
git commit -m "docs: production evaluation report 2026-06-02"
```

---

## Task 25: Final review pass

**Files:** all created above.

- [ ] **Step 1: Run the full test suite**

```bash
cd eval && PYTHONPATH=. .venv/bin/pytest -v
```

Expected: all green.

- [ ] **Step 2: Re-run the notebook top-to-bottom**

Open `eval/aurora_eval/analyze.ipynb`, Cell → Run All. Confirm every cell still executes cleanly and that all referenced charts in the report exist in `eval/charts/`.

- [ ] **Step 3: Sanity-check every number in the report against the notebook**

For every figure quoted in the markdown report, find the source in the notebook output. If any number is undefined or out of sync, fix and recommit.

- [ ] **Step 4: Re-run the scrubber against the final report**

```bash
cd eval && PYTHONPATH=. .venv/bin/python -c "
from pathlib import Path
from aurora_eval import scrubber
text = Path('../docs/aurora-production-evaluation-2026-06-02.md').read_text()
for issue in scrubber.scan(text):
    print(issue)
"
```

Expected: no output. If anything is reported, redact and recommit.

- [ ] **Step 5: Confirm caveats section is honest**

The methodology appendix must explicitly state:
- No ground truth corpus exists; correctness numbers come from LLM-as-judge only.
- Pricing in section 3 is placeholder unless verified.
- Single-snapshot; not a longitudinal trend.

If any of these aren't present, add them.

- [ ] **Step 6: Final commit**

```bash
git status
# If there are any uncommitted changes from review fixes:
git add -A
git commit -m "docs: final review pass for evaluation report"
```

---

## Done — handoff

Final artifacts:

1. `eval/aurora_eval/` — reproducible analysis package with tests
2. `eval/aurora_eval/analyze.ipynb` — notebook driving every chart and number
3. `eval/data/` — snapshot inputs (gitignored)
4. `eval/charts/` — rendered charts (gitignored)
5. `docs/aurora-production-evaluation-2026-06-02.md` — the report

To re-run later: delete `eval/data/` and `eval/charts/`, run `cli scout`, choose the window, run `cli dump`, run `cli judge`, re-execute the notebook, then refresh the numbers in the markdown report.
