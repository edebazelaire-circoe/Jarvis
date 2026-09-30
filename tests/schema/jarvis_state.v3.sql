-- schema_version = [(3,)]
-- index idx_bindings_conversation ON board_conversation_bindings
CREATE INDEX idx_bindings_conversation ON board_conversation_bindings(conversation_id);
-- index idx_brain_outcomes_conversation ON brain_outcomes
CREATE INDEX idx_brain_outcomes_conversation ON brain_outcomes(conversation_id,created_at,id);
-- index idx_conversation_events_conversation ON conversation_events
CREATE INDEX idx_conversation_events_conversation ON conversation_events(conversation_id, sequence);
-- index idx_conversation_events_correlation_id ON conversation_events
CREATE INDEX idx_conversation_events_correlation_id ON conversation_events(correlation_id, sequence) WHERE correlation_id IS NOT NULL;
-- index idx_conversation_events_occurred ON conversation_events
CREATE INDEX idx_conversation_events_occurred ON conversation_events(occurred_at, sequence);
-- index idx_conversation_events_outcome_id ON conversation_events
CREATE INDEX idx_conversation_events_outcome_id ON conversation_events(outcome_id, sequence) WHERE outcome_id IS NOT NULL;
-- index idx_conversation_events_session_id ON conversation_events
CREATE INDEX idx_conversation_events_session_id ON conversation_events(session_id, sequence) WHERE session_id IS NOT NULL;
-- index idx_conversation_events_span_id ON conversation_events
CREATE INDEX idx_conversation_events_span_id ON conversation_events(span_id, sequence) WHERE span_id IS NOT NULL;
-- index idx_conversation_events_speech_id ON conversation_events
CREATE INDEX idx_conversation_events_speech_id ON conversation_events(speech_id, sequence) WHERE speech_id IS NOT NULL;
-- index idx_conversation_events_task_id ON conversation_events
CREATE INDEX idx_conversation_events_task_id ON conversation_events(task_id, sequence) WHERE task_id IS NOT NULL;
-- index idx_conversation_events_turn_id ON conversation_events
CREATE INDEX idx_conversation_events_turn_id ON conversation_events(turn_id, sequence) WHERE turn_id IS NOT NULL;
-- index idx_conversation_events_work_id ON conversation_events
CREATE INDEX idx_conversation_events_work_id ON conversation_events(work_id, sequence) WHERE work_id IS NOT NULL;
-- index idx_jarvis_sessions_started ON jarvis_sessions
CREATE INDEX idx_jarvis_sessions_started ON jarvis_sessions(started_at, jarvis_session_id);
-- index idx_jobs_status ON jobs
CREATE INDEX idx_jobs_status ON jobs(status, created_at);
-- index idx_notifications_state ON notifications
CREATE INDEX idx_notifications_state ON notifications(state, created_at);
-- index idx_one_foreground_binding ON board_conversation_bindings
CREATE UNIQUE INDEX idx_one_foreground_binding ON board_conversation_bindings(jarvis_session_id) WHERE lifecycle = 'foreground';
-- index idx_one_open_jarvis_session ON jarvis_sessions
CREATE UNIQUE INDEX idx_one_open_jarvis_session ON jarvis_sessions((1)) WHERE status = 'open';
-- index idx_one_unresolved_live_session ON live_sessions
CREATE UNIQUE INDEX idx_one_unresolved_live_session ON live_sessions((1)) WHERE state <> 'stopped';
-- index idx_schedule_due ON scheduled_items
CREATE INDEX idx_schedule_due ON scheduled_items(status, next_fire_at);
-- index idx_turns_conversation_time ON turns
CREATE INDEX idx_turns_conversation_time ON turns(conversation_id, created_at, id);
-- index idx_work_boards_status ON work_boards
CREATE INDEX idx_work_boards_status ON work_boards(status, created_at, board_id);
-- table back_brain_advisories ON back_brain_advisories
CREATE TABLE back_brain_advisories (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
-- table board_conversation_bindings ON board_conversation_bindings
CREATE TABLE board_conversation_bindings ( jarvis_session_id TEXT NOT NULL REFERENCES jarvis_sessions(jarvis_session_id), board_id TEXT NOT NULL REFERENCES work_boards(board_id), conversation_id TEXT NOT NULL, lifecycle TEXT NOT NULL CHECK (lifecycle IN ('foreground', 'background_running', 'suspended')), status TEXT NOT NULL CHECK (status IN ('open', 'closed')), created_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (jarvis_session_id, board_id));
-- table brain_current_sources ON brain_current_sources
CREATE TABLE brain_current_sources ( conversation_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, data TEXT NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table brain_invalidated_dependencies ON brain_invalidated_dependencies
CREATE TABLE brain_invalidated_dependencies ( conversation_id TEXT NOT NULL, work_id TEXT NOT NULL, source_correlation_id TEXT NOT NULL, PRIMARY KEY(conversation_id,work_id,source_correlation_id), FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table brain_outcome_selections ON brain_outcome_selections
CREATE TABLE brain_outcome_selections ( conversation_id TEXT NOT NULL, selection_id TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY(conversation_id,selection_id), FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table brain_outcomes ON brain_outcomes
CREATE TABLE brain_outcomes ( id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table brain_sources ON brain_sources
CREATE TABLE brain_sources ( conversation_id TEXT NOT NULL, correlation_id TEXT NOT NULL, epoch INTEGER NOT NULL, data TEXT NOT NULL, PRIMARY KEY(conversation_id,correlation_id), UNIQUE(conversation_id,epoch), FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table conversation_events ON conversation_events
CREATE TABLE conversation_events ( sequence INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, conversation_id TEXT NOT NULL, session_id TEXT, event_type TEXT NOT NULL, actor TEXT NOT NULL, visibility TEXT NOT NULL, occurred_at TEXT NOT NULL, recorded_at TEXT NOT NULL, span_id TEXT, turn_id TEXT, correlation_id TEXT, task_id TEXT, work_id TEXT, speech_id TEXT, outcome_id TEXT, data TEXT NOT NULL);
-- table conversations ON conversations
CREATE TABLE conversations (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, data TEXT NOT NULL);
-- table devices ON devices
CREATE TABLE devices (id TEXT PRIMARY KEY, data TEXT NOT NULL);
-- table jarvis_sessions ON jarvis_sessions
CREATE TABLE jarvis_sessions ( jarvis_session_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('open', 'closed')), started_at TEXT NOT NULL, active_board_id TEXT NOT NULL, data TEXT NOT NULL);
-- table jobs ON jobs
CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
-- table live_sessions ON live_sessions
CREATE TABLE live_sessions ( session_id TEXT PRIMARY KEY, state TEXT NOT NULL, revision INTEGER NOT NULL, data TEXT NOT NULL );
-- table notifications ON notifications
CREATE TABLE notifications (id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
-- table scheduled_items ON scheduled_items
CREATE TABLE scheduled_items (id TEXT PRIMARY KEY, status TEXT NOT NULL, next_fire_at TEXT NOT NULL, data TEXT NOT NULL);
-- table schema_version ON schema_version
CREATE TABLE schema_version (version INTEGER NOT NULL);
-- table turns ON turns
CREATE TABLE turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table voice_conversation_snapshots ON voice_conversation_snapshots
CREATE TABLE voice_conversation_snapshots ( conversation_id TEXT PRIMARY KEY, data TEXT NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table voice_history_projections ON voice_history_projections
CREATE TABLE voice_history_projections ( conversation_id TEXT NOT NULL, output_key TEXT NOT NULL, confirmed_end INTEGER NOT NULL DEFAULT 0, pending_turn TEXT, PRIMARY KEY(conversation_id, output_key), FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table work_boards ON work_boards
CREATE TABLE work_boards ( board_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('active', 'archived')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
