-- ScholarMap Core Schema
create extension if not exists "uuid-ossp";

create table public.programs (
  id uuid primary key default uuid_generate_v4(),
  name text not null,
  provider text not null,
  level text not null check (level in ('bachelor', 'masters', 'phd', 'postdoc')),
  funding_type text not null check (funding_type in ('full', 'partial', 'tuition_only', 'stipend_only')),
  countries_eligible text[] default '{}',
  countries_of_study text[] default '{}',
  fields text[] default '{}',
  official_url text not null,
  description text,
  who_wins text,
  rejection_reasons text,
  status text not null default 'active' check (status in ('active', 'paused', 'discontinued', 'unknown')),
  last_verified_at timestamptz,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create table public.eligibility_rules (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid references public.programs(id) on delete cascade not null,
  rule_type text not null check (rule_type in ('gpa', 'degree', 'nationality', 'age', 'work_experience', 'language', 'other')),
  operator text not null check (operator in ('=', '>=', '<=', '>', '<', 'in', 'not_in', 'exists', 'between')),
  value jsonb not null,
  confidence text not null default 'medium' check (confidence in ('high', 'medium', 'inferred')),
  source_snippet text,
  created_at timestamptz default now()
);

create table public.requirements (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid references public.programs(id) on delete cascade not null,
  type text not null check (type in ('transcript', 'cv', 'essay', 'references', 'proposal', 'test', 'interview', 'other')),
  description text not null,
  mandatory boolean default true,
  created_at timestamptz default now()
);

create table public.deadlines (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid references public.programs(id) on delete cascade not null,
  cycle text not null,
  deadline_date date not null,
  timezone text default 'UTC',
  stage text not null check (stage in ('application', 'interview', 'nomination', 'result')),
  created_at timestamptz default now()
);

create table public.sources (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid references public.programs(id) on delete cascade not null,
  url text not null,
  retrieved_at timestamptz default now(),
  agent_model text,
  raw_summary text,
  confidence_score numeric(3,2) check (confidence_score >= 0 and confidence_score <= 1),
  created_at timestamptz default now()
);

create table public.agent_reviews (
  id uuid primary key default uuid_generate_v4(),
  program_id uuid references public.programs(id) on delete cascade not null,
  issue_type text not null check (issue_type in ('outdated', 'conflicting', 'missing_data', 'suspicious')),
  note text,
  severity text not null default 'medium' check (severity in ('low', 'medium', 'high')),
  resolved boolean default false,
  created_at timestamptz default now()
);

create table public.profiles (
  id uuid primary key references auth.users(id) on delete cascade,
  email text,
  full_name text,
  nationality text,
  degree text,
  gpa_band text check (gpa_band in ('below_2.5', '2.5_3.0', '3.0_3.5', '3.5_4.0', 'above_4.0')),
  field text,
  work_experience_years integer default 0,
  created_at timestamptz default now(),
  updated_at timestamptz default now()
);

create index idx_programs_level on public.programs(level);
create index idx_programs_status on public.programs(status);
create index idx_programs_countries on public.programs using gin(countries_eligible);
create index idx_programs_fields on public.programs using gin(fields);
create index idx_deadlines_date on public.deadlines(deadline_date);
create index idx_agent_reviews_resolved on public.agent_reviews(resolved);

create or replace function public.handle_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

create trigger programs_updated_at before update on public.programs
  for each row execute function public.handle_updated_at();

create trigger profiles_updated_at before update on public.profiles
  for each row execute function public.handle_updated_at();
