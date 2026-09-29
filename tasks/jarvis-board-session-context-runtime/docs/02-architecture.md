# 02 - Target architecture

JarvisRuntime = SessionManager + BoardManager/Store + BrainRuntime/VoiceRouter + Notifications + MCP/UI APIs.

Board minimum: board_id, title, status, created_at, updated_at, last_opened_at, context_snapshot/ref, project_refs, task_refs, artifact_refs, scene/workspace_state_ref, interaction_mode, runtime_metadata. Prefer references/ownership on canonical stores instead of duplicating payloads.

Session minimum: session_id, started_at, ended_at, status, active_board_id, visited_board_ids, board_conversation_bindings. Closed Sessions are immutable.

BoardConversationBinding minimum: session_id, board_id, brain_conversation_id, created_at, last_active_at, status.

Brain lifecycle: foreground | background_running | suspended. switch_board persists outgoing state, revokes speech authority, keeps background work alive only if needed, loads/resumes target binding/context, applies target Board mode, binds Voice, then commits active Board. Failure rolls back safely.

start_new_session closes old Session, keeps active Board and work, creates a new Session and fresh active-Board conversation binding. Other Boards get bindings lazily. Notifications carry board_id; inactive Boards never speak directly.
