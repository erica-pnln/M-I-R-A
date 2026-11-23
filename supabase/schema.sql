-- MIRA schema. Run in the Supabase SQL Editor.
create extension if not exists pgcrypto;
create schema if not exists extensions;
create extension if not exists vector with schema extensions;

create table if not exists profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  display_name text,
  username text,
  interests text[] default '{}',
  journalism_fields text[] not null default '{}',
  onboarding_completed boolean not null default false,
  system_language text not null default 'en' check (system_language in ('en', 'fil', 'ceb')),
  language text not null default 'en' check (language in ('en', 'fil', 'ceb')),
  ai_language text not null default 'en' check (ai_language in ('en', 'fil', 'ceb')),
  created_at timestamptz default now()
);

alter table profiles add column if not exists username text;
alter table profiles add column if not exists journalism_fields text[] not null default '{}';
alter table profiles add column if not exists onboarding_completed boolean not null default false;
alter table profiles add column if not exists system_language text not null default 'en';
alter table profiles add column if not exists language text not null default 'en';
alter table profiles add column if not exists ai_language text not null default 'en';
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_language_check'
      and conrelid = 'public.profiles'::regclass
  ) then
    alter table profiles add constraint profiles_language_check
      check (language in ('en', 'fil', 'ceb'));
  end if;
end;
$$;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_system_language_check'
      and conrelid = 'public.profiles'::regclass
  ) then
    alter table profiles add constraint profiles_system_language_check
      check (system_language in ('en', 'fil', 'ceb'));
  end if;
end;
$$;
do $$
begin
  if not exists (
    select 1 from pg_constraint
    where conname = 'profiles_ai_language_check'
      and conrelid = 'public.profiles'::regclass
  ) then
    alter table profiles add constraint profiles_ai_language_check
      check (ai_language in ('en', 'fil', 'ceb'));
  end if;
end;
$$;
create unique index if not exists profiles_username_idx on profiles (username) where username is not null;

create table if not exists articles (
  id text primary key,
  canonical_url text not null unique,
  title text not null,
  summary text not null default '',
  source text not null,
  author text,
  section text not null check (section in ('local', 'regional', 'national', 'international')),
  category text,
  url text not null,
  image_url text,
  published timestamptz,
  collected_at timestamptz not null default now()
);

alter table articles add column if not exists author text;

do $$
begin
  if exists (
    select 1 from pg_constraint
    where conrelid = 'public.articles'::regclass
      and conname = 'articles_section_check'
      and pg_get_constraintdef(oid) not like '%regional%'
  ) then
    alter table public.articles drop constraint articles_section_check;
  end if;
  if not exists (
    select 1 from pg_constraint
    where conrelid = 'public.articles'::regclass
      and conname = 'articles_section_check'
  ) then
    alter table public.articles
      add constraint articles_section_check
      check (section in ('local', 'regional', 'national', 'international'));
  end if;
end;
$$;

create index if not exists articles_published_idx on articles (published desc);
create index if not exists articles_section_published_idx on articles (section, published desc);

-- Sentence-transformer vectors power semantic and hybrid news retrieval.
create table if not exists article_embeddings (
  article_id text primary key references articles(id) on delete cascade,
  embedding extensions.vector(384) not null,
  model text not null,
  content_hash text not null,
  updated_at timestamptz not null default now()
);

alter table article_embeddings enable row level security;
create index if not exists article_embeddings_vector_idx
  on article_embeddings using hnsw (embedding extensions.vector_cosine_ops);

create or replace function public.hybrid_search_articles(
  query_embedding extensions.vector(384),
  match_count integer default 10,
  embedding_model text default 'sentence-transformers/all-MiniLM-L6-v2'
)
returns setof public.articles
language sql
stable
set search_path = public, extensions
as $$
  select a.*
  from public.articles a
  join public.article_embeddings e on e.article_id = a.id
  where e.model = embedding_model
  order by e.embedding <=> query_embedding
  limit greatest(1, least(match_count, 1000));
$$;

create table if not exists favorites (
  user_id uuid references auth.users(id) on delete cascade,
  article_id text not null,
  title text, source text, url text, summary text,
  saved_at timestamptz default now(),
  primary key (user_id, article_id)
);

create table if not exists reading_history (
  id bigserial primary key,
  user_id uuid references auth.users(id) on delete cascade,
  article_id text not null,
  title text, source text, url text,
  viewed_at timestamptz default now()
);
create index if not exists reading_history_user_viewed_idx on reading_history (user_id, viewed_at desc);

create table if not exists search_history (
  id bigserial primary key,
  user_id uuid not null references auth.users(id) on delete cascade,
  query text not null,
  searched_at timestamptz not null default now()
);
create index if not exists search_history_user_searched_idx on search_history (user_id, searched_at desc);

create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 80),
  created_at timestamptz not null default now()
);
create index if not exists projects_user_created_idx on projects (user_id, created_at desc);

create table if not exists conversations (
  id uuid primary key default gen_random_uuid(),
  user_id uuid references auth.users(id) on delete cascade,
  kind text not null default 'chat',        -- 'chat' or 'story'
  article_id text,
  title text,
  project_id uuid references projects(id) on delete set null,
  created_at timestamptz default now()
);
alter table conversations add column if not exists project_id uuid references projects(id) on delete set null;
create index if not exists conversations_project_created_idx on conversations (project_id, created_at desc);

create table if not exists messages (
  id bigserial primary key,
  conversation_id uuid references conversations(id) on delete cascade,
  role text not null check (role in ('user','assistant')),
  content text not null,
  created_at timestamptz default now()
);

-- Provider metadata only; never store prompts, uploaded files, or API credentials here.
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

-- Ask Story has a separate provider-usage table from MIRA AI Chat.
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

-- Row Level Security: users only see their own rows.
alter table profiles enable row level security;
alter table articles enable row level security;
alter table favorites enable row level security;
alter table reading_history enable row level security;
alter table search_history enable row level security;
alter table projects enable row level security;
alter table conversations enable row level security;
alter table messages enable row level security;

drop policy if exists "public articles are readable" on articles;
drop policy if exists "own profile" on profiles;
drop policy if exists "own favorites" on favorites;
drop policy if exists "own history" on reading_history;
drop policy if exists "own search history" on search_history;
drop policy if exists "own projects" on projects;
drop policy if exists "own conversations" on conversations;
drop policy if exists "own messages" on messages;

create policy "own profile" on profiles for all using (auth.uid() = id) with check (auth.uid() = id);
create policy "public articles are readable" on articles for select using (true);
create policy "own favorites" on favorites for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own history" on reading_history for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own search history" on search_history for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own projects" on projects for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own conversations" on conversations for all using (auth.uid() = user_id) with check (auth.uid() = user_id);
create policy "own messages" on messages for all
  using (exists (select 1 from conversations c where c.id = conversation_id and c.user_id = auth.uid()))
  with check (exists (select 1 from conversations c where c.id = conversation_id and c.user_id = auth.uid()));

-- Create a profile automatically when someone signs up.
create or replace function public.handle_new_user()
returns trigger
language plpgsql
security definer
set search_path = pg_catalog, public
as $$
declare
  profile_username text := nullif(btrim(new.raw_user_meta_data->>'username'), '');
begin
  begin
    insert into public.profiles (id, display_name, username)
    values (
      new.id,
      coalesce(
        nullif(new.raw_user_meta_data->>'display_name', ''),
        profile_username,
        split_part(coalesce(new.email, ''), '@', 1)
      ),
      profile_username
    );
  exception when unique_violation then
    if profile_username is null then
      raise;
    end if;

    insert into public.profiles (id, display_name, username)
    values (
      new.id,
      coalesce(
        nullif(new.raw_user_meta_data->>'display_name', ''),
        profile_username,
        split_part(coalesce(new.email, ''), '@', 1)
      ),
      left(profile_username, 64) || '_' || replace(new.id::text, '-', '')
    );
  end;
  return new;
end;
$$;
drop trigger if exists on_auth_user_created on auth.users;
create trigger on_auth_user_created after insert on auth.users
  for each row execute function public.handle_new_user();
