alter table profiles
  add column if not exists journalism_fields text[] not null default '{}';

alter table profiles
  add column if not exists onboarding_completed boolean not null default false;

update profiles
set journalism_fields = interests,
    interests = '{}'
where cardinality(journalism_fields) = 0
  and cardinality(interests) > 0
  and interests <@ array[
    'Photojournalism',
    'Sports Journalism',
    'Mobile Journalism',
    'Media Arts',
    'Campus Journalism',
    'News Writing',
    'Feature Writing',
    'Editorial Writing',
    'Science and Technology',
    'Investigative Journalism',
    'Campus News Writing',
    'Campus Editorial Writing',
    'Campus Feature Writing',
    'Campus Sports Writing',
    'Campus Science and Technology Writing',
    'Campus Photojournalism',
    'Campus Copyreading and Headline Writing',
    'Campus Cartooning',
    'Campus Radio Broadcasting',
    'Campus TV Broadcasting',
    'Campus Collaborative Publishing',
    'Campus Online Publishing'
  ]::text[];
