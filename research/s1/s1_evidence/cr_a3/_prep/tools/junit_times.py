"""Summarise a JUnit XML: total, per file, per test function (params summed), top-N cases."""
import sys
import xml.etree.ElementTree as ET
from collections import defaultdict

path, top = sys.argv[1], int(sys.argv[2]) if len(sys.argv) > 2 else 25
cases = list(ET.parse(path).getroot().iter("testcase"))
per_file, per_fn = defaultdict(float), defaultdict(lambda: [0.0, 0])
rows = []
for tc in cases:
    t = float(tc.get("time", 0))
    cls, name = tc.get("classname", ""), tc.get("name", "")
    per_file[cls] += t
    fn = name.split("[")[0]
    per_fn[f"{cls}::{fn}"][0] += t
    per_fn[f"{cls}::{fn}"][1] += 1
    rows.append((t, f"{cls}::{name}"))
print(f"cases {len(cases)} total {sum(r[0] for r in rows):.1f}s")
for f, t in sorted(per_file.items(), key=lambda x: -x[1]):
    print(f"  file {t:8.1f}s {f}")
for f, (t, n) in sorted(per_fn.items(), key=lambda x: -x[1][0])[:top]:
    print(f"  fn {t:8.1f}s n={n:3d} {f}")
