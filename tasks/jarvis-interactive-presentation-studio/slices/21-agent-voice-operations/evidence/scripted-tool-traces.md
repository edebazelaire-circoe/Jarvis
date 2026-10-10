# Scripted tool traces (Slice 21)

This is not a model trace: a scripted brain makes the calls a correct model would make, against the real tools on a real Core.
The real-model traces are in `real-model-traces.md`. Redacted: ids are aliases; no title, value or author text appears.

Totals: 9 scenarios, 20 tool calls, 0 ids typed from memory.

## show all variants

User: "montre toutes les variantes" - said aloud: 0

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_view | explorer_open | opened | silent |

## open variant 2 (fullscreen needs a click)

User: "ouvre la 2" - said aloud: 1

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_inspect | presentation | ok | silent |
| 2 | presentation_view | explorer_open | opened | say |

## make a variant

User: "fais une variante" - said aloud: 1

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_variant | create | created | say |

## compare these four

User: "compare ces quatre" - said aloud: 0

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_inspect | presentation | ok | silent |
| 2 | presentation_compare | open | ok | silent |

## semantic edit of a control

User: "raccourcis le texte de la première scène" - said aloud: 0

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_inspect | variant | ok | silent |
| 2 | presentation_inspect | scene | ok | silent |
| 3 | presentation_edit |  | applied | silent |

## delete a branch (archive with the canonical confirmation)

User: "supprime la branche 3" - said aloud: 2

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_inspect | presentation | ok | silent |
| 2 | presentation_variant | archive_plan | confirmation_required | say |
| 3 | presentation_variant | archive | archived | say |

## rehearse from the second scene

User: "répète depuis la deuxième scène" - said aloud: 0

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_inspect | variant | ok | silent |
| 2 | presentation_play | start | applied | silent |
| 3 | presentation_play | goto | applied | silent |
| 4 | presentation_inspect | playback | ok | silent |
| 5 | presentation_play | stop | applied | silent |

## undo the user's own edit

User: "annule" - said aloud: 1

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_undo |  | confirmation_required | say |
| 2 | presentation_undo |  | applied | silent |

## hostile text in a title

User: "montre-moi les variantes" - said aloud: 0

| # | tool | op | result | speech |
| --- | --- | --- | --- | --- |
| 1 | presentation_inspect | presentation | ok | silent |

