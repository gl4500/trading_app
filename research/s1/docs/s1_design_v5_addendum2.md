# S1 design v5 — Addendum 2 (Task-12 design rulings) — revision 1

Status: DRAFT for Codex approval. Builds on Addendum 1 revision 3 (sha256 6cb89e36840975b8d949ec85debf9d2cedbe45bbeb9dcb374d91343dddc5e590,
approved 92312e4f), which stays byte-identical. Source: Codex rulings 9a72159a (2026-10-17) on the Task-12 review
(reports/task-12-review.md). Where this addendum and Addendum 1 differ, this addendum governs. It must be approved,
implemented and tested before any registration; both addenda's sha256 are part of the registered bundle (A3.1).

## B1. Slot resolution deadline (amends A5.2; ruling R-b, explicit prospective amendment)
1. RESOLUTION_TIMEOUT = 30 minutes, named and single-sourced in the bundle. For every slot s: D(s) = E(s) + 30 min.
   D is a resolution deadline for a claimed attempt, slow or dead; elapsed time is never claimed to prove a worker died.
   This amendment changes which otherwise eligible captures can qualify (a capture whose report is not published
   before D cannot seal); that operational limitation is disclosed.
2. A never-claimed slot resolves as MISSED only after E, with its disposition preserved. A claimed slot stays PENDING
   until an immutable success/failure report is published or D is reached. A report resolves the slot only if it is
   complete: capture, consistency, receipt/process disposition and hashes; an arbitrary or partial file does not.
3. A success report must be durably published strictly before D (publication at D is a timeout). Completion and
   expiration are one exclusive, irreversible state transition per slot. At or after D a still-pending attempt
   becomes a preserved RESOLUTION-TIMEOUT failure, even if its worker is alive; a late worker cannot replace that
   outcome, publish a seal or reopen a persisted stop; its late evidence is preserved separately. An observed
   integrity or semantic violation is never erased by classifying an invocation as timed out.
4. Close-level selection is serialized (not only slot claims): among resolved successful candidates the seal is the
   first in original slot order; no later seal while an earlier slot is PENDING; selection respects any persisted
   stop or invalidity. File-existence checks followed by exclusive seal creation are not sufficient under concurrent
   finalizers.
5. D never extends capture eligibility: s <= capture_start <= capture_end <= E (A5.2) is unchanged, including exact E
   and W = 08:00. D may lie after W only for processing already captured evidence; no extra capture, retry or shifted
   slot. An unsealed-close or NO-VALID-SEAL outcome is not frozen while a qualifying claimed attempt of that close is
   PENDING; once a terminal outcome is persisted there is no rescue. Opening and authorization still finish before
   planned START.
6. Acceptance examples (written before the fix; injected aware clocks and synchronization barriers, no real sleeps):
   the review's overlap race in both completion orders selects the earlier slot; claim without report stays pending
   after E; success published just before D qualifies, at/after D times out; expiration racing late completion cannot
   change the winner; killed and merely slow workers get the same timeout disposition; no capture beyond E/W;
   concurrent finalizers plus restart replay give one deterministic seal; pending resolution cannot cause an early
   terminal stop followed by rescue.

## B2. Process binding reference (amends A1.1, A9; ruling R-c)
1. The opening capture must contain a usable observed sanitized process binding; if unavailable, the opening attempt
   is preserved as failed and no opening seal is written. The opening artifact's binding is the reference, bound
   through the START attestation, RUN-ACK and prereg. Later observations never establish or reset it;
   `process_binding.json` is not an authority (a cache, if kept, cannot select the reference).
2. The registered semantic binding fields are compared (executable and sanitized launcher binding), not PID/start
   time: a restart with an identical binding is reported provenance, not a semantic change. No secrets are exposed.
3. Each later observed binding is compared with the reference; an observed difference is terminal and persistent.
   Score rechecks every relevant seal from the opening through the frozen stop; a missing or malformed claimed-observed
   binding is not equality.
4. An explicitly represented unavailable observation (permitted by the registered observation contract, not an
   exception) is a GAP: never MATCH, never by itself a semantic change, never a reason to rebase when observations
   resume; it is reported. A process-observation EXCEPTION follows A9.1 (exception class + sanitized reason, no seal).
   Missing other REQUIRED evidence still fails under A9.2/A9.3. A gap is not claimed to prove effective-config equality.
5. Acceptance examples: unobservable opening -> no seal; deleting/replacing the reference sidecar cannot rebase;
   A, gap, B -> persistent invalidity incl. at score; A, gap, A -> gap preserved, no change invented; exception ->
   report, no seal; identical-binding restart -> provenance only; corrupt bound reference fails closed; non-numeric
   final dispositions make zero valuation calls.

## B3. Registration boundary and artifact integrity (amends A3.3, A8.2, A9.2; ruling R-e)
1. Registration exists from the valid plan/audit-authorized OPENING SEAL (A3.3, Codex R-a). The registered state and
   its expected bindings are identified independently of the artifact being checked (not "prereg parses" or "opening
   file exists"), so deleting artifacts cannot move a registration back to pre-registration.
2. Before a legitimate opening registration exists, invalid or fabricated authorization is a preserved refusal with
   zero live callbacks and reservations; it cannot manufacture a registration.
3. Once registration exists, any command observing a missing, changed or unparseable artifact that is already
   REQUIRED/BOUND at that stage records sanitized immutable failure evidence plus first-wins `aborted.json` (reason
   "registration artifact"); restoration does not resume. This covers the interval between the opening and RUN-ACK,
   every normal post-registration command (audit/opening re-entry included) and post-stop integrity of frozen trial
   artifacts. A not-yet-created START attestation or prereg is not missing-required before its stage; no abort for
   legitimate future-stage artifacts.
4. The minimal externally approved bootstrap/bundle comparison stays first; damaged authorization never selects a new
   expected bundle or registration. An unavailable mailbox with no established artifact violation is an
   authorization-observation failure (refusal), not proof of tampering, and never permits a live callback or priced
   work. Once a registered-artifact violation is observed, failure to look up another artifact or ACK cannot downgrade
   it. Earlier terminal reasons (e.g. bundle) remain first-wins. A corrupt `aborted.json` fails closed (never means
   "no abort").
5. Acceptance examples: invalid handmade prereg before the opening -> preserved refusal, no callback; opening changed
   after the opening but before RUN-ACK -> persistent abort; prereg not yet due is not corruption; registered
   plan/attestation/prereg/opening changed or deleted then restored -> still invalid; deleting prereg and opening
   together cannot erase registered status; audit/re-entry and post-stop checks cannot bypass persistence; mailbox
   outage distinguished from established corruption; forbidden callback/pricing paths proven with spies.

## B4. Acknowledged (Codex R-a, R-d)
AUDIT-ACK carries `bundle_sha256=`; the bundle is fixed from AUDIT-ACK and registration starts at the opening seal.
Corporate-action conflict identity is the provider action id alone (absent a pinned contract authorizing type
scoping); a type/date/symbol change under one id is a conflict and cannot evade reconciliation.
