"""The `audio` execution profile: the real local audio chain, a fixture instead of a microphone.

Binding contract: `docs/testlab.md` ("Audio profile"). Nothing here opens a device
and nothing here calls a provider: this profile exists to run the production
writer, the production duplex capture and the real echo canceller over a
controlled stimulus, which is the acoustic half the `virtual` profile cannot
prove and the half `hardware:*` (Slice 09) does not need a room for.
"""
