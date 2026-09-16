-- Schema v1 of the Core state DB, dumped verbatim from sqlite_master of
-- data/state/jarvis.sqlite3 on 2026-09-16 (before the v2 conversation_events
-- migration). Rows are synthetic. Used by tests/unit/test_conversation_event_store.py.

CREATE TABLE schema_version (version INTEGER NOT NULL);
CREATE TABLE devices (id TEXT PRIMARY KEY, data TEXT NOT NULL);
CREATE TABLE conversations (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE INDEX idx_turns_conversation_time ON turns(conversation_id, created_at, id);
CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX idx_jobs_status ON jobs(status, created_at);
CREATE TABLE scheduled_items (id TEXT PRIMARY KEY, status TEXT NOT NULL, next_fire_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX idx_schedule_due ON scheduled_items(status, next_fire_at);
CREATE TABLE notifications (id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE INDEX idx_notifications_state ON notifications(state, created_at);
CREATE TABLE voice_history_projections (
                conversation_id TEXT NOT NULL, output_key TEXT NOT NULL,
                confirmed_end INTEGER NOT NULL DEFAULT 0, pending_turn TEXT,
                PRIMARY KEY(conversation_id, output_key),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE voice_conversation_snapshots (
                conversation_id TEXT PRIMARY KEY, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_sources (
                conversation_id TEXT NOT NULL, correlation_id TEXT NOT NULL, epoch INTEGER NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(conversation_id,correlation_id), UNIQUE(conversation_id,epoch),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_current_sources (
                conversation_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_invalidated_dependencies (
                conversation_id TEXT NOT NULL, work_id TEXT NOT NULL, source_correlation_id TEXT NOT NULL,
                PRIMARY KEY(conversation_id,work_id,source_correlation_id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_outcomes (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE INDEX idx_brain_outcomes_conversation ON brain_outcomes(conversation_id,created_at,id);
CREATE TABLE brain_outcome_selections (
                conversation_id TEXT NOT NULL, selection_id TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(conversation_id,selection_id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE back_brain_advisories (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE live_sessions (
                session_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                revision INTEGER NOT NULL, data TEXT NOT NULL
            );
CREATE UNIQUE INDEX idx_one_unresolved_live_session
                ON live_sessions((1)) WHERE state <> 'stopped';

INSERT INTO schema_version(version) VALUES (1);
INSERT INTO devices(id,data) VALUES ('windows-desktop','{"device_id":"windows-desktop"}');
INSERT INTO conversations(id,updated_at,data) VALUES ('conv-v1','2026-09-03T09:41:19.197536+00:00','{"created_at":"2026-09-03T09:41:19.197532+00:00","current_device_id":"windows-desktop","id":"conv-v1","originating_device_id":"windows-desktop","status":"closed","summary":"","transport_session_id":null,"updated_at":"2026-09-03T09:41:19.197536+00:00"}');
INSERT INTO turns(id,conversation_id,created_at,data) VALUES ('turn-v1','conv-v1','2026-09-03T09:41:20.000000+00:00','{"content":"bonjour","conversation_id":"conv-v1","correlation_id":"corr-v1","created_at":"2026-09-03T09:41:20.000000+00:00","id":"turn-v1","kind":"user","metadata":{},"reference_id":null}');
