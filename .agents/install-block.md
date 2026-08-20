# The canonical install block

One install story, one wording. `README.md` and every page under `docs/` must
say **this** and nothing else. Change it here first, then propagate.

This repo is its own single-plugin marketplace via
`.claude-plugin/marketplace.json`. It is not listed in Claude Code's official
marketplace; the marketplace-add step below is therefore part of the documented
route, not a fallback.

## Claude Code: the plugin

<canonical-block name="claude-code">

```
/plugin marketplace add ANcpLua/maturity-skills
/plugin install maturity-skills@ancplua
```

</canonical-block>

## Codex, and other agents: copy the files

The plugin is Claude Code only. Everywhere else, copy the skill folders you
want from `skills/maturity/` into your harness's skill directory, or symlink
the whole set with `scripts/link-skills.sh` (maintainer script, unsupported).

## The two routes are exclusive

The plugin is a managed bundle you subscribe to. Copied files are yours to
edit. Installing both leaves you with every skill twice: pick one.
