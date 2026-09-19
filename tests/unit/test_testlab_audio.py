"""The audio fixture root, the PCM helpers, and the `live` cost/usage accounting.

Pure and fast: no voice stack, no device, no provider. The runners are exercised in
`tests/integration/test_testlab_audio_runners.py` and
`tests/integration/test_testlab_live_runners.py`.
"""

from __future__ import annotations

import hashlib
import json
import os

import pytest

from jarvis.runtime.pricing import PRICING_SCHEMA_VERSION
from jarvis.testlab.audio.chain import INPUT_BLOCK_BYTES, INPUT_BLOCK_MS, split_blocks
from jarvis.testlab.audio.fixtures import (
    AUDIO_FIXTURE_ROOT,
    BYTES_PER_SAMPLE,
    MAX_FIXTURE_BYTES,
    SHIPPED_FIXTURES,
    VOICE_SAMPLE_RATE,
    AudioFixtureError,
    AudioFixtureRoot,
    apply_gain_db,
    build_reference_clip,
    build_silence,
    frame_peak_dbfs,
    read_wav_pcm16,
    render_shipped_fixture,
    resample_pcm16,
    wav_bytes,
    write_wav_pcm16,
)
from jarvis.testlab.live.cost import (
    PROVIDER_FINAL_SOURCE,
    CostBudget,
    CostBudgetExceeded,
    CostModel,
    UsageTotals,
)
from jarvis.testlab.live.session import (
    API_KEY_ENV,
    LIVE_OPT_IN_ENV,
    LiveGateError,
    check_live_gates,
    live_opt_in,
    resolve_identity,
)
from jarvis.testlab.primitives import ARG_SPECS, check_arg_value
from jarvis.testlab.runners import MeasurementUnavailable


# ------------------------------------------------------------ the fixture root

def test_the_shipped_fixtures_are_reproducible_byte_for_byte(tmp_path):
    """No audio in the repository that nobody can regenerate from its declaration."""
    for name in SHIPPED_FIXTURES:
        shipped = (AUDIO_FIXTURE_ROOT / name).read_bytes()
        rebuilt_path = tmp_path / name
        write_wav_pcm16(rebuilt_path, render_shipped_fixture(name), VOICE_SAMPLE_RATE)
        assert rebuilt_path.read_bytes() == shipped, name
        assert len(shipped) < MAX_FIXTURE_BYTES


def test_the_shipped_fixtures_are_mono_pcm16_at_the_voice_rate():
    for name in SHIPPED_FIXTURES:
        pcm, rate = read_wav_pcm16(AUDIO_FIXTURE_ROOT / name)
        assert rate == VOICE_SAMPLE_RATE
        assert len(pcm) % BYTES_PER_SAMPLE == 0


def test_the_root_lists_exactly_the_shipped_fixtures():
    assert AudioFixtureRoot().refs() == tuple(sorted(SHIPPED_FIXTURES))


@pytest.mark.parametrize("ref", ["../secret.wav", "/abs/clip.wav", "C:/clip.wav", "a\\b.wav", ".hidden/clip.wav",
                                 "clips/../../escape.wav", "", "nested/" * 9 + "clip.wav"])
def test_a_traversal_or_unsafe_audio_ref_is_refused(ref):
    with pytest.raises(AudioFixtureError) as caught:
        AudioFixtureRoot().resolve(ref)
    assert caught.value.code == "testlab_audio_fixture_unsafe"


def test_a_ref_that_is_not_a_wav_is_refused():
    with pytest.raises(AudioFixtureError) as caught:
        AudioFixtureRoot().resolve("reference-tone-1s.mp3")
    assert caught.value.code == "testlab_audio_fixture_unsafe"


def test_a_ref_naming_nothing_is_unknown_not_unsafe():
    with pytest.raises(AudioFixtureError) as caught:
        AudioFixtureRoot().resolve("no-such-clip.wav")
    assert caught.value.code == "testlab_audio_fixture_unknown"
    assert "no-such-clip.wav" in caught.value.detail


def test_the_same_path_rule_guards_the_primitive_and_the_root():
    """`audio_ref` is checked twice, by the Slice 02 rule and again against the root."""
    spec = ARG_SPECS["audio_ref"]
    check_arg_value(spec, "reference-tone-1s.wav", "steps[0].args.audio_ref")
    with pytest.raises(Exception):
        check_arg_value(spec, "../secret.wav", "steps[0].args.audio_ref")


@pytest.mark.skipif(os.name != "nt", reason="junctions are a Windows concept")
def test_a_fixture_reached_through_a_junction_is_refused(tmp_path):
    """A junction is not a symlink, so `is_symlink` alone would follow it out of the root."""
    import _winapi

    root = tmp_path / "fixtures"
    outside = tmp_path / "outside"
    (root).mkdir()
    outside.mkdir()
    write_wav_pcm16(outside / "clip.wav", build_silence(duration_ms=20), VOICE_SAMPLE_RATE)
    _winapi.CreateJunction(str(outside), str(root / "linked"))
    with pytest.raises(AudioFixtureError) as caught:
        AudioFixtureRoot(root).resolve("linked/clip.wav")
    assert caught.value.code == "testlab_audio_fixture_unsafe"
    assert "link" in caught.value.detail


def test_a_missing_root_is_reported_and_not_crashed(tmp_path):
    root = AudioFixtureRoot(tmp_path / "absent")
    assert root.refs() == ()
    with pytest.raises(AudioFixtureError) as caught:
        root.resolve("clip.wav")
    assert caught.value.code == "testlab_audio_fixture_unknown"


def test_a_stereo_or_8_bit_fixture_is_refused_never_converted(tmp_path):
    import wave

    path = tmp_path / "stereo.wav"
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(2)
        handle.setsampwidth(2)
        handle.setframerate(VOICE_SAMPLE_RATE)
        handle.writeframes(bytes(400))
    with pytest.raises(AudioFixtureError) as caught:
        read_wav_pcm16(path)
    assert caught.value.code == "testlab_audio_fixture_invalid"
    assert "mono 16-bit" in caught.value.detail


def test_a_fixture_that_is_not_a_wav_at_all_is_refused(tmp_path):
    path = tmp_path / "broken.wav"
    path.write_bytes(b"not a riff header at all")
    with pytest.raises(AudioFixtureError) as caught:
        read_wav_pcm16(path)
    assert caught.value.code == "testlab_audio_fixture_invalid"


def test_loading_resamples_to_the_voice_rate_and_says_it_did(tmp_path):
    root = tmp_path / "fixtures"
    write_wav_pcm16(root / "at22k.wav", build_reference_clip(sample_rate=22_050, duration_ms=500), 22_050)
    clip = AudioFixtureRoot(root).load("at22k.wav")
    assert clip.sample_rate == VOICE_SAMPLE_RATE and clip.source_sample_rate == 22_050
    assert clip.resampled
    assert abs(clip.duration_ms - 500) <= 2


# ------------------------------------------------------------- the PCM helpers

def test_resampling_keeps_the_duration_and_never_clips():
    pcm = build_reference_clip(duration_ms=200, peak=0.9)
    out = resample_pcm16(pcm, VOICE_SAMPLE_RATE, 16_000)
    expected = round(len(pcm) // BYTES_PER_SAMPLE * 16_000 / VOICE_SAMPLE_RATE)
    assert abs(len(out) // BYTES_PER_SAMPLE - expected) <= 1
    assert frame_peak_dbfs(out) <= frame_peak_dbfs(pcm) + 0.5


def test_resampling_to_the_same_rate_is_the_identity():
    pcm = build_reference_clip(duration_ms=50)
    assert resample_pcm16(pcm, VOICE_SAMPLE_RATE, VOICE_SAMPLE_RATE) is pcm


def test_gain_attenuates_and_clips_at_full_scale():
    pcm = build_reference_clip(duration_ms=100, peak=0.5)
    quiet = apply_gain_db(pcm, -12.0)
    assert frame_peak_dbfs(quiet) == pytest.approx(frame_peak_dbfs(pcm) - 12.0, abs=0.3)
    loud = apply_gain_db(pcm, 60.0)
    assert frame_peak_dbfs(loud) == pytest.approx(0.0, abs=0.1), "a huge gain clips, it never wraps"
    assert apply_gain_db(pcm, 0.0) is pcm


def test_silence_is_silent_and_the_reference_clip_is_not():
    assert frame_peak_dbfs(build_silence(duration_ms=100)) == -96.0
    assert frame_peak_dbfs(build_reference_clip(duration_ms=100)) > -20.0


def test_blocks_are_the_production_input_block_size_and_the_tail_is_padded():
    blocks = split_blocks(build_reference_clip(duration_ms=INPUT_BLOCK_MS * 2 + 5))
    assert len(blocks) == 3
    assert all(len(block) == INPUT_BLOCK_BYTES for block in blocks)
    assert split_blocks(b"") == []


def test_the_wav_container_round_trips(tmp_path):
    pcm = build_reference_clip(duration_ms=120)
    path = tmp_path / "round.wav"
    path.write_bytes(wav_bytes(pcm, VOICE_SAMPLE_RATE))
    assert read_wav_pcm16(path) == (pcm, VOICE_SAMPLE_RATE)


def test_the_stored_clip_path_fits_the_windows_path_budget():
    """The default root leaves 171 characters for an artifact path (docs/testlab.md, Storage)."""
    from jarvis.testlab.audio.runners import CLIP_ARTIFACT, METADATA_ARTIFACT

    for path in (CLIP_ARTIFACT, METADATA_ARTIFACT):
        assert len(path) <= 171 and "/" not in path


# ------------------------------------------------------------------- the cost

def _token_prices(model_id: str, *, input_price: float, output_price: float) -> dict:
    return {model_id: {"schema_version": PRICING_SCHEMA_VERSION, "model_id": model_id, "currency": "usd",
                       "input_price_per_million_tokens": input_price,
                       "output_price_per_million_tokens": output_price,
                       "source": "test fixture", "effective_at": "2026-01-01T00:00:00+00:00"}}


def _minute_prices(model_id: str, *, per_minute: float) -> dict:
    return {model_id: {"schema_version": PRICING_SCHEMA_VERSION, "model_id": model_id, "currency": "usd",
                       "price_per_minute": per_minute, "source": "test fixture",
                       "effective_at": "2026-01-01T00:00:00+00:00"}}


def test_usage_folds_cumulative_totals_and_never_multiplies_them():
    """The provider reports session totals; adding them would bill every update again."""
    usage = UsageTotals()
    for payload in ({"input_tokens": 100, "output_tokens": 10, "duration_seconds": 1.0},
                    {"input_tokens": 220, "output_tokens": 40, "duration_seconds": 3.5},
                    {"input_tokens": 220, "output_tokens": 55, "duration_seconds": 4.0,
                     "source": PROVIDER_FINAL_SOURCE}):
        usage = usage.fold(payload)
    assert (usage.input_tokens, usage.output_tokens) == (220, 55)
    assert usage.duration_seconds == 4.0 and usage.updates == 3 and usage.final


def test_a_malformed_usage_payload_contributes_nothing_and_raises_nothing():
    usage = UsageTotals().fold({"input_tokens": 50}).fold("not an object").fold({"input_tokens": "many"})
    assert usage.input_tokens == 50 and usage.updates == 2


def test_an_unpriced_model_reports_no_cost_and_says_so():
    model = CostModel("gpt-realtime-2.1-mini")
    assert not model.priced and model.basis == "unpriced"
    assert model.estimate(UsageTotals(input_tokens=1_000_000)) is None
    budget = CostBudget(0.0, model)
    budget.observe({"input_tokens": 10_000_000, "output_tokens": 10_000_000})
    assert budget.cost_usd is None, "no price, no estimate — and therefore no false abort"
    assert budget.to_dict()["cost_basis"] == "unpriced"


def test_a_token_price_from_the_control_center_shape_is_reused_not_reinvented():
    model = CostModel.from_settings("m1", _token_prices("m1", input_price=10.0, output_price=20.0))
    assert model.basis == "provider_tokens"
    estimate = model.estimate(UsageTotals(input_tokens=1_000_000, output_tokens=500_000))
    assert estimate["amount"] == pytest.approx(10.0 + 10.0)
    assert estimate["pricing_source"] == "test fixture" and estimate["currency"] == "USD"


def test_a_per_minute_price_is_used_when_there_is_no_token_price():
    model = CostModel.from_settings("m1", _minute_prices("m1", per_minute=0.6))
    assert model.basis == "duration"
    assert model.estimate(UsageTotals(duration_seconds=120))["amount"] == pytest.approx(1.2)


def test_a_price_document_that_does_not_parse_leaves_the_model_unpriced():
    for pricing in (None, "nonsense", {}, {"m1": "nope"}, {"m1": {"schema_version": 99}},
                    {"other": _token_prices("other", input_price=1, output_price=1)["other"]}):
        assert not CostModel.from_settings("m1", pricing).priced


def test_the_budget_aborts_the_moment_the_estimate_crosses():
    model = CostModel.from_settings("m1", _token_prices("m1", input_price=1.0, output_price=1.0))
    budget = CostBudget(0.50, model)
    budget.observe({"input_tokens": 100_000, "output_tokens": 100_000})  # 0.20 USD
    assert budget.cost_usd == pytest.approx(0.20)
    with pytest.raises(CostBudgetExceeded) as caught:
        budget.observe({"input_tokens": 400_000, "output_tokens": 300_000})  # 0.70 USD
    assert caught.value.code == "testlab_cost_budget_exceeded"
    assert "0.7000" in caught.value.detail and "0.5000" in caught.value.detail
    assert isinstance(caught.value, MeasurementUnavailable), "a budget abort is inconclusive, not a crash"


def test_the_budget_records_what_it_believed_it_spent():
    model = CostModel.from_settings("m1", _token_prices("m1", input_price=1.0, output_price=2.0))
    budget = CostBudget(10.0, model)
    budget.observe({"input_tokens": 1_000_000, "output_tokens": 1_000_000, "source": PROVIDER_FINAL_SOURCE})
    payload = budget.to_dict()
    assert payload["cost_usd"] == pytest.approx(3.0)
    assert payload["usage"]["final"] is True and payload["model_id"] == "m1"
    assert json.loads(json.dumps(payload))  # the metadata artifact must be JSON-serialisable


# ------------------------------------------------------------- the live gates

def test_the_live_gates_need_both_the_opt_in_and_a_key():
    with pytest.raises(LiveGateError) as caught:
        check_live_gates({})
    assert LIVE_OPT_IN_ENV in caught.value.detail
    with pytest.raises(LiveGateError) as caught:
        check_live_gates({LIVE_OPT_IN_ENV: "1"})
    assert API_KEY_ENV in caught.value.detail
    check_live_gates({LIVE_OPT_IN_ENV: "1", API_KEY_ENV: "sk-test"})


def test_the_opt_in_is_exactly_one_and_nothing_else_enables_it():
    for value in ("0", "true", "yes", "", "01", None):
        assert not live_opt_in({LIVE_OPT_IN_ENV: value} if value is not None else {})
    assert live_opt_in({LIVE_OPT_IN_ENV: "1"})


def test_the_provider_identity_is_resolved_before_connecting_and_carries_no_secret():
    identity = resolve_identity({"OPENAI_REALTIME_MODEL": "gpt-realtime-x", "OPENAI_REALTIME_VOICE": "ash",
                                 API_KEY_ENV: "sk-secret"}, config_fingerprint="a" * 64)
    payload = identity.to_dict()
    assert payload == {"provider": "openai", "model_id": "gpt-realtime-x", "voice": "ash",
                       "config_fingerprint": "a" * 64, "session_id": None}
    assert "sk-secret" not in json.dumps(payload)


def test_the_identity_falls_back_to_the_continuous_surface_model():
    from jarvis.v2_config import DEFAULT_CONTINUOUS_SURFACE_MODEL

    identity = resolve_identity({})
    assert identity.model_id == DEFAULT_CONTINUOUS_SURFACE_MODEL and identity.voice == "cedar"


def test_the_fixture_root_lives_inside_the_package_so_a_worker_can_find_it():
    assert AUDIO_FIXTURE_ROOT.is_dir()
    assert AUDIO_FIXTURE_ROOT.parent.parent.name == "testlab"
    digests = {name: hashlib.sha256((AUDIO_FIXTURE_ROOT / name).read_bytes()).hexdigest()
               for name in SHIPPED_FIXTURES}
    assert digests == {
        "reference-tone-1s.wav": "c332fc39485c1c7f2ac7f8354bbaf73e082c6785a3f1d2a7bc10c5c19080bea0",
        "silence-500ms.wav": "6043c420a1d463d946725d1942bf8b2233f172de243ec85f2ae8f9431acdb755",
    }
