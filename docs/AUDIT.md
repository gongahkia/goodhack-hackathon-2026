# AUDIT — 3-Bucket Taxonomy + Research Extraction

Judge-style critical audit. Completeness over ease. No sycophancy. File:line refs are static-read; not runtime-tested.

[Inference] tags apply to: race conditions, idempotency claims, PDPA exposure, ICS unauthenticated-by-default, audit cross-patient leakage, encryption-coverage gaps. [Unverified] `_url_key` collision behavior not exercised against live Tinyfish output.

---

## Structural framing gap (cross-cutting)

[Inference] Repo claims 3 buckets but ships only 2 scheduled artifacts (`daily_task`, `appointment_candidate`) plus `ad_hoc_research_task`. There is **no first-class ad-hoc *event* node** — caregiver-stated one-off non-clinical events ("nephew visiting Sat") collapse into either a `daily_task` or get dropped at extraction. Taxonomy in `extraction.py:736–807` has no `ad_hoc_event` branch.

**Remedy:** introduce `ad_hoc_event` node w/ explicit `{anchor_datetime, duration, recurrence:none, scheduling_semantics:"movable_personal"}`, separate from clinical `daily_task` and from `appointment_candidate` (calendar-bound). Wire into scheduler conflict graph and ICS feed under a different `CATEGORIES` value.

---

## Bucket 1 — Fixed appointment date (`appointment_candidate`)

### Gaps

- **No idempotency on Google insert** — `approvals.py:87–172` read-then-writes `calendar_write_status` across awaits; `acquire_system_lock` (`store.py:428`) is unused. Concurrent approvals → duplicate events.
- **Silent time defaulting** — `approvals.py:193` hardcodes `09:00` when `time` missing; "Tuesday afternoon" writes 09:00 with no clarification gate. `extraction.py:545` only fills time on `HH:MM` regex match.
- **TZ/date-roll bug surface** — `extraction.py:191` normalizes against UTC `today`; calendar writes in Asia/Singapore (`approvals.py:194`). Late-night SGT statements roll wrong calendar date. `extraction.py:849` auto-rolls past dates to `year+1` with no confirmation.
- **No conflict check at write time** — appointments don't pre-flight against existing Google events or other pending appointments. Scheduler's overlap logic (`scheduler.py:294`) is daily-task-only.
- **No update/cancel path** — `google_event_id` is stored but no PATCH/DELETE in `main.py`. Reschedules produce orphans.
- **Plaintext PII to Google** — `approvals.py` rehydrates patient name into `summary`/`description` (`extraction.py:803`). PDPA: cross-border processor disclosure with no DPIA recorded.
- **`location` is dead code** — `extraction.py:807` hardwires `None`; clinic name never captured.
- **No reminder generation** — appointments don't emit `notification_candidate`; only daily-task conflicts do (`scheduler.py:165`).

### Remedies

- Compound-unique index on `(appointment_candidate_id, calendar_write_status="written")`; wrap insert in `acquire_system_lock(f"calwrite:{id}")` w/ idempotency-key sent to Google.
- Replace 09:00 fallback w/ explicit `requires_clarification=true` and gate write on resolved time.
- Centralize TZ in `config.py` (`PATIENT_TZ`); normalize all "today" via `datetime.now(PATIENT_TZ).date()`. Forbid `extraction` from writing `date_value` without a TZ-anchored timestamp.
- Add `freebusy.query` precheck before insert; surface conflicts as `schedule_conflict` node.
- Add PATCH/DELETE endpoints that mirror to Google via stored `google_event_id`.
- Replace plaintext name in event body w/ tokenized initials + private link to internal record; keep PII server-side.
- Capture location at extraction (NER or regex on "at <X> clinic/polyclinic/hospital"); persist + ship to calendar `location` field.
- Emit T-24h/T-1h `notification_candidate` rows on appointment approval; one delivery worker drains them.

---

## Bucket 2 — Scheduled event (`daily_task` + next-day check)

### Gaps

- **No actual scheduler** — ROADMAP claims daily 22:00 SGT cron; reality is on-demand `POST /scheduler/next-day-check` (`main.py:362`), no idempotency, double-runs duplicate `schedule_conflict`/`notification_candidate` nodes.
- **`three_times_daily` spacing only checks "before" meals** (`scheduler.py:223`); "after meals" passes even when interval-incompatible.
- **Naive alternative-time suggestion** (`scheduler.py:260`): 7am–9pm 15-min sweep, ignores other daily tasks, ignores med-spacing constraints, no working-hours model.
- **Implicit TZ** — `scheduled_time` is `HH:MM` w/ no field declaring TZ; caregiver travel → silent corruption.
- **Meal times global** (`scheduler.py:17` `08:00/12:00/18:00`); no per-patient profile.
- **`send_at` math** (`scheduler.py:173`) can be in the past w/ no late flag; no delivery channel reads `notification_candidate.delivery_status`.
- **`append_reasoning_step` JSONB read-modify-write race** (`store.py:260`) — no `SELECT … FOR UPDATE`. Steps lost under concurrency.
- **`list_nodes` linear scan** (`store.py:358–369`) — every scheduler tick is O(N).
- **Conflict reconciliation missing** — resolved conflicts aren't auto-closed; only filtered when `status="dismissed"`.
- **All-day `transparent` events**: handled via L282; correct but undocumented invariant.

### Remedies

- Real scheduler (APScheduler or external cron → authenticated webhook) wrapped in `acquire_system_lock("nextday:" + date)`; idempotent on `(patient_id, target_date)`.
- Replace meal-anchored spacing rule with absolute clinical interval map per drug class (e.g. levothyroxine 30-min fast, anticoagulant 12h spacing) sourced from a reviewable table.
- Add `daily_task.timezone` field; default to `PATIENT_TZ`; UI surfaces TZ on edit.
- Per-patient `meal_profile` node; meal anchors derived from it.
- Build a real conflict solver: pull all daily_tasks, pending appointments, ad-hoc events, busy Google blocks; constraint-solve (greedy first; document fallback). Don't suggest into another task's slot.
- Add `notification_dispatcher` worker that drains `delivery_status="pending"` w/ `send_at <= now`; mark `late=true` if `send_at` in past at creation.
- Wrap `append_reasoning_step` in single SQL `UPDATE … SET payload = jsonb_set(payload, '{steps}', payload->'steps' || $1::jsonb)` row-locked; or move to append-only `reasoning_step` child table.
- Add SQL index `(type, payload->>'patient_id', status)`; cap `list_nodes` page size.
- Auto-resolve conflict when underlying task's `scheduled_time` no longer overlaps; emit `conflict_resolved` reasoning step.

---

## Bucket 3 — Ad-hoc event

### Gaps

- **Doesn't exist as a type** (see structural gap above). Closest paths are caregiver clarifications (`main.py:219`) and research tasks.
- **Last-writer-wins on clarifications** — no `If-Match`/version on `update_node_payload` (`store.py:394`).
- **Reprocess race**: parallel `process_transcription` calls duplicate `pii_redaction` + downstream tasks because `_existing_processed_result` (`extraction.py:420`) only checks `extracted_entities` edge.
- **No global dedup on transcript_id** for extraction outputs.

### Remedies

- Add `ad_hoc_event` node + extraction branch detecting non-clinical one-offs (gift, visit, errand) w/ low-confidence default and explicit caregiver confirmation.
- Add `version` field on every node; `update_node_payload` requires matching `If-Match` header; 412 on mismatch.
- Idempotency lock around transcript processing keyed `transcript:{id}`; `INSERT … ON CONFLICT DO NOTHING` on `pii_redaction(transcript_id)` w/ a uniqueness constraint.

---

## Bucket 4 — Research extraction

### Gaps

- **No PDPA processing record** — `research.py` never calls `record_processing_activity`; consent purpose `research_task_processing` is never recorded or checked. `compliance.py:34` records only `audio_transcription`.
- **Consent is write-only audit theatre** — no code path reads `consent_record` to *gate* processing; withdrawal triggers no purge.
- **Guardrail is keyword-substring** (`research.py:248`) — adversarial prompt containing "research/grant/wheelchair" passes even when intent is daily-task. No semantic guard.
- **Two-stage Sealion guardrail is illusory** — `research.py:163` runs *after* primary approval and after edges/nodes are created; "block" decision arrives post-fact.
- **PII leakage to OpenAI** — `PiiRedactor()` instantiated w/o patient seed (`research.py:501`); only regex catches NRIC/email/phone. Patient/relative names in scraped page text ship verbatim. PDPA: third-party data w/ no legal basis.
- **No URL allow-list re-validation** — provider may return out-of-domain URLs; `research.py` trusts hostnames without re-checking against `domains` allow-list.
- **Source-tier dedup collision** — `_url_key` `endswith` matching (`research.py:597`) collides unrelated `/apply` paths across hosts.
- **No per-fact provenance** — `RecommendationCard.verified_facts` is `list[str]` w/o `(source_url, retrieved_at, char_offset)`; can't audit which page produced which claim.
- **Silent local-fallback** — `research.py:472` keyword-greps when LLM extraction fails but `extraction_status` doesn't propagate to `RecommendationCard`; UI cannot warn.
- **Task auto-`approved`** — `research.py:211` sets the *task* approved on completion before the user reviews the *recommendation*.
- **Informal sources promoted** — `community_tips` lines (`research.py:574`) elevated by keyword filter only.
- **No fetch-budget cap** — `RESEARCH_FETCH_MAX_URLS` is per-question (`research.py:31`); fan-out unbounded across questions.
- **`extracted_at` is model-construction time** (`research.py:71`), not fetch time — provenance off.

### Remedies

- Wrap `run_guarded_research_pipeline` w/ `record_consent` precondition check + `record_processing_activity("research_task_processing")`. Refuse if no granted consent; on withdrawal, hard-purge research nodes + edges.
- Replace keyword guardrail w/ LLM classifier (Sealion *primary*, before plan execution) returning `{is_research, is_daily_task_misclassified, contains_third_party_phi}`. Run *before* any node creation; persist verdict.
- Move Sealion review *before* fetch; `audit_research_plan` becomes 2-of-2 gate. On block, no edges/nodes created.
- Seed `PiiRedactor` w/ `Patient` model + caregiver name + extracted relatives; enable `contextual_person_names`. Redact at fetch time, not just at LLM-payload time.
- Re-validate every returned URL against `RESEARCH_DOMAIN_ALLOWLIST` post-search; drop+log mismatches.
- Replace `endswith` dedup w/ canonical URL hash (`hashlib.sha256(scheme+host+path+sorted_query)`).
- Extend `ResearchExtraction` to `list[Fact]` where `Fact = {text, source_url, retrieved_at, page_section}`; `RecommendationCard.verified_facts` carries provenance; UI renders citation chips.
- Propagate `extraction_status="local_extracted"` into `RecommendationCard.confidence_qualifier`; UI banner.
- Flip status semantics: task `pending_review` until caregiver reviews recommendation; auto-approve only the *fetch* step.
- Run informal-source content through Sealion safety filter before any promotion; never elevate informal text to `verified_facts`.
- Add global `(patient_id, day)` fetch budget; circuit-break on exceed.
- Capture `extracted_at` from page fetch metadata, not model `default_factory`.

---

## Cross-cutting (impacts all 4 buckets)

- **Encryption-at-rest gap** — `storage_security.py:9` `SENSITIVE_PAYLOAD_FIELDS` omits `description`, `title`, `original_instruction_redacted`, `body`; rehydrated names persist plaintext. Fernet from SHA-256 of string secret (`storage_security.py:21`); no key rotation, no envelope encryption, no per-record DEK.
  **Remedy:** envelope encryption (KMS-wrapped DEK per row); rotate via re-encrypt job; expand sensitive-field set to all free-text payload fields; encrypt content not just by name but by classifier ("contains rehydrated tokens").
- **Sanitization is field-name-based**, not content-based — `sanitize_public` lets rehydrated names through in `title`/`description`.
  **Remedy:** content scanner that strips placeholder rehydrations before egress; default to redacted form, only rehydrate at last hop with explicit `Authorization` scope.
- **`require_read_access` fail-open in dev** (`main.py:97`) — no keys configured = public.
  **Remedy:** fail-closed default; explicit `ALLOW_UNAUTHENTICATED=true` to opt out, refused in `ENV ∈ {pilot,prod}`.
- **Single-patient hardcode** (`patient.py` constant) — `/audit` returns *all* reasoning logs (`main.py:445`); cross-patient leak under multi-tenant.
  **Remedy:** every endpoint scoped by `patient_id` path param; ACL on reasoning_logs; remove global `PATIENT`.
- **Reasoning logs not retained-purged** — `compliance.py:124` purges `transcript`/`pii_redaction`/`calendar_write_request` only; reasoning steps may carry `original_redacted_text` snippets.
  **Remedy:** add `reasoning_log` to retention sweep.
- **No schema migrations** — `store.py:238` raw `schema.sql` exec; no version table.
  **Remedy:** Alembic; CI gate on migration presence.
- **No audit atomicity** — feedback / decision / node mutation are 3 writes (`main.py:403–415`).
  **Remedy:** single SQL transaction wrapping all three; rollback on partial failure.
- **`Node.created_by` lacks `clinician`** — clinician edits filed under `agent`/`system`.
  **Remedy:** add literal + plumb auth principal into writes.
- **ICS feed unauthenticated by default** — `/calendar/feed.ics` (`main.py:184`) and `/calendar.ics` (`main.py:173`) only enforce auth if read keys configured (`main.py:97`). ICS body contains rehydrated patient name + care actions.
  **Remedy:** require signed feed token; fail-closed default; redact rehydrations from ICS body.
