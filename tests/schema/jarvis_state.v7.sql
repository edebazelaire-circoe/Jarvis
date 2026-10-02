-- schema_version = [(7,)]
-- index idx_artifact_relations_origin ON artifact_relations
CREATE INDEX idx_artifact_relations_origin ON artifact_relations(origin_artifact_id, relation, artifact_id);
-- index idx_artifacts_context ON artifacts
CREATE INDEX idx_artifacts_context ON artifacts(context_id, created_at, artifact_id) WHERE context_id IS NOT NULL;
-- index idx_artifacts_kind ON artifacts
CREATE INDEX idx_artifacts_kind ON artifacts(kind, created_at, artifact_id);
-- index idx_artifacts_session ON artifacts
CREATE INDEX idx_artifacts_session ON artifacts(jarvis_session_id, created_at, artifact_id) WHERE jarvis_session_id IS NOT NULL;
-- index idx_artifacts_state ON artifacts
CREATE INDEX idx_artifacts_state ON artifacts(state, created_at, artifact_id);
-- index idx_artifacts_time ON artifacts
CREATE INDEX idx_artifacts_time ON artifacts(created_at, artifact_id);
-- index idx_bindings_conversation ON board_conversation_bindings
CREATE INDEX idx_bindings_conversation ON board_conversation_bindings(conversation_id);
-- index idx_brain_outcomes_conversation ON brain_outcomes
CREATE INDEX idx_brain_outcomes_conversation ON brain_outcomes(conversation_id,created_at,id);
-- index idx_captures_artifact ON captures
CREATE INDEX idx_captures_artifact ON captures(artifact_id) WHERE artifact_id IS NOT NULL;
-- index idx_captures_session ON captures
CREATE INDEX idx_captures_session ON captures(jarvis_session_id, created_at, capture_id) WHERE jarvis_session_id IS NOT NULL;
-- index idx_captures_state ON captures
CREATE INDEX idx_captures_state ON captures(state, created_at, capture_id);
-- index idx_captures_time ON captures
CREATE INDEX idx_captures_time ON captures(created_at, capture_id);
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
-- index idx_mcp_credentials_plugin ON mcp_credentials
CREATE INDEX idx_mcp_credentials_plugin ON mcp_credentials(plugin_id);
-- index idx_notifications_state ON notifications
CREATE INDEX idx_notifications_state ON notifications(state, created_at);
-- index idx_one_active_session_context ON session_contexts
CREATE UNIQUE INDEX idx_one_active_session_context ON session_contexts(jarvis_session_id) WHERE status = 'active';
-- index idx_one_adopted_session_context ON session_contexts
CREATE UNIQUE INDEX idx_one_adopted_session_context ON session_contexts(jarvis_session_id) WHERE origin = 'adopted';
-- index idx_one_foreground_binding ON board_conversation_bindings
CREATE UNIQUE INDEX idx_one_foreground_binding ON board_conversation_bindings(jarvis_session_id) WHERE lifecycle = 'foreground';
-- index idx_one_open_capture_per_device ON captures
CREATE UNIQUE INDEX idx_one_open_capture_per_device ON captures(channel, device) WHERE mode = 'continuous' AND state IN ('starting', 'active', 'stopping');
-- index idx_one_open_jarvis_session ON jarvis_sessions
CREATE UNIQUE INDEX idx_one_open_jarvis_session ON jarvis_sessions((1)) WHERE status = 'open';
-- index idx_one_unresolved_live_session ON live_sessions
CREATE UNIQUE INDEX idx_one_unresolved_live_session ON live_sessions((1)) WHERE state <> 'stopped';
-- index idx_schedule_due ON scheduled_items
CREATE INDEX idx_schedule_due ON scheduled_items(status, next_fire_at);
-- index idx_session_activity_context ON session_activity
CREATE INDEX idx_session_activity_context ON session_activity(context_id, seq) WHERE context_id IS NOT NULL;
-- index idx_session_activity_kind ON session_activity
CREATE INDEX idx_session_activity_kind ON session_activity(kind, seq);
-- index idx_session_activity_session ON session_activity
CREATE INDEX idx_session_activity_session ON session_activity(jarvis_session_id, seq) WHERE jarvis_session_id IS NOT NULL;
-- index idx_session_activity_time ON session_activity
CREATE INDEX idx_session_activity_time ON session_activity(occurred_at, seq);
-- index idx_session_contexts_session ON session_contexts
CREATE INDEX idx_session_contexts_session ON session_contexts(jarvis_session_id, status, created_at, context_id);
-- index idx_turns_conversation_time ON turns
CREATE INDEX idx_turns_conversation_time ON turns(conversation_id, created_at, id);
-- index idx_work_boards_status ON work_boards
CREATE INDEX idx_work_boards_status ON work_boards(status, created_at, board_id);
-- table artifact_relations ON artifact_relations
CREATE TABLE artifact_relations ( artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE, relation TEXT NOT NULL, origin_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id), created_at TEXT NOT NULL, PRIMARY KEY (artifact_id, relation, origin_artifact_id), CHECK (artifact_id <> origin_artifact_id));
-- table artifacts ON artifacts
CREATE TABLE artifacts ( artifact_id TEXT PRIMARY KEY, kind TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('pending', 'partial', 'complete', 'failed')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, jarvis_session_id TEXT REFERENCES jarvis_sessions(jarvis_session_id), context_id TEXT REFERENCES session_contexts(context_id), payload_ref TEXT, data TEXT NOT NULL);
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
-- table captures ON captures
CREATE TABLE captures ( capture_id TEXT PRIMARY KEY, channel TEXT NOT NULL, mode TEXT NOT NULL CHECK (mode IN ('continuous', 'one_shot')), device TEXT NOT NULL, state TEXT NOT NULL CHECK (state IN ('starting', 'active', 'stopping', 'complete', 'partial', 'failed')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, jarvis_session_id TEXT REFERENCES jarvis_sessions(jarvis_session_id), context_id TEXT REFERENCES session_contexts(context_id), artifact_id TEXT, error_code TEXT, data TEXT NOT NULL);
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
-- table mcp_credentials ON mcp_credentials
CREATE TABLE mcp_credentials ( credential_ref TEXT PRIMARY KEY, plugin_id TEXT NOT NULL REFERENCES mcp_plugins(plugin_id), scheme TEXT NOT NULL CHECK (scheme IN ('dpapi-user-v1')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, blob BLOB NOT NULL);
-- table mcp_plugins ON mcp_plugins
CREATE TABLE mcp_plugins ( plugin_id TEXT PRIMARY KEY, endpoint TEXT NOT NULL UNIQUE, enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)), connection_status TEXT NOT NULL CHECK (connection_status IN ('disconnected','connecting','connected','error')), auth_status TEXT NOT NULL CHECK (auth_status IN ('unknown','not_required','required','authorizing','authorized','expired','failed')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
-- table notifications ON notifications
CREATE TABLE notifications (id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
-- table scheduled_items ON scheduled_items
CREATE TABLE scheduled_items (id TEXT PRIMARY KEY, status TEXT NOT NULL, next_fire_at TEXT NOT NULL, data TEXT NOT NULL);
-- table schema_version ON schema_version
CREATE TABLE schema_version (version INTEGER NOT NULL);
-- table session_activity ON session_activity
CREATE TABLE session_activity ( seq INTEGER PRIMARY KEY AUTOINCREMENT, event_id TEXT NOT NULL UNIQUE, kind TEXT NOT NULL, occurred_at TEXT NOT NULL, jarvis_session_id TEXT, context_id TEXT, data TEXT NOT NULL);
-- table session_contexts ON session_contexts
CREATE TABLE session_contexts ( context_id TEXT PRIMARY KEY, jarvis_session_id TEXT NOT NULL REFERENCES jarvis_sessions(jarvis_session_id), status TEXT NOT NULL CHECK (status IN ('active', 'dormant')), origin TEXT NOT NULL CHECK (origin IN ('created', 'adopted')), created_at TEXT NOT NULL, activated_at TEXT NOT NULL, last_active_at TEXT NOT NULL, data TEXT NOT NULL);
-- table turns ON turns
CREATE TABLE turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table voice_conversation_snapshots ON voice_conversation_snapshots
CREATE TABLE voice_conversation_snapshots ( conversation_id TEXT PRIMARY KEY, data TEXT NOT NULL, FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table voice_history_projections ON voice_history_projections
CREATE TABLE voice_history_projections ( conversation_id TEXT NOT NULL, output_key TEXT NOT NULL, confirmed_end INTEGER NOT NULL DEFAULT 0, pending_turn TEXT, PRIMARY KEY(conversation_id, output_key), FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
-- table work_boards ON work_boards
CREATE TABLE work_boards ( board_id TEXT PRIMARY KEY, status TEXT NOT NULL CHECK (status IN ('active', 'archived')), created_at TEXT NOT NULL, updated_at TEXT NOT NULL, data TEXT NOT NULL);
