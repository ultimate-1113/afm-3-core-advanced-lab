"""Export synthetic observations and paired metrics from a completed or paused study."""

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import statistics
from evaluate import dataset
from fixtures import js, write_json, token_count
from tasks import grade

BASELINE = {
    "notice": "direct",
    "delivery": "image",
    "update": "batch",
    "regression": "baseline",
}


def read(path):
    return (
        [json.loads(line) for line in path.read_text().splitlines()]
        if path.exists()
        else []
    )


def save(path, rows):
    path.write_text("".join(js(r) + "\n" for r in rows))


def med(values):
    v = [x for x in values if x is not None]
    return round(statistics.median(v), 3) if v else None


def export_legacy(source, out):
    m = json.loads((source / "manifest.json").read_text())
    write_json(
        out / "legacy-manifest.json",
        dict(
            commit=m["commit"],
            runner_sha256=m["runner_sha256"],
            inputs=m["inputs"],
            model=m["ready"]["model"],
            runner_version=m["ready"]["runner_version"],
        ),
    )
    rows = []
    for file in ("heldout", "regressions"):
        for r in read(source / (file + ".jsonl")):
            result = r["result"]
            keys = (
                "status",
                "text",
                "input_tokens",
                "output_tokens",
                "cached_tokens",
                "ttft_s",
                "elapsed_s",
                "host_e2e_s",
            )
            rows.append(
                dict(
                    id=r["case"]["id"],
                    dataset=r["dataset"],
                    method=r["method"],
                    request=r["request"],
                    result={k: result.get(k) for k in keys},
                    grade=r["grade"],
                )
            )
    save(out / "legacy-cases.jsonl", rows)
    return rows


def collect(work, legacy, cache, out, counts=True):
    out.mkdir(parents=True, exist_ok=True)
    fixtures, shared, _ = dataset()
    selection_path = work / "selected.json"
    selected = (
        json.loads(selection_path.read_text()) if selection_path.is_file() else {}
    )
    old = export_legacy(legacy, out)
    calls = read(work / "calls.jsonl")
    cases = read(work / "cases.jsonl")
    sizes = {}
    for c in calls:
        c["measurement_date"] = c.pop("started", "")[:10]
        text = c.get("text")
        c["retokenized_output_text_tokens"] = None
        if text and counts:
            if text not in sizes:
                sizes[text] = token_count(text)
            c["retokenized_output_text_tokens"] = sizes[text]
    for c in cases:
        c["measurement_date"] = c.pop("recorded", "")[:10]
    save(out / "calls.jsonl", calls)
    save(out / "cases.jsonl", cases)
    ocr = [
        dict(id=f.stem, **json.loads(f.read_text()))
        for f in sorted(cache.glob("*.json"))
    ]
    save(out / "vision.jsonl", ocr)
    different = [
        dict(trial=f.stem, **json.loads(f.read_text()))
        for f in sorted(work.glob("ocr-*.json"))
    ]
    save(out / "vision-differences.jsonl", different)
    status = json.loads((work / "status.json").read_text())
    grouped = defaultdict(list)
    for c in cases:
        grouped[(c["split"], c["domain"], c["model"], c["method"])].append(c)
    methods = []
    for (split, d, model, method), grp in sorted(grouped.items()):
        methods.append(
            dict(
                split=split,
                domain=d,
                model=model,
                method=method,
                n=len(grp),
                exact=sum(r["grade"]["exact"] for r in grp),
                first_stdout_median_s=med(r["first_stdout_s"] for r in grp),
                active_e2e_median_s=med(r["active_e2e_s"] for r in grp),
                steps=sum(r["steps"] for r in grp),
                ocr_differences=sum(r["ocr_matches_frozen"] is False for r in grp),
            )
        )
    paired = {}
    for label, mapping in (
        ("baseline", BASELINE),
        ("dev_selected", dict(selected, regression="baseline")),
    ):
        if label == "dev_selected" and not selected:
            continue
        by = {
            model: {
                r["id"]: r
                for r in cases
                if r["id"] in shared
                and r["model"] == model
                and r["method"] == mapping[r["domain"]]
            }
            for model in ("system", "pcc")
        }
        ids = sorted(by["system"].keys() & by["pcc"].keys())

        def hits(model):
            return sum(by[model][i]["grade"]["exact"] for i in ids)

        def only(win, other):
            return [
                i
                for i in ids
                if by[win][i]["grade"]["exact"] and not by[other][i]["grade"]["exact"]
            ]

        paired[label] = dict(
            n=len(ids),
            system=hits("system"),
            pcc=hits("pcc"),
            system_only=only("system", "pcc"),
            pcc_only=only("pcc", "system"),
            pending=sorted(shared - set(ids)),
        )
    long = []
    token_by_id = {
        r["id"]: r["document_tokens"] for r in fixtures if r["domain"] == "long"
    }
    for band in ("4000", "12000", "24000"):
        for model in ("system", "pcc"):
            rows = [
                r
                for r in cases
                if r["domain"] == "long"
                and r["condition"] == band
                and r["model"] == model
            ]
            if rows:
                long.append(
                    dict(
                        target=int(band),
                        model=model,
                        method=rows[0]["method"],
                        n=len(rows),
                        full_document_tokens=sorted(token_by_id[r["id"]] for r in rows),
                        exact=sum(r["grade"]["exact"] for r in rows),
                        first_stdout_median_s=med(r["first_stdout_s"] for r in rows),
                        active_e2e_median_s=med(r["active_e2e_s"] for r in rows),
                    )
                )
    by_id = {c["id"]: c for c in fixtures}
    detail = {}
    for model in ("system", "pcc"):
        group = [r for r in cases if r["split"] == "held" and r["model"] == model]
        detail[model] = {}
        for m in ("direct", "evidence"):
            nr = [r for r in group if r["domain"] == "notice" and r["method"] == m]
            if not nr:
                continue
            metric = {
                k: sum(r["grade"][k] for r in nr)
                for k in (
                    "unsupported",
                    "omitted",
                    "correct_abstentions",
                    "abstention_opportunities",
                )
            }
            metric.update(n=len(nr), exact=sum(r["grade"]["exact"] for r in nr))
            if m == "evidence":
                raw_exact = 0
                for r in nr:
                    original = r["answer"]
                    vals = (
                        {
                            k: v.get("value")
                            for k, v in original.items()
                            if isinstance(v, dict)
                        }
                        if isinstance(original, dict)
                        else None
                    )
                    raw_exact += grade(by_id[r["id"]], "direct", vals)["exact"]
                metric.update(
                    values_before_validation_exact=raw_exact,
                    rejected_fields=sum(
                        len(r["grade"]["rejected_evidence"]) for r in nr
                    ),
                )
            detail[model]["notice_" + m] = metric
        for m in ("batch", "step"):
            ar = [r for r in group if r["domain"] == "update" and r["method"] == m]
            if ar:
                detail[model]["update_" + m] = {
                    k: sum(r["grade"].get(k, 0) for r in ar)
                    for k in ("state", "trace", "extra_actions", "missing_actions")
                }
    for item in long:
        subset = [
            r
            for r in cases
            if r["domain"] == "long"
            and r["model"] == item["model"]
            and int(r["condition"]) == item["target"]
        ]
        item["fields_exact"] = {
            k: sum(r["grade"]["fields"][k] for r in subset)
            for k in ("venue", "deadline", "limit", "pending")
        }
    history = defaultdict(list)
    for r in old:
        history[r["dataset"] + "/" + r["method"]].append(r)
    summary = dict(
        run_status=status["status"],
        reason=status.get("reason"),
        fixture_lock=status["fixture_lock"],
        models=status["models"],
        selected_on_dev=selected,
        case_methods=len(cases),
        model_requests=len(calls),
        route_counts=dict(Counter(c["model"] for c in calls)),
        status_counts=dict(Counter(c.get("status", "interrupted") for c in calls)),
        quota_before=dict(
            Counter(c["quota_before"] for c in calls if c.get("quota_before"))
        ),
        quota_after=dict(
            Counter(c["quota_after"] for c in calls if c.get("quota_after"))
        ),
        actual_usage_observations=sum(c.get("usage") is not None for c in calls),
        legacy={
            k: {"n": len(v), "exact": sum(r["grade"]["pass"] for r in v)}
            for k, v in history.items()
        },
        methods=methods,
        common30=paired,
        details=detail,
        long=long,
        vision_differences=len(different),
    )
    write_json(out / "summary.json", summary)
    return summary


def table(rows, cols):
    return (
        "| "
        + " | ".join(cols)
        + " |\n|"
        + "|".join("---" for _ in cols)
        + "|\n"
        + "".join(
            "| " + " | ".join(str(x) if x is not None else "—" for x in row) + " |\n"
            for row in rows
        )
    )


def markdown(summary):
    s = summary
    parts = [
        "# ケース別集計",
        "実験用時刻は秒。完全一致の分母は実際に完了したケース数。全回答は cases.jsonl、各モデル呼び出しは calls.jsonl に収録した。",
        "## 10月の固定入力の再測定",
        table(
            ((k, v["exact"], v["n"]) for k, v in sorted(s["legacy"].items())),
            ["条件", "完全一致", "件数"],
        ),
        "## 共通30問",
        table(
            (
                (
                    k,
                    x["n"],
                    x["system"],
                    x["pcc"],
                    len(x["system_only"]),
                    len(x["pcc_only"]),
                )
                for k, x in s["common30"].items()
            ),
            ["方式", "比較済み", "Core正解", "PCC正解", "Coreのみ正解", "PCCのみ正解"],
        ),
    ]
    for split, title in (
        ("dev", "調整用"),
        ("held", "初見評価"),
        ("regression", "旧失敗6問・共通CLI"),
    ):
        parts += [
            "## " + title,
            table(
                (
                    (
                        r["domain"],
                        r["model"],
                        r["method"],
                        f"{r['exact']}/{r['n']}",
                        r["steps"],
                        r["first_stdout_median_s"],
                        r["active_e2e_median_s"],
                    )
                    for r in s["methods"]
                    if r["split"] == split
                ),
                [
                    "用途",
                    "経路",
                    "方式",
                    "完全一致",
                    "モデル呼出し",
                    "初回表示中央値",
                    "完了中央値",
                ],
            ),
        ]
    parts += [
        "## 長文",
        table(
            (
                (
                    r["target"],
                    r["model"],
                    r["method"],
                    str(r["exact"]) + "/" + str(r["n"]),
                    r["first_stdout_median_s"],
                    r["active_e2e_median_s"],
                )
                for r in s["long"]
            ),
            [
                "全文の目標トークン",
                "経路",
                "入力",
                "完全一致",
                "初回表示中央値",
                "完了中央値",
            ],
        ),
    ]
    return "\n\n".join(parts).rstrip() + "\n"


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--work", type=Path, required=True)
    p.add_argument("--legacy-results", type=Path, required=True)
    p.add_argument("--ocr", type=Path, required=True)
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--skip-text-counts", action="store_true")
    a = p.parse_args()
    summary = collect(a.work, a.legacy_results, a.ocr, a.out, not a.skip_text_counts)
    (a.out / "metrics.md").write_text(markdown(summary))
    print(
        js(
            {
                k: summary[k]
                for k in (
                    "run_status",
                    "case_methods",
                    "model_requests",
                    "route_counts",
                    "status_counts",
                    "actual_usage_observations",
                )
            }
        )
    )
