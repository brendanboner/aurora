#!/usr/bin/env python3
"""Aurora production evaluation report generator.

One-shot script that pulls production telemetry (oracle_query_history Postgres
table, Neo4j corpus snapshot) and produces a markdown report with charts.
Optionally runs an LLM-as-judge pass on a stratified sample of queries.

Run from the prod EC2 box (after `make connect_aurora_ec2`) or from anywhere
that can reach prod Postgres + Neo4j.

Required env vars:
  POSTGRES_HOST POSTGRES_PORT POSTGRES_DB POSTGRES_USER POSTGRES_PASSWORD
  NEO4J_URI NEO4J_USER NEO4J_PASSWORD   (optional — skip with --no-neo4j)
  AZURE_OPENAI_ENDPOINT AZURE_OPENAI_API_KEY AZURE_OPENAI_API_VERSION
  AZURE_OPENAI_DEPLOYMENT               (all four required for --judge)

Usage:
  python eval_aurora.py                            # full report, no judge
  python eval_aurora.py --judge --sample 100       # add LLM-as-judge
  python eval_aurora.py --since 2026-01-01         # restrict window
  python eval_aurora.py --no-neo4j                 # skip KG snapshot
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd
import psycopg2
import seaborn as sns

sns.set_theme(style="whitegrid")

log = logging.getLogger("eval_aurora")

OUT_DIR = Path("eval_output")
CHARTS_DIR = OUT_DIR / "charts"
REPORT_DATE = datetime.now(timezone.utc).strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--since", default=None, help="ISO date, e.g. 2026-01-01")
    p.add_argument("--until", default=None, help="ISO date, default = now")
    p.add_argument("--no-neo4j", action="store_true", help="Skip Neo4j snapshot")
    p.add_argument("--judge", action="store_true", help="Run LLM-as-judge on a sample")
    p.add_argument("--sample", type=int, default=100, help="Judge sample size")
    p.add_argument("--judge-deployment", default=None,
                   help="Azure OpenAI deployment to use for judging (defaults to $AZURE_OPENAI_DEPLOYMENT)")
    p.add_argument("--refresh", action="store_true",
                   help="Force re-pulling DB and re-running judge even if cached parquets exist")
    p.add_argument("--azure-input-price", type=float, default=0.0025,
                   help="USD per 1K input tokens (default = gpt-4o rate; verify for your model)")
    p.add_argument("--azure-output-price", type=float, default=0.010,
                   help="USD per 1K output tokens (default = gpt-4o rate; verify for your model)")
    return p.parse_args()


# ---------------------------------------------------------------------------
# Data pull
# ---------------------------------------------------------------------------

QUERY_HISTORY_SQL = """
    SELECT
        query_id, created_at, user_id, question, mode, effective_mode,
        answer, citations, documents, intent, intent_confidence,
        confidence_score, confidence_level, documents_count, total_candidates,
        processing_time_ms, llm_tokens_used, cache_hit, strategies_used,
        feedback_type, feedback_comment, feedback_at,
        error, error_message, request_options
    FROM oracle_query_history
    WHERE (%s IS NULL OR created_at >= %s)
      AND (%s IS NULL OR created_at <  %s)
    ORDER BY created_at
"""


def pull_query_history(since: datetime | None, until: datetime | None) -> pd.DataFrame:
    conn_kwargs = dict(
        host=os.environ.get("POSTGRES_HOST", "aurora-postgres"),
        port=int(os.environ.get("POSTGRES_PORT", "5432")),
        dbname=os.environ.get("POSTGRES_DB", "aurora"),
        user=os.environ.get("POSTGRES_USER", "aurora"),
        password=os.environ["POSTGRES_PASSWORD"],
    )
    log.info("Connecting to Postgres at %s:%s/%s", conn_kwargs["host"], conn_kwargs["port"], conn_kwargs["dbname"])
    with psycopg2.connect(**conn_kwargs) as conn:
        df = pd.read_sql_query(
            QUERY_HISTORY_SQL,
            conn,
            params=(since, since, until, until),
        )
    log.info("Pulled %d rows from oracle_query_history", len(df))

    # request_options arrives as dict (psycopg2 auto-decodes JSONB); citations/documents/strategies_used same.
    df["pipeline"] = df["request_options"].apply(
        lambda o: (o or {}).get("pipeline") if isinstance(o, dict) else None
    )
    df["pipeline"] = df["pipeline"].fillna("unspecified")

    df["citations_count"] = df["citations"].apply(
        lambda c: len(c) if isinstance(c, list) else 0
    )
    df["documents_returned"] = df["documents"].apply(
        lambda d: len(d) if isinstance(d, list) else 0
    )

    def cache_field(opts, field):
        if not isinstance(opts, dict):
            return None
        cache = opts.get("cache") or {}
        return cache.get(field)

    for fld in ("overall_hit", "route_hit", "result_hit", "answer_hit"):
        df[f"cache_{fld}"] = df["request_options"].apply(lambda o: cache_field(o, fld))

    return df


def pull_neo4j_snapshot() -> dict | None:
    try:
        from neo4j import GraphDatabase
    except ImportError:
        log.warning("neo4j driver not installed — skipping KG snapshot")
        return None
    uri = os.environ.get("NEO4J_URI", "bolt://localhost:7687")
    user = os.environ.get("NEO4J_USER", "neo4j")
    password = os.environ.get("NEO4J_PASSWORD")
    if not password:
        log.warning("NEO4J_PASSWORD not set — skipping KG snapshot")
        return None
    log.info("Connecting to Neo4j at %s", uri)
    # Label names match the actual production schema: Resource is the content
    # node (was wrongly queried as :Document before); Agent nodes are populated
    # by oracle/scripts/sync_agents_to_neo4j.py.
    queries = {
        "total_nodes": "MATCH (n) RETURN COUNT(n) AS v",
        "total_relationships": "MATCH ()-[r]->() RETURN COUNT(r) AS v",
        "nodes_by_label": (
            "MATCH (n) UNWIND labels(n) AS label "
            "RETURN label, COUNT(*) AS count ORDER BY count DESC"
        ),
        "relationships_by_type": (
            "MATCH ()-[r]->() RETURN type(r) AS type, COUNT(*) AS count "
            "ORDER BY count DESC"
        ),
        "orphan_nodes": "MATCH (n) WHERE NOT (n)--() RETURN COUNT(n) AS v",
        "resources": "MATCH (n:Resource) RETURN COUNT(n) AS v",
        "datasources": "MATCH (n:DataSource) RETURN COUNT(n) AS v",
        "ingestion_batches": "MATCH (n:IngestionBatch) RETURN COUNT(n) AS v",
        "topics": "MATCH (n:Topic) RETURN COUNT(n) AS v",
        "people": "MATCH (n:Person) RETURN COUNT(n) AS v",
        "organizations": "MATCH (n:Organization) RETURN COUNT(n) AS v",
        "events": "MATCH (n:Event) RETURN COUNT(n) AS v",
        "agents": "MATCH (n:Agent) RETURN COUNT(n) AS v",
    }
    out: dict = {"captured_at": datetime.now(timezone.utc).isoformat()}
    driver = GraphDatabase.driver(uri, auth=(user, password))
    try:
        with driver.session() as s:
            for key, q in queries.items():
                rows = s.run(q).data()
                if not rows:
                    out[key] = None
                elif len(rows) == 1 and "v" in rows[0]:
                    out[key] = rows[0]["v"]
                else:
                    out[key] = rows
    finally:
        driver.close()
    return out


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def chart(name: str, fig: plt.Figure) -> Path:
    CHARTS_DIR.mkdir(parents=True, exist_ok=True)
    out = CHARTS_DIR / f"{name}.png"
    fig.savefig(out, dpi=130, bbox_inches="tight")
    plt.close(fig)
    return out


def chart_daily_volume(df: pd.DataFrame) -> Path:
    df = df.copy()
    df["day"] = pd.to_datetime(df["created_at"]).dt.date
    daily = df.groupby("day").size()
    fig, ax = plt.subplots(figsize=(10, 3))
    daily.plot(ax=ax, color="#3b82f6")
    ax.set_title("Daily query volume")
    ax.set_ylabel("Queries")
    return chart("01_daily_volume", fig)


def chart_latency_by_pipeline(df: pd.DataFrame) -> Path:
    fig, ax = plt.subplots(figsize=(9, 4))
    pipelines = df["pipeline"].dropna().unique()
    for p in sorted(pipelines):
        sub = df[df["pipeline"] == p]["processing_time_ms"].dropna()
        if len(sub):
            ax.hist(sub.clip(upper=10000), bins=40, alpha=0.5, label=f"{p} (n={len(sub)})")
    ax.set_xlabel("Latency (ms, clipped at 10s)")
    ax.set_ylabel("Queries")
    ax.set_title("Query latency distribution by pipeline")
    ax.legend()
    return chart("02_latency_by_pipeline", fig)


def chart_confidence_by_pipeline(df: pd.DataFrame) -> Path:
    sub = df.dropna(subset=["confidence_score", "pipeline"])
    if sub.empty:
        return None
    fig, ax = plt.subplots(figsize=(7, 4))
    sns.violinplot(data=sub, x="pipeline", y="confidence_score", ax=ax)
    ax.set_ylim(0, 1)
    ax.set_title("Confidence score by pipeline")
    return chart("03_confidence_by_pipeline", fig)


def chart_tokens_by_pipeline(df: pd.DataFrame) -> Path | None:
    sub = df.dropna(subset=["llm_tokens_used", "pipeline"])
    if sub.empty:
        return None
    fig, ax = plt.subplots(figsize=(7, 4))
    sns.boxplot(data=sub, x="pipeline", y="llm_tokens_used", showfliers=False, ax=ax)
    ax.set_title("LLM tokens per query by pipeline")
    return chart("04_tokens_by_pipeline", fig)


def chart_cache_hit_rate(df: pd.DataFrame) -> Path | None:
    if df["cache_overall_hit"].isna().all():
        return None
    rates = df.dropna(subset=["pipeline"]).groupby("pipeline")[
        ["cache_overall_hit", "cache_route_hit", "cache_result_hit", "cache_answer_hit"]
    ].mean()
    fig, ax = plt.subplots(figsize=(8, 4))
    rates.plot.bar(ax=ax)
    ax.set_ylim(0, 1)
    ax.set_title("Cache hit rate by pipeline (3-tier)")
    ax.set_ylabel("Hit rate")
    ax.legend(loc="upper right")
    return chart("05_cache_hit_rate", fig)


def chart_intent_distribution(df: pd.DataFrame) -> Path:
    counts = df["intent"].dropna().value_counts().head(15)
    fig, ax = plt.subplots(figsize=(8, 4))
    counts.plot.barh(ax=ax, color="#10b981")
    ax.invert_yaxis()
    ax.set_xlabel("Queries")
    ax.set_title("Query intent distribution")
    return chart("06_intent_distribution", fig)


def chart_feedback_over_time(df: pd.DataFrame) -> Path | None:
    fb = df.dropna(subset=["feedback_type"]).copy()
    if fb.empty:
        return None
    fb["day"] = pd.to_datetime(fb["created_at"]).dt.date
    grouped = fb.groupby(["day", "feedback_type"]).size().unstack(fill_value=0)
    if "positive" not in grouped.columns:
        grouped["positive"] = 0
    if "negative" not in grouped.columns:
        grouped["negative"] = 0
    grouped["ratio"] = grouped["positive"] / (grouped["positive"] + grouped["negative"]).replace(0, pd.NA)
    fig, ax = plt.subplots(figsize=(10, 3))
    grouped["ratio"].plot(ax=ax, marker="o", color="#f59e0b")
    ax.set_ylim(0, 1)
    ax.set_title("Daily positive feedback ratio")
    ax.set_ylabel("positive / (positive + negative)")
    return chart("07_feedback_ratio", fig)


def chart_neo4j_labels(snapshot: dict) -> Path | None:
    labels = snapshot.get("nodes_by_label")
    if not isinstance(labels, list) or not labels:
        return None
    df = pd.DataFrame(labels)
    fig, ax = plt.subplots(figsize=(8, 4))
    df.set_index("label")["count"].sort_values().plot.barh(ax=ax, color="#8b5cf6")
    ax.set_xlabel("Nodes")
    ax.set_title("Neo4j nodes by label")
    return chart("08_neo4j_labels", fig)


# ---------------------------------------------------------------------------
# LLM-as-judge
# ---------------------------------------------------------------------------

JUDGE_SYSTEM_PROMPT = """You are evaluating answers from a Wi-Fi Alliance Q&A system that uses RAG + a knowledge graph.

For each (question, answer, citations), return a JSON object with these fields exactly:
{
  "faithfulness": 0-5,         # are claims supported by the citations?
  "faithfulness_rationale": "one sentence",
  "relevance": 0-5,            # does the answer address the question?
  "relevance_rationale": "one sentence",
  "hallucination": true|false, # any specific factual claim not supported?
  "hallucination_rationale": "one sentence",
  "citation_usefulness": 0-5,  # would the citations help a reader verify?
  "citation_usefulness_rationale": "one sentence"
}

Return ONLY the JSON object, no markdown, no surrounding text.
"""


def stratified_sample(df: pd.DataFrame, n: int) -> pd.DataFrame:
    eligible = df[
        (df["error"] != True) &  # noqa: E712
        df["answer"].astype(str).str.strip().ne("") &
        df["question"].astype(str).str.strip().ne("")
    ].copy()
    if eligible.empty:
        return eligible
    # Stratify by pipeline × intent (drop rare strata)
    by = ["pipeline", "intent"]
    groups = eligible.groupby(by, dropna=False)
    n_strata = len(groups)
    per = max(1, n // n_strata)
    picked = pd.concat(
        [g.sample(min(len(g), per), random_state=42) for _, g in groups],
        ignore_index=True,
    )
    return picked


def run_judge(sample: pd.DataFrame, deployment: str) -> pd.DataFrame:
    from openai import AzureOpenAI

    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )
    records: list[dict] = []
    for i, row in sample.iterrows():
        citations = row.get("citations") or []
        cite_block = "\n".join(
            f"[{j+1}] {c.get('title', '(no title)')} — {c.get('url', '')}\n  snippet: {c.get('snippet', '')[:400]}"
            for j, c in enumerate(citations[:8])
        ) or "(no citations)"
        prompt = (
            f"Question:\n{row['question']}\n\n"
            f"Answer:\n{row['answer']}\n\n"
            f"Citations:\n{cite_block}\n\n"
            f"Score this answer."
        )
        rec = {
            "query_id": row["query_id"],
            "pipeline": row["pipeline"],
            "intent": row.get("intent"),
        }
        try:
            resp = client.chat.completions.create(
                model=deployment,
                max_tokens=800,
                messages=[
                    {"role": "system", "content": JUDGE_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                response_format={"type": "json_object"},
            )
            raw = resp.choices[0].message.content or ""
            m = re.search(r"\{.*\}", raw, re.DOTALL)
            if not m:
                raise ValueError(f"no JSON in response: {raw[:200]}")
            scored = json.loads(m.group(0))
            rec.update({
                "faithfulness": scored["faithfulness"],
                "relevance": scored["relevance"],
                "hallucination": scored["hallucination"],
                "citation_usefulness": scored["citation_usefulness"],
                "faithfulness_rationale": scored.get("faithfulness_rationale"),
                "relevance_rationale": scored.get("relevance_rationale"),
                "judge_error": None,
            })
            if (i + 1) % 10 == 0:
                log.info("Judged %d/%d", i + 1, len(sample))
        except Exception as exc:  # noqa: BLE001
            log.warning("Judge failed for %s: %s", row["query_id"], exc)
            rec.update({
                "faithfulness": None, "relevance": None, "hallucination": None,
                "citation_usefulness": None, "faithfulness_rationale": None,
                "relevance_rationale": None, "judge_error": str(exc),
            })
        records.append(rec)
    return pd.DataFrame(records)


# ---------------------------------------------------------------------------
# Light PII scrub for the appendix
# ---------------------------------------------------------------------------

_PII = {
    "email": re.compile(r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"),
    "phone": re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b"),
    "secret": re.compile(r"\b(?:sk-|api[_-]?key[=:\s])\S{15,}", re.IGNORECASE),
}


def scrub(text: str) -> str:
    if not isinstance(text, str):
        return ""
    out = text
    for kind, pat in _PII.items():
        out = pat.sub(f"[REDACTED-{kind.upper()}]", out)
    return out


# ---------------------------------------------------------------------------
# Report writer
# ---------------------------------------------------------------------------

def _fmt(x, fmt=".2f"):
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return "—"
    return format(x, fmt)


def _percentiles(s: pd.Series) -> dict:
    if s.dropna().empty:
        return {"n": 0, "mean": None, "p50": None, "p95": None, "p99": None}
    s = s.dropna()
    return {
        "n": len(s),
        "mean": s.mean(),
        "p50": s.quantile(0.50),
        "p95": s.quantile(0.95),
        "p99": s.quantile(0.99),
    }


def write_report(
    df: pd.DataFrame,
    neo4j: dict | None,
    judgements: pd.DataFrame | None,
    args,
    charts_made: dict[str, Path],
) -> Path:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = OUT_DIR / f"aurora-production-evaluation-{REPORT_DATE}.md"
    rel = lambda p: f"charts/{p.name}" if p else None  # noqa: E731

    earliest = pd.to_datetime(df["created_at"]).min()
    latest = pd.to_datetime(df["created_at"]).max()

    by_pipe_latency = {
        p: _percentiles(g["processing_time_ms"])
        for p, g in df.groupby("pipeline")
    }
    by_pipe_tokens = {
        p: _percentiles(g["llm_tokens_used"])
        for p, g in df.groupby("pipeline")
    }
    by_pipe_conf = {
        p: _percentiles(g["confidence_score"])
        for p, g in df.groupby("pipeline")
    }

    total_tokens = df["llm_tokens_used"].fillna(0).sum()
    # Rough cost: split half/half input/output (no per-call breakdown in this table)
    est_cost = (total_tokens / 1000) * ((args.azure_input_price + args.azure_output_price) / 2)
    per_query_cost = est_cost / max(len(df), 1)

    err_rate = df["error"].mean() if "error" in df else None

    fb_pos = (df["feedback_type"] == "positive").sum()
    fb_neg = (df["feedback_type"] == "negative").sum()
    fb_total = fb_pos + fb_neg
    fb_ratio = fb_pos / fb_total if fb_total else None

    pipeline_counts = df["pipeline"].value_counts().to_dict()

    cache_rates = {}
    for p, g in df.groupby("pipeline"):
        cache_rates[p] = {
            tier: g[f"cache_{tier}"].mean() for tier in ("overall_hit", "route_hit", "result_hit", "answer_hit")
        }

    # Intent distribution
    intent_top = df["intent"].value_counts().head(10).to_dict()

    # Citation density
    cite_by_pipe = df.groupby("pipeline")["citations_count"].agg(["count", "mean", "median"]).to_dict("index")

    # Judge summary
    judge_summary = {}
    judge_best, judge_worst = None, None
    if judgements is not None and not judgements.empty:
        for p, g in judgements.groupby("pipeline"):
            judge_summary[p] = {
                "n": len(g),
                "faithfulness_mean": g["faithfulness"].mean(),
                "relevance_mean": g["relevance"].mean(),
                "citation_usefulness_mean": g["citation_usefulness"].mean(),
                "hallucination_rate": g["hallucination"].mean(),
            }
        merged = judgements.merge(
            df[["query_id", "question", "answer"]], on="query_id", how="left"
        )
        scored = merged[merged["faithfulness"].notna()]
        if not scored.empty:
            judge_worst = scored.sort_values("faithfulness").head(5)
            judge_best = scored.sort_values("faithfulness", ascending=False).head(5)

    # Negative feedback themes (top bigrams)
    neg_comments = df[
        (df["feedback_type"] == "negative") &
        df["feedback_comment"].notna() &
        (df["feedback_comment"].astype(str).str.strip() != "")
    ]["feedback_comment"].astype(str).tolist()
    bigrams: Counter = Counter()
    for c in neg_comments:
        toks = re.findall(r"[a-z]{3,}", c.lower())
        for i in range(len(toks) - 1):
            bigrams[(toks[i], toks[i + 1])] += 1
    top_neg_bigrams = bigrams.most_common(15)

    md = []
    md.append(f"# Aurora Production Evaluation Report")
    md.append("")
    md.append(f"**Window:** {earliest} → {latest}  ")
    md.append(f"**Generated:** {REPORT_DATE}  ")
    md.append(f"**Query volume:** {len(df):,}  ")
    md.append(f"**Source:** `oracle_query_history` Postgres table + Neo4j corpus snapshot")
    md.append("")
    md.append("---")
    md.append("")

    # -- Executive summary --
    md.append("## Executive summary")
    md.append("")
    pipe_lines = ", ".join(f"{p}: {n:,}" for p, n in sorted(pipeline_counts.items(), key=lambda x: -x[1]))
    md.append(f"- **Pipeline split:** {pipe_lines}")

    if "fast" in by_pipe_latency or "baseline" in by_pipe_latency:
        f_p95 = by_pipe_latency.get("fast", {}).get("p95")
        b_p95 = by_pipe_latency.get("baseline", {}).get("p95")
        md.append(f"- **p95 latency:** fast = {_fmt(f_p95, '.0f')} ms, baseline = {_fmt(b_p95, '.0f')} ms")
    else:
        all_p95 = df["processing_time_ms"].quantile(0.95)
        md.append(f"- **p95 latency:** {_fmt(all_p95, '.0f')} ms (no pipeline tag on rows)")

    md.append(f"- **Error rate:** {_fmt((err_rate or 0) * 100, '.2f')}%")

    if fb_total:
        md.append(f"- **User feedback:** {fb_pos:,} 👍 / {fb_neg:,} 👎 ({_fmt(fb_ratio * 100, '.0f')}% positive over {fb_total:,} rated)")
    else:
        md.append("- **User feedback:** none captured in the window")

    md.append(f"- **Total LLM tokens:** {int(total_tokens):,}")
    md.append(f"- **Estimated LLM cost over window:** ${_fmt(est_cost)} (per-query avg ${_fmt(per_query_cost, '.4f')}, see methodology)")

    if neo4j:
        md.append(f"- **KG corpus:** {neo4j.get('total_nodes', '?'):,} nodes / {neo4j.get('total_relationships', '?'):,} relationships; resources={neo4j.get('resources', '?'):,}; agents={neo4j.get('agents', '?'):,}")

    if judge_summary:
        for p, s in judge_summary.items():
            hallu = s["hallucination_rate"] or 0
            md.append(f"- **LLM-judge ({p}):** faithfulness {_fmt(s['faithfulness_mean'])}, relevance {_fmt(s['relevance_mean'])}, hallucination rate {_fmt(hallu * 100, '.0f')}% (n={s['n']})")

    md.append("")
    md.append("**Verdict.** _Fill in 2–3 sentences based on the numbers above. Suggested framing: did the fast/KG pipeline meaningfully reduce latency or token cost vs. baseline at comparable correctness?_")
    md.append("")
    md.append("**Limitations.** No domain-expert ground-truth corpus exists; correctness numbers are LLM-judge scored (claude-opus-4-7 by default) and should be read as relative, not absolute. All numbers are a single snapshot over the window above; this is not a longitudinal trend report.")
    md.append("")
    md.append("---")
    md.append("")

    # -- Section 1: Operational health --
    md.append("## 1. Operational health")
    md.append("")
    if "01_daily_volume" in charts_made:
        md.append(f"![Daily volume]({rel(charts_made['01_daily_volume'])})")
        md.append("")

    md.append("### Latency")
    md.append("")
    md.append("| pipeline | n | mean (ms) | p50 | p95 | p99 |")
    md.append("|---|---|---|---|---|---|")
    for p, stats in sorted(by_pipe_latency.items()):
        md.append(f"| {p} | {stats['n']:,} | {_fmt(stats['mean'], '.0f')} | {_fmt(stats['p50'], '.0f')} | {_fmt(stats['p95'], '.0f')} | {_fmt(stats['p99'], '.0f')} |")
    md.append("")
    if "02_latency_by_pipeline" in charts_made:
        md.append(f"![Latency]({rel(charts_made['02_latency_by_pipeline'])})")
        md.append("")

    md.append("### Errors")
    md.append("")
    md.append(f"Overall error rate: **{_fmt((err_rate or 0) * 100, '.2f')}%**")
    md.append("")
    if df["error"].any():
        top_err = df[df["error"] == True]["error_message"].value_counts().head(10)  # noqa: E712
        md.append("Top error messages:")
        md.append("")
        md.append("| count | error |")
        md.append("|---|---|")
        for msg, n in top_err.items():
            md.append(f"| {n} | `{scrub(str(msg))[:200]}` |")
        md.append("")

    md.append("### Cache hit rate (3-tier)")
    md.append("")
    md.append("| pipeline | overall | route | result | answer |")
    md.append("|---|---|---|---|---|")
    for p, tiers in sorted(cache_rates.items()):
        md.append(f"| {p} | {_fmt((tiers['overall_hit'] or 0) * 100, '.1f')}% | {_fmt((tiers['route_hit'] or 0) * 100, '.1f')}% | {_fmt((tiers['result_hit'] or 0) * 100, '.1f')}% | {_fmt((tiers['answer_hit'] or 0) * 100, '.1f')}% |")
    md.append("")
    if "05_cache_hit_rate" in charts_made:
        md.append(f"![Cache hit rate]({rel(charts_made['05_cache_hit_rate'])})")
        md.append("")

    # -- Section 2: KG vs RAG --
    md.append("## 2. KG (fast) vs RAG (baseline)")
    md.append("")

    md.append("### Tokens per query")
    md.append("")
    md.append("| pipeline | n | mean | p50 | p95 |")
    md.append("|---|---|---|---|---|")
    for p, stats in sorted(by_pipe_tokens.items()):
        md.append(f"| {p} | {stats['n']:,} | {_fmt(stats['mean'], '.0f')} | {_fmt(stats['p50'], '.0f')} | {_fmt(stats['p95'], '.0f')} |")
    md.append("")
    if "04_tokens_by_pipeline" in charts_made:
        md.append(f"![Tokens]({rel(charts_made['04_tokens_by_pipeline'])})")
        md.append("")

    md.append("### Confidence")
    md.append("")
    md.append("| pipeline | n | mean | p50 | p95 |")
    md.append("|---|---|---|---|---|")
    for p, stats in sorted(by_pipe_conf.items()):
        md.append(f"| {p} | {stats['n']:,} | {_fmt(stats['mean'])} | {_fmt(stats['p50'])} | {_fmt(stats['p95'])} |")
    md.append("")
    if "03_confidence_by_pipeline" in charts_made:
        md.append(f"![Confidence]({rel(charts_made['03_confidence_by_pipeline'])})")
        md.append("")

    # -- Section 3: LLM efficiency --
    md.append("## 3. LLM efficiency")
    md.append("")
    md.append(f"- Total LLM tokens over window: **{int(total_tokens):,}**")
    md.append(f"- Average tokens per query: **{_fmt(df['llm_tokens_used'].mean(), '.0f')}**")
    md.append(f"- Estimated cost: **${_fmt(est_cost)}** total, **${_fmt(per_query_cost, '.4f')}** per query")
    md.append("")
    md.append("Cost estimate uses rates: input ${:.4f}, output ${:.4f} per 1K tokens (placeholder — confirm against Azure OpenAI pricing for the deployed model).".format(
        args.azure_input_price, args.azure_output_price
    ))
    md.append("")
    md.append("> Per-prompt-type breakdown requires parsing structured Loki logs and is omitted from this one-shot script. To add it, follow the methodology section: filter Loki for `llm.prompt_type` and aggregate.")
    md.append("")

    # -- Section 4: KG utilization --
    md.append("## 4. Knowledge graph utilization")
    md.append("")
    md.append("### Intent distribution")
    md.append("")
    md.append("| intent | queries |")
    md.append("|---|---|")
    for intent, n in intent_top.items():
        md.append(f"| {intent} | {n:,} |")
    md.append("")
    if "06_intent_distribution" in charts_made:
        md.append(f"![Intents]({rel(charts_made['06_intent_distribution'])})")
        md.append("")

    md.append("### Citation density")
    md.append("")
    md.append("| pipeline | count | mean citations | median citations |")
    md.append("|---|---|---|---|")
    for p, stats in cite_by_pipe.items():
        md.append(f"| {p} | {int(stats['count']):,} | {_fmt(stats['mean'])} | {_fmt(stats['median'])} |")
    md.append("")

    if neo4j:
        md.append("### Neo4j corpus snapshot")
        md.append("")
        md.append(f"Captured at: `{neo4j.get('captured_at')}`")
        md.append("")
        md.append("| metric | value |")
        md.append("|---|---|")
        for k in ("total_nodes", "total_relationships", "orphan_nodes",
                  "resources", "ingestion_batches", "datasources",
                  "topics", "people", "organizations", "events", "agents"):
            v = neo4j.get(k)
            md.append(f"| {k} | {v:,} |" if isinstance(v, int) else f"| {k} | {v} |")
        md.append("")
        if "08_neo4j_labels" in charts_made:
            md.append(f"![Neo4j nodes]({rel(charts_made['08_neo4j_labels'])})")
            md.append("")

    # -- Section 5: User satisfaction --
    md.append("## 5. User satisfaction")
    md.append("")
    if fb_total:
        md.append(f"- {fb_pos:,} 👍 / {fb_neg:,} 👎 across {fb_total:,} rated queries")
        md.append(f"- Positive ratio: **{_fmt(fb_ratio * 100, '.1f')}%**")
        md.append(f"- Rated coverage: **{_fmt(fb_total / len(df) * 100, '.1f')}%** of all queries")
        md.append("")
        if "07_feedback_ratio" in charts_made:
            md.append(f"![Feedback]({rel(charts_made['07_feedback_ratio'])})")
            md.append("")
        if top_neg_bigrams:
            md.append("Top bigrams in negative feedback comments:")
            md.append("")
            md.append("| count | phrase |")
            md.append("|---|---|")
            for bg, n in top_neg_bigrams:
                md.append(f"| {n} | {' '.join(bg)} |")
            md.append("")
    else:
        md.append("No user feedback captured during this window.")
        md.append("")

    # -- Section 6: Correctness (judge) --
    md.append("## 6. Correctness (LLM-as-judge)")
    md.append("")
    if not judge_summary:
        md.append("LLM-as-judge was not run (use `--judge` to enable).")
        md.append("")
    else:
        deployment_label = getattr(args, "judge_deployment", None) or os.environ.get("AZURE_OPENAI_DEPLOYMENT", "?")
        md.append(f"Sample: stratified by (pipeline × intent), Azure OpenAI deployment = `{deployment_label}`.")
        md.append("")
        md.append("| pipeline | n | faithfulness | relevance | citation usefulness | hallucination rate |")
        md.append("|---|---|---|---|---|---|")
        for p, s in judge_summary.items():
            md.append(
                f"| {p} | {s['n']} | {_fmt(s['faithfulness_mean'])} | {_fmt(s['relevance_mean'])} | "
                f"{_fmt(s['citation_usefulness_mean'])} | {_fmt((s['hallucination_rate'] or 0) * 100, '.0f')}% |"
            )
        md.append("")
        md.append("> Faithfulness, relevance, citation usefulness are 0–5 (higher is better).")
        md.append("")

    # -- Appendix --
    md.append("---")
    md.append("")
    md.append("## Appendix A — Methodology")
    md.append("")
    md.append(f"- **Window:** {earliest} → {latest}")
    md.append(f"- **Total rows:** {len(df):,}")
    md.append(f"- **Pipeline tagging:** read from `request_options->>'pipeline'`; rows without this tag are bucketed as `unspecified`.")
    md.append(f"- **Cost rates (placeholder):** input ${args.azure_input_price}/1K, output ${args.azure_output_price}/1K tokens. Verify against the current Azure OpenAI pricing for the deployed model before publishing.")
    if judge_summary:
        md.append(f"- **LLM-as-judge:** Azure OpenAI deployment `{getattr(args, 'judge_deployment', os.environ.get('AZURE_OPENAI_DEPLOYMENT', '?'))}`, sample size {args.sample}, stratified by (pipeline × intent). Rubric: 0–5 on faithfulness, relevance, citation usefulness; boolean hallucination flag. Full prompt embedded in `eval_aurora.py`.")
        md.append(f"- **Judge biases:** (1) LLMs tend to over-score verbose answers; (2) judge and answer-generator share the same model family (gpt-4o), so self-judge bias may inflate scores. Treat absolute numbers as relative; the more useful signal is the *delta between pipelines*, which any shared bias cancels out.")
    md.append("- **No ground truth:** there is no domain-expert-authored expected-answer corpus. Correctness numbers reflect citation grounding, not document correctness.")
    md.append("- **Reproducibility:** re-run `python eval_aurora.py [...]` to regenerate. Charts in `eval_output/charts/`.")
    md.append("")

    md.append("## Appendix B — Glossary")
    md.append("")
    md.append("- **fast pipeline** — KG-first; Cypher template + Neo4j lookup before fallback.")
    md.append("- **baseline pipeline** — vector + keyword retrieval + LLM synthesis.")
    md.append("- **intent** — high-level question classification (FACTUAL, ANALYTICAL, COMPARATIVE, TEMPORAL, ENTITY).")
    md.append("- **confidence score** — model-estimated 0.0–1.0.")
    md.append("- **cache tiers** — plan / result / answer caches in Redis (each ~1h TTL).")
    md.append("")

    if judge_best is not None or judge_worst is not None:
        md.append("## Appendix C — Judged answer examples (PII-scrubbed)")
        md.append("")
        if judge_worst is not None and not judge_worst.empty:
            md.append("### Worst-scoring (faithfulness)")
            md.append("")
            md.append("| query_id | pipeline | intent | faith | rationale | question (truncated) |")
            md.append("|---|---|---|---|---|---|")
            for _, r in judge_worst.iterrows():
                q = scrub(str(r["question"] or ""))[:120].replace("|", "\\|").replace("\n", " ")
                rat = scrub(str(r.get("faithfulness_rationale") or ""))[:160].replace("|", "\\|").replace("\n", " ")
                md.append(f"| `{r['query_id'][:12]}` | {r['pipeline']} | {r.get('intent') or '—'} | {r['faithfulness']} | {rat} | {q} |")
            md.append("")
        if judge_best is not None and not judge_best.empty:
            md.append("### Best-scoring (faithfulness)")
            md.append("")
            md.append("| query_id | pipeline | intent | faith | rationale | question (truncated) |")
            md.append("|---|---|---|---|---|---|")
            for _, r in judge_best.iterrows():
                q = scrub(str(r["question"] or ""))[:120].replace("|", "\\|").replace("\n", " ")
                rat = scrub(str(r.get("faithfulness_rationale") or ""))[:160].replace("|", "\\|").replace("\n", " ")
                md.append(f"| `{r['query_id'][:12]}` | {r['pipeline']} | {r.get('intent') or '—'} | {r['faithfulness']} | {rat} | {q} |")
            md.append("")

    out_path.write_text("\n".join(md))
    return out_path


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def main() -> int:
    args = parse_args()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    since = datetime.fromisoformat(args.since).replace(tzinfo=timezone.utc) if args.since else None
    until = datetime.fromisoformat(args.until).replace(tzinfo=timezone.utc) if args.until else None

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    qh_path = OUT_DIR / "query_history.parquet"
    if qh_path.exists() and not args.refresh:
        log.info("Loading cached query_history.parquet (use --refresh to re-pull)")
        df = pd.read_parquet(qh_path)
    else:
        df = pull_query_history(since=since, until=until)
        if df.empty:
            log.error("No rows returned — check window or credentials")
            return 1
        df.to_parquet(qh_path, index=False)
        log.info("Saved snapshot to %s", qh_path)

    neo4j_path = OUT_DIR / "neo4j_snapshot.json"
    neo4j_snap = None
    if not args.no_neo4j:
        if neo4j_path.exists() and not args.refresh:
            log.info("Loading cached neo4j_snapshot.json")
            neo4j_snap = json.loads(neo4j_path.read_text())
        else:
            try:
                neo4j_snap = pull_neo4j_snapshot()
                if neo4j_snap:
                    neo4j_path.write_text(json.dumps(neo4j_snap, indent=2, default=str))
            except Exception as exc:  # noqa: BLE001
                log.warning("Neo4j snapshot failed: %s", exc)

    # Charts
    charts_made = {}
    for name, fn in [
        ("01_daily_volume", lambda: chart_daily_volume(df)),
        ("02_latency_by_pipeline", lambda: chart_latency_by_pipeline(df)),
        ("03_confidence_by_pipeline", lambda: chart_confidence_by_pipeline(df)),
        ("04_tokens_by_pipeline", lambda: chart_tokens_by_pipeline(df)),
        ("05_cache_hit_rate", lambda: chart_cache_hit_rate(df)),
        ("06_intent_distribution", lambda: chart_intent_distribution(df)),
        ("07_feedback_ratio", lambda: chart_feedback_over_time(df)),
        ("08_neo4j_labels", lambda: chart_neo4j_labels(neo4j_snap) if neo4j_snap else None),
    ]:
        try:
            path = fn()
            if path is not None:
                charts_made[name] = path
                log.info("wrote %s", path)
        except Exception as exc:  # noqa: BLE001
            log.warning("chart %s failed: %s", name, exc)

    judgements = None
    judge_path = OUT_DIR / "judgements.parquet"
    if args.judge:
        deployment = args.judge_deployment or os.environ.get("AZURE_OPENAI_DEPLOYMENT")
        if not deployment:
            log.error("--judge requires AZURE_OPENAI_DEPLOYMENT env var or --judge-deployment flag")
            return 2
        if judge_path.exists() and not args.refresh:
            log.info("Loading cached judgements.parquet")
            judgements = pd.read_parquet(judge_path)
        else:
            sample = stratified_sample(df, args.sample)
            log.info("Judging %d queries with Azure OpenAI deployment %s", len(sample), deployment)
            judgements = run_judge(sample, deployment)
            judgements.to_parquet(judge_path, index=False)
        args.judge_deployment = deployment  # for the methodology appendix

    report_path = write_report(df, neo4j_snap, judgements, args, charts_made)
    log.info("Report written to %s", report_path)
    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
