"""S1 Task 9 round 2: triage every Cosmic Ray job that the focused per-module run did not kill.
Inputs: the executed shard sessions (WORK_DIR), the full-suite recheck TSV and the new-test recheck TSVs.
Classes: KILLED-by-full-suite (recheck against the FULL suite), KILLED-by-new-test (a labelled retrospective test
added in Task 9 round 2 / fix round 1, re-applied by cr_recheck_s1.py with CR_TESTS), EQUIVALENT / NOT-MEANINGFUL
(reason below; fix round 1: applied only to the exact module:row:operator:occurrence listed in OCCURRENCES),
KILLED-by-focused-rerun / KILLED-by-timeout (fix round 1, review I-1: the jobs cosmic-ray scored KILLED only by its
timeout, re-run with the measured timeout: cr_recheck_timeouts_focused.tsv, survivors cr_recheck_timeouts_full.tsv),
OPEN (none expected; anything unmatched is OPEN "unclassified").
Usage: python cr_triage_s1.py WORK_DIR FULL.tsv OUT.tsv NEW1.tsv [NEW2.tsv ...]"""
import glob
import sqlite3
import sys
from pathlib import Path

EQ, NM = "EQUIVALENT", "NOT-MEANINGFUL"
INDENT = (NM, "JSON indentation/key order of a file only; every reader parses the JSON (identical content)")
RULES = {
    # s1_books
    ("s1_books.py", 46, "Eq_LtE"): (EQ, "rows() admits only BUY/SELL; 'SELL' <= 'BUY' is False, as is ==" ),
    ("s1_books.py", 58, "NotEq_Gt"): (EQ, "operational quantities are never negative (oversell -> 0; any remainder "
                                          "< 0.001, negatives within tolerance included, -> 0)"),
    ("s1_books.py", 91, "NotEq_Lt"): (EQ, "actions are BUY/SELL only; 'BUY' < 'SELL' and not 'SELL' < 'SELL', as !="),
    ("s1_books.py", 99, "Gt_NotEq"): (EQ, "a lot's fill count never decreases along the prefix replay (FIFO is "
                                          "deterministic, fills are only appended): n != prev <=> n > prev"),
    ("s1_books.py", 99, "Gt_IsNot"): (EQ, "fill counts never decrease and are small ints (< 257, CPython cache): "
                                          "`is not` agrees with !=, hence with >"),
    ("s1_books.py", 112, "Gt_NotEq"): (EQ, "economic rem_qty is never negative (set to 0, or reduced by less than it "
                                           "holds)"),
    # s1_checkpoint
    ("s1_checkpoint.py", 53, "NumberReplacer"): INDENT, ("s1_checkpoint.py", 66, "NumberReplacer"): INDENT,
    ("s1_checkpoint.py", 164, "NumberReplacer"): INDENT, ("s1_checkpoint.py", 277, "NumberReplacer"): INDENT,
    ("s1_checkpoint.py", 277, "ReplaceTrueWithFalse"): INDENT,
    ("s1_checkpoint.py", 406, "NumberReplacer"): INDENT, ("s1_checkpoint.py", 410, "NumberReplacer"): INDENT,
    ("s1_checkpoint.py", 90, "NumberReplacer"): (EQ, "process_starts is always overwritten by _observe_process "
                                                     "before the report is used, in both seal modes"),
    ("s1_checkpoint.py", 148, "ReplaceFalseWithTrue"): (EQ, "the return value only makes run_checkpoint re-read the "
                                                            "unchanged seal files (opening mode ignores it)"),
    ("s1_checkpoint.py", 151, "ReplaceTrueWithFalse"): (EQ, "parents=False: the parent s1_out always exists here"),
    ("s1_checkpoint.py", 381, "ReplaceTrueWithFalse"): (EQ, "parents=False: the parent s1_out always exists here"),
    ("s1_checkpoint.py", 202, "GtE_IsNot"): (EQ, "`close is not start` is always True: a bridge record would also be "
                                                 "attached to a pre-START seal, which every bridge reader ignores "
                                                 "(post_start_seals filters close >= START)"),
    ("s1_checkpoint.py", 341, "Eq_Is"): (EQ, "'RUNNING' is an identifier-like literal, interned; stop_decision "
                                             "returns that literal"),
    ("s1_checkpoint.py", 380, "ReplaceOrWithAnd"): (NM, "wording of a refusal message; the refusal itself is "
                                                        "tested"),
    ("s1_checkpoint.py", 445, "Eq_Is"): (EQ, "`__name__ is '__main__'` holds when run as a script (interned)"),
    # s1_seal
    ("s1_seal.py", 37, "Eq_GtE"): (EQ, "the calendar is sorted ascending: a >= b only when equal"),
    ("s1_seal.py", 85, "NumberReplacer"): (EQ, "with no prior seal max_seen guards no observed id; ledger ids are "
                                               "SQLite AUTOINCREMENT >= 1 (default -1 never flags, default 1 only "
                                               "ids <= 0)"),
    ("s1_seal.py", 100, "Lt_LtE"): (EQ, "a new id equal to max_seen cannot exist: max_id is the largest id of a sealed "
                                        "capture and is in that seal's fence (hence in `seen`)"),
    ("s1_seal.py", 158, "NumberReplacer"): (EQ, "post[0:] adds post[0], which never differs from itself"),
    ("s1_seal.py", 170, "Eq_LtE"): (EQ, "an action other than BUY/SELL makes the books raise (failed capture / "
                                        "invalid score) before any cohort is used; 'SELL' <= 'BUY' is False"),
    ("s1_seal.py", 186, "Mul_Div"): (EQ, "every caller passes today= by keyword; `/` only loosens the signature"),
    ("s1_seal.py", 203, "Gt_Is"): (EQ, "never breaking only visits closes after today: they have no seal (a seal "
                                       "after today raises) and their windows have not passed -> no effect"),
    ("s1_seal.py", 204, "ReplaceBreakWithContinue"): (EQ, "same as s1_seal:203 Gt_Is: closes after today have no "
                                                          "seal and are never missed"),
    # s1_run
    ("s1_run.py", 81, "LtE_Lt"): (EQ, "sessions are sorted and stop_date is their last member; dropping it and "
                                      "appending it gives the same list"),
    ("s1_run.py", 103, "Gt_NotEq"): (EQ, "economic rem_qty is never negative"),
    ("s1_run.py", 123, "Mul_Div"): (EQ, "every caller passes untrusted= by keyword; `/` only loosens the signature"),
    ("s1_run.py", 165, "Mul_Div"): (EQ, "every caller passes the optional arguments by keyword"),
    ("s1_run.py", 156, "NumberReplacer:-1"): (EQ, "n is never negative; for n == 0 (K == 0) the later rules give "
                                                  "INSUFFICIENT anyway"),
    ("s1_run.py", 156, "Eq_Lt"): (EQ, "n is never negative"),
    ("s1_run.py", 156, "Eq_LtE"): (EQ, "n is never negative; n == 0 gives INSUFFICIENT through the minimum rule"),
    ("s1_run.py", 175, "Gt_NotEq"): (EQ, "holdings at START are never negative"),
    ("s1_run.py", 197, "Eq_LtE"): (EQ, "phase is validated to audit/final; 'final' <= 'audit' is False"),
    ("s1_run.py", 205, "Eq_LtE"): (EQ, "every other exit reason (hard/trail/target/time) sorts after 'endpoint'"),
    ("s1_run.py", 205, "Eq_Is"): (EQ, "'endpoint' is an interned identifier-like literal in both modules"),
    ("s1_run.py", 213, "Eq_GtE"): (EQ, "prov is one of two literals; 'UNVERIFIED-PROVENANCE' < 'VERIFIED'"),
    ("s1_run.py", 213, "Eq_GtE:9"): (EQ, "numeric is SHADOW PASS or FAIL only; 'FAIL' >= 'SHADOW PASS' is False "
                                         "(fix round 1: the timeout job, re-run)"),
    ("s1_run.py", 213, "Eq_Is"): (EQ, "prov is the literal assigned in the same function (same constant object)"),
    ("s1_run.py", 303, "Gt_NotEq"): (EQ, "economic rem_qty is never negative"),
    ("s1_run.py", 308, "ZeroIterationForLoop"): (EQ, "`first` is read only for an operational holding without an "
                                                     "open economic lot, which cannot arise (see s1_run:311)"),
    ("s1_run.py", 310, "ZeroIterationForLoop"): (EQ, "the operational-only branch cannot fire (see s1_run:311)"),
    ("s1_run.py", 311, "*"): (EQ, "unreachable branch: both books replay the same rows; the operational quantity is "
                                  "<= the exact economic remainder (write-offs >= 0, its oversell reset only when "
                                  "the economic book still holds), and economic snapping removes <= 1e-12 per lot, so "
                                  "an operational holding > 0 always has an open economic lot (s in held)"),
    ("s1_run.py", 522, "Eq_Is"): (EQ, "'RUNNING' literal returned by stop_decision is interned"),
    ("s1_run.py", 527, "GtE_Gt"): (EQ, "only the LAST eligible session is used; this changes only the first ones"),
    ("s1_run.py", 527, "GtE_IsNot"): (EQ, "only the LAST eligible session is used; this adds earlier sessions"),
    ("s1_run.py", 527, "GtE_NotEq"): (EQ, "only the LAST eligible session is used; this adds earlier sessions"),
    ("s1_run.py", 638, "ExceptionReplacer:3"): (EQ, "no AttributeError is reachable inside that try "
                                                    "(post_start_seals, outside it, already indexed every seal; row "
                                                    "and calendar defects raise KeyError/TypeError/ValueError)"),
    ("s1_run.py", 717, "ExceptionReplacer:1"): (EQ, "the only FileNotFoundError reachable there is a missing "
                                                    "attest_start.json, which _stop_attestation hashes later outside "
                                                    "any handler: the attempt records 'score error: "
                                                    "FileNotFoundError' either way"),
    ("s1_run.py", 730, "Eq_Is"): (EQ, "unreachable: the pre-reservation gate refuses RUNNING with the same clock; "
                                      "the literal is interned anyway"),
    ("s1_run.py", 730, "IsNot_Is"): (EQ, "unreachable: RUNNING never reaches _score (pre-reservation gate)"),
    ("s1_run.py", 779, "Eq_LtE"): (EQ, "statuses here are STOPPED/TIMEOUT/NO-VALID-SEAL; only NO-VALID-SEAL "
                                       "<= 'NO-VALID-SEAL'"),
    ("s1_run.py", 793, "Eq_Is"): (EQ, "both operands are the same str objects: held keys and lot symbols both come "
                                      "from the one parsed frozen-ledger row list"),
    ("s1_run.py", 806, "Sub_BitXor"): (EQ, "the extra problem records name only symbols with no cohort lot; problems "
                                           "are consulted only for cohort lots"),
    ("s1_run.py", 816, "NotEq_IsNot"): (EQ, "disposition returns the interned literal 'OK'"),
    ("s1_run.py", 816, "NotEq_Lt"): (EQ, "'INCONCLUSIVE' and 'INSUFFICIENT' both sort before 'OK'"),
    ("s1_run.py", 828, "Sub_BitXor"): (EQ, "the subtrahend is 0, or 1 only with len(path) == 1 (endpoint-day entry), "
                                           "where ^ equals -"),
    ("s1_run.py", 828, "Sub_RShift"): (EQ, "the subtrahend is 0, or 1 only with len(path) == 1, where >> equals -"),
    ("s1_run.py", 829, "Eq_GtE"): (EQ, "a cohort entry date is never after the stop date"),
    ("s1_run.py", 840, "Eq_LtE"): (EQ, "eligible_sessions is never negative"),
    ("s1_books.py", 66, "NumberReplacer:23"): (EQ, "portfolio default -1.0 is used only for a symbol present in the "
                                                   "replay, whose quantity is > 0: |q - 0| and |q + 1| both exceed "
                                                   "the tolerance"),
    ("s1_books.py", 91, "NotEq_Gt"): (EQ, "'BUY' > 'SELL' is False, so BUY rows are also replayed; a BUY adds no fill "
                                          "to any lot, so no event can be created there"),
    ("s1_checkpoint.py", 436, "Eq_Is"): (EQ, "parse_mode returns the module's own constant 'final-snapshot' (equal "
                                             "string constants are one object within a compiled module)"),
    ("s1_checkpoint.py", 438, "Eq_Is"): (EQ, "parse_mode returns the module's own constant 'opening' (same object)"),
    ("s1_checkpoint.py", 436, "Eq_LtE"): (EQ, "modes are final-snapshot/opening/scheduled; 'opening' and 'scheduled' "
                                              "sort after 'final-snapshot'"),
    ("s1_checkpoint.py", 438, "Eq_LtE"): (EQ, "the remaining modes are opening/scheduled; 'scheduled' sorts after "
                                              "'opening'"),
    ("s1_checkpoint.py", 442, "NumberReplacer"): INDENT,
    ("s1_checkpoint.py", 445, "Eq_LtE"): (EQ, "imported, __name__ ('s1_checkpoint') sorts after '__main__'; as a "
                                              "script it equals it"),
    ("s1_run.py", 697, "Eq_GtE"): (EQ, "no verdict sorts after 'SHADOW PASS' (ABORTED-INVALID, BLOCKED, FAIL, "
                                       "INCONCLUSIVE, INSUFFICIENT, NO-VALID-SEAL all sort before it)"),
    ("s1_run.py", 697, "Eq_Is"): (EQ, "the verdict passed to done() is the module's own constant 'SHADOW PASS' "
                                      "(equal string constants are one object within a compiled module)"),

}
# Fix round 1 (review M-4): a rule applies ONLY to the exact (module, row, operator, occurrence) listed here; any other
# surviving occurrence on the same line stays OPEN until it is listed. (s1_run:793 Eq_Is removed: review I-2.)
OCCURRENCES = {
    ('s1_books.py', 46, 'Eq_LtE', 0),
    ('s1_books.py', 58, 'NotEq_Gt', 0),
    ('s1_books.py', 66, 'NumberReplacer', 23),
    ('s1_books.py', 91, 'NotEq_Gt', 1),
    ('s1_books.py', 91, 'NotEq_Lt', 1),
    ('s1_books.py', 99, 'Gt_IsNot', 1),
    ('s1_books.py', 99, 'Gt_NotEq', 3),
    ('s1_books.py', 112, 'Gt_NotEq', 4),
    ('s1_checkpoint.py', 53, 'NumberReplacer', 0),
    ('s1_checkpoint.py', 53, 'NumberReplacer', 1),
    ('s1_checkpoint.py', 66, 'NumberReplacer', 2),
    ('s1_checkpoint.py', 66, 'NumberReplacer', 3),
    ('s1_checkpoint.py', 90, 'NumberReplacer', 4),
    ('s1_checkpoint.py', 90, 'NumberReplacer', 5),
    ('s1_checkpoint.py', 148, 'ReplaceFalseWithTrue', 5),
    ('s1_checkpoint.py', 151, 'ReplaceTrueWithFalse', 2),
    ('s1_checkpoint.py', 164, 'NumberReplacer', 10),
    ('s1_checkpoint.py', 164, 'NumberReplacer', 11),
    ('s1_checkpoint.py', 202, 'GtE_IsNot', 0),
    ('s1_checkpoint.py', 277, 'NumberReplacer', 16),
    ('s1_checkpoint.py', 277, 'NumberReplacer', 17),
    ('s1_checkpoint.py', 277, 'ReplaceTrueWithFalse', 7),
    ('s1_checkpoint.py', 341, 'Eq_Is', 1),
    ('s1_checkpoint.py', 380, 'ReplaceOrWithAnd', 9),
    ('s1_checkpoint.py', 381, 'ReplaceTrueWithFalse', 10),
    ('s1_checkpoint.py', 406, 'NumberReplacer', 22),
    ('s1_checkpoint.py', 406, 'NumberReplacer', 23),
    ('s1_checkpoint.py', 410, 'NumberReplacer', 24),
    ('s1_checkpoint.py', 410, 'NumberReplacer', 25),
    ('s1_checkpoint.py', 436, 'Eq_Is', 2),
    ('s1_checkpoint.py', 436, 'Eq_LtE', 2),
    ('s1_checkpoint.py', 438, 'Eq_Is', 3),
    ('s1_checkpoint.py', 438, 'Eq_LtE', 3),
    ('s1_checkpoint.py', 442, 'NumberReplacer', 26),
    ('s1_checkpoint.py', 442, 'NumberReplacer', 27),
    ('s1_checkpoint.py', 445, 'Eq_LtE', 4),
    ('s1_run.py', 81, 'LtE_Lt', 0),
    ('s1_run.py', 103, 'Gt_NotEq', 0),
    ('s1_run.py', 123, 'Mul_Div', 0),
    ('s1_run.py', 156, 'Eq_Lt', 6),
    ('s1_run.py', 156, 'Eq_LtE', 6),
    ('s1_run.py', 156, 'NumberReplacer', 17),
    ('s1_run.py', 165, 'Mul_Div', 2),
    ('s1_run.py', 175, 'Gt_NotEq', 2),
    ('s1_run.py', 197, 'Eq_LtE', 7),
    ('s1_run.py', 205, 'Eq_Is', 7),
    ('s1_run.py', 205, 'Eq_LtE', 8),
    ('s1_run.py', 213, 'Eq_GtE', 10),
    ('s1_run.py', 213, 'Eq_GtE', 9),
    ('s1_run.py', 213, 'Eq_Is', 9),
    ('s1_run.py', 303, 'Gt_NotEq', 3),
    ('s1_run.py', 308, 'ZeroIterationForLoop', 9),
    ('s1_run.py', 310, 'ZeroIterationForLoop', 10),
    ('s1_run.py', 311, 'AddNot', 36),
    ('s1_run.py', 311, 'Gt_Eq', 4),
    ('s1_run.py', 311, 'Gt_GtE', 4),
    ('s1_run.py', 311, 'Gt_Lt', 4),
    ('s1_run.py', 311, 'Gt_LtE', 4),
    ('s1_run.py', 311, 'Gt_NotEq', 4),
    ('s1_run.py', 311, 'NumberReplacer', 34),
    ('s1_run.py', 311, 'NumberReplacer', 35),
    ('s1_run.py', 522, 'Eq_Is', 10),
    ('s1_run.py', 527, 'GtE_Gt', 4),
    ('s1_run.py', 527, 'GtE_IsNot', 4),
    ('s1_run.py', 527, 'GtE_NotEq', 4),
    ('s1_run.py', 697, 'Eq_GtE', 12),
    ('s1_run.py', 697, 'Eq_Is', 11),
    ('s1_run.py', 730, 'Eq_Is', 12),
    ('s1_run.py', 779, 'Eq_LtE', 14),
    ('s1_run.py', 806, 'Sub_BitXor', 2),
    ('s1_run.py', 816, 'NotEq_IsNot', 30),
    ('s1_run.py', 816, 'NotEq_Lt', 30),
    ('s1_run.py', 828, 'Sub_BitXor', 4),
    ('s1_run.py', 828, 'Sub_RShift', 4),
    ('s1_run.py', 829, 'Eq_GtE', 16),
    ('s1_run.py', 840, 'Eq_LtE', 17),
    ('s1_seal.py', 37, 'Eq_GtE', 1),
    ('s1_seal.py', 85, 'NumberReplacer', 32),
    ('s1_seal.py', 85, 'NumberReplacer', 33),
    ('s1_seal.py', 100, 'Lt_LtE', 0),
    ('s1_seal.py', 158, 'NumberReplacer', 41),
    ('s1_seal.py', 170, 'Eq_LtE', 2),
    ('s1_seal.py', 186, 'Mul_Div', 0),
    ('s1_seal.py', 203, 'Gt_Is', 3),
    ('s1_seal.py', 204, 'ReplaceBreakWithContinue', 0),
}
IDENTITY = (NM, "interpreter-specific identity: `is`/`is not` on equal immutable literals (interned or shared "
                "constants, small-int cache) agrees with ==/!= on CPython only; not a program equivalence (review M-1)")
IDENTITY_ROWS = {("s1_books.py", 99, "Gt_IsNot"), ("s1_checkpoint.py", 341, "Eq_Is"), ("s1_checkpoint.py", 436, "Eq_Is"),
                 ("s1_checkpoint.py", 438, "Eq_Is"), ("s1_run.py", 205, "Eq_Is"), ("s1_run.py", 213, "Eq_Is"),
                 ("s1_run.py", 522, "Eq_Is"), ("s1_run.py", 697, "Eq_Is"), ("s1_run.py", 730, "Eq_Is"),
                 ("s1_run.py", 816, "NotEq_IsNot")}
TOOL_FAIL = (NM, "cosmic-ray could not build this mutant (ExceptionReplacer on a dotted name `b.BookError`: "
                 "AttributeError 'PythonNode' has no 'value'); no mutant exists to test")


def short(op):
    return op.replace("core/", "").replace("ReplaceComparisonOperator_", "").replace("ReplaceBinaryOperator_", "")


def rule(mod, row, op, occ, src_line):
    o = short(op)
    if (mod, row, o, occ) not in OCCURRENCES:
        return None
    if (mod, row, o) in IDENTITY_ROWS:
        return IDENTITY
    for key in ((mod, row, f"{o}:{occ}"), (mod, row, o), (mod, row, "*")):
        if key in RULES:
            return RULES[key]
    if o == "NumberReplacer" and (mod, row, "NumberReplacer:-1") in RULES and "-1" in src_line:
        return RULES[(mod, row, "NumberReplacer:-1")]
    return None


def load(p):
    return {ln.split("\t")[0]: ln.split("\t") for ln in Path(p).read_text(encoding="utf-8").splitlines()
            if ln and ln[0] != "#"}


def main(work, full_p, out_p, new_ps):
    full = load(full_p)
    ev = Path(full_p).parent
    tfoc = load(ev / "cr_recheck_timeouts_focused.tsv") if (ev / "cr_recheck_timeouts_focused.tsv").exists() else {}
    tfull = load(ev / "cr_recheck_timeouts_full.tsv") if (ev / "cr_recheck_timeouts_full.tsv").exists() else {}
    new = {}
    for p in new_ps:
        new.update(load(p))
    diffs = load(Path(full_p).with_name("cr_diffs_all.tsv")) if Path(full_p).with_name("cr_diffs_all.tsv").exists() \
        else {}
    rows = []
    for d in sorted(glob.glob(str(Path(work) / "s1_*_s[0-9]"))):
        con = sqlite3.connect(Path(d) / "cr.sqlite")
        for jid, mod, op, occ, row, to, out in con.execute(
                """SELECT s.job_id, s.module_path, s.operator_name, s.occurrence, s.start_pos_row, r.test_outcome,
                          r.output FROM work_results r JOIN mutation_specs s ON s.job_id = r.job_id"""):
            timed_out = to == "KILLED" and out == "timeout"
            if (to == "KILLED" and not timed_out) or (to == "INCOMPETENT" and "returned non-zero exit status 1"
                                                       in (out or "")):
                continue
            mline = diffs.get(jid, [""] * 7)[6] if diffs else ""
            if timed_out:                                   # fix round 1 (review I-1): cosmic-ray's timeout "kill"
                f = tfoc.get(jid, [""] * 6)[5]
                if f.startswith("KILLED timeout"):
                    cls, why = "KILLED-by-timeout", f"hangs: the focused set timed out again ({f[15:]})"
                elif f.startswith("KILLED"):
                    cls = "KILLED-by-new-test" if ("test_cr_" in f or "test_fr1_" in f) else "KILLED-by-focused-rerun"
                    why = f"focused re-run with the measured timeout: {f}"
                elif jid in tfull and tfull[jid][5].startswith("KILLED"):
                    t = tfull[jid][5]
                    cls = "KILLED-by-new-test" if ("test_cr_" in t or "test_fr1_" in t) else "KILLED-by-full-suite"
                    why = f"focused re-run SURVIVED; full suite: {t}"
                elif f.startswith("SURVIVED"):
                    hit = rule(mod, row, op, occ, mline)
                    cls, why = hit if hit else ("OPEN", "timeout job survived the focused re-run and the full suite")
                else:
                    cls, why = "OPEN", "timeout job not re-run"
            elif to == "INCOMPETENT":
                cls, why = TOOL_FAIL
            elif jid in full and full[jid][5].startswith("KILLED"):
                cls, why = "KILLED-by-full-suite", full[jid][5]
            elif jid in new and new[jid][5].startswith("KILLED"):
                cls, why = "KILLED-by-new-test", new[jid][5]
            else:
                hit = rule(mod, row, op, occ, mline)
                cls, why = hit if hit else ("OPEN", "unclassified")
            rows.append([Path(d).name, jid, mod, str(row), short(op), str(occ), cls, why, mline])
        con.close()
    rows.sort(key=lambda r: (r[2], int(r[3]), r[4], int(r[5])))
    head = "shard\tjob_id\tmodule\trow\toperator\toccurrence\tclass\treason\tmutated_line"
    Path(out_p).write_text(head + "\n" + "\n".join("\t".join(r) for r in rows) + "\n", encoding="utf-8")
    from collections import Counter
    for (m, c), n in sorted(Counter((r[2], r[6]) for r in rows).items()):
        print(m, c, n)
    print("total not killed by the focused run:", len(rows))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3], sys.argv[4:])
