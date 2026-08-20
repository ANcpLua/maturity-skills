Skills are organized into bucket folders under `skills/`:

- `maturity/`: evidence-first maintenance routines (the promoted set)

Every skill in a promoted bucket must have a reference in the top-level
`README.md` and an entry in `.claude-plugin/plugin.json`'s `skills` array (the
plugin ships exactly the promoted set). Run `claude plugin validate . --strict`
after touching either manifest. `.claude-plugin/marketplace.json` makes the
repo its own single-plugin marketplace; for this repo that is the documented
install route (see `.agents/install-block.md`).

Install commands are copied verbatim from
[.agents/install-block.md](./.agents/install-block.md). Change them there
first, then propagate.

Each bucket folder has a `README.md` listing every skill in the bucket with a
one-line description, the skill name linked to its `SKILL.md`, grouped into
**User-invoked** and **Model-invoked**.

Each promoted skill also has a human-facing docs page at
`docs/<bucket>/<skill-name>.md` carrying four sections: **What it does**,
**When to reach for it**, **Common questions**, and **It's working if**. When
you add, rename, or change the behaviour of a promoted skill, re-sync its docs
page.

Every `SKILL.md` is either user-invoked or model-invoked; see
[.agents/invocation.md](./.agents/invocation.md).

Versioning is changesets-driven: add a changeset with every user-visible skill
change; `npm run version` keeps `.claude-plugin/plugin.json` in lockstep with
`package.json` via `scripts/sync-plugin-version.mjs`.

To (re)link every skill into the local harness skill directories, run
`scripts/link-skills.sh` (maintainer-only, unsupported); re-run after adding,
removing, or renaming a skill.
