# beebots 🐝

> [!IMPORTANT]
> **Experiment concluded: -21.4% in 30 days of real money.**
> From 25 Sep to 26 Oct 2026 the three official bees traded $999 of real money on OKX. They ended at $785.16, and the AI
> calls cost another $42.35 on top. Boozy lost 46%, Bizzy 15%, Breezy 3%. Every number is in the write-up, along with
> the 200,000 coin-flip bots I ran as a control:
>
> - **Read the full result:** [Do AI Trading Bots Work? A Real-Money Test](https://creatormagic.ai/blog/do-ai-trading-bots-work/)
> - **Watch the video:** [youtu.be/bp_u9Gzp1OU](https://youtu.be/bp_u9Gzp1OU)
>
> **Read this before you run it.** The code still works and stays here as a record of how it was built, but it is no
> longer maintained. It made no money for me, and nothing about it suggests it will for you. Run it on paper (the
> default). If you switch it to real money anyway, only use money you are happy to lose.
>
> beebots.tech now redirects to the write-up, and **the Hive leaderboard is closed**. A self-hosted install keeps
> trading on paper as before, but joining the Hive does nothing.

[![Watch the video: I built AI trading bees with Jev](docs/video.jpg)](https://www.youtube.com/watch?v=8ijN8LGljKg)

Three AI trading bees race each other on OKX perpetual futures. Their moves are picked by an AI model, **Gemini 4
Argon** (see [Run it with Gemini 4 Argon](#run-it-with-gemini-4-argon)) or **Jev** (TypeSafe AI's decision model),
whenever the model is asked and answers. Not every decision is the model's: between paced calls, over the daily spend
cap, without a key, or when a call fails, a deterministic code chooser picks instead, and when only one move is legal
the rules make the call. Every order goes through a risk layer written in plain code. A live dashboard shows each
decision (and who made it), order, fee and funding payment as it happens.

**It runs on paper by default.** The bees use real market prices and simulated money. Nothing touches an exchange
account unless you change the settings yourself, on purpose.

![The beebots dashboard: three named bees trading on paper](docs/screenshots/dashboard.jpg)

> **Not financial advice.** beebots is an experiment and a piece of open-source software. It is not a trading product,
> and nothing it does is a recommendation to buy or sell anything. Leveraged crypto trading can lose everything you
> put in. The software comes with no warranty (see [LICENSE](LICENSE)). If you ever switch it to real money, that
> is your decision and your risk.

## Run your own in one click

[![Deploy on Hostinger](https://assets.hostinger.com/vps/deploy.svg)](https://www.hostg.xyz/aff_c?offer_id=815&aff_id=202403&url=https%3A%2F%2Fwww.hostinger.com%2Fdocker-hosting%3Fcompose_url%3Dhttps%3A%2F%2Fraw.githubusercontent.com%2Fimikerussell%2Fbeebots%2Fmain%2Fdocker-compose.yml%26utm_medium%3Daffiliate%26utm_source%3Daff%7Baffiliate_id%7D%26utm_campaign%3D%7Boffer_id%7D%26session%3D%7Btransaction_id%7D)

Use code **MAGIC10** at checkout for 10% off.

1. Click the button, pick a VPS plan (a **KVM 2** is plenty) and check out. Hostinger sets up Docker and starts
   beebots for you.
2. Open `https://<your-server-ip>/` in a browser. It warns once about the certificate (Caddy made it itself; see
   [Setup safety](#setup-safety)): carry on to the site. You'll see the **Setup** page. Do this soon: Setup stays
   open for 2 hours after the server starts.
3. On Setup:
   - enter the **setup code** from the engine's log: Hostinger **Docker Manager** → the `beebots` project → the
     `engine` container's logs, on the line that says `setup is open`
   - tick the three risk statements
   - pick an **owner password** (8+ characters). Your dashboard is public; the password is what lets *you* change
     things from it later, like joining or leaving the Hive. Write it down.
   - paste a **Gemini key** for Gemini 4 Argon (see [Run it with Gemini 4 Argon](#run-it-with-gemini-4-argon)), or
     press **Use Jev instead** and paste a **Jev key** (from [console.typesafe.ai/keys](https://console.typesafe.ai/keys))
   - paste an **OpenAI key** (required: it designs your bees and paints them; a few cents in total)
   - design your three bees. For each one, answer **How do you want this bee to trade?** in a sentence ("a Trump bee
     that only ever trades TRUMP", "a sleepy bee that only buys bitcoin dips"), press **Create my bee**, and OpenAI
     invents its name, tagline, trading rules and the coins it may trade. Rename it if you like, then press
     **Generate your bee's portrait**. You can carry on once all three bees have their portraits.
   - choose whether to join **the Hive** (see below). "Not now" is fine; you can join later.
4. Press **Start paper trading**. The engine restarts, and the dashboard goes live.

| Agree to the rules | Pick an owner password | Design your bees |
|---|---|---|
| ![Risk statements](docs/screenshots/setup-rules.jpg) | ![Owner password](docs/screenshots/setup-password.jpg) | ![Design your bees](docs/screenshots/setup-bees.jpg) |

### Setup safety

The Setup page is public, so reaching it first is not enough to take your server:

- **A setup code.** Setup asks for a code the engine prints to its log when it starts: Hostinger **Docker Manager** →
  the `engine` container's logs, or `docker compose logs engine`, on the line that says `setup is open`. Each restart
  prints a new one. Ten wrong codes and that visitor is refused until the next restart.
- **Once saved, closed.** Once you press Start, Setup closes for good. Nobody else can change your keys or bees.
- **A setup window.** If nobody finishes Setup within 2 hours of the engine starting (`SETUP_WINDOW_MIN`, default
  120), it locks, and the page says so. Restart the engine to open it again: Hostinger **Docker Manager** → the
  `beebots` project → **Restart** on the `engine` container, or `docker compose restart engine`.
- **Caps** on the calls that cost money (designs and portraits) and on save attempts, in total and per visitor.

The page is always HTTPS. Without a domain, your browser warns once that it doesn't know who signed the server's
certificate (Caddy made it itself); your keys are still encrypted. With a domain (`PUBLIC_DOMAIN`, below) there's no
warning.

Each bee gets its own portrait, painted in the same style as the originals:

<img src="docs/screenshots/generated-bee.jpg" alt="A generated bee portrait" width="256">

**Copy a winning bee.** Every bee on [beebots.tech](https://beebots.tech) shows its rules with a **Copy** button. Copy
a winner's rules and paste them into **How do you want this bee to trade?** to start from its playbook.

Each bee starts with $333 of paper money. Decision spending is capped by default at $3 a day with Gemini, or about $2 a
day with Jev (a soft threshold; see [Settings](#settings)).

### Already have a server?

Any machine with Docker works:

```sh
curl -fsSLO https://raw.githubusercontent.com/imikerussell/beebots/main/docker-compose.yml
docker compose up -d
```

Then open `https://<your-server-ip>/` (your browser warns once about the certificate: see [Setup safety](#setup-safety)),
and have `docker compose logs engine` handy for the setup code.

### Updating

New versions are published as [releases](https://github.com/imikerussell/beebots/releases) (what changed in each:
[docs/RELEASES.md](docs/RELEASES.md)). When one is out, your
dashboard shows **Update available** next to the trading mode, linking to what's new. Nothing updates by itself.

To update, pull the new images and restart. Your bees, settings and history live in Docker volumes and are kept:

```sh
docker compose pull
docker compose up -d
```

The images your compose file pulls (`:latest`) change only when a release is published, never on an ordinary push.
Some releases also change `docker-compose.yml`, and pulling images does not update that file. **Gemini 4 Argon
(`v2026.10.14`) is one of them**: it passes `GEMINI_API_KEY` and `GEMINI_DAILY_USD_CAP` from Docker Manager's variables
or your shell to the engine (an older file passes them only from `.env`). To take it, keep
a copy of your old file if you edited it, then fetch the release's own copy and restart:

```sh
cp docker-compose.yml docker-compose.yml.bak
curl -fsSLO https://raw.githubusercontent.com/imikerussell/beebots/v2026.10.14/docker-compose.yml
docker compose pull
docker compose up -d
```

On Hostinger's one-click install, Docker Manager keeps its own copy of the compose file: update it there the same way.

Run it over SSH (or hPanel's browser terminal on Hostinger) in the folder that holds your `docker-compose.yml`
(`docker compose ls` shows where it is). To turn the check off, set `UPDATE_CHECK=false`.

## Run it with Gemini 4 Argon

Gemini 4 Argon (`gemini-4-argon`) is Google's model. It rewrote the three trading styles (see
[`strategies/`](strategies/)), and with a Gemini key the bees ask it to pick their moves (each bee at most once a
minute; see [When Argon is not answering](#when-argon-is-not-answering) for when code picks instead). The dashboard then
shows **Powered by Gemini 4 Argon** as the configured chooser, and marks every call that the code chooser made instead.

**1. Get a key.** Open [Google AI Studio](https://aistudio.google.com/apikey) and create an API key in a Google Cloud
project that has billing turned on (the paid tier). **The free tier cannot use Argon**: a free-tier key may pass
Setup's check, but the bees' calls are refused, and the bees fall back to the code chooser.

**2. Give it to your bees.** Either:

- a new install: paste it on Setup, in the **Who makes the calls** step; or
- an existing install: first update to the **Gemini 4 Argon** release (`v2026.10.14`) or later, **including its
  `docker-compose.yml`** (see [Updating](#updating)). An older image does not know what to do with the key, and an
  older compose file passes it only from `.env`, not from Docker Manager's variables or your shell. Then put `GEMINI_API_KEY=...` in the `.env` next to
  `docker-compose.yml` (or in Hostinger Docker Manager's environment variables) and run `docker compose up -d`. Check
  that it took with the `--runtime` command under [Already changed some settings?](#already-changed-some-settings).

A Gemini key wins over a Jev key, so you can leave the Jev key where it is. To go back to Jev, remove the Gemini key
from your `.env` or Docker Manager variables. If you pasted it on Setup, it is also in `/data/settings.json`, where it
still wins: run Setup again (see [Settings](#settings); it starts Setup over, bees included) and choose **Use Jev
instead**.

**3. The settings.** All are optional. The defaults price calls at Argon's full (post-launch) rates, cap model spend
at $3 a day for all three bees together, and ask each bee at most once a minute. They protect your model bill. They do
not make trading safe: that is the risk layer's job, and no setting makes trading risk-free.

| setting | default | what it does |
|---|---|---|
| `GEMINI_API_KEY` | blank | Your key. It is sent only in the `x-goog-api-key` header, never in a URL, a prompt or a log. |
| `GEMINI_MODEL` | `gemini-4-argon` | The model. |
| `GEMINI_DAILY_USD_CAP` | `3` | Daily cap on Gemini spend as the engine counts it, for all three bees together. A call is only sent if its worst case fits; otherwise, and once the cap is reached, the code chooser answers until 00:00 UTC. |
| `GEMINI_MIN_INTERVAL_MS` | `60000` | At most one paid call per bee this often, whatever `TICK_MS` is. In between, the bee keeps what it has. |
| `GEMINI_USD_PER_MTOK` | `4` | Price per million input tokens, used to keep score against the cap. Must be above 0. |
| `GEMINI_USD_PER_MTOK_OUT` | `20` | Price per million output tokens (thinking counts as output). Must be above 0. |
| `GEMINI_TIMEOUT_MS` | `3000` | How long one call may take before the bee falls back to code for that decision. |
| `GEMINI_THINKING_LEVEL` | blank | Optional `thinkingConfig.thinkingLevel`. Blank = the model's default. |

**Pricing.** At launch (13 Oct 2026), Argon's introductory price was **$2 per million input tokens and $10 per million
output tokens until 30 Nov 2026**, then **$4 and $20** ([Google's announcement](https://x.com/Google/status/2110041305925484716);
the later price as reported by [Artificial Analysis](https://x.com/ArtificialAnlys/status/2110068185793970576)). The
defaults above use the later price. With those published rates and fully reported usage, the local counter prices tokens
at twice the billed rate until 30 Nov 2026, so paid model calls stop well before $3 of real spend; trading continues on
code when model calls stop. That is not an invoice guarantee: calls whose billing is unknown (timeouts, errors) are
counted at their worst case, and a call can be refused early when its worst case does not fit in what is left. Set
`GEMINI_USD_PER_MTOK=2` and `GEMINI_USD_PER_MTOK_OUT=10` if you want the counter to match the launch price, and set them
back on 1 Dec 2026. Check [Google's pricing page](https://ai.google.dev/gemini-api/docs/pricing) before you rely on any
of these numbers. The engine refuses to start with a price of 0 or less, but it cannot check that your prices match
what Google actually bills.

**How the Gemini cap holds.** Before each call the engine reserves the call's worst case: its whole prompt, plus the full
1,024-token answer budget (about 2 cents at $20 per million). It adds that to what has been spent today plus every
call still in flight, and if the total would pass the cap, the call is not sent and the bee uses the code chooser
instead (the dashboard says so, even before the day's settled spend reaches the cap). When Google answers, the
reservation settles to the amount its usage report prices at your configured rates. Reservations are written to the
database first, so a restart in the middle of a call cannot reset the count. Asking once a minute for three bees all
day would be up to 4,320 calls, so on the default cap expect the cap, not the interval, to set how many Argon calls you
get each day.

(Jev's cap works differently: it is a soft threshold. See `JEV_DAILY_USD_CAP` under [Settings](#settings).)

### When Argon is not answering

No key, the cap reached, a call refused because its worst case would not fit under the cap, a backoff after errors, a
timeout, an error, or an answer that is not on the menu: in each case a deterministic code chooser picks the move
instead. Between paced calls (inside `GEMINI_MIN_INTERVAL_MS`) the bee simply keeps what it has, and that hold is
marked as code's too. Every decision records who actually made it: the decision stream tags code's calls **CODE** with
the reason and shows no model confidence for them, and the header says when code is standing in. Stops, time stops and
the daily loss stop never wait for any model: they run on their own timer.

**The code chooser does not read your rules.** It picks from the style's built-in menu by fixed priorities (take
profit, cut a loser, add to a winner, take the top strict setup, otherwise hold). Your bee's free-text rules go only to
the model: a bee told "never open a trade, only wait" can still open one while code is choosing. Coin restrictions do
still apply (they shape the menu), and so does the risk layer. Keep this in mind before relying on custom rules with
real money.

### Already changed some settings?

A value set in your `.env` (or in Docker Manager's environment variables) beats the new defaults, so an `.env` copied
from an older `.env.example` keeps the old rules' trade caps and fee budgets. To see what your **running** engine
actually uses, and every knob that differs from Argon's rules, ask the engine container itself:

```sh
docker compose exec engine node dist/tools/effective-config.js --runtime --diff strategies/ARGON_INTENDED.json
```

It reads the container's own environment and Setup file through the engine's own config loader, and prints settings
only: keys show as present or absent, never their values, and the environment itself is never printed. A running
container keeps the settings it was started with, so after editing `.env` run `docker compose up -d` first, then check.
Remove the lines it lists from your `.env` (or Docker Manager) to get Argon's values, then `docker compose up -d`.

To check an `.env` file before you use it, there is also a file **simulation**. It reads only that file plus the
compose file's defaults, so it cannot see variables set anywhere else (Docker Manager, your shell): it checks a file,
not your server.

```sh
docker compose run --rm --no-deps --entrypoint node -v "$PWD/.env:/cfg/env:ro" engine \
  dist/tools/effective-config.js /cfg/env --settings /data/settings.json --diff strategies/ARGON_INTENDED.json
```

From a checkout: `pnpm effective-config .env --diff strategies/ARGON_INTENDED.json`. The output's `source` field says
which one you ran (`runtime` or `file-simulation`).

## The Hive

The Hive is a public leaderboard at [beebots.tech](https://beebots.tech) where everyone's bees race each other. It is
**opt-in**: nothing is sent unless you join. What you agree to when you join:

> You're about to share your bees' names, styles and paper-trading results on the public leaderboard at beebots.tech. The board shows % gain/loss only. No keys, no exchange account details, no IP address. Paper trading only. Not financial advice. You can leave any time.

- **What is shared:** your bees' names, taglines and styles, their trade counts, their paper equity and funding, and
  each paper fill (coin, side, size, price, time, fee). The board shows the % gain or loss, not dollars; the equity and fills are
  there so it can replay every trade against OKX's public prices and mark the bee **verified**. Also a random hive id
  and key made when you join, so later reports can be matched to your install.
- **Never shared:** your Gemini, Jev, OpenAI or OKX keys, any exchange account data, your server's address, or anything else.
- **Paper only.** The engine refuses to report in `MODE=live`, and the board rejects live reports.
- **Join or leave:** tick it on Setup, or use **Join the Hive** in the dashboard header. Joining and leaving from the
  dashboard need your **owner password** (the one you picked on Setup; 8 wrong tries lock it for 15 minutes). Leaving
  removes your bees and their history from the board. Running Setup
  again and answering **Not now** also leaves the Hive, on the next engine start.

The Hive is a game, not a signal service. **Not financial advice.**

## The Beekeeper (optional, Zapier)

The Beekeeper is an outside coach for your bees. Every few hours he looks at all three, and if one keeps losing
because its rules are wrong, he writes it new rules. He runs as a Zap on Zapier: Jev picks the bee, and Claude
Opus 5.5 writes the rules.

- **Watch it being built:** [youtube.com/watch?v=cTUnM9trqfs](https://www.youtube.com/watch?v=cTUnM9trqfs)
- **Set it up:** copy the Zap from [mrc.fm/beekeeper](https://mrc.fm/beekeeper), then paste its hook URL into
  **Connect the Beekeeper** on your dashboard. The full walk-through is in [docs/BEEKEEPER.md](docs/BEEKEEPER.md).
- **What he can change:** a bee's rules text and its coin list. Never leverage, stops, caps or real money settings.
  One rewrite per bee every 20 hours.
- **You stay in charge:** every rewrite shows on the dashboard with an **Undo** next to it. Undo, Connect and
  Disconnect need your owner password.
- **Works on paper.** No exchange account needed.

## How your bees trade

Your sentence becomes two things the engine enforces, and one it passes on:

- **Coins.** If your bee names coins, it only ever trades those. They must be crypto perpetuals listed on OKX EEA right
  now (Setup checks the live list and asks you to rephrase if none match).
- **The engine it runs on.** Every bee runs on one of three built-in trading styles below. A bee limited to BTC and/or
  ETH can run on Trend; one limited to BTC, ETH, SOL, HYPE, XRP, SUI, DOGE or LINK can run on Breakout; everything else
  runs on Momentum, which works on any coin.
- **Rules.** Its rules go to the decision model (Gemini 4 Argon or Jev) with every decision, and it follows them when
  picking among the moves the style offers. They steer the choice; they can't invent moves the style doesn't have, and the risk layer below still applies.

A coin still has to pass the same gates as any other (at least $1M of 24h volume, a tight spread). If your bee's coin
doesn't, the bee just waits until it does.

## The three trading styles

| style | the original bee | what it does |
|---|---|---|
| **Breakout** | Bizzy, the grinder | Both ways on 8 liquid majors: fades stretched moves (RSI and Bollinger bands), and takes confirmed daily breakouts on BTC, ETH, SOL or HYPE. Banks at the middle band or +1R, 4-hour time stop. Up to 4 trades a day. |
| **Trend** | Breezy, the calculated one | Trend following on BTC and ETH only. Sits in cash in chop, adds only to a winner, sized by trend strength under a volatility cap. Up to 2 trades a day. |
| **Momentum** | Boozy, the degen | Chases fresh, high-volume moves long or short, adds once to a winner, bails when the move stalls, 12-hour time stop. Up to 3 trades a day. |

Bizzy, Breezy and Boozy are the official bees (they run on [beebots.tech](https://beebots.tech)), so their names and art
are theirs; your bees get their own. Two of your bees can share a style. The styles were rewritten by Gemini 4 Argon on
13 Oct 2026: no style is ever forced into a trade any more, and each waits flat for its own setup. The full rules are
in [`strategies/`](strategies/), and the rules every bee shares (caps, stops) are in
[`strategies/DRAMA_RULES.md`](strategies/DRAMA_RULES.md).

## How a decision is made

Every tick, for every bee:

1. **Look.** Live OKX market data: tickers, candles, RSI, MACD, ATR, Bollinger, Donchian, funding, open interest.
2. **Summarise.** A small numeric snapshot of the market and the bee's own position.
3. **Ask the model.** Gemini 4 Argon (or Jev) picks one move from a menu of moves that are actually valid right now.
   With Gemini, each bee asks at most once a minute. When the model is not asked or does not answer usefully, the code
   chooser picks (see [When Argon is not answering](#when-argon-is-not-answering)).
4. **Check.** Plain code can veto, shrink or force the move: max 2x leverage, per-bee stops, a daily loss stop,
   trade caps, a fee budget, cooldowns, and a daily cap on model spending.
5. **Record, then act.** The decision, and who made it (the model, the code chooser and why, or the rules), is written
   to SQLite before anything happens.
6. **Broadcast.** The dashboard streams it live.

The model is stateless and never sees an order endpoint. If it is down, slow, over its daily cap, answers off the menu,
or there is no key, a deterministic code chooser picks from the same menu (without reading the bee's free-text rules),
and the same risk layer applies. Stops never wait for the model:
a separate exit watch checks every open position every couple of seconds, and each bee has an order lock, so the watch
and the tick can never send two orders for one bee.

## Settings

Most people need none: Setup covers the keys. To change anything else, create a `.env` next to
`docker-compose.yml` (or set the variables in Hostinger Docker Manager) and restart. Every setting is documented
in [`.env.example`](.env.example). The common ones:

| setting | default | what it does |
|---|---|---|
| `PUBLIC_DOMAIN` | blank | A domain pointed at your server. Caddy then gets a real HTTPS certificate on its own. **Recommended**: without it, the server's IP gets Caddy's own certificate, and browsers warn about it. |
| `GEMINI_API_KEY` | blank | Runs the bees on Gemini 4 Argon (see [Run it with Gemini 4 Argon](#run-it-with-gemini-4-argon)). |
| `GEMINI_DAILY_USD_CAP` | `3` | Daily cap on Gemini spend as the engine counts it; each call's worst case is reserved before it is sent. When there is no room, the code chooser answers until 00:00 UTC. |
| `TICK_MS` | `10000` | How often each bee is looked at, and how often it asks Jev. Faster is more exciting and costs more with Jev (see [docs/COSTS.md](docs/COSTS.md)). Gemini is paced by `GEMINI_MIN_INTERVAL_MS`. |
| `JEV_DAILY_USD_CAP` | `2` | A **soft** daily threshold on Jev spend: no new Jev call once today's spend plus the calls in flight would pass it, and then the code chooser answers until 00:00 UTC. Jev bills by its own token count, which can be more than the engine's estimate, so calls already in flight can take a day somewhat over it. |
| `BEE_START_EQUITY_USD` | `333` | Paper money per bee. |

**Run Setup again** (new names, new keys, or a forgotten owner password):

```sh
docker compose exec engine rm /data/settings.json
docker compose restart engine
```

Run these on the server (on Hostinger, over SSH from hPanel), then open the site and go through Setup again. The
setup window starts over with the restart.

**Owner password:** it's stored only as a salted hash in `/data/settings.json`, so nobody (including you) can read it
back. If you forget it, run Setup again as above. Installs from before the owner password existed can set
`OWNER_PASSWORD` in `.env` (8+ characters) instead.

**Something wrong?** The engine's log says what it's doing: `docker compose logs engine`, or Hostinger Docker
Manager → the `engine` container's logs.

**Backups:** a sidecar writes a nightly copy of each database to `/data/backups` inside the `bees-data` volume and
keeps 7 days. That copy lives on the same server, so take an off-server copy yourself if you care about the history.

## Real money (read this twice)

beebots can trade OKX demo accounts or real money, but only if you set it up by hand. It is **not** part of Setup, and
there is no button for it.

- Real money needs **all** of: `DRY_RUN=false`, `MODE=live`, three OKX **EEA** sub-account API keys
  (`BEE1_OKX_API_KEY` etc., Read + Trade only, **never Withdraw or Transfer**, IP-bound to your server), and
  `LIVE_ACK=I-ACCEPT-REAL-MONEY-RISK`. With any one of them missing, the engine refuses to start.
- The first hours of live trading run at reduced size (`LIVE_SIZE_MULTIPLIER`, `LIVE_RAMP_HOURS`).
- The bot can never withdraw. Moving money off the exchange is always done by you, by hand.
- Try `MODE=demo` first, with OKX **demo** keys (`BEE1_OKX_DEMO_API_KEY` etc.).
- The engine talks to OKX's EEA site (`eea.okx.com`). Check that OKX's derivatives are available where you live
  before you go anywhere near real money.

**Ending a live run:** `docker compose exec engine touch /data/close-live`. The engine stops asking the model, closes every
position with reduce-only market orders, and stays up so the dashboard keeps the final result.

Again: this is not financial advice, and you can lose everything.

## Develop

```sh
pnpm install
pnpm test            # risk layer (every cap, gate and forced move, both directions), setup, redaction, indicators, ledger
pnpm universe        # the tradable coin list from live public data (no keys)
pnpm snapshot        # each style's menu and snapshot from live data (no model call)
pnpm e2e:fake-jev    # the whole engine on paper with a random fake Jev (no spend)
pnpm dev             # the real engine on paper, with real model calls (Setup runs if there is no key)
pnpm effective-config .env --diff strategies/ARGON_INTENDED.json   # simulate a .env file's config, secrets as presence only

cd dashboard && pnpm install && pnpm dev    # http://127.0.0.1:5173, proxied to the engine
```

Build the images yourself instead of pulling them:

```sh
docker compose -f docker-compose.yml -f docker-compose.build.yml up -d --build
```

Everything on OKX is built on OKX's own open-source [Agent Trade Kit](https://github.com/okx/agent-trade-kit) (MIT).
Public market data (instruments, tickers, candles, open interest, funding) runs in-process on the kit's own public REST
client and rate limiter, vendored in `src/okx/kit/` with its licence, so there is no child process per call; `pnpm parity`
checks it returns the same data as the CLI. Signed calls (orders, positions, fills, leverage, news) go through the kit's
CLI. Keys never touch disk inside the container except in the Setup file (`/data/settings.json`, owner-only). The
logger and the event stream redact anything that looks like a key, an IP address or an email.

## Credits

Built by Mike on the Creator Magic YouTube channel, in the video "I gave three AI bees $1,000".
Hosted on [Hostinger](https://www.hostg.xyz/aff_c?offer_id=815&aff_id=202403&url=https%3A%2F%2Fwww.hostinger.com%2Fdocker-hosting%3Fcompose_url%3Dhttps%3A%2F%2Fraw.githubusercontent.com%2Fimikerussell%2Fbeebots%2Fmain%2Fdocker-compose.yml%26utm_medium%3Daffiliate%26utm_source%3Daff%7Baffiliate_id%7D%26utm_campaign%3D%7Boffer_id%7D%26session%3D%7Btransaction_id%7D). Decisions by [Gemini 4 Argon](https://ai.google.dev/gemini-api/docs) or [Jev](https://typesafe.ai).

MIT licence. No warranty. Not financial advice.
