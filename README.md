# Shiny Wars 2026 Automated Horde Dashboard

This repository reads a private Google Sheets catch checklist, recalculates the current team and player-specific PokeMMO Shiny Wars 2026 horde strategy, and deploys an English GitHub Pages dashboard.

## What is included

- Team-wide Top 25 route contexts
- One player dropdown containing all active team members
- Top 25 route contexts for every player
- Season and time-of-day filters
- Unique Species Clause and personal duplicate scoring
- Temporal exclusivity weighting
- Optional hard player-context exclusion derived only from owned Pokémon families
- Strict `location_id` grouping with readable route/location names
- Google Sheets input and generated status tabs
- Scheduled GitHub Actions deployment every 15 minutes

## Quick start

1. Read [`docs/SETUP_GUIDE_DE.md`](docs/SETUP_GUIDE_DE.md).
2. Import [`templates/shiny_wars_google_sheet_template.xlsx`](templates/shiny_wars_google_sheet_template.xlsx) into Google Sheets.
3. Create the Google service account and share the sheet with its email address.
4. Add the two GitHub Actions secrets.
5. Enable GitHub Pages with **GitHub Actions** as the source.
6. Run **Update Shiny Wars dashboard** manually once.

## Manual input

Only these sheets are edited manually:

- `Players`: active in-game names
- `Catches`: `Player`, `Pokemon`, `Active`, optional `Notes`

Catch count, catch time, and catch location are deliberately ignored. Duplicate player/Pokémon rows are collapsed.

## Player route exclusion

The default configuration removes a route context from a player's ranking when the player has already caught **any scoring evolution family available in that context**. This makes `Player + Pokémon` sufficient input.

This is not the same as remembering the physical map on which the catch occurred. If the desired rule later changes to “exclude only the exact map where the shiny was caught,” a `location_id` input column would be required.

## Local build

```bash
python -m pip install -r requirements.txt
./scripts/build_local.sh
python -m http.server 8000 --directory web
```

Then open `http://localhost:8000`.
