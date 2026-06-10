# Scorito WK Odds Optimizer

Python tool that turns bookmaker-implied World Cup 2026 market probabilities
into Scorito recommendations. It maximizes expected Scorito points. It does not
optimize betting value and does not provide betting advice.

## Windows setup

```powershell
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python -m playwright install chromium
```

## Configuration

Copy `.env.example` to `.env` and add optional API keys:

```dotenv
THE_ODDS_API_KEY=your_key_here
API_FOOTBALL_KEY=your_key_here
API_FOOTBALL_MAX_REQUESTS=25
API_FOOTBALL_REQUEST_INTERVAL=2.5
```

Scorito rules are loaded from `config/scorito_rules.yaml`. Always verify these
values against the official Scorito WK 2026 rules:

```powershell
python -m scorito_wk_odds_optimizer.cli print-rules
```

## Run

Run the complete pipeline:

```powershell
python -m scorito_wk_odds_optimizer.cli run-all --headless false
```

Refresh all data shortly before the submission deadline and write to a
timestamped output directory:

```powershell
python -m scorito_wk_odds_optimizer.cli final-update --headless false
```

Useful individual commands:

```powershell
python -m scorito_wk_odds_optimizer.cli scrape-oddsportal --headless false
python -m scorito_wk_odds_optimizer.cli scrape-oddschecker --headless false
python -m scorito_wk_odds_optimizer.cli import-oddschecker-html
python -m scorito_wk_odds_optimizer.cli fetch-theoddsapi
python -m scorito_wk_odds_optimizer.cli fetch-apifootball
python -m scorito_wk_odds_optimizer.cli load-manual
python -m scorito_wk_odds_optimizer.cli optimize-matches
python -m scorito_wk_odds_optimizer.cli optimize-outrights
python -m scorito_wk_odds_optimizer.cli optimize-topscorers
python -m scorito_wk_odds_optimizer.cli compute-group-standings
python -m scorito_wk_odds_optimizer.cli export-summary
```

All processing commands support `--rules`, `--output-dir`, `--prefer-source`
and `--use-manual-fallback`. Scraping commands support `--headless`; match
scraping also supports `--max-matches`.

## Source roles

- OddsPortal is primary for fixtures, 1X2, correct score, over/under 2.5 and
  both-teams-to-score odds.
- Oddschecker is primary for tournament winner and top goalscorer odds.
- The Odds API is an optional match-market fallback when configured.
- API-Football is optional player metadata support.
- Manual CSVs under `input/` are last-resort fallback data and do not replace
  better source data unless `--prefer-source manual` is used.

Data is cached under `data/raw/`. A failed page creates a screenshot and HTML
dump under `debug/`. Scraping is resumable.

API-Football metadata is also resumable. Existing player metadata is retained,
only missing players from the bookmaker-implied top 100 goalscorer ranking are
requested, and the default budget is 25 new requests per run. API results are
accepted only when the player name matches exactly after accent normalization.
Every request is spaced by 6.5 seconds by default, including searches that
return no usable player, to remain below short request-rate limits.
Players without an exact API name match are recorded and skipped on later
runs, allowing subsequent batches to continue through the top 100.
After an HTTP 429, the remaining lookups stop immediately and no more requests
are attempted during the server-provided cooldown (15 minutes when no
`Retry-After` header is provided). Change `API_FOOTBALL_MAX_REQUESTS` when your
API plan permits a different per-run budget. The standalone command supports
`--force-retry`, but `run-all` always respects the cooldown.
API-Football can also return a daily-quota error inside an HTTP 200 response;
this is detected as rate limiting and is never stored as a missing player.

### Oddschecker Cloudflare fallback

Oddschecker may allow a normal personal browser but block Playwright. The tool
does not bypass that protection. Existing successful cache data is preserved.
`run-all` also automatically imports the two files below when they exist. Use
a one-time manual local DOM export to create or refresh them:

1. Open the winner page normally:
   `https://www.oddschecker.com/football/world-cup/winner`
2. Open DevTools (`F12`), select **Console**, paste the snippet below and press
   Enter.
3. Repeat on the top-goalscorer page, changing the filename to
   `oddschecker_top_goalscorer.html`.
4. Move the downloaded HTML file(s) into `input/`.
5. Run the import command. Winner and top-goalscorer HTML are imported
   independently, so either file may be omitted.

```javascript
const a = document.createElement("a");
a.href = URL.createObjectURL(new Blob(
  [document.documentElement.outerHTML],
  {type: "text/html"}
));
a.download = "oddschecker_winner.html";
a.click();
```

```powershell
python -m scorito_wk_odds_optimizer.cli import-oddschecker-html
python -m scorito_wk_odds_optimizer.cli run-all --headless false
```

## Match expected value

For every correct score `k` listed by the market:

```text
E[S_k] = S_toto * P_toto(k) + (S_exact - S_toto) * P_exact(k)
```

- `E[S_k]`: expected Scorito points for score `k`
- `S_toto`: points for the correct HOME/DRAW/AWAY result
- `S_exact`: total points for the exact score
- `P_toto(k)`: normalized 1X2 probability matching score `k`
- `P_exact(k)`: normalized full-time correct-score market probability

The selected score is the listed score with maximum expected Scorito points.
No Poisson, xG, machine-learning or simulated football model is used.

## Topscorer value

Topscorers are ranked by a relative **Scorito-weighted market value**:

```text
V_player =
    p_topscorer
    * team_progression_proxy
    * position_points
    * starter_prob
    * penalty_multiplier
    * set_piece_multiplier
    * minutes_risk_multiplier
```

- `p_topscorer`: aggregated top goalscorer market probability
- `team_progression_proxy`: square root of the country's champion probability
- `position_points`: configured Scorito points per goal for the position
- `starter_prob`: metadata-based playing probability
- role and minutes multipliers: configured deterministic adjustments

This value is not an expected-goals estimate. Unknown positions use FWD points
conservatively and are marked LOW confidence.

## Outputs

The pipeline writes:

- `match_predictions.csv`
- `all_score_candidates.csv`
- `outright_recommendations.csv`
- `group_rankings_from_predictions.csv`
- `consistency_warnings.csv`
- `topscorer_recommendations.csv`
- `final_scorito_entry_sheet.csv`
- `summary.md`
- optional `quality_gate_warnings.csv`
- optional `validation_errors.csv`

## Warnings

- OddsPortal scraping may break if the website changes.
- Oddschecker scraping may break if the website changes.
- Scorito rules may change; verify official rules before submitting.
- Bookmaker-implied probabilities are estimates, not guaranteed true
  probabilities.
- Missing data lowers confidence and is never silently guessed.
- This is not a betting tool.

## Tests

```powershell
pytest
```
