# Shiny Wars 2026 Rules Used by the Parser

## Sources

- Official event thread: https://forums.pokemmo.com/index.php?/topic/198507-pokemmo-shiny-wars-2026/
- Readable rules mirror: https://pokemmo.shoutwiki.com/wiki/Event:Shiny_Wars_2026

## Implemented scoring rules

1. Each Pokémon in a scoring evolution line inherits the same tier value.
2. The first shiny from an evolution line caught by the team receives an additional 8 points.
3. If the team has already caught the line but the current player has not, the catch receives normal base tier points.
4. If the same player catches another shiny from an evolution line they already caught, the normal wild shiny is worth 1 point.
5. Alpha, Secret Shiny, Safari and Egg-specific modifiers are outside this Sweet Scent route model.

## Implemented horde mechanics

The route data stores ordinary hordes as portions of a 5% wild-encounter pool. Sweet Scent chooses between the active horde portions. Therefore:

- 2.5% raw horde split / 5% total horde pool = 50% Sweet Scent horde probability.
- 1% raw horde split / 5% total horde pool = 20% Sweet Scent horde probability.

Explicit early-game rows whose encounter type is already `Sweet Scent` are retained and normalized within their own active horde table. The parser never filters them out.

## Event season schedule

- Week 1: Summer — 2026-08-01 through 2026-08-07 UTC
- Week 2: Autumn — 2026-08-08 through 2026-08-14 UTC
- Week 3: Winter — 2026-08-15 through 2026-08-21 UTC
- Week 4: Spring — 2026-08-22 through 2026-08-28 UTC
