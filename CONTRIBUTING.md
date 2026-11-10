# Contributing

Contributions are accepted under the MIT license (`LICENSE`), the same license as the rest of the code.

## Sign your commits (DCO)

Every commit needs a `Signed-off-by` line certifying the [Developer Certificate of Origin 1.1](https://developercertificate.org/): you wrote the change, or you have the right to submit it under the project's license.

```bash
git commit -s -m "your message"
```

This adds `Signed-off-by: Your Name <you@example.com>` with the name and email from your git config. Pull requests with unsigned commits aren't merged. To sign commits you already made: `git rebase --signoff main`.

## Before opening a pull request

- Run the tests: `python3 -m unittest discover -s tests`.
- If you changed `commands/commands.json`, regenerate the command files: `python3 tools/gen_commands.py`. `--check` confirms they're current.
- The example docs in `skills/bluedoc/examples/` are built, so with the bluedoc plugin installed your agent's edit and write tools refuse them (patch-only edits). Change them with `build.py patch`, or start the agent with `BLUEDOC_PATCH_ONLY=0` to edit one by hand, then rebuild it with `python3 skills/bluedoc/scripts/build.py <doc>`.
- Issues are tracked with beads (`bd`). See `AGENTS.md`.

## Name and logo

A fork or derived product needs its own name and logo. See `TRADEMARK.md`.
