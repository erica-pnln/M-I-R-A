create table if not exists ask_story_usage (
  id bigserial primary key,
  request_id uuid not null,
  provider text not null,
  model text not null,
  request_type text not null,
  article_id text,
  status text not null check (status in ('success', 'cached', 'error')),
  input_tokens integer,
  output_tokens integer,
  fallback_attempt integer not null default 0,
  error_category text,
  response_time_ms integer,
  created_at timestamptz not null default now()
);

create index if not exists ask_story_usage_created_at_idx
  on ask_story_usage (created_at desc);
create index if not exists ask_story_usage_request_id_idx
  on ask_story_usage (request_id);
create index if not exists ask_story_usage_article_id_idx
  on ask_story_usage (article_id);

alter table ask_story_usage enable row level security;
