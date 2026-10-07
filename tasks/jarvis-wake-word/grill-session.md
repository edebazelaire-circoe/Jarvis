# Reconstructed planning session

This file is reconstructed from the current conversation because a verbatim persisted transcript was not available to the task materializer.

User need:
- Jarvis currently wakes via F9.
- Jarvis should also wake by voice with "Hey Jarvis".
- Jarvis must be able to become active by voice and return to passive mode on request.
- The solution should be testable immediately and should avoid dependence on a commercial-only wake-word service.

Planning outcome:
- Use openWakeWord for v1 because it is local, open source, and has an immediately usable `hey_jarvis` pre-trained model.
- Put wake-word detection in the runtime/body layer, not in the Brain.
- F9 and wake-word detection must call the same canonical activation command.
- Keep openWakeWord behind a replaceable provider interface.
- Use normal active-mode transcription/intent handling for "go to sleep" style commands in v1 rather than adding a second passive detector.
- Record the licensing caveat: openWakeWord code is Apache-2.0, while included pre-trained models are CC BY-NC-SA 4.0 and therefore are not suitable as an unquestioned commercial redistribution dependency.
