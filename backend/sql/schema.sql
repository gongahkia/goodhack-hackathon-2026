create table if not exists reasoning_logs (
  id uuid primary key,
  trigger text not null,
  steps jsonb not null default '[]'::jsonb,
  conclusion text,
  created_at timestamptz default now()
);

create table if not exists nodes (
  id uuid primary key,
  type text not null check (type in (
    'nehr_record',
    'inferred_condition',
    'scheduled_action',
    'recommended_resource',
    'grant_opportunity',
    'caregiver_feedback',
    'caregiver_note',
    'care_intent',
    'research_note',
    'decision_forecast',
    'memory_profile',
    'human_evaluation',
    'transcription_session',
    'transcript',
    'transcript_review',
    'pii_redaction',
    'extracted_entities',
    'triage_decision',
    'daily_task',
    'schedule_conflict',
    'notification_candidate',
    'ad_hoc_research_task',
    'research_plan',
    'guardrail_review',
    'research_result',
    'synthesized_recommendation',
    'appointment_candidate',
    'calendar_write_request',
    'user_decision'
  )),
  payload jsonb not null,
  created_by text not null check (created_by in ('agent', 'system', 'user')),
  created_at timestamptz default now(),
  reasoning_log_id uuid references reasoning_logs(id),
  status text default 'pending_review' check (status in ('pending_review', 'approved', 'dismissed', 'edited', 'clarification_required'))
);

create table if not exists edges (
  id uuid primary key,
  from_node uuid references nodes(id) on delete cascade,
  to_node uuid references nodes(id) on delete cascade,
  type text not null check (type in (
    'derived_from',
    'triggers',
    'recommends',
    'applies_to',
    'feedback_on',
    'extracted_from',
    'clarifies',
    'researches',
    'scheduled_from',
    'evaluates',
    'transcribed_to',
    'redacted_as',
    'reviewed_from',
    'triaged_from',
    'classified_as',
    'conflicts_with',
    'notifies_about',
    'guarded_by',
    'approved_research',
    'blocked_research',
    'synthesized_from',
    'requires_approval',
    'approved_by_user',
    'written_to_calendar'
  )),
  created_at timestamptz default now()
);

alter table nodes drop constraint if exists nodes_type_check;
alter table nodes add constraint nodes_type_check check (type in (
  'nehr_record',
  'inferred_condition',
  'scheduled_action',
  'recommended_resource',
  'grant_opportunity',
  'caregiver_feedback',
  'caregiver_note',
  'care_intent',
  'research_note',
  'decision_forecast',
  'memory_profile',
  'human_evaluation',
  'transcription_session',
  'transcript',
  'transcript_review',
  'pii_redaction',
  'extracted_entities',
  'triage_decision',
  'daily_task',
  'schedule_conflict',
  'notification_candidate',
  'ad_hoc_research_task',
  'research_plan',
  'guardrail_review',
  'research_result',
  'synthesized_recommendation',
  'appointment_candidate',
  'calendar_write_request',
  'user_decision'
));

alter table nodes drop constraint if exists nodes_status_check;
alter table nodes add constraint nodes_status_check check (status in ('pending_review', 'approved', 'dismissed', 'edited', 'clarification_required'));

alter table edges drop constraint if exists edges_type_check;
alter table edges add constraint edges_type_check check (type in (
  'derived_from',
  'triggers',
  'recommends',
  'applies_to',
  'feedback_on',
  'extracted_from',
  'clarifies',
  'researches',
  'scheduled_from',
  'evaluates',
  'transcribed_to',
  'redacted_as',
  'reviewed_from',
  'triaged_from',
  'classified_as',
  'conflicts_with',
  'notifies_about',
  'guarded_by',
  'approved_research',
  'blocked_research',
  'synthesized_from',
  'requires_approval',
  'approved_by_user',
  'written_to_calendar'
));

create table if not exists nehr_records_raw (
  id uuid primary key,
  patient_id text not null,
  record_type text not null check (record_type in ('diagnosis', 'prescription', 'lab_result', 'doctor_note', 'appointment')),
  content jsonb not null,
  recorded_at timestamptz not null,
  ingested_at timestamptz default now()
);

create table if not exists system_state (
  key text primary key,
  value jsonb not null default '{}'::jsonb,
  locked_until timestamptz,
  updated_at timestamptz default now()
);

create index if not exists idx_nodes_type on nodes(type);
create index if not exists idx_nodes_patient on nodes((payload->>'patient_id'));
create index if not exists idx_edges_from on edges(from_node);
create index if not exists idx_edges_to on edges(to_node);
create index if not exists idx_edges_type on edges(type);
create index if not exists idx_nehr_patient_recorded on nehr_records_raw(patient_id, recorded_at desc);
create index if not exists idx_system_state_locked_until on system_state(locked_until);

create or replace function validate_scheduled_action_provenance()
returns trigger
language plpgsql
as $$
begin
  if new.type = 'scheduled_action' and not exists (
    select 1
    from edges e
    join nodes source on source.id = e.to_node
    where e.from_node = new.id
      and e.type = 'derived_from'
      and source.type in ('nehr_record', 'inferred_condition', 'caregiver_note', 'care_intent', 'decision_forecast')
  ) then
    raise exception 'scheduled_action % must have a derived_from edge to a nehr_record or inferred_condition', new.id;
  end if;

  return new;
end;
$$;

drop trigger if exists scheduled_action_provenance_check on nodes;
create constraint trigger scheduled_action_provenance_check
after insert or update of type on nodes
deferrable initially deferred
for each row
execute function validate_scheduled_action_provenance();
