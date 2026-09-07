## What

- [ ] New fixtures (list the paths below)
- [ ] Site / docs
- [ ] Infra
- [ ] Toolchain

<!-- Paths added, one per line. -->

## Checklist

- [ ] `loremfile catalog validate` passes locally (inside the toolchain container)
- [ ] Every new fixture has `description`, `tags`, `expect`, `size_class`
- [ ] Generator, validator, negative test and determinism test are all in **this** PR
- [ ] No third-party content, no real personal data, no private keys, no executables, no
      external entities (`docs/13-legal-and-policy.md` §5)
- [ ] I did not modify any existing manifest entry (immutability)
- [ ] `manifest.json` / `sha256sums.txt` were produced by `loremfile manifest update` in the
      container, not edited by hand
- [ ] `CHANGELOG.md` updated
- [ ] Dependency added? `tools/requirements.lock` regenerated **and**
      `tools/TOOLCHAIN_DIGEST` bumped in this PR
- [ ] New format? `loremfile infra locks --write` run — owner step noted below

## Owner steps needed before deploy

<!-- e.g. "apply the new bucket-lock rule for `avif/`". Write "none" if there are none. -->
