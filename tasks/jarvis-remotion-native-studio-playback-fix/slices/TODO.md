# Slices - dependency-ordered implementation plan


Start with `00-project-manager`. Do not mark any Slice complete from design notes; all work is pending. A current Workspace Task Type is mandatory for work assignment.


- [ ] `00-project-manager` - Readiness, independent audit and execution control
- [ ] `01-independent-intention-and-code-audit` - Independent intent versus implementation audit (depends on: 00-project-manager)
- [ ] `02-product-experience-contract` - Single presentation UX and semantics contract (depends on: 01-independent-intention-and-code-audit)
- [ ] `03-reproduce-timeline-and-transition-failures` - Runtime reproduction and observability (depends on: 01-independent-intention-and-code-audit)
- [ ] `04-canonical-composition-clock` - One composition and one playback clock contract (depends on: 02-product-experience-contract, 03-reproduce-timeline-and-transition-failures)
- [ ] `05-continuous-remotion-sequencing` - Seamless full-deck Remotion playback (depends on: 04-canonical-composition-clock)
- [ ] `06-player-lifecycle-and-transport` - Correct Player lifecycle, seek and transport (depends on: 04-canonical-composition-clock, 05-continuous-remotion-sequencing)
- [ ] `07-presentation-score-voice-compatibility` - Presenter cue and score bridge without clock conflict (depends on: 04-canonical-composition-clock, 06-player-lifecycle-and-transport)
- [ ] `08-media-fullscreen-stability` - Reliable audiovisual and fullscreen experience (depends on: 05-continuous-remotion-sequencing, 06-player-lifecycle-and-transport)
- [ ] `09-remove-legacy-floating-viewer` - Retire the unwanted floating presentation visualizer (depends on: 01-independent-intention-and-code-audit, 02-product-experience-contract, 06-player-lifecycle-and-transport)
- [ ] `10-variants-interface-control-audit` - Simplify the existing Variants UI (depends on: 02-product-experience-contract, 06-player-lifecycle-and-transport, 09-remove-legacy-floating-viewer)
- [ ] `11-studio-variants-navigation` - First-class Remotion Studio and Variants choices (depends on: 02-product-experience-contract, 09-remove-legacy-floating-viewer, 10-variants-interface-control-audit)
- [ ] `12-native-authoring-workspace-roundtrip` - Safe native Remotion source edit and sync round trip (depends on: 01-independent-intention-and-code-audit, 11-studio-variants-navigation)
- [ ] `13-claude-native-generation-parity` - Agent-native creative workflow and Remotion parity benchmark (depends on: 01-independent-intention-and-code-audit, 12-native-authoring-workspace-roundtrip)
- [ ] `14-visual-quality-and-media-gates` - Real rendered-frame quality and regression gates (depends on: 03-reproduce-timeline-and-transition-failures, 05-continuous-remotion-sequencing, 10-variants-interface-control-audit, 13-claude-native-generation-parity)
- [ ] `15-retire-duplicate-runtime-and-doc-migration` - Code cleanup and durable documentation migration (depends on: 06-player-lifecycle-and-transport, 07-presentation-score-voice-compatibility, 09-remove-legacy-floating-viewer, 10-variants-interface-control-audit, 11-studio-variants-navigation, 12-native-authoring-workspace-roundtrip)
- [ ] `16-release-and-human-acceptance` - Integrated regression, comparison and sign-off (depends on: 07-presentation-score-voice-compatibility, 08-media-fullscreen-stability, 10-variants-interface-control-audit, 11-studio-variants-navigation, 12-native-authoring-workspace-roundtrip, 13-claude-native-generation-parity, 14-visual-quality-and-media-gates, 15-retire-duplicate-runtime-and-doc-migration)