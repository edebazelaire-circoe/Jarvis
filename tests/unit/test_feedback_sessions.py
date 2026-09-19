from jarvis.runtime import feedback_sessions
from jarvis.runtime.claude_local import BRAIN_SYSTEM_PROMPT
from jarvis.runtime.feedback_sessions import FEEDBACK_DIR_ENV, LAUNCHED_AT_ENV, feedback_session_dir


def test_session_dir_is_named_by_launch_second_and_exported(tmp_path, monkeypatch):
    monkeypatch.delenv(LAUNCHED_AT_ENV, raising=False)
    monkeypatch.delenv(FEEDBACK_DIR_ENV, raising=False)

    directory = feedback_session_dir(tmp_path, now=1789654261.73)

    assert directory == tmp_path / "retours-utilisateur" / "1789654261"
    assert directory.is_dir()
    assert feedback_sessions.os.environ[FEEDBACK_DIR_ENV] == str(directory)
    assert feedback_sessions.os.environ[LAUNCHED_AT_ENV] == "1789654261"


def test_launch_stamp_is_fixed_once_per_session(tmp_path, monkeypatch):
    monkeypatch.setenv(LAUNCHED_AT_ENV, "1789650000")
    monkeypatch.delenv(FEEDBACK_DIR_ENV, raising=False)

    first = feedback_session_dir(tmp_path, now=1789654261)
    again = feedback_session_dir(tmp_path, now=1789659999)

    assert first == again == tmp_path / "retours-utilisateur" / "1789650000"


def test_brain_is_told_where_feedback_goes():
    assert FEEDBACK_DIR_ENV in BRAIN_SYSTEM_PROMPT
