# Legacy window item labels are nowrap and unreadable

Found by: Slice 00 audit (2026-10-03). Status: open.

(feedback §2). Per D-LEGACY the legacy renderer is untouched; `jarvis.window` wraps labels. A small CSS fix to the legacy `.sc-items` row is independent and cheap.
