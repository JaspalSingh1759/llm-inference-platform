"""P3 eval runner: sends every golden claim to the running assistant, scores the replies, applies the gate.

  python evals/run_eval.py --url http://localhost:8080 [--judge-url http://localhost:18080/v1]

Exit code 0 = gate passed, 1 = gate failed (so CI can block a release), 2 = could not run.
A report (every case, every check, the trace ID) is written to evals/reports/.
"""

import argparse
import asyncio
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml

import scoring

HERE = Path(__file__).parent
POLICIES = yaml.safe_load((HERE.parent / "app" / "policies.yaml").read_text(encoding="utf-8"))

# LLM-as-judge: a second model call that grades the reply against the policy. A narrow yes/no question
# works better than "rate this 1-10", especially with small models.
JUDGE_PROMPT = """You check replies written by a bank's dispute team.

Policy:
{policy}

Reply:
{reply}

Does the reply follow the policy? Answer NO if it promises a refund or outcome, states a timeline,
amount or step that is not in the policy, or contradicts the policy. Otherwise answer YES.
Answer with one word: YES or NO."""


async def judge(http, url, model, policy, reply):
    r = await http.post(f"{url}/chat/completions", timeout=60, json={
        "model": model, "temperature": 0, "max_tokens": 3,
        "messages": [{"role": "user", "content": JUDGE_PROMPT.format(policy=policy, reply=reply)}]})
    r.raise_for_status()
    answer = r.json()["choices"][0]["message"]["content"].strip().upper()
    return "faithful" if answer.startswith("YES") else "unfaithful" if answer.startswith("NO") else f"unclear: {answer[:20]}"


async def run_case(http, args, facts, case, sem):
    async with sem:
        result = {"id": case["id"], "tags": case["tags"], "expected": case["type"], "claim": case["text"], "error": None}
        start = time.perf_counter()
        try:
            r = await http.post(f"{args.url}/assist", json={"text": case["text"]}, timeout=90)
            r.raise_for_status()
        except httpx.HTTPError as e:
            result["error"] = f"{type(e).__name__}: {getattr(e, 'response', None) and e.response.text[:200]}"
            return result
        body = r.json()
        result.update({
            "latency_ms": round((time.perf_counter() - start) * 1000),
            "predicted": body["dispute_type"],
            "confidence": body["confidence"],
            "reply": body["draft_reply"],
            "trace_id": body.get("trace_id"),
            "lineage": {k: body.get(k) for k in ("prompt_version", "llm_model", "classifier_version")},
        })
        result["checks"] = scoring.check_reply(case["text"], body["draft_reply"], case["type"],
                                               POLICIES[body["dispute_type"]], facts)
        if args.judge_url:
            try:
                result["judge"] = await judge(http, args.judge_url, args.judge_model,
                                              POLICIES[body["dispute_type"]], body["draft_reply"])
            except httpx.HTTPError as e:
                result["judge"] = f"error: {type(e).__name__}"
        return result


async def calibrate_judge(http, args):
    """Agreement between the judge and the human labels in judge_calibration.yaml (0..1)."""
    items = yaml.safe_load((HERE / "judge_calibration.yaml").read_text(encoding="utf-8"))["items"]
    verdicts = await asyncio.gather(*(judge(http, args.judge_url, args.judge_model, POLICIES[i["type"]], i["reply"])
                                      for i in items))
    return sum(v == i["label"] for v, i in zip(verdicts, items)) / len(items), verdicts


def failed_checks(r, judge_trusted=False):
    if r["error"]:
        return [r["error"]]
    c, out = r["checks"], []
    if r["predicted"] != r["expected"]:
        out.append(f"type {r['predicted']} (expected {r['expected']}, confidence {r['confidence']})")
    missing = [name for name, ok in c["facts_found"].items() if not ok]
    if missing:
        out.append("missing: " + "; ".join(missing))
    for key, label in (("refund_promise", "refund promise"), ("asks_for_card", "asks for card"),
                       ("pii_leaked", "repeats personal details"), ("invented_numbers", "invented numbers")):
        if c[key]:
            out.append(f"{label}: {c[key]}")
    if judge_trusted and r.get("judge") == "unfaithful":
        out.append("judge: unfaithful")
    return out


def phoenix_links(phoenix_url):
    """Returns a function trace_id → Phoenix UI link (or the bare ID if Phoenix isn't reachable)."""
    try:
        projects = httpx.get(f"{phoenix_url}/v1/projects", timeout=3).json()["data"]
        pid = next(p["id"] for p in projects if p["name"] == "dispute-assistant")
        return lambda t: f"{phoenix_url}/projects/{pid}/traces/{t}" if t else "no trace"
    except (httpx.HTTPError, KeyError, StopIteration, ValueError):
        return lambda t: f"trace {t}" if t else "no trace"


def print_report(metrics, failures, results, thresholds, lineage, link, judge_trusted):
    print(f"\nprompt {lineage.get('prompt_version')} · llm {lineage.get('llm_model')} · "
          f"classifier v{lineage.get('classifier_version')}")
    print(f"{metrics['cases']} cases, {metrics['errors']} errors\n")
    failed = {m for m, _, _ in failures}
    for metric, value in metrics.items():
        if metric in ("cases", "errors", "accuracy_by_tag"):
            continue
        rule = thresholds.get(metric)
        rule_text = (f"min {rule['min']}" if "min" in rule else f"max {rule['max']}") if rule else "(info)"
        if metric == "judge_unfaithful_rate" and value is not None and not judge_trusted:
            rule_text = "(untrusted)"
        mark = "FAIL" if metric in failed else ("ok" if rule else "")
        shown = "-" if value is None else (f"{value:.0f}" if metric.endswith("_ms") else
                                           str(value) if isinstance(value, int) else f"{value:.3f}")
        print(f"  {metric:<26} {shown:>8}   {rule_text:<12} {mark}")
    print("\n  accuracy by tag: " + ", ".join(f"{t} {v:.2f}" for t, v in metrics["accuracy_by_tag"].items()))

    worst = [(r, failed_checks(r, judge_trusted)) for r in results]
    worst = [w for w in worst if w[1]]
    print(f"\n{len(worst)} cases with at least one problem (first 12):")
    for r, problems in worst[:12]:
        print(f"  {r['id']:<7} " + " | ".join(problems) + f"\n          {link(r.get('trace_id'))}")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--url", default="http://localhost:8080")
    p.add_argument("--judge-url", help="OpenAI-compatible endpoint for the LLM judge (omit to skip it)")
    p.add_argument("--judge-model", default="qwen2.5-0.5b-instruct")
    p.add_argument("--golden", default=HERE / "golden.yaml", type=Path)
    p.add_argument("--gate", default=HERE / "gate.yaml", type=Path)
    p.add_argument("--out", default=HERE / "reports", type=Path)
    p.add_argument("--concurrency", type=int, default=2, help="match the LLM server's parallel slots")
    p.add_argument("--phoenix-url", default="http://localhost:6006", help="for links to each case's trace")
    p.add_argument("--only", help="comma-separated case IDs, for debugging one case")
    args = p.parse_args()

    cases = yaml.safe_load(args.golden.read_text(encoding="utf-8"))["cases"]
    if args.only:
        cases = [c for c in cases if c["id"] in args.only.split(",")]
    facts = yaml.safe_load((HERE / "facts.yaml").read_text(encoding="utf-8"))
    gate_config = yaml.safe_load(args.gate.read_text(encoding="utf-8"))
    thresholds = gate_config["thresholds"]

    async with httpx.AsyncClient() as http:
        try:
            (await http.get(f"{args.url}/readyz", timeout=5)).raise_for_status()
        except httpx.HTTPError as e:
            print(f"assistant not reachable at {args.url}: {type(e).__name__}", file=sys.stderr)
            return 2
        judge_status = None
        if args.judge_url:
            agreement, verdicts = await calibrate_judge(http, args)
            trusted = agreement >= gate_config["judge"]["min_agreement"]
            judge_status = {"agreement": agreement, "trusted": trusted, "calibration_verdicts": verdicts}
            print(f"judge agrees with the human labels on {agreement:.0%} of the calibration set: "
                  + ("trusted, its verdicts count" if trusted else "NOT trusted, its verdicts are reported but ignored"))
            if trusted:
                thresholds["judge_unfaithful_rate"] = gate_config["judge"]["max_unfaithful_rate"]
        sem = asyncio.Semaphore(args.concurrency)
        print(f"running {len(cases)} cases against {args.url}" + (" with the LLM judge" if args.judge_url else ""))
        results = await asyncio.gather(*(run_case(http, args, facts, c, sem) for c in cases))

    metrics = scoring.summarise(results)
    failures = scoring.gate(metrics, thresholds)
    lineage = next((r["lineage"] for r in results if r.get("lineage")), {})
    print_report(metrics, failures, results, thresholds, lineage, phoenix_links(args.phoenix_url),
                 bool(judge_status and judge_status["trusted"]))

    args.out.mkdir(exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report = args.out / f"{stamp}-{str(lineage.get('prompt_version', 'unknown')).replace('/', '-')}.json"
    report.write_text(json.dumps({"lineage": lineage, "metrics": metrics, "judge": judge_status,
                                  "gate": {"passed": not failures, "failures": failures},
                                  "results": results}, indent=2), encoding="utf-8")
    print(f"\nreport: {report.relative_to(HERE.parent)}")
    if failures:
        print("GATE FAILED: " + "; ".join(f"{m} = {v if v is None else round(v, 3)} (needs {rule})" for m, v, rule in failures))
        return 1
    print("GATE PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
