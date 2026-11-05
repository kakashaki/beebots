# Release notes

Each release is a `v*` tag on GitHub ([releases](https://github.com/imikerussell/beebots/releases)). The tag publishes
the `:latest` images that installs pull; see the README's "Updating".

## v2026.11.05: Security audit fixes

The fixes from the 29 Oct security audit (README, "Security audit"; video: https://youtu.be/N5VouhdyQkA). Open-source
models on Telnyx Inference read the code (GLM-5.3 Flash over the whole repo, Kimi K3 on the riskiest findings), and
Claude Code checked and fixed what they found.

**Updating from an earlier release:** this release changes `docker-compose.yml` as well as the images (the new
`Caddyfile` ships inside the web image). Pulling the images alone is not enough: fetch the release's compose file too
(README, "Updating"), then pull and restart. Your dashboard moves to `https://`, and the setup code is in
`docker compose logs engine`.

```sh
cp docker-compose.yml docker-compose.yml.bak
curl -fsSLO https://raw.githubusercontent.com/imikerussell/beebots/v2026.11.05/docker-compose.yml
docker compose pull
docker compose up -d
```

- **Setup code.** Every write on the Setup page needs a one-time code that the engine prints only to its own log, new
  on every start. Ten wrong codes from one address and that visitor is refused until the next restart. Before this,
  whoever reached a fresh install first could finish Setup and own it.
- **Save is rate limited:** 10 attempts per address, 30 in total.
- **HTTPS by default.** Without `PUBLIC_DOMAIN`, Caddy now serves the bare IP over HTTPS with its own certificate
  (browsers warn once) and redirects plain HTTP, so keys and the owner password are never sent in the clear. Only the
  Zap's public scorecard and the HMAC-signed `/lab/*` stay on HTTP, because Zapier refuses the internal certificate.
- **No stop, no trade.** A trade no longer opens when no stop loss can be computed (a gap in market data); the stop
  is computed at the mid before the order is sent. Same for the dry-run resume.
- **Per-address lockout.** Wrong owner passwords lock out only the address that sent them, not the owner.
- **`X-Forwarded-For`** was a false alarm (Caddy trusts no proxy, so it overwrites the client's header); documented in
  `clientAddr` and pinned by a test.

## v2026.10.14: Gemini 4 Argon

Run your bees on Google's Gemini 4 Argon, on the trading rules Argon rewrote. Existing Jev installs keep working.

**Updating from an earlier release:** this release changes `docker-compose.yml` as well as the images. Pulling the
images alone is not enough if you set the Gemini key in Docker Manager or your shell: fetch the release's compose file
too (README, "Updating"), then `docker compose pull` and `docker compose up -d`.

- **Chooser.** With a Gemini key (from `.env` or Setup) the bees ask Gemini 4 Argon (`gemini-4-argon`) to pick their
  moves; with only a Jev key they ask Jev, as before. With no key, on paper or demo, a deterministic code chooser picks.
  Live trading still refuses to start without a model key.
- **Who decided, every time.** Each decision records, streams and shows who actually made it: the model, the code
  chooser (with the reason: no key, cap reached, a call refused because it could pass the cap, backoff, timeout, error,
  an answer off the menu, or a paced hold), or the rules. Code's calls are tagged **CODE** in the decision stream and
  show no model confidence, and the header says when code is standing in, including near the cap. The badge names the
  configured chooser only.
- **The code chooser does not read your bees' free-text rules.** It picks from the style's menu by fixed priorities.
  Coin limits and the risk layer still apply. The README says so before you rely on custom rules.
- **Gemini spend cap.** Before each call the engine reserves the call's worst case (prompt bound plus the full answer
  budget) against today's spend plus every call in flight, and writes it to the database first, so concurrent bees and
  a restart cannot overspend the count. Calls with unknown billing are counted at their worst case. Default $3 a day,
  priced at Argon's full rates ($4 / $20 per million tokens); each bee asks at most once a minute.
- **Prices are checked.** The engine refuses to start with a Gemini price (or, when Jev is in use, a Jev price) of 0 or
  less, or not a number; the error names the setting, never its value.
- **Jev's cap is a soft threshold,** and is now described that way. Jev calls also reserve an estimate in the database
  before they are sent, so concurrent bees and restarts count them, but Jev bills by its own token count, so calls in
  flight can take a day somewhat over the threshold.
- **Strategies.** Argon's rewrite of all three styles (`strategies/`): no style is forced into a trade any more,
  Breakout covers 8 majors, and the defaults, `.env.example` and the Beekeeper's playbook follow.
- **Exits never wait for a model.** Stops, time stops, the daily loss stop and retirement run on their own exit watch;
  a per-bee order lock stops the watch and the tick from sending two orders for one bee.
- **Setup** has a "Who makes the calls" step: a Gemini key by default, or **Use Jev instead**. The Gemini key check
  shares the per-visitor request cap with the other checks.
- **Effective config.** `effective-config --runtime`, run inside the engine container, shows the settings the running
  engine actually uses (keys as present or absent only). The file form is labelled a simulation: it cannot see settings
  set outside the file.
- **Dashboard.** "Powered by Gemini 4 Argon" badge, chooser-named labels, and the equity chart no longer overflows on a
  long curve.
