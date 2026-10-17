# Capture busy-ness is keyed by device name, not by physical device

- **Found in:** Slice 04 QA (tier critical), 2026-10-16. Filed in Slice 10.
- **Not a regression.** The rule is in Core since before this task: at the
  planning commit `57f28a74`, `CaptureService` already held one capture per
  `record.device_key` (`jarvis/core/capture_service.py`, `_holders`), and
  `device_key` is `(channel, device)` with `device` the token string
  (`jarvis/domain/capture.py`, `CaptureRecord.device_key`). This task added
  no new path to the same physical device; it only lists the targets
  (`GET /v1/captures/targets`).
- **Owner:** Core capture (`docs/capture.md`), a later task. No Slice of this
  task owns it.

## What happens

Two different tokens that name the same physical device are two free
"devices" for Core:

- screen: the brain records `display1` (the primary display) while the wheel
  records `default` (also the primary display) — two ffmpeg `gdigrab` runs on
  the same rectangle;
- audio: `default` (the Voice setting, resolved to a name) and the explicit
  token of that same input — two streams opened on one microphone.

The wheel itself avoids it in normal use: the targets list never names the
primary display twice (`display1` is hidden behind `default`) and the audio
list puts `default` first and then the *other* inputs. The brain's MCP tools
and a direct HTTP caller can still pass the second name.

## Impact

Duplicate recording of the same source (CPU, disk), and, for audio, a second
open stream on a device the driver may refuse (`device_unavailable` on start)
or share. No data loss, no wrong attribution: each capture stays its own
artifact with its own `device` metadata, and each stops on its own.

## Possible fix (not designed here)

Resolve every token to a physical identity before checking the holder (the
display rectangle / `display_device` for screens, the resolved host-API device
index or name for audio) and refuse `already_active` on that identity, with a
test for `display1` + `default` and for `default` + the explicit token of the
same input. Human product decision on whether two recordings of one screen
are ever wanted.
