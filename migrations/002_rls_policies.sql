-- Row Level Security Policies
alter table public.programs enable row level security;
alter table public.eligibility_rules enable row level security;
alter table public.requirements enable row level security;
alter table public.deadlines enable row level security;
alter table public.sources enable row level security;
alter table public.agent_reviews enable row level security;
alter table public.profiles enable row level security;

-- Programs: public read, service role write
create policy "Programs are viewable by everyone" on public.programs
  for select using (status = 'active');

create policy "Service role can manage programs" on public.programs
  for all using (auth.role() = 'service_role');

-- Eligibility rules: public read
create policy "Eligibility rules viewable by everyone" on public.eligibility_rules
  for select using (true);

create policy "Service role manages rules" on public.eligibility_rules
  for all using (auth.role() = 'service_role');

-- Requirements: public read
create policy "Requirements viewable by everyone" on public.requirements
  for select using (true);

create policy "Service role manages requirements" on public.requirements
  for all using (auth.role() = 'service_role');

-- Deadlines: public read
create policy "Deadlines viewable by everyone" on public.deadlines
  for select using (true);

create policy "Service role manages deadlines" on public.deadlines
  for all using (auth.role() = 'service_role');

-- Sources: public read
create policy "Sources viewable by everyone" on public.sources
  for select using (true);

create policy "Service role manages sources" on public.sources
  for all using (auth.role() = 'service_role');

-- Agent reviews: service role only
create policy "Service role manages reviews" on public.agent_reviews
  for all using (auth.role() = 'service_role');

-- Profiles: users manage own profile
create policy "Users can view own profile" on public.profiles
  for select using (auth.uid() = id);

create policy "Users can insert own profile" on public.profiles
  for insert with check (auth.uid() = id);

create policy "Users can update own profile" on public.profiles
  for update using (auth.uid() = id);
