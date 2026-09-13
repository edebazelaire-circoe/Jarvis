# Realtime audio-part manifest — Task07

Verified 2026-09-12 against current official documentation, fetching the Markdown reference because its HTML exceeded the web tool limit. Documentation only; no provider session or code change.

## Exact relevant wire facts

The three part-final events share required `event_id`, `response_id`, `item_id` strings and numeric `output_index`, `content_index`. These indices address response output and item content arrays respectively.

| Event | Additional payload |
|---|---|
| `response.content_part.done` | Required `part` object; optional `type: audio|text`, `audio`, `text`, `transcript` strings. |
| `response.output_audio.done` | None: no byte count, duration or chunk count. |
| `response.output_audio_transcript.done` | Required final `transcript` string. |

All three also occur for interrupted, incomplete or cancelled generation. `response.output_item.done` closes an item, not the whole response. `response.content_part.added` announces a part, without a total count.

`response.done` always terminates generation; inspect `response.status`: `completed`, `cancelled`, `failed`, `incomplete`. The shared resource schema also permits `in_progress`; that is not successful terminal evidence. Its output array includes every generated item, omitting raw audio. Assistant message `content` is an array with `type: output_audio|output_text`; audio includes its transcript. Shared resource fields `id`, `output`, `status` and item `id` are optional in the schema. No maximum part count is specified here. [Official server reference](https://developers.openai.com/api/reference/resources/realtime/server-events), [fetched Markdown](https://developers.openai.com/api/reference/resources/realtime/server-events.md).

## Implementation interpretation and limits

The response manifest is the available response-wide inventory **after generation terminates**. During streaming, a set of observed or closed parts cannot establish that another item/part will never arrive. The conversation guide separates response completion from streamed audio and describes the final text result. It also explicitly warns that transcript/audio alignment is not precise. [Realtime conversation guide](https://developers.openai.com/api/docs/guides/realtime-conversations).

Recommended reconciliation, an application rule rather than an additional provider guarantee:

1. Key each part by frontend incarnation, response ID, item ID and content index; cross-check output index against the final array position. Never collapse all parts into a single “last content_index”. Reject conflicting identity/index mappings.
2. Enumerate actual assistant content array entries from the terminal manifest; select `output_audio` as expected generated audio parts. Normalize `audio` in content-part events explicitly to the manifest's `output_audio` vocabulary. Function-call items are not missing speech. Do not invent absent array entries or require every content index to be audio.
3. Compare this inventory with observed part state: decoded audio duration, audio-close marker, final generated transcript and local audio enqueuing/write outcome. A manifest part with no observed audio is missing delivery evidence, not an empty successfully played part. Conversely, observed audio absent from the manifest is an inconsistency requiring investigation.
4. A valid final manifest can supply final **generated text** even if a transcript-final callback was not retained. It cannot supply missing PCM or prove its delivery. Part-close markers aid coverage checks but cannot replace the response status or expand its manifest.
5. Missing/malformed manifest, unknown type/identity, resource limit overflow or contradictory terminal evidence must remain explicit unknown/incomplete coverage. Do not coerce missing `output` to `[]`. A genuine empty output list or function-only response produces no successful zero-duration speech.

This verifies inventory consistency without guessing unobserved parts. It is **not** byte-for-byte transport integrity: audio events provide no expected total bytes/chunks or per-chunk sequence counter. Even a closed observed part can have lost a delta inside an application queue. Preserve ordered lossless intake, decode errors, queue overflow and enqueue/write outcomes as separate evidence; fail closed on known loss. Do not treat arbitrary event IDs as consecutive sequence numbers. The reference does not promise an independent recovery checksum, absent-event reconstruction or an exact relative arrival order between audio and transcript callbacks.

Only after successful generation, consistent required-part coverage and completion of the actual output-device drain fence for the same non-invalidated playback epoch may Task07 consider complete delivery. A cancelled/incomplete response may have drained its generated prefix; that remains a partial/interrupted response, with heard words unknown where alignment is unavailable. `content_part.done`, manifest enumeration and device drain each answer a different question.

Focused tests: multiple content indices; multiple output items including a tool; added part with no audio; final manifest containing a never-observed part; observed part missing from manifest; completed parts followed by cancelled response; transcript before audio; missing manifest versus genuine empty manifest; conflicting indices/types; duplicate terminal events; known dropped delta; full manifest while device still buffers; epoch invalidated during drain. Use synthetic multipart inputs as robustness cases, not as claimed captured provider traces.
