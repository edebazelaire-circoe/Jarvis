"""Independent Task15A prompt provenance and composition review.

Only controlled builders and pure resolution run; no provider or CLI is opened.
"""
from dataclasses import replace
import json
from pathlib import Path

import pytest

from jarvis.domain.prompt_registry import (
    PromptDescriptor, PromptError, PromptOperation, PromptProgram, PromptRegistry,
    PromptStep, PromptTarget,
)


@pytest.fixture
def catalog():
    from jarvis.runtime.prompt_catalog import default_prompt_registry
    return default_prompt_registry()


def test_preview_reports_missing_dynamic_inputs_without_claiming_a_sent_prompt():
    target = PromptTarget('conversation', 'simple', 'openai', 'controlled-model')
    registry = PromptRegistry((
        PromptDescriptor('review.static', __file__, 'test', 'Policy'),
        PromptDescriptor('review.dynamic', __file__, 'test', '{observation}', variables=('observation',)),
    ), (PromptProgram('review.program', target, (
        PromptStep('review.static', 'session.instructions'),
        PromptStep('review.dynamic', 'user.message', PromptOperation.MESSAGE),
    )),))
    preview = registry.resolve(target).to_payload()
    rendered = registry.resolve(target, variables={'observation': 'private observation {not_a_template}'}).to_payload()
    assert preview['missing_variables'] == ['observation']
    assert preview['render_fingerprint'] is None
    assert preview['channels'][1]['text'] is None
    assert preview['application'] == 'preview_only'
    assert preview['provider_internal_prompts'] == 'unavailable'
    assert rendered['channels'][1]['text'] == 'private observation {not_a_template}'
    assert preview['static_fingerprint'] == rendered['static_fingerprint']
    assert rendered['render_fingerprint'] != rendered['static_fingerprint']
    again = registry.resolve(target, variables={'observation': 'changed observation'}).to_payload()
    assert again['static_fingerprint'] == rendered['static_fingerprint']
    assert again['render_fingerprint'] != rendered['render_fingerprint']


def test_replacement_and_message_channels_are_not_flattened_or_duplicated():
    target = PromptTarget('reflex', invocation='verbatim')
    descriptors = tuple(PromptDescriptor('review.' + key, __file__, key, text) for key, text in (
        ('old', 'session policy'), ('replace', 'response policy'), ('append', 'suffix'), ('data', 'user data')))
    registry = PromptRegistry(descriptors, (PromptProgram('review.replace', target, (
        PromptStep('review.old', 'response.instructions'),
        PromptStep('review.replace', 'response.instructions', PromptOperation.REPLACE),
        PromptStep('review.append', 'response.instructions', separator='\n'),
        PromptStep('review.data', 'user.message', PromptOperation.MESSAGE),
        PromptStep('review.data', 'user.message', PromptOperation.MESSAGE),
    )),))
    result = registry.resolve(target).to_payload()
    assert result['channels'] == [
        {'channel': 'response.instructions', 'operation': 'replace', 'text': 'response policy\nsuffix'},
        {'channel': 'user.message', 'operation': 'message', 'text': 'user data'},
        {'channel': 'user.message', 'operation': 'message', 'text': 'user data'},
    ]
    assert [layer['order'] for layer in result['layers']] == list(range(5))
    result['channels'][0]['text'] = 'mutation'
    assert registry.resolve(target).channels[0]['text'] == 'response policy\nsuffix'


@pytest.mark.parametrize('changed', [
    {'role': 'backend'}, {'architecture': 'duplex'}, {'provider': 'google'},
    {'model': 'different'}, {'compatibility': 'legacy'}, {'invocation': 'verbatim'},
])
def test_target_applicability_does_not_alias_different_roles_models_or_invocations(changed):
    target = PromptTarget('conversation', 'simple', 'openai', 'review-model')
    descriptor = PromptDescriptor('review.layer', __file__, 'test', 'visible policy')
    registry = PromptRegistry((descriptor,), (PromptProgram('review.program', target, (
        PromptStep(descriptor.prompt_id, 'session.instructions'),
    )),))
    with pytest.raises(PromptError) as failure:
        registry.resolve(replace(target, **changed))
    assert failure.value.code == 'prompt_target_unsupported'


def test_catalog_descriptors_resolve_real_source_paths_and_do_not_discover_hidden_prompts(catalog):
    descriptors = catalog.describe()
    assert descriptors
    assert len({descriptor.prompt_id for descriptor in descriptors}) == len(descriptors)
    for descriptor in descriptors:
        assert descriptor.source_symbol
        assert Path(descriptor.source_path).is_file(), descriptor.source_path
        assert len(descriptor.default_revision) == 64
    inspected = catalog.inspect()
    assert inspected['provider_internal_prompts'] == 'unavailable'
    assert inspected['application'] == 'preview_only'
    assert not any('hidden' in layer['prompt_id'] for layer in inspected['layers'])
