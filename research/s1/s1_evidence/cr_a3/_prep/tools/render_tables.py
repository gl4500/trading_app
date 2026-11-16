"""Render the per-module/shard markdown tables for a3/t15c_prep.md from budget.json + evidence (prints markdown)."""
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from t15c_common import EVID, MODULES, WORK, load  # noqa: E402

b = load(WORK / "budget.json")
sel = load(HERE / "selectors.json")
print("| # | Module / shard | Selector | Nodes | Baseline median / max (s, outer wall) | pytest median / max (s) "
      "| Candidates pre -> post filter | Sessions (<=24) | Est. s/item | In-scope functions covered |")
print("|---|---|---|---|---|---|---|---|---|---|")
for i, (m, md) in enumerate(b["modules"].items(), 1):
    for s, r in md["shards"].items():
        d = EVID / m / ("" if s == "_" else s)
        cov = load(d / "selector_coverage_detail.json") if (d / "selector_coverage_detail.json").is_file() else None
        fn = "n/a" if cov is None else f"{len(cov['functions']) - len(cov['uncovered'])}/{len(cov['functions'])}" + \
            (f" (uncovered: {', '.join(cov['uncovered'])})" if cov["uncovered"] else "")
        selector = " ".join(a.replace("research/s1/s1_tests/", "").replace("research/s1/s1_evidence/cr_a3/", "")
                            for a in r["selector"])
        flag = "" if r["within_budget"] else " **OVER**"
        print(f"| {i} | {m}{'' if s == '_' else ' / ' + s} | `{selector}` | {r['nodes']} | {r['median_s']:.1f} / "
              f"{r['max_s']:.1f}{flag} | {r['pytest_median_s']:.1f} / {r['pytest_max_s']:.1f} | {r['pre']} -> "
              f"{r['post']} | {r['sessions']} | {r['est_item_s']} | {fn} |")
print()
print("Candidates by operator family (post filter):")
print()
for m, md in b["modules"].items():
    for s, r in md["shards"].items():
        fam = ", ".join(f"{k} {v}" for k, v in sorted(r["post_by_family"].items(), key=lambda x: -x[1]))
        print(f"- **{m}{'' if s == '_' else ' / ' + s}** ({r['post']}): {fam}")
