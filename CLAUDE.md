# Project notes for Claude

This is a static site (plain HTML, no build step) deployed on Vercel.

## Communication preferences

- The user is a product designer/founder, not a developer. Explain work in plain English.
- **After every change, always end the summary with the exact terminal commands to view the work locally** (fetch/checkout the branch, then serve or open the page). Don't assume the user remembers them from last time.
- **Never use placeholder paths like `path/to/playgrnd` in those commands** — the user pastes them verbatim. Assume the repo may not be cloned on their machine: give a `find ~ -maxdepth 4 -type d -name playgrnd` step to locate it, with a `git clone` fallback, or point to the Vercel branch preview link as the no-terminal option.
