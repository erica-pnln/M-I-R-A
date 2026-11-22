alter table public.articles
  drop constraint if exists articles_section_check;

alter table public.articles
  add constraint articles_section_check
  check (section in ('local', 'regional', 'national', 'international'));
