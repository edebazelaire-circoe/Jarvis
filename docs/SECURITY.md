# Jarvis V1 security model

## Security objective

V1 is a personal local prototype, not a general autonomous computer-control agent. Its safest property is a deliberately small authority surface: the model may request only three known tools and persistent writes are mediated by a user confirmation broker.

## Trust boundaries

### Trusted application code

`jarvis/core`, `jarvis/domain`, `jarvis/security`, and the local configuration/policy.

### Provider boundary

Audio/transcript/prompt/tool data sent to the configured OpenAI API crosses the local machine boundary. The browser never receives the OpenAI key.

### Local UI boundary

Barehands and ai-visualizer are separate third-party processes pinned to exact upstream revisions. They are not imported into the Jarvis core.

### User memory boundary

Markdown memory may contain private content. It is canonical local data and must not be mutated except through the broker-backed `memory_append` tool in V1.

## Controls implemented

### 1. Deny-by-default tool surface

The model is not given a shell or arbitrary I/O primitive. Unknown tool calls become errors and never reach an executor. Action risk comes from server-owned policy, not model arguments.

### 2. Confirmation for persistent writes

`memory_append` pauses at `awaiting_confirmation`. No write occurs before confirmation. A confirmation is bound to the currently pending action id and timeout. Only exact `oui`/`yes` executes; exact `non`/`no` denies. Ambiguous text stays pending.

### 3. No alternate mutation path

V1 executors are constructed centrally and tool mutations flow through `ActionBroker`. The release verifier scans the Jarvis package for general shell execution primitives.

### 4. Loopback-only local services

Board and visualizer URLs are rejected unless they use HTTP and resolve by configured hostname to `127.0.0.1`, `localhost` or `::1`. Upstream servers are run on loopback.

Note: hostname validation is a configuration guard, not a DNS pinning mechanism. Keep V1 on trusted local workstations and do not proxy these ports to external interfaces.

### 5. Barehands mutation authentication

At each full launch, Jarvis generates a high-entropy random token. It is passed in process environment to Jarvis and Barehands; commands send it only in `X-Jarvis-Token`. It is not embedded in a URL, page, config file or visualizer process environment.

Patched Barehands rejects `/cmd` when the configured token is absent, mismatched, or an explicitly supplied Origin is non-loopback.

### 6. No runtime CDN/model dependency for Barehands

Bootstrap downloads immutable/pinned upstream snapshots and exact browser packages/model once, verifies integrity, then replaces runtime remote references with local assets.

The patched page receives CSP including `connect-src 'self'`, preventing the gesture page from making arbitrary external network connections. Upstream uses inline code/styles, so CSP retains `'unsafe-inline'`; this is a documented residual risk rather than pretending a stricter CSP is compatible.

### 7. Post-install tamper detection

`INSTALL-STATE.json` records hashes produced after verified installation. `bootstrap_third_party.py --verify` checks:

- lock hash;
- patched Barehands server and stage hashes;
- hand model hash;
- deterministic installed trees for Three.js and MediaPipe;
- deterministic ai-visualizer runtime tree, excluding only its generated local config;
- absence of reintroduced remote runtime asset URLs.

The full launcher performs this verification before starting UI components.

### 8. Archive extraction safety

Bootstrap rejects absolute and `..` archive paths and extracts only expected archive layouts/files. Package archives are integrity checked before extraction.

### 9. Memory path safety

Memory adapter resolves paths within a fixed root, repeatedly decodes URL-encoded input before checks, and rejects symlink escapes. Search index is derived and disposable.

### 10. Privacy-safe diagnostics

Default `log_content = false`. Structured JSONL logs retain event type, timing and error class while redacting transcript/prompt/body-like fields. API keys and authorization values are not logged by adapters.

Changing `log_content` to true is an explicit privacy tradeoff and should be temporary.

### 11. Provider transport and process least privilege

Remote OpenAI-compatible endpoints must use HTTPS. Plain HTTP is accepted only on loopback for controlled local proxies/tests. Optional UI processes are started from sanitized environments: Barehands receives its board token but no OpenAI key; ai-visualizer and bootstrap verification receive neither secret.

### 12. Provider failures fail soft

STT, agent and TTS failures are typed. Provider errors transition through visible `error`, attempt a short spoken user-safe error, and return to idle. Technical class/context stay in diagnostics without reading raw provider messages aloud.

## Residual risks / non-goals

- OpenAI is an online provider in this V1; requests leave the machine according to provider/API policy.
- Barehands and ai-visualizer are third-party AGPL software; operational/distribution license obligations require legal review for commercial packaging.
- The patched Barehands page still contains upstream inline JavaScript/styles and therefore CSP allows inline execution.
- A fully compromised local user account can read process memory/environment, modify Python code, or replace the interpreter; V1 does not attempt to defend against a hostile OS account.
- There is no cryptographic code signing of this Jarvis ZIP.
- Confirmation is conversational, not OS-level privileged authorization.
- Board placement is an ephemeral UI write and intentionally does not require confirmation.
- V1 has no destructive memory delete tool, no messaging/email tool, no browser navigation tool and no general filesystem writer.

## Release rule

Do not label the V1 fully released until the manual workstation gates in `ACCEPTANCE_STATUS.md` pass, especially authenticated/unauthenticated Barehands checks, browser offline load, physical gestures, real microphone/speaker loop, and real-provider latency measurement.
