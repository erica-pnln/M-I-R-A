alter table profiles
  add column if not exists language text not null default 'en';

update profiles
set language = 'en'
where language not in ('en', 'fil', 'ceb');

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

alter table profiles
  add column if not exists system_language text not null default 'en';

update profiles
set system_language = language
where system_language = 'en'
  and language in ('en', 'fil', 'ceb')
  and language <> 'en';

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
