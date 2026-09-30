# Issues

Uniquement pour des découvertes réelles hors de la Slice courante. Une régression de la Slice courante est bloquante et n'a rien à faire ici.

## Pistes connues à la planification

- Live : `cancel_output` rend la surface muette jusqu'à la fin de l'incarnation (`suppress_playback_until_session_end`). À confirmer en Slice 00 : effet sur la suite de la conversation après un barge-in, et coût d'une reconnexion.
- Commentaire de `_eligibility` (« reportée… après ce que celle-ci a déjà en file ») contredit par la sélection `ordering_key` — traité en Slice 04.
