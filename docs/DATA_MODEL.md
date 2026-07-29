# Data Model and Ranking Semantics

## Manual input

### Players

- `Player`: exact in-game name
- `Active`: active roster flag
- `Notes`: ignored by scoring

### Catches

- `Player`: must match an active player
- `Pokemon`: must resolve to a Pokémon or scoring family
- `Active`: false rows are ignored
- `Notes`: ignored by scoring

Duplicate player/Pokémon rows are collapsed. Catch count, timestamp, and location are not used.

## Derived state

- `team_caught_families`: union of all active players' scoring families
- `player_caught_families[player]`: scoring families owned by the selected player
- `location_id`: authoritative route/map instance key
- `context_id`: location plus method, season, and time

## Default player eligibility rule

A context is removed from a player's ranking when:

```text
context_scoring_families ∩ player_caught_families != ∅
```

This rule allows the workflow to work with only player and Pokémon input. It does not represent the physical map where the shiny was caught.

## Team view

The team view uses the current team state but an empty personal-catch state:

- new team family: base + unique bonus
- team-owned family: base points

## Player view

With hard exclusion enabled, ineligible contexts are removed before the Top 25 views are generated.

With hard exclusion disabled:

- personal family: duplicate points
- team-owned family: base points
- new team family: base + unique bonus
