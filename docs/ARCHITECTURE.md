# Architecture

```text
Private Google Sheet
  ├─ Players (manual)
  ├─ Catches (manual)
  ├─ Sync Status (generated)
  ├─ Team Checklist (generated)
  └─ Player Summary (generated)
             │
             │ Google Sheets API / service account
             ▼
GitHub Actions every 15 minutes
  ├─ validate input
  ├─ parse monsters.json
  ├─ map evolution scoring families
  ├─ calculate horde probabilities
  ├─ apply team Unique Species state
  ├─ generate team ranking
  ├─ generate all player rankings in one process
  ├─ write generated Google Sheet tabs
  └─ build web/data/strategy.json
             │
             ▼
GitHub Pages
  ├─ Team overall dropdown option
  ├─ one option per active player
  ├─ season filter
  ├─ time filter
  └─ Top 25 spot table
```

## Trust boundaries

- The Google Sheet is private.
- The service-account private key exists only in a GitHub Actions secret.
- The workflow-generated Pages artifact contains no Google credentials.
- The GitHub Pages dashboard is public unless a separate authenticated hosting solution is used.
