-- schema_version = [(1,)]
-- index idx_scene_history_revision ON scene_history
CREATE INDEX idx_scene_history_revision ON scene_history(revision);
-- table scene_history ON scene_history
CREATE TABLE scene_history ( object_id TEXT NOT NULL, revision INTEGER NOT NULL, archived_at TEXT NOT NULL, data TEXT NOT NULL, PRIMARY KEY (object_id, revision));
-- table scene_meta ON scene_meta
CREATE TABLE scene_meta ( singleton INTEGER PRIMARY KEY CHECK (singleton = 1), scene_id TEXT NOT NULL, revision INTEGER NOT NULL CHECK (revision >= 0), wire_schema_version INTEGER NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
-- table scene_objects ON scene_objects
CREATE TABLE scene_objects ( object_id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, data TEXT NOT NULL);
-- table scene_relations ON scene_relations
CREATE TABLE scene_relations ( relation_id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE, data TEXT NOT NULL);
-- table scene_tombstones ON scene_tombstones
CREATE TABLE scene_tombstones ( object_id TEXT PRIMARY KEY, position INTEGER NOT NULL UNIQUE);
-- table schema_version ON schema_version
CREATE TABLE schema_version (version INTEGER NOT NULL);
