-- Schema Enhancements v2
-- Add application URL, benefits, and saved programs

-- Add new columns to programs table
ALTER TABLE public.programs 
ADD COLUMN IF NOT EXISTS application_url text,
ADD COLUMN IF NOT EXISTS benefits jsonb DEFAULT '{}',
ADD COLUMN IF NOT EXISTS contact_email text,
ADD COLUMN IF NOT EXISTS host_institution text,
ADD COLUMN IF NOT EXISTS duration text,
ADD COLUMN IF NOT EXISTS age_min integer,
ADD COLUMN IF NOT EXISTS age_max integer,
ADD COLUMN IF NOT EXISTS gpa_min numeric(3,2),
ADD COLUMN IF NOT EXISTS language_requirements text[],
ADD COLUMN IF NOT EXISTS award_amount text,
ADD COLUMN IF NOT EXISTS number_of_awards integer,
ADD COLUMN IF NOT EXISTS is_renewable boolean DEFAULT false;

-- Add comments for clarity
COMMENT ON COLUMN public.programs.application_url IS 'Direct link to apply (may differ from official info page)';
COMMENT ON COLUMN public.programs.benefits IS 'JSON object with tuition, stipend, housing, travel, insurance, etc.';
COMMENT ON COLUMN public.programs.host_institution IS 'University or organization hosting the program';
COMMENT ON COLUMN public.programs.duration IS 'Program duration e.g. "2 years", "4 semesters"';
COMMENT ON COLUMN public.programs.award_amount IS 'Total value or amount of award e.g. "$50,000/year"';

-- Create saved_programs table for user bookmarks
CREATE TABLE IF NOT EXISTS public.saved_programs (
  id uuid PRIMARY KEY DEFAULT uuid_generate_v4(),
  user_id uuid REFERENCES auth.users(id) ON DELETE CASCADE NOT NULL,
  program_id uuid REFERENCES public.programs(id) ON DELETE CASCADE NOT NULL,
  notes text,
  status text DEFAULT 'interested' CHECK (status IN ('interested', 'applying', 'applied', 'accepted', 'rejected')),
  created_at timestamptz DEFAULT now(),
  UNIQUE(user_id, program_id)
);

-- Enable RLS on saved_programs
ALTER TABLE public.saved_programs ENABLE ROW LEVEL SECURITY;

-- Users can only see their own saved programs
CREATE POLICY "Users view own saved programs" ON public.saved_programs
  FOR SELECT USING (auth.uid() = user_id);

CREATE POLICY "Users insert own saved programs" ON public.saved_programs
  FOR INSERT WITH CHECK (auth.uid() = user_id);

CREATE POLICY "Users update own saved programs" ON public.saved_programs
  FOR UPDATE USING (auth.uid() = user_id);

CREATE POLICY "Users delete own saved programs" ON public.saved_programs
  FOR DELETE USING (auth.uid() = user_id);

-- Create index for faster lookups
CREATE INDEX IF NOT EXISTS idx_saved_programs_user ON public.saved_programs(user_id);
CREATE INDEX IF NOT EXISTS idx_saved_programs_program ON public.saved_programs(program_id);
CREATE INDEX IF NOT EXISTS idx_programs_host ON public.programs(host_institution);
