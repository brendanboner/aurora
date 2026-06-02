#!/usr/bin/env python3
"""Replay the lowest-faithfulness queries from a prior eval against the
currently-deployed Oracle, and judge the new answers.

Reads ``eval_output/{query_history.parquet, judgements.parquet}`` (produced
by eval_aurora.py), picks the bottom-N by faithfulness, calls the live
oracle ``/query`` endpoint with the same question text, then asks the
LLM judge to score the new answer. Prints a side-by-side comparison.

Use to validate code changes (entity guard, agent redirect, etc.) on
specific known-bad cases without waiting for accumulated natural traffic.

Env vars: same as eval_aurora.py (POSTGRES_*, NEO4J_*, AZURE_OPENAI_*)
plus ORACLE_URL (default http://aurora-oracle:8000).
"""
from __future__ import annotations

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import requests

# Make eval_aurora's judge prompt + parsing reusable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
import eval_aurora  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger("replay")


def load_worst(n: int = 5) -> pd.DataFrame:
    eval_dir = Path("eval_output")
    qh = pd.read_parquet(eval_dir / "query_history.parquet")
    j = pd.read_parquet(eval_dir / "judgements.parquet")
    merged = j.merge(qh[["query_id", "question", "answer", "citations"]],
                     on="query_id", how="left",
                     suffixes=("_judge", "_qh"))
    merged = merged[merged["faithfulness"].notna()]
    return merged.sort_values("faithfulness").head(n)


def call_oracle(question: str, oracle_url: str) -> dict[str, Any]:
    """POST to oracle /query as a synthetic user. Returns the JSON response."""
    headers = {
        "Content-Type": "application/json",
        "X-User-Id": "replay-worst-queries",
        "X-User-Email": "replay@aurora.local",
        "X-User-Role": "user",
    }
    body = {
        "question": question,
        "mode": "answer",
        "options": {"max_documents": 10, "personalize": "off"},
    }
    resp = requests.post(f"{oracle_url}/query", json=body, headers=headers, timeout=90)
    resp.raise_for_status()
    return resp.json()


def judge_new(client, deployment: str, question: str, answer: str,
              citations: list[dict]) -> dict[str, Any]:
    """Re-use eval_aurora's judge prompt + parser."""
    cite_block = "\n".join(
        f"[{j+1}] {c.get('title', '(no title)')} — {c.get('url', '')}\n  snippet: {c.get('snippet', '')[:400]}"
        for j, c in enumerate((citations or [])[:8])
    ) or "(no citations)"
    prompt = (
        f"Question:\n{question}\n\n"
        f"Answer:\n{answer}\n\n"
        f"Citations:\n{cite_block}\n\n"
        f"Score this answer."
    )
    resp = client.chat.completions.create(
        model=deployment,
        max_tokens=800,
        messages=[
            {"role": "system", "content": eval_aurora.JUDGE_SYSTEM_PROMPT},
            {"role": "user", "content": prompt},
        ],
        response_format={"type": "json_object"},
    )
    raw = resp.choices[0].message.content or ""
    m = re.search(r"\{.*\}", raw, re.DOTALL)
    return json.loads(m.group(0)) if m else {}


def main() -> int:
    from openai import AzureOpenAI

    oracle_url = os.environ.get("ORACLE_URL", "http://aurora-oracle:8000")
    n = int(os.environ.get("REPLAY_N", "5"))

    log.info("Loading bottom-%d queries by faithfulness", n)
    worst = load_worst(n)

    client = AzureOpenAI(
        azure_endpoint=os.environ["AZURE_OPENAI_ENDPOINT"],
        api_key=os.environ["AZURE_OPENAI_API_KEY"],
        api_version=os.environ["AZURE_OPENAI_API_VERSION"],
    )
    deployment = os.environ["AZURE_OPENAI_DEPLOYMENT"]

    results = []
    for _, row in worst.iterrows():
        qid = row["query_id"]
        q = row["question"]
        old_faith = row["faithfulness"]
        old_hallu = row["hallucination"]
        log.info("---")
        log.info("query_id=%s pipeline_was=%s old_faith=%s", qid, row["pipeline"], old_faith)
        log.info("Q: %s", (q or "")[:200])

        try:
            new_resp = call_oracle(q, oracle_url)
        except Exception as exc:  # noqa: BLE001
            log.error("oracle call failed for %s: %s", qid, exc)
            continue

        new_answer = new_resp.get("answer") or ""
        new_pipeline = new_resp.get("pipeline")
        new_confidence = new_resp.get("confidence_score")
        new_citations = new_resp.get("citations") or []
        new_docs = new_resp.get("documents") or []
        new_tokens = (new_resp.get("metadata") or {}).get("llm_tokens_used")

        log.info("NEW pipeline=%s confidence=%s tokens=%s n_docs=%d",
                 new_pipeline, new_confidence, new_tokens, len(new_docs))
        log.info("NEW answer: %s", new_answer[:400].replace("\n", " "))

        try:
            scored = judge_new(client, deployment, q, new_answer, new_citations)
        except Exception as exc:  # noqa: BLE001
            log.error("judge failed for %s: %s", qid, exc)
            scored = {}

        results.append({
            "query_id": qid,
            "question": q,
            "pipeline_was": row["pipeline"],
            "pipeline_now": new_pipeline,
            "faith_was": old_faith,
            "faith_now": scored.get("faithfulness"),
            "hallu_was": old_hallu,
            "hallu_now": scored.get("hallucination"),
            "conf_was": row.get("confidence_score"),
            "conf_now": new_confidence,
            "tokens_now": new_tokens,
            "answer_was": (row["answer"] or "")[:300],
            "answer_now": new_answer[:300],
            "rationale_now": scored.get("faithfulness_rationale"),
        })

    out = pd.DataFrame(results)
    out_path = Path("eval_output/replay_results.parquet")
    out.to_parquet(out_path, index=False)
    log.info("Wrote %s", out_path)

    print()
    print("=" * 80)
    print("REPLAY SUMMARY")
    print("=" * 80)
    for _, r in out.iterrows():
        print(f"\n[{r['query_id']}] pipeline {r['pipeline_was']} → {r['pipeline_now']}")
        print(f"  Q: {r['question'][:160]}")
        print(f"  faithfulness: {r['faith_was']} → {r['faith_now']}    "
              f"hallucination: {r['hallu_was']} → {r['hallu_now']}    "
              f"confidence: {r['conf_was']} → {r['conf_now']}")
        print(f"  NEW answer: {r['answer_now'][:240].strip()}")
        if r["rationale_now"]:
            print(f"  judge rationale: {r['rationale_now']}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
