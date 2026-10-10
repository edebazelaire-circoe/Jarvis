# Issue 04 - The attested commit proves an echo, not reachability (Slice 18)

Found by QA of Slice 18. Nonblocking, documented in `docs/remotion-import.md` §3 and `docs/SECURITY.md` §20.

The importer pins a full commit SHA and refuses an archive whose pax header does not repeat it. That only proves GitHub echoed the SHA that was
asked for. Objects of a fork network can be served under an allowed owner's repository path: a SHA from a hostile fork may resolve under
`github.com/<allowed owner>/<repo>`. Not tested here. The allowlist therefore protects the owner, not the commit.

Possible follow-up: before accepting the archive, ask GitHub whether the commit is reachable from a branch or tag of that exact repository
(compare API), or require a tag/branch name that the user confirms, and record the answer in `upstream.changes`. Needs an API call and a
rate-limit policy; out of scope for the import slice.
