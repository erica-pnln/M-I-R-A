create table if not exists projects (
  id uuid primary key default gen_random_uuid(),
  user_id uuid not null references auth.users(id) on delete cascade,
  title text not null check (char_length(title) between 1 and 80),
  created_at timestamptz not null default now()
);

create index if not exists projects_user_created_idx
  on projects (user_id, created_at desc);

alter table conversations
  add column if not exists project_id uuid
  references projects(id) on delete set null;

create index if not exists conversations_project_created_idx
  on conversations (project_id, created_at desc);

alter table projects enable row level security;
drop policy if exists "own projects" on projects;
create policy "own projects" on projects
  for all using (auth.uid() = user_id)
  with check (auth.uid() = user_id);
