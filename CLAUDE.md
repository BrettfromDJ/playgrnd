# Project notes for Claude

This is a static site (plain HTML, no build step) deployed on Vercel.

## Communication preferences

- The user is a product designer/founder, not a developer. Explain work in plain English.
- **After every change, always end the summary with the exact terminal commands to view the work locally** (fetch/checkout the branch, then serve or open the page). Don't assume the user remembers them from last time.
- **Never use placeholder paths like `path/to/playgrnd` or `<the path it printed>` in those commands** — no angle brackets, no fill-in-the-blank of any kind; the user pastes every line verbatim. Give complete literal commands only (their repo lives at `/Users/brett/playgrnd`; a stale extra copy may exist under `~/Documents`).
- **It must be ONE command, chained with `&&`, not a numbered list of steps.** The user pastes a single line. It should clone the repo if it isn't there, get the branch, start the server on a fixed port, and open the page in the browser. Template — swap the branch name and the tool path:

  ```
  cd /Users/brett/playgrnd 2>/dev/null || git clone https://github.com/BrettfromDJ/playgrnd.git /Users/brett/playgrnd; cd /Users/brett/playgrnd && git fetch origin BRANCH && git checkout BRANCH && git pull origin BRANCH && (sleep 3 && open http://localhost:3000/TOOL/ &) && npx serve -l 3000
  ```

  Mention Ctrl+C to stop it, and give the Vercel branch preview link as the no-terminal option.
