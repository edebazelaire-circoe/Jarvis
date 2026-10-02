-- jarvis.sqlite3 au schéma 7, fabriqué par le code v7 (origin/main 467232f) le 2026-10-03,
-- worktree temporaire, générateur : tasks/jarvis-board-memory-workspace-inspector/slices/09-e2e-rollout/evidence/make_v7_fixture.py.
-- Deux Sessions (une close new_session), quatre Boards (default, Atlas actif avec résumé, tâche et réf. legacy,
-- Borée visité, Archive 2025 archivé), trois Contexts, trois Artifacts (dont une provenance derived_from),
-- ledger, deux tours. Données synthétiques. Utilisé par tests/integration/test_board_workspace_e2e.py.

BEGIN TRANSACTION;
CREATE TABLE artifact_relations (
            artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id) ON DELETE CASCADE,
            relation TEXT NOT NULL,
            origin_artifact_id TEXT NOT NULL REFERENCES artifacts(artifact_id),
            created_at TEXT NOT NULL,
            PRIMARY KEY (artifact_id, relation, origin_artifact_id),
            CHECK (artifact_id <> origin_artifact_id));
INSERT INTO "artifact_relations" VALUES('jart_22222222222222222222222222222222','derived_from','jart_11111111111111111111111111111111','2026-10-02T22:59:06.302158+00:00');
CREATE TABLE artifacts (
            artifact_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('pending', 'partial', 'complete', 'failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            jarvis_session_id TEXT REFERENCES jarvis_sessions(jarvis_session_id),
            context_id TEXT REFERENCES session_contexts(context_id),
            payload_ref TEXT,
            data TEXT NOT NULL);
INSERT INTO "artifacts" VALUES('jart_11111111111111111111111111111111','transcript','complete','2026-10-02T22:59:06.295906+00:00','2026-10-02T22:59:06.295906+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_a44e0b17d8de4978bf7ed914c5ea107e',NULL,'{"artifact_id":"jart_11111111111111111111111111111111","context_id":"jctx_a44e0b17d8de4978bf7ed914c5ea107e","created_at":"2026-10-02T22:59:06.295906+00:00","duration_ms":null,"ended_at":null,"enrichment":{},"error_code":null,"height":null,"jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"transcript","metadata":{},"mime_type":null,"payload_ref":null,"size_bytes":null,"source":"v7-fixture","started_at":null,"state":"complete","text":"réunion Borée : décision ORION","updated_at":"2026-10-02T22:59:06.295906+00:00","width":null}');
INSERT INTO "artifacts" VALUES('jart_22222222222222222222222222222222','derived','complete','2026-10-02T22:59:06.302158+00:00','2026-10-02T22:59:06.302158+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_e498f3177b814418bde9ce2d353d32a9',NULL,'{"artifact_id":"jart_22222222222222222222222222222222","context_id":"jctx_e498f3177b814418bde9ce2d353d32a9","created_at":"2026-10-02T22:59:06.302158+00:00","duration_ms":null,"ended_at":null,"enrichment":{},"error_code":null,"height":null,"jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"derived","metadata":{},"mime_type":null,"payload_ref":null,"size_bytes":null,"source":"v7-fixture","started_at":null,"state":"complete","text":"résumé Borée","updated_at":"2026-10-02T22:59:06.302158+00:00","width":null}');
INSERT INTO "artifacts" VALUES('jart_33333333333333333333333333333333','description','complete','2026-10-02T22:59:06.320754+00:00','2026-10-02T22:59:06.320754+00:00','jsess_ef8971b03f6f48faaa247b104c9067a1',NULL,NULL,'{"artifact_id":"jart_33333333333333333333333333333333","context_id":null,"created_at":"2026-10-02T22:59:06.320754+00:00","duration_ms":null,"ended_at":null,"enrichment":{},"error_code":null,"height":null,"jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","kind":"description","metadata":{},"mime_type":null,"payload_ref":null,"size_bytes":null,"source":"v7-fixture","started_at":null,"state":"complete","text":"note Atlas","updated_at":"2026-10-02T22:59:06.320754+00:00","width":null}');
CREATE TABLE back_brain_advisories (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE board_conversation_bindings (
            jarvis_session_id TEXT NOT NULL REFERENCES jarvis_sessions(jarvis_session_id),
            board_id TEXT NOT NULL REFERENCES work_boards(board_id),
            conversation_id TEXT NOT NULL,
            lifecycle TEXT NOT NULL CHECK (lifecycle IN ('foreground', 'background_running', 'suspended')),
            status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
            created_at TEXT NOT NULL,
            data TEXT NOT NULL,
            PRIMARY KEY (jarvis_session_id, board_id));
INSERT INTO "board_conversation_bindings" VALUES('jsess_0216590e645447b7ae7a0103dd69751c','default','d977f0f9-5c85-4e87-8f35-24f30ff9f297','suspended','closed','2026-10-02T22:59:06.223009+00:00','{"agent_cli":"pending","agent_session_id":null,"board_id":"default","conversation_id":"d977f0f9-5c85-4e87-8f35-24f30ff9f297","created_at":"2026-10-02T22:59:06.223009+00:00","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","last_active_at":"2026-10-02T22:59:06.316580+00:00","lifecycle":"suspended","status":"closed"}');
INSERT INTO "board_conversation_bindings" VALUES('jsess_0216590e645447b7ae7a0103dd69751c','board_69a3f249315d46ab8915cd093d6806fe','8708ee74-dc21-486e-94a4-f5ee0490f010','suspended','closed','2026-10-02T22:59:06.291922+00:00','{"agent_cli":"pending","agent_session_id":null,"board_id":"board_69a3f249315d46ab8915cd093d6806fe","conversation_id":"8708ee74-dc21-486e-94a4-f5ee0490f010","created_at":"2026-10-02T22:59:06.291922+00:00","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","last_active_at":"2026-10-02T22:59:06.316580+00:00","lifecycle":"suspended","status":"closed"}');
INSERT INTO "board_conversation_bindings" VALUES('jsess_0216590e645447b7ae7a0103dd69751c','board_22d40338bbda4c75918681e175585e13','410a0734-ad60-4e7b-a691-fd2410ceb528','suspended','closed','2026-10-02T22:59:06.308876+00:00','{"agent_cli":"pending","agent_session_id":null,"board_id":"board_22d40338bbda4c75918681e175585e13","conversation_id":"410a0734-ad60-4e7b-a691-fd2410ceb528","created_at":"2026-10-02T22:59:06.308876+00:00","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","last_active_at":"2026-10-02T22:59:06.316580+00:00","lifecycle":"suspended","status":"closed"}');
INSERT INTO "board_conversation_bindings" VALUES('jsess_ef8971b03f6f48faaa247b104c9067a1','board_22d40338bbda4c75918681e175585e13','86c0cd59-36fd-47ab-b9b7-538e3eb52a97','foreground','open','2026-10-02T22:59:06.316245+00:00','{"agent_cli":"pending","agent_session_id":null,"board_id":"board_22d40338bbda4c75918681e175585e13","conversation_id":"86c0cd59-36fd-47ab-b9b7-538e3eb52a97","created_at":"2026-10-02T22:59:06.316245+00:00","jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","last_active_at":"2026-10-02T22:59:06.316245+00:00","lifecycle":"foreground","status":"open"}');
CREATE TABLE brain_current_sources (
                conversation_id TEXT PRIMARY KEY, epoch INTEGER NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_invalidated_dependencies (
                conversation_id TEXT NOT NULL, work_id TEXT NOT NULL, source_correlation_id TEXT NOT NULL,
                PRIMARY KEY(conversation_id,work_id,source_correlation_id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_outcome_selections (
                conversation_id TEXT NOT NULL, selection_id TEXT NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(conversation_id,selection_id),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_outcomes (
                id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE brain_sources (
                conversation_id TEXT NOT NULL, correlation_id TEXT NOT NULL, epoch INTEGER NOT NULL, data TEXT NOT NULL,
                PRIMARY KEY(conversation_id,correlation_id), UNIQUE(conversation_id,epoch),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE captures (
            capture_id TEXT PRIMARY KEY,
            channel TEXT NOT NULL,
            mode TEXT NOT NULL CHECK (mode IN ('continuous', 'one_shot')),
            device TEXT NOT NULL,
            state TEXT NOT NULL CHECK (state IN ('starting', 'active', 'stopping', 'complete', 'partial', 'failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            jarvis_session_id TEXT REFERENCES jarvis_sessions(jarvis_session_id),
            context_id TEXT REFERENCES session_contexts(context_id),
            artifact_id TEXT,
            error_code TEXT,
            data TEXT NOT NULL);
CREATE TABLE conversation_events (
            sequence INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            conversation_id TEXT NOT NULL,
            session_id TEXT,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL,
            visibility TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            recorded_at TEXT NOT NULL,
            span_id TEXT, turn_id TEXT, correlation_id TEXT, task_id TEXT, work_id TEXT, speech_id TEXT,
            outcome_id TEXT,
            data TEXT NOT NULL);
CREATE TABLE conversations (id TEXT PRIMARY KEY, updated_at TEXT NOT NULL, data TEXT NOT NULL);
INSERT INTO "conversations" VALUES('d977f0f9-5c85-4e87-8f35-24f30ff9f297','2026-10-02T22:59:06.223438+00:00','{"created_at":"2026-10-02T22:59:06.223436+00:00","current_device_id":"windows-desktop","id":"d977f0f9-5c85-4e87-8f35-24f30ff9f297","originating_device_id":"windows-desktop","status":"active","summary":"","transport_session_id":null,"updated_at":"2026-10-02T22:59:06.223438+00:00"}');
INSERT INTO "conversations" VALUES('8708ee74-dc21-486e-94a4-f5ee0490f010','2026-10-02T22:59:06.290454+00:00','{"created_at":"2026-10-02T22:59:06.290452+00:00","current_device_id":"windows-desktop","id":"8708ee74-dc21-486e-94a4-f5ee0490f010","originating_device_id":"windows-desktop","status":"active","summary":"","transport_session_id":null,"updated_at":"2026-10-02T22:59:06.290454+00:00"}');
INSERT INTO "conversations" VALUES('410a0734-ad60-4e7b-a691-fd2410ceb528','2026-10-02T22:59:06.307440+00:00','{"created_at":"2026-10-02T22:59:06.307439+00:00","current_device_id":"windows-desktop","id":"410a0734-ad60-4e7b-a691-fd2410ceb528","originating_device_id":"windows-desktop","status":"active","summary":"","transport_session_id":null,"updated_at":"2026-10-02T22:59:06.307440+00:00"}');
INSERT INTO "conversations" VALUES('86c0cd59-36fd-47ab-b9b7-538e3eb52a97','2026-10-02T22:59:06.314988+00:00','{"created_at":"2026-10-02T22:59:06.314986+00:00","current_device_id":"windows-desktop","id":"86c0cd59-36fd-47ab-b9b7-538e3eb52a97","originating_device_id":"windows-desktop","status":"active","summary":"","transport_session_id":null,"updated_at":"2026-10-02T22:59:06.314988+00:00"}');
CREATE TABLE devices (id TEXT PRIMARY KEY, data TEXT NOT NULL);
INSERT INTO "devices" VALUES('windows-desktop','{"capabilities":[],"device_id":"windows-desktop","display_name":"Windows desktop","enabled":true,"kind":"windows-desktop","last_seen_at":"2026-10-02T22:59:06.278757+00:00"}');
CREATE TABLE jarvis_sessions (
            jarvis_session_id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('open', 'closed')),
            started_at TEXT NOT NULL,
            active_board_id TEXT NOT NULL,
            data TEXT NOT NULL);
INSERT INTO "jarvis_sessions" VALUES('jsess_0216590e645447b7ae7a0103dd69751c','closed','2026-10-02T22:59:06.223009+00:00','board_22d40338bbda4c75918681e175585e13','{"active_board_id":"board_22d40338bbda4c75918681e175585e13","end_reason":"new_session","ended_at":"2026-10-02T22:59:06.316580+00:00","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","started_at":"2026-10-02T22:59:06.223009+00:00","status":"closed","visited_board_ids":["default","board_69a3f249315d46ab8915cd093d6806fe","board_22d40338bbda4c75918681e175585e13"]}');
INSERT INTO "jarvis_sessions" VALUES('jsess_ef8971b03f6f48faaa247b104c9067a1','open','2026-10-02T22:59:06.316245+00:00','board_22d40338bbda4c75918681e175585e13','{"active_board_id":"board_22d40338bbda4c75918681e175585e13","end_reason":null,"ended_at":null,"jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","started_at":"2026-10-02T22:59:06.316245+00:00","status":"open","visited_board_ids":["board_22d40338bbda4c75918681e175585e13"]}');
CREATE TABLE jobs (id TEXT PRIMARY KEY, status TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE live_sessions (
                session_id TEXT PRIMARY KEY, state TEXT NOT NULL,
                revision INTEGER NOT NULL, data TEXT NOT NULL
            );
CREATE TABLE mcp_credentials (
            credential_ref TEXT PRIMARY KEY,
            plugin_id TEXT NOT NULL REFERENCES mcp_plugins(plugin_id),
            scheme TEXT NOT NULL CHECK (scheme IN ('dpapi-user-v1')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            blob BLOB NOT NULL);
CREATE TABLE mcp_plugins (
            plugin_id TEXT PRIMARY KEY,
            endpoint TEXT NOT NULL UNIQUE,
            enabled INTEGER NOT NULL CHECK (enabled IN (0, 1)),
            connection_status TEXT NOT NULL CHECK (connection_status IN ('disconnected','connecting','connected','error')),
            auth_status TEXT NOT NULL CHECK (auth_status IN ('unknown','not_required','required','authorizing','authorized','expired','failed')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            data TEXT NOT NULL);
CREATE TABLE notifications (id TEXT PRIMARY KEY, state TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE scheduled_items (id TEXT PRIMARY KEY, status TEXT NOT NULL, next_fire_at TEXT NOT NULL, data TEXT NOT NULL);
CREATE TABLE schema_version (version INTEGER NOT NULL);
INSERT INTO "schema_version" VALUES(7);
CREATE TABLE session_activity (
            seq INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL UNIQUE,
            kind TEXT NOT NULL,
            occurred_at TEXT NOT NULL,
            jarvis_session_id TEXT,
            context_id TEXT,
            data TEXT NOT NULL);
INSERT INTO "session_activity" VALUES(1,'jact_2bc17482d1084c4a8427c05e6379534c','session.opened','2026-10-02T22:59:06.223009+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_a44e0b17d8de4978bf7ed914c5ea107e','{"artifact_ids":[],"capture_ids":[],"context_id":"jctx_a44e0b17d8de4978bf7ed914c5ea107e","data":{"origin":"core_start"},"event_id":"jact_2bc17482d1084c4a8427c05e6379534c","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"session.opened","occurred_at":"2026-10-02T22:59:06.223009+00:00"}');
INSERT INTO "session_activity" VALUES(2,'jact_cf70cc3788814477970417094bced358','context.created','2026-10-02T22:59:06.223009+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_a44e0b17d8de4978bf7ed914c5ea107e','{"artifact_ids":[],"capture_ids":[],"context_id":"jctx_a44e0b17d8de4978bf7ed914c5ea107e","data":{"context_origin":"created","origin":"core_start"},"event_id":"jact_cf70cc3788814477970417094bced358","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"context.created","occurred_at":"2026-10-02T22:59:06.223009+00:00"}');
INSERT INTO "session_activity" VALUES(3,'jact_a3646b5bf7964f25ae518ff29f012b12','artifact.created','2026-10-02T22:59:06.295906+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_a44e0b17d8de4978bf7ed914c5ea107e','{"artifact_ids":["jart_11111111111111111111111111111111"],"capture_ids":[],"context_id":"jctx_a44e0b17d8de4978bf7ed914c5ea107e","data":{"artifact_kind":"transcript","origins":0,"source":"v7-fixture"},"event_id":"jact_a3646b5bf7964f25ae518ff29f012b12","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"artifact.created","occurred_at":"2026-10-02T22:59:06.295906+00:00"}');
INSERT INTO "session_activity" VALUES(4,'jact_6cbcdada469d4d289c7b3ef5e0acf5d9','artifact.finalized','2026-10-02T22:59:06.295906+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_a44e0b17d8de4978bf7ed914c5ea107e','{"artifact_ids":["jart_11111111111111111111111111111111"],"capture_ids":[],"context_id":"jctx_a44e0b17d8de4978bf7ed914c5ea107e","data":{"artifact_kind":"transcript","error_code":null,"recovered":false,"size_bytes":null,"state":"complete"},"event_id":"jact_6cbcdada469d4d289c7b3ef5e0acf5d9","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"artifact.finalized","occurred_at":"2026-10-02T22:59:06.295906+00:00"}');
INSERT INTO "session_activity" VALUES(5,'jact_7838ff29ff3c4662802116decfb0e257','context.dormant','2026-10-02T22:59:06.298497+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_a44e0b17d8de4978bf7ed914c5ea107e','{"artifact_ids":[],"capture_ids":[],"context_id":"jctx_a44e0b17d8de4978bf7ed914c5ea107e","data":{"origin":"protocol"},"event_id":"jact_7838ff29ff3c4662802116decfb0e257","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"context.dormant","occurred_at":"2026-10-02T22:59:06.298497+00:00"}');
INSERT INTO "session_activity" VALUES(6,'jact_3d459ddc8c864d0fbe2f0be1fdaf2216','context.created','2026-10-02T22:59:06.298497+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_e498f3177b814418bde9ce2d353d32a9','{"artifact_ids":[],"capture_ids":[],"context_id":"jctx_e498f3177b814418bde9ce2d353d32a9","data":{"context_origin":"created","origin":"protocol"},"event_id":"jact_3d459ddc8c864d0fbe2f0be1fdaf2216","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"context.created","occurred_at":"2026-10-02T22:59:06.298497+00:00"}');
INSERT INTO "session_activity" VALUES(7,'jact_380821cf06224190a1d738da8983a17b','artifact.created','2026-10-02T22:59:06.302158+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_e498f3177b814418bde9ce2d353d32a9','{"artifact_ids":["jart_22222222222222222222222222222222","jart_11111111111111111111111111111111"],"capture_ids":[],"context_id":"jctx_e498f3177b814418bde9ce2d353d32a9","data":{"artifact_kind":"derived","origins":1,"source":"v7-fixture"},"event_id":"jact_380821cf06224190a1d738da8983a17b","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"artifact.created","occurred_at":"2026-10-02T22:59:06.302158+00:00"}');
INSERT INTO "session_activity" VALUES(8,'jact_4aad4e7150b04e6784c3925348cbb7b2','artifact.finalized','2026-10-02T22:59:06.302158+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_e498f3177b814418bde9ce2d353d32a9','{"artifact_ids":["jart_22222222222222222222222222222222"],"capture_ids":[],"context_id":"jctx_e498f3177b814418bde9ce2d353d32a9","data":{"artifact_kind":"derived","error_code":null,"recovered":false,"size_bytes":null,"state":"complete"},"event_id":"jact_4aad4e7150b04e6784c3925348cbb7b2","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"artifact.finalized","occurred_at":"2026-10-02T22:59:06.302158+00:00"}');
INSERT INTO "session_activity" VALUES(9,'jact_6a56c9eec084446090819cbcb5f9d754','context.dormant','2026-10-02T22:59:06.316580+00:00','jsess_0216590e645447b7ae7a0103dd69751c','jctx_e498f3177b814418bde9ce2d353d32a9','{"artifact_ids":[],"capture_ids":[],"context_id":"jctx_e498f3177b814418bde9ce2d353d32a9","data":{"origin":"protocol"},"event_id":"jact_6a56c9eec084446090819cbcb5f9d754","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"context.dormant","occurred_at":"2026-10-02T22:59:06.316580+00:00"}');
INSERT INTO "session_activity" VALUES(10,'jact_a6e6ae39f65e4279aab2ce2f7133e092','session.closed','2026-10-02T22:59:06.316580+00:00','jsess_0216590e645447b7ae7a0103dd69751c',NULL,'{"artifact_ids":[],"capture_ids":[],"context_id":null,"data":{"origin":"protocol"},"event_id":"jact_a6e6ae39f65e4279aab2ce2f7133e092","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","kind":"session.closed","occurred_at":"2026-10-02T22:59:06.316580+00:00"}');
INSERT INTO "session_activity" VALUES(11,'jact_27c8e7a201c04cf8958b072b3a1fbf54','session.opened','2026-10-02T22:59:06.316580+00:00','jsess_ef8971b03f6f48faaa247b104c9067a1','jctx_da7c9530cda94c9498768c1183443ae3','{"artifact_ids":[],"capture_ids":[],"context_id":"jctx_da7c9530cda94c9498768c1183443ae3","data":{"origin":"protocol"},"event_id":"jact_27c8e7a201c04cf8958b072b3a1fbf54","jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","kind":"session.opened","occurred_at":"2026-10-02T22:59:06.316580+00:00"}');
INSERT INTO "session_activity" VALUES(12,'jact_00a16c3f853c454086fd72d52aa6c281','context.created','2026-10-02T22:59:06.316580+00:00','jsess_ef8971b03f6f48faaa247b104c9067a1','jctx_da7c9530cda94c9498768c1183443ae3','{"artifact_ids":[],"capture_ids":[],"context_id":"jctx_da7c9530cda94c9498768c1183443ae3","data":{"context_origin":"created","origin":"protocol"},"event_id":"jact_00a16c3f853c454086fd72d52aa6c281","jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","kind":"context.created","occurred_at":"2026-10-02T22:59:06.316580+00:00"}');
INSERT INTO "session_activity" VALUES(13,'jact_af20d2a222c54f2db9be7f8476283bf7','artifact.created','2026-10-02T22:59:06.320754+00:00','jsess_ef8971b03f6f48faaa247b104c9067a1',NULL,'{"artifact_ids":["jart_33333333333333333333333333333333"],"capture_ids":[],"context_id":null,"data":{"artifact_kind":"description","origins":0,"source":"v7-fixture"},"event_id":"jact_af20d2a222c54f2db9be7f8476283bf7","jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","kind":"artifact.created","occurred_at":"2026-10-02T22:59:06.320754+00:00"}');
INSERT INTO "session_activity" VALUES(14,'jact_8568e12ffd2f4e9e9ab5f7fa1ed5bed8','artifact.finalized','2026-10-02T22:59:06.320754+00:00','jsess_ef8971b03f6f48faaa247b104c9067a1',NULL,'{"artifact_ids":["jart_33333333333333333333333333333333"],"capture_ids":[],"context_id":null,"data":{"artifact_kind":"description","error_code":null,"recovered":false,"size_bytes":null,"state":"complete"},"event_id":"jact_8568e12ffd2f4e9e9ab5f7fa1ed5bed8","jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","kind":"artifact.finalized","occurred_at":"2026-10-02T22:59:06.320754+00:00"}');
CREATE TABLE session_contexts (
            context_id TEXT PRIMARY KEY,
            jarvis_session_id TEXT NOT NULL REFERENCES jarvis_sessions(jarvis_session_id),
            status TEXT NOT NULL CHECK (status IN ('active', 'dormant')),
            origin TEXT NOT NULL CHECK (origin IN ('created', 'adopted')),
            created_at TEXT NOT NULL,
            activated_at TEXT NOT NULL,
            last_active_at TEXT NOT NULL,
            data TEXT NOT NULL);
INSERT INTO "session_contexts" VALUES('jctx_a44e0b17d8de4978bf7ed914c5ea107e','jsess_0216590e645447b7ae7a0103dd69751c','dormant','created','2026-10-02T22:59:06.223009+00:00','2026-10-02T22:59:06.223009+00:00','2026-10-02T22:59:06.298497+00:00','{"activated_at":"2026-10-02T22:59:06.223009+00:00","context_id":"jctx_a44e0b17d8de4978bf7ed914c5ea107e","created_at":"2026-10-02T22:59:06.223009+00:00","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","last_active_at":"2026-10-02T22:59:06.298497+00:00","origin":"created","runtime_metadata":{},"source_context_ids":[],"status":"dormant","title":null}');
INSERT INTO "session_contexts" VALUES('jctx_e498f3177b814418bde9ce2d353d32a9','jsess_0216590e645447b7ae7a0103dd69751c','dormant','created','2026-10-02T22:59:06.298497+00:00','2026-10-02T22:59:06.298497+00:00','2026-10-02T22:59:06.316580+00:00','{"activated_at":"2026-10-02T22:59:06.298497+00:00","context_id":"jctx_e498f3177b814418bde9ce2d353d32a9","created_at":"2026-10-02T22:59:06.298497+00:00","jarvis_session_id":"jsess_0216590e645447b7ae7a0103dd69751c","last_active_at":"2026-10-02T22:59:06.316580+00:00","origin":"created","runtime_metadata":{},"source_context_ids":[],"status":"dormant","title":"Revue Borée"}');
INSERT INTO "session_contexts" VALUES('jctx_da7c9530cda94c9498768c1183443ae3','jsess_ef8971b03f6f48faaa247b104c9067a1','active','created','2026-10-02T22:59:06.316580+00:00','2026-10-02T22:59:06.316580+00:00','2026-10-02T22:59:06.316580+00:00','{"activated_at":"2026-10-02T22:59:06.316580+00:00","context_id":"jctx_da7c9530cda94c9498768c1183443ae3","created_at":"2026-10-02T22:59:06.316580+00:00","jarvis_session_id":"jsess_ef8971b03f6f48faaa247b104c9067a1","last_active_at":"2026-10-02T22:59:06.316580+00:00","origin":"created","runtime_metadata":{},"source_context_ids":[],"status":"active","title":null}');
CREATE TABLE turns (id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
INSERT INTO "turns" VALUES('099617c5-5e1b-450c-8ebe-2ed73ee85a4c','86c0cd59-36fd-47ab-b9b7-538e3eb52a97','2026-10-02T22:59:06.322862+00:00','{"content":"où en est Atlas ?","conversation_id":"86c0cd59-36fd-47ab-b9b7-538e3eb52a97","correlation_id":"6acec8ef-14c5-48b8-a31f-c979e318981d","created_at":"2026-10-02T22:59:06.322862+00:00","id":"099617c5-5e1b-450c-8ebe-2ed73ee85a4c","kind":"user","metadata":{},"reference_id":null}');
INSERT INTO "turns" VALUES('3cb9c523-31c8-46fd-b8f5-cd38fc7e4b6a','86c0cd59-36fd-47ab-b9b7-538e3eb52a97','2026-10-02T22:59:06.324145+00:00','{"content":"Lot 2 en cours.","conversation_id":"86c0cd59-36fd-47ab-b9b7-538e3eb52a97","correlation_id":"37be4c85-e69a-44b0-abe9-f15b0a818c75","created_at":"2026-10-02T22:59:06.324145+00:00","id":"3cb9c523-31c8-46fd-b8f5-cd38fc7e4b6a","kind":"assistant","metadata":{},"reference_id":null}');
CREATE TABLE voice_conversation_snapshots (
                conversation_id TEXT PRIMARY KEY, data TEXT NOT NULL,
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE voice_history_projections (
                conversation_id TEXT NOT NULL, output_key TEXT NOT NULL,
                confirmed_end INTEGER NOT NULL DEFAULT 0, pending_turn TEXT,
                PRIMARY KEY(conversation_id, output_key),
                FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE);
CREATE TABLE work_boards (
            board_id TEXT PRIMARY KEY,
            status TEXT NOT NULL CHECK (status IN ('active', 'archived')),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            data TEXT NOT NULL);
INSERT INTO "work_boards" VALUES('default','active','2026-10-02T22:59:06.219733+00:00','2026-10-02T22:59:06.219733+00:00','{"artifact_refs":[],"board_id":"default","context_summary":"","created_at":"2026-10-02T22:59:06.219733+00:00","interaction_mode":"assistant","interaction_mode_origin":"unset","last_opened_at":null,"project_refs":[],"runtime_metadata":{},"scene_ref":null,"status":"active","task_refs":[],"title":"Board principal","updated_at":"2026-10-02T22:59:06.219733+00:00"}');
INSERT INTO "work_boards" VALUES('board_22d40338bbda4c75918681e175585e13','active','2026-10-02T22:59:06.281629+00:00','2026-10-02T22:59:06.310839+00:00','{"artifact_refs":["drive:atlas-brief"],"board_id":"board_22d40338bbda4c75918681e175585e13","context_summary":"Refonte du site, lot 2","created_at":"2026-10-02T22:59:06.281629+00:00","interaction_mode":"assistant","interaction_mode_origin":"unset","last_opened_at":"2026-10-02T22:59:06.310839+00:00","project_refs":[],"runtime_metadata":{},"scene_ref":null,"status":"active","task_refs":["task-atlas-1"],"title":"Projet Atlas","updated_at":"2026-10-02T22:59:06.310839+00:00"}');
INSERT INTO "work_boards" VALUES('board_69a3f249315d46ab8915cd093d6806fe','active','2026-10-02T22:59:06.283427+00:00','2026-10-02T22:59:06.293713+00:00','{"artifact_refs":[],"board_id":"board_69a3f249315d46ab8915cd093d6806fe","context_summary":"","created_at":"2026-10-02T22:59:06.283427+00:00","interaction_mode":"assistant","interaction_mode_origin":"unset","last_opened_at":"2026-10-02T22:59:06.293713+00:00","project_refs":[],"runtime_metadata":{},"scene_ref":null,"status":"active","task_refs":[],"title":"Ancien projet Borée","updated_at":"2026-10-02T22:59:06.293713+00:00"}');
INSERT INTO "work_boards" VALUES('board_d8d701e6131b41eabcde695eddfc9de1','archived','2026-10-02T22:59:06.285052+00:00','2026-10-02T22:59:06.313079+00:00','{"artifact_refs":[],"board_id":"board_d8d701e6131b41eabcde695eddfc9de1","context_summary":"","created_at":"2026-10-02T22:59:06.285052+00:00","interaction_mode":"assistant","interaction_mode_origin":"unset","last_opened_at":null,"project_refs":[],"runtime_metadata":{},"scene_ref":null,"status":"archived","task_refs":[],"title":"Archive 2025","updated_at":"2026-10-02T22:59:06.313079+00:00"}');
CREATE INDEX idx_turns_conversation_time ON turns(conversation_id, created_at, id);
CREATE INDEX idx_brain_outcomes_conversation ON brain_outcomes(conversation_id,created_at,id);
CREATE INDEX idx_jobs_status ON jobs(status, created_at);
CREATE INDEX idx_schedule_due ON scheduled_items(status, next_fire_at);
CREATE INDEX idx_notifications_state ON notifications(state, created_at);
CREATE UNIQUE INDEX idx_one_unresolved_live_session
                ON live_sessions((1)) WHERE state <> 'stopped';
CREATE INDEX idx_conversation_events_conversation ON conversation_events(conversation_id, sequence);
CREATE INDEX idx_conversation_events_occurred ON conversation_events(occurred_at, sequence);
CREATE INDEX idx_conversation_events_session_id ON conversation_events(session_id, sequence) WHERE session_id IS NOT NULL;
CREATE INDEX idx_conversation_events_turn_id ON conversation_events(turn_id, sequence) WHERE turn_id IS NOT NULL;
CREATE INDEX idx_conversation_events_correlation_id ON conversation_events(correlation_id, sequence) WHERE correlation_id IS NOT NULL;
CREATE INDEX idx_conversation_events_task_id ON conversation_events(task_id, sequence) WHERE task_id IS NOT NULL;
CREATE INDEX idx_conversation_events_work_id ON conversation_events(work_id, sequence) WHERE work_id IS NOT NULL;
CREATE INDEX idx_conversation_events_speech_id ON conversation_events(speech_id, sequence) WHERE speech_id IS NOT NULL;
CREATE INDEX idx_conversation_events_outcome_id ON conversation_events(outcome_id, sequence) WHERE outcome_id IS NOT NULL;
CREATE INDEX idx_conversation_events_span_id ON conversation_events(span_id, sequence) WHERE span_id IS NOT NULL;
CREATE INDEX idx_work_boards_status ON work_boards(status, created_at, board_id);
CREATE UNIQUE INDEX idx_one_open_jarvis_session ON jarvis_sessions((1)) WHERE status = 'open';
CREATE INDEX idx_jarvis_sessions_started ON jarvis_sessions(started_at, jarvis_session_id);
CREATE UNIQUE INDEX idx_one_foreground_binding ON board_conversation_bindings(jarvis_session_id) WHERE lifecycle = 'foreground';
CREATE INDEX idx_bindings_conversation ON board_conversation_bindings(conversation_id);
CREATE INDEX idx_mcp_credentials_plugin ON mcp_credentials(plugin_id);
CREATE UNIQUE INDEX idx_one_active_session_context ON session_contexts(jarvis_session_id) WHERE status = 'active';
CREATE UNIQUE INDEX idx_one_adopted_session_context ON session_contexts(jarvis_session_id) WHERE origin = 'adopted';
CREATE INDEX idx_session_contexts_session ON session_contexts(jarvis_session_id, status, created_at, context_id);
CREATE INDEX idx_artifacts_time ON artifacts(created_at, artifact_id);
CREATE INDEX idx_artifacts_kind ON artifacts(kind, created_at, artifact_id);
CREATE INDEX idx_artifacts_state ON artifacts(state, created_at, artifact_id);
CREATE INDEX idx_artifacts_session ON artifacts(jarvis_session_id, created_at, artifact_id) WHERE jarvis_session_id IS NOT NULL;
CREATE INDEX idx_artifacts_context ON artifacts(context_id, created_at, artifact_id) WHERE context_id IS NOT NULL;
CREATE INDEX idx_artifact_relations_origin ON artifact_relations(origin_artifact_id, relation, artifact_id);
CREATE INDEX idx_session_activity_session ON session_activity(jarvis_session_id, seq) WHERE jarvis_session_id IS NOT NULL;
CREATE INDEX idx_session_activity_context ON session_activity(context_id, seq) WHERE context_id IS NOT NULL;
CREATE INDEX idx_session_activity_kind ON session_activity(kind, seq);
CREATE INDEX idx_session_activity_time ON session_activity(occurred_at, seq);
CREATE UNIQUE INDEX idx_one_open_capture_per_device ON captures(channel, device) WHERE mode = 'continuous' AND state IN ('starting', 'active', 'stopping');
CREATE INDEX idx_captures_state ON captures(state, created_at, capture_id);
CREATE INDEX idx_captures_time ON captures(created_at, capture_id);
CREATE INDEX idx_captures_session ON captures(jarvis_session_id, created_at, capture_id) WHERE jarvis_session_id IS NOT NULL;
CREATE INDEX idx_captures_artifact ON captures(artifact_id) WHERE artifact_id IS NOT NULL;
DELETE FROM "sqlite_sequence";
INSERT INTO "sqlite_sequence" VALUES('session_activity',14);
COMMIT;
