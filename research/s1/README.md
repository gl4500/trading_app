# research/s1 — MeanReversion P13 offline shadow trial (S1)

Offline research toolchain. **Not imported by the app** and never run against live state during the build.
- Design (governing): `docs/s1_design_v5.md` (Codex APPROVE-DESIGN 502ca2a4)
- Spec: `docs/s1_spec.md` (Codex APPROVE-SPEC 7a6b16fd); plan: `docs/s1_plan.md`
- `e1_sim.py` / `e1_fetch.py`: byte-identical copies of the frozen E1 core/collector, loaded only by hash
  (68f21ab1… / 401f17de…) via `s1_common.load_pinned`.
- Tests: `C:/Users/gl450/.coordination/trading_app/testenv/Scripts/python.exe -m pytest s1_tests -q -p no:cacheprovider`
  (run from this folder; isolated test env with hypothesis/cosmic-ray, no app dependencies).
- Runtime outputs go to `s1_out/` (git-ignored). Mailbox ACKs are read from the coordination folder at run time.
