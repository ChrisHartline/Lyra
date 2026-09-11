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

CREATE TABLE IF NOT EXISTS chat_sessions (
  id UUID PRIMARY KEY,
  name TEXT NOT NULL,
  synopsis TEXT,
  synopsis_through_sequence BIGINT NOT NULL DEFAULT 0,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

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

CREATE INDEX IF NOT EXISTS idx_notification_events_created
  ON notification_events (created_at DESC);

CREATE TABLE IF NOT EXISTS commitment_candidates (
  id UUID PRIMARY KEY,
  summary TEXT NOT NULL,
  kind TEXT NOT NULL CHECK (
    kind IN ('promise', 'deadline', 'follow_up', 'unresolved_decision', 'task')
  ),
  due_at TIMESTAMPTZ,
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
  snoozed_until TIMESTAMPTZ,
  last_reminded_at TIMESTAMPTZ,
  confirmed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  CHECK (status = 'snoozed' OR snoozed_until IS NULL)
);

CREATE INDEX IF NOT EXISTS idx_commitments_status_due
  ON commitments (status, due_at);

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
