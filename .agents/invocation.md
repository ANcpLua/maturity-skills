# Invocation convention

Every `SKILL.md` is either:

- **User-invoked**: `disable-model-invocation: true` in the frontmatter plus
  `policy.allow_implicit_invocation: false` in `agents/openai.yaml`. Reachable
  only when the human types it.
- **Model-invoked**: neither flag set. The frontmatter `description` must carry
  rich trigger phrasing (the situations and words that should make an agent
  reach for it), because that description is all the model sees when deciding.

All three maturity routines are model-invoked: they are audit tools an agent
should reach for when the user describes the problem, not ceremonies the user
must know by name.
