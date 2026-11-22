alter table profiles
  add column if not exists ai_language text not null default 'en';

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
