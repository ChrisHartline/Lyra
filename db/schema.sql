CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS sources (
  id BIGSERIAL PRIMARY KEY,
  url TEXT,
  file_path TEXT,
  title TEXT,
  fetched_at TIMESTAMPTZ DEFAULT now(),
  metadata JSONB DEFAULT '{}'::jsonb,
  superseded_by BIGINT REFERENCES sources(id),
  is_own_work BOOLEAN DEFAULT false
);

CREATE TABLE IF NOT EXISTS chunks (
  id BIGSERIAL PRIMARY KEY,
  source_id BIGINT REFERENCES sources(id) ON DELETE CASCADE,
  content TEXT NOT NULL,
  embedding vector(384),
  metadata JSONB DEFAULT '{}'::jsonb
);

CREATE TABLE IF NOT EXISTS memories (
  id BIGSERIAL PRIMARY KEY,
  content TEXT NOT NULL,
  embedding vector(384),
  memory_type TEXT,
  salience SMALLINT DEFAULT 5,
  created_at TIMESTAMPTZ DEFAULT now(),
  metadata JSONB DEFAULT '{}'::jsonb,
  approved BOOLEAN DEFAULT false,
  review_status TEXT NOT NULL DEFAULT 'pending'
    CHECK (review_status IN ('pending', 'approved'))
);

ALTER TABLE memories ADD COLUMN IF NOT EXISTS review_status TEXT;
UPDATE memories
SET review_status = CASE WHEN approved THEN 'approved' ELSE 'pending' END
WHERE review_status IS NULL;
ALTER TABLE memories ALTER COLUMN review_status SET DEFAULT 'pending';
ALTER TABLE memories ALTER COLUMN review_status SET NOT NULL;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint WHERE conname = 'memories_review_status_check'
  ) THEN
    ALTER TABLE memories
      ADD CONSTRAINT memories_review_status_check
      CHECK (review_status IN ('pending', 'approved'));
  END IF;
END $$;

CREATE TABLE IF NOT EXISTS memory_review_audit (
  id BIGSERIAL PRIMARY KEY,
  proposal_id BIGINT NOT NULL,
  destination_plane TEXT NOT NULL
    CHECK (destination_plane IN ('semantic_memory', 'knowledge_graph')),
  action TEXT NOT NULL
    CHECK (action IN ('approved', 'corrected', 'rejected', 'forgotten')),
  actor TEXT NOT NULL DEFAULT 'local_user',
  reason TEXT,
  content_sha256 TEXT NOT NULL,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_memory_review_audit_proposal
  ON memory_review_audit (proposal_id, created_at DESC);

CREATE TABLE IF NOT EXISTS memory_policy (
  singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
  private_shared_mode TEXT NOT NULL DEFAULT 'auto'
    CHECK (private_shared_mode IN ('auto', 'review', 'off')),
  professional_mode TEXT NOT NULL DEFAULT 'review'
    CHECK (professional_mode IN ('auto', 'review', 'off')),
  story_mode TEXT NOT NULL DEFAULT 'auto'
    CHECK (story_mode IN ('auto', 'review', 'off')),
  campaign_mode TEXT NOT NULL DEFAULT 'auto'
    CHECK (campaign_mode IN ('auto', 'review', 'off')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO memory_policy (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  context_scope TEXT NOT NULL DEFAULT 'general'
    CHECK (context_scope IN ('general', 'professional', 'story', 'campaign')),
  synopsis TEXT,
  synopsis_through_sequence BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE chat_sessions
  ADD COLUMN IF NOT EXISTS context_scope TEXT NOT NULL DEFAULT 'general';

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'chat_sessions_context_scope_check'
      AND conrelid = 'chat_sessions'::regclass
  ) THEN
    ALTER TABLE chat_sessions
      ADD CONSTRAINT chat_sessions_context_scope_check
      CHECK (context_scope IN ('general', 'professional', 'story', 'campaign'));
  END IF;
END
$$;

CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_sessions_name_ci
  ON chat_sessions (lower(name));

CREATE TABLE IF NOT EXISTS session_messages (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  sequence BIGINT NOT NULL,
  role TEXT NOT NULL CHECK (role IN ('system', 'user', 'assistant', 'tool')),
  content TEXT NOT NULL,
  visible BOOLEAN NOT NULL DEFAULT true,
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, sequence)
);

CREATE TABLE IF NOT EXISTS memory_control_intents (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  source_message_id BIGINT NOT NULL
    REFERENCES session_messages(id) ON DELETE CASCADE,
  action TEXT NOT NULL CHECK (action IN ('forget', 'correct')),
  target_memory_id BIGINT NOT NULL,
  status TEXT NOT NULL DEFAULT 'pending'
    CHECK (status IN ('pending', 'completed', 'cancelled', 'expired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ NOT NULL,
  resolved_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_memory_control_intents_session_status
  ON memory_control_intents (session_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS session_channels (
  id BIGSERIAL PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  channel TEXT NOT NULL,
  external_id TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (channel, external_id),
  UNIQUE (session_id, channel)
);

CREATE TABLE IF NOT EXISTS channel_preferences (
  channel TEXT PRIMARY KEY,
  presentation_mode TEXT NOT NULL DEFAULT 'standard'
    CHECK (presentation_mode IN ('standard', 'concise')),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS away_policy (
  singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
  enabled BOOLEAN NOT NULL DEFAULT false,
  quiet_start TIME,
  quiet_end TIME,
  timezone TEXT NOT NULL DEFAULT 'America/Chicago',
  daily_notification_budget SMALLINT NOT NULL DEFAULT 6
    CHECK (daily_notification_budget >= 0),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS notification_events (
  id BIGSERIAL PRIMARY KEY,
  channel TEXT NOT NULL,
  category TEXT NOT NULL CHECK (
    category IN ('security', 'safety', 'service_failure', 'user_requested',
                 'digest', 'commitment', 'research', 'social', 'status')
  ),
  disposition TEXT NOT NULL CHECK (disposition IN ('send', 'batch', 'suppress')),
  reason TEXT NOT NULL,
  content TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS ritual_policy (
  singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
  morning_enabled BOOLEAN NOT NULL DEFAULT false,
  evening_enabled BOOLEAN NOT NULL DEFAULT false,
  morning_time TIME NOT NULL DEFAULT '08:00',
  evening_time TIME NOT NULL DEFAULT '21:00',
  timezone TEXT NOT NULL DEFAULT 'America/Chicago',
  channel TEXT NOT NULL DEFAULT 'telegram' CHECK (channel IN ('telegram', 'web')),
  target_session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
  notion_publish BOOLEAN NOT NULL DEFAULT false,
  vacation_until DATE,
  morning_snoozed_until TIMESTAMPTZ,
  evening_snoozed_until TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

ALTER TABLE ritual_policy
  ADD COLUMN IF NOT EXISTS target_session_id UUID
  REFERENCES chat_sessions(id) ON DELETE SET NULL;

INSERT INTO ritual_policy (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS ritual_runs (
  id UUID PRIMARY KEY,
  ritual_type TEXT NOT NULL CHECK (ritual_type IN ('morning', 'evening')),
  local_date DATE NOT NULL,
  status TEXT NOT NULL CHECK (status IN ('planned', 'delivered', 'skipped', 'batched', 'suppressed', 'failed')),
  channel TEXT NOT NULL CHECK (channel IN ('telegram', 'web')),
  session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
  source_planes JSONB NOT NULL DEFAULT '[]'::jsonb,
  content_sha256 TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at TIMESTAMPTZ,
  UNIQUE (ritual_type, local_date)
);

CREATE TABLE IF NOT EXISTS research_garden_policy (
  singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
  enabled BOOLEAN NOT NULL DEFAULT false,
  channel TEXT NOT NULL DEFAULT 'telegram' CHECK (channel IN ('telegram', 'web')),
  interval_hours SMALLINT NOT NULL DEFAULT 168 CHECK (interval_hours BETWEEN 1 AND 720),
  min_dormant_days SMALLINT NOT NULL DEFAULT 14 CHECK (min_dormant_days BETWEEN 1 AND 365),
  max_suggestions SMALLINT NOT NULL DEFAULT 3 CHECK (max_suggestions BETWEEN 1 AND 10),
  last_run_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO research_garden_policy (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS research_garden_topic_mutes (
  topic_key TEXT PRIMARY KEY,
  topic_label TEXT NOT NULL,
  muted_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  expires_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS research_garden_suggestions (
  id UUID PRIMARY KEY,
  fingerprint TEXT NOT NULL UNIQUE,
  topic_key TEXT NOT NULL,
  topic_label TEXT NOT NULL,
  summary TEXT NOT NULL,
  evidence JSONB NOT NULL,
  status TEXT NOT NULL CHECK (
    status IN ('planned', 'delivered', 'batched', 'suppressed', 'dismissed', 'failed')
  ),
  channel TEXT NOT NULL CHECK (channel IN ('telegram', 'web')),
  session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
  content_sha256 TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at TIMESTAMPTZ,
  dismissed_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_research_garden_suggestions_status
  ON research_garden_suggestions (status, created_at DESC);

CREATE TABLE IF NOT EXISTS shared_journal_entries (
  id UUID PRIMARY KEY,
  entry_type TEXT NOT NULL
    CHECK (entry_type IN ('moment', 'reflection', 'milestone')),
  title TEXT,
  content TEXT NOT NULL,
  source_session_id UUID,
  source_message_id BIGINT,
  source_channel TEXT,
  created_by TEXT NOT NULL DEFAULT 'local_user'
    CHECK (created_by = 'local_user'),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (
    (source_session_id IS NULL AND source_message_id IS NULL)
    OR
    (source_session_id IS NOT NULL AND source_message_id IS NOT NULL)
  )
);

CREATE TABLE IF NOT EXISTS shared_journal_private_sessions (
  session_id UUID PRIMARY KEY REFERENCES chat_sessions(id) ON DELETE CASCADE,
  authorized_by TEXT NOT NULL DEFAULT 'local_user'
    CHECK (authorized_by = 'local_user'),
  authorized_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS shared_journal_audit (
  id BIGSERIAL PRIMARY KEY,
  journal_entry_id UUID NOT NULL,
  action TEXT NOT NULL CHECK (action IN ('created', 'edited', 'forgotten')),
  actor TEXT NOT NULL DEFAULT 'local_user' CHECK (actor = 'local_user'),
  reason TEXT,
  old_content_sha256 TEXT,
  new_content_sha256 TEXT,
  details JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_shared_journal_entries_created
  ON shared_journal_entries (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_shared_journal_audit_entry
  ON shared_journal_audit (journal_entry_id, created_at DESC);

CREATE TABLE IF NOT EXISTS relationship_rhythm_policy (
  singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
  enabled BOOLEAN NOT NULL DEFAULT false,
  callbacks_enabled BOOLEAN NOT NULL DEFAULT false,
  rituals_enabled BOOLEAN NOT NULL DEFAULT false,
  milestones_enabled BOOLEAN NOT NULL DEFAULT false,
  cadence_days SMALLINT NOT NULL DEFAULT 7 CHECK (cadence_days BETWEEN 1 AND 90),
  local_time TIME NOT NULL DEFAULT '19:00',
  timezone TEXT NOT NULL DEFAULT 'America/Chicago',
  target_session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO relationship_rhythm_policy (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS relationship_source_mutes (
  source_key TEXT PRIMARY KEY,
  source_label_sha256 TEXT NOT NULL,
  muted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS relationship_rhythm_events (
  id UUID PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('callback', 'ritual', 'milestone')),
  dedupe_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (
    status IN ('offered', 'planned', 'delivered', 'batched', 'suppressed',
               'dismissed', 'failed')
  ),
  target_session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  content_sha256 TEXT NOT NULL,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_relationship_rhythm_events_status
  ON relationship_rhythm_events (status, created_at DESC);

CREATE TABLE IF NOT EXISTS ship_continuity_policy (
  singleton BOOLEAN PRIMARY KEY DEFAULT true CHECK (singleton),
  enabled BOOLEAN NOT NULL DEFAULT false,
  paused BOOLEAN NOT NULL DEFAULT true,
  briefs_enabled BOOLEAN NOT NULL DEFAULT false,
  ambient_enabled BOOLEAN NOT NULL DEFAULT false,
  intensity TEXT NOT NULL DEFAULT 'quiet'
    CHECK (intensity IN ('quiet', 'balanced', 'vivid')),
  cadence_days SMALLINT NOT NULL DEFAULT 7 CHECK (cadence_days BETWEEN 1 AND 30),
  local_time TIME NOT NULL DEFAULT '18:00',
  timezone TEXT NOT NULL DEFAULT 'America/Chicago',
  target_session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

INSERT INTO ship_continuity_policy (singleton) VALUES (true)
ON CONFLICT (singleton) DO NOTHING;

CREATE TABLE IF NOT EXISTS ship_continuity_events (
  id UUID PRIMARY KEY,
  event_type TEXT NOT NULL CHECK (event_type IN ('ambient')),
  dedupe_key TEXT NOT NULL UNIQUE,
  status TEXT NOT NULL CHECK (
    status IN ('planned', 'delivered', 'batched', 'suppressed', 'failed')
  ),
  target_session_id UUID REFERENCES chat_sessions(id) ON DELETE SET NULL,
  source_refs JSONB NOT NULL DEFAULT '[]'::jsonb,
  content_sha256 TEXT NOT NULL,
  canon_status TEXT NOT NULL CHECK (
    canon_status IN ('ephemeral_noncanonical')
  ),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  delivered_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_ship_continuity_events_status
  ON ship_continuity_events (status, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_notification_events_created
  ON notification_events (created_at DESC);

CREATE TABLE IF NOT EXISTS commitment_candidates (
  id UUID PRIMARY KEY,
  summary TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (
    kind IN ('promise', 'deadline', 'follow_up', 'unresolved_decision', 'task')
  ),
  due_at TIMESTAMPTZ,
  visibility_scope TEXT NOT NULL DEFAULT 'general'
    CHECK (visibility_scope IN ('general', 'professional', 'private_shared')),
  source_type TEXT NOT NULL CHECK (source_type IN ('session', 'dashboard')),
  source_session_id UUID,
  source_message_id BIGINT,
  source_url TEXT,
  source_approved BOOLEAN NOT NULL DEFAULT false,
  detection_reason TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'offered'
    CHECK (status IN ('offered', 'confirmed', 'dismissed', 'expired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  resolved_at TIMESTAMPTZ,
  CHECK (
    (source_type = 'session' AND source_session_id IS NOT NULL
      AND source_message_id IS NOT NULL)
    OR
    (source_type = 'dashboard' AND source_url IS NOT NULL
      AND source_approved = true)
  )
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'commitment_candidates'
      AND column_name = 'visibility_scope'
  ) THEN
    ALTER TABLE commitment_candidates
      ADD COLUMN visibility_scope TEXT NOT NULL DEFAULT 'general';
    UPDATE commitment_candidates
      SET visibility_scope = 'professional'
      WHERE source_type = 'dashboard';
    UPDATE commitment_candidates c
      SET visibility_scope = 'professional'
      FROM chat_sessions s
      WHERE c.source_session_id = s.id
        AND s.context_scope = 'professional';
    UPDATE commitment_candidates c
      SET visibility_scope = 'private_shared'
      FROM shared_journal_private_sessions p
      WHERE c.source_session_id = p.session_id;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'commitment_candidates_visibility_scope_check'
      AND conrelid = 'commitment_candidates'::regclass
  ) THEN
    ALTER TABLE commitment_candidates
      ADD CONSTRAINT commitment_candidates_visibility_scope_check
      CHECK (visibility_scope IN ('general', 'professional', 'private_shared'));
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_commitment_candidates_session_status
  ON commitment_candidates (source_session_id, status, created_at DESC);

CREATE TABLE IF NOT EXISTS commitments (
  id UUID PRIMARY KEY,
  candidate_id UUID NOT NULL UNIQUE
    REFERENCES commitment_candidates(id) ON DELETE RESTRICT,
  summary TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (
    kind IN ('promise', 'deadline', 'follow_up', 'unresolved_decision', 'task')
  ),
  status TEXT NOT NULL DEFAULT 'active'
    CHECK (status IN ('active', 'done', 'snoozed', 'dropped')),
  due_at TIMESTAMPTZ,
  visibility_scope TEXT NOT NULL DEFAULT 'general'
    CHECK (visibility_scope IN ('general', 'professional', 'private_shared')),
  snoozed_until TIMESTAMPTZ,
  last_reminded_at TIMESTAMPTZ,
  confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (status = 'snoozed' OR snoozed_until IS NULL)
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = current_schema()
      AND table_name = 'commitments'
      AND column_name = 'visibility_scope'
  ) THEN
    ALTER TABLE commitments
      ADD COLUMN visibility_scope TEXT NOT NULL DEFAULT 'general';
    UPDATE commitments c
      SET visibility_scope = o.visibility_scope
      FROM commitment_candidates o
      WHERE c.candidate_id = o.id;
  END IF;
END
$$;

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'commitments_visibility_scope_check'
      AND conrelid = 'commitments'::regclass
  ) THEN
    ALTER TABLE commitments
      ADD CONSTRAINT commitments_visibility_scope_check
      CHECK (visibility_scope IN ('general', 'professional', 'private_shared'));
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_commitments_status_due
  ON commitments (status, due_at);

CREATE TABLE IF NOT EXISTS stuck_interactions (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  trigger_message_id BIGINT NOT NULL REFERENCES session_messages(id) ON DELETE CASCADE,
  trigger_kind TEXT NOT NULL CHECK (trigger_kind IN ('explicit', 'observational')),
  suggested_mode TEXT NOT NULL CHECK (
    suggested_mode IN ('technical_diagnosis', 'task_decomposition',
                       'decision_support', 'stress_check_in', 'companionship')
  ),
  selected_mode TEXT CHECK (
    selected_mode IN ('technical_diagnosis', 'task_decomposition',
                      'decision_support', 'stress_check_in', 'companionship')
  ),
  depth TEXT CHECK (depth IN ('light', 'standard', 'deep')),
  status TEXT NOT NULL DEFAULT 'offered'
    CHECK (status IN ('offered', 'active', 'dismissed', 'resolved', 'expired')),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  cooldown_until TIMESTAMPTZ,
  CHECK (
    (status = 'active' AND selected_mode IS NOT NULL AND depth IS NOT NULL)
    OR status <> 'active'
  ),
  CHECK (status = 'dismissed' OR cooldown_until IS NULL)
);

DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conname = 'stuck_interactions_trigger_message_id_fkey'
      AND conrelid = 'stuck_interactions'::regclass
  ) THEN
    ALTER TABLE stuck_interactions
      ADD CONSTRAINT stuck_interactions_trigger_message_id_fkey
      FOREIGN KEY (trigger_message_id) REFERENCES session_messages(id)
      ON DELETE CASCADE;
  END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_stuck_interactions_session_status
  ON stuck_interactions (session_id, status, updated_at DESC);

CREATE TABLE IF NOT EXISTS session_turns (
  id UUID PRIMARY KEY,
  session_id UUID NOT NULL REFERENCES chat_sessions(id) ON DELETE CASCADE,
  status TEXT NOT NULL CHECK (
    status IN ('pending', 'running', 'completed', 'failed', 'cancelled', 'disconnected')
  ),
  error_code TEXT,
  started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE INDEX IF NOT EXISTS idx_session_messages_session_sequence
  ON session_messages (session_id, sequence);
CREATE INDEX IF NOT EXISTS idx_session_turns_session_started
  ON session_turns (session_id, started_at DESC);

CREATE TABLE IF NOT EXISTS telegram_updates (
  update_id BIGINT PRIMARY KEY,
  status TEXT NOT NULL CHECK (status IN ('processing', 'completed', 'failed', 'ignored')),
  error_code TEXT,
  received_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  finished_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS telegram_inbox (
  id UUID PRIMARY KEY,
  update_id BIGINT NOT NULL UNIQUE REFERENCES telegram_updates(update_id) ON DELETE RESTRICT,
  message_id BIGINT NOT NULL,
  sender_id TEXT NOT NULL,
  chat_id TEXT NOT NULL,
  media_type TEXT NOT NULL,
  original_filename TEXT,
  local_path TEXT,
  source_url TEXT,
  route TEXT NOT NULL CHECK (route IN ('corpus_candidate', 'pending_review', 'unsupported')),
  metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_telegram_inbox_created
  ON telegram_inbox (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_chunks_embedding_hnsw
  ON chunks USING hnsw (embedding vector_cosine_ops);
CREATE INDEX IF NOT EXISTS idx_memories_embedding_hnsw
  ON memories USING hnsw (embedding vector_cosine_ops);
