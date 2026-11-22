create table if not exists ai_usage (
  id bigserial primary key,
  request_id uuid not null,
  provider text not null,
  model text not null,
  request_type text not null,
  status text not null check (status in ('success', 'cached', 'error')),
  input_tokens integer,
  output_tokens integer,
  fallback_attempt integer not null default 0,
  error_category text,
  created_at timestamptz not null default now()
);

create index if not exists ai_usage_created_at_idx on ai_usage (created_at desc);
create index if not exists ai_usage_request_id_idx on ai_usage (request_id);
alter table ai_usage enable row level security;
