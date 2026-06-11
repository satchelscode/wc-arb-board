# World Cup Arb Board

Standalone site that scans **World Cup 2026** team totals and game totals across PPH (ACE-family) and retail books, then lists **cross-book arbs only**.

Lines that exist on just one book are never shown.

## Sources

| Source | How |
|--------|-----|
| Falcon / BetVegas23 | ACE `NewScheduleHelper.aspx?lg=3749` JSON |
| Pinnacle, DraftKings, FanDuel, … | [The Odds API](https://the-odds-api.com) |

## Local run

```bash
cp .env.example .env
# Edit .env — set ODDS_API_KEY and Falcon credentials
pip install -r requirements.txt
python worker.py   # terminal 1 — polls every SCAN_INTERVAL_SECONDS
python web.py      # terminal 2 — http://localhost:5000
```

## Deploy (Render)

1. Push this repo to GitHub.
2. **New Blueprint** → point at `render.yaml`.
3. Set secrets: `ODDS_API_KEY`, `FALCON_USERNAME`, `FALCON_PASSWORD`.
4. Open the **wc-arb-board-web** URL.

Web and worker share one Postgres database; the worker writes snapshots, the web app reads them.

## Env vars

See `.env.example`. Key settings:

- `ODDS_API_BOOKS` — comma-separated book keys (e.g. `pinnacle,draftkings,fanduel,bookmaker`)
- `ODDS_API_MARKETS` — `team_totals,totals` (more markets later)
- `MIN_EDGE_PCT` — hide small edges (default `0`)
- `BETVEGAS23_ENABLED` — add a second ACE skin

## Adding books later

- **Another ACE skin** — copy the Falcon env block, set `BETVEGAS23_*` or add a new site in `app/ace_sites.py`.
- **Metallic / other PPH** — add an adapter in `app/scanner.py` that returns `Offer` rows.
- **More markets** — extend Odds API `ODDS_API_MARKETS` and parsing in `collect_odds_api_offers()`.
