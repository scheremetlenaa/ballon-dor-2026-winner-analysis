# Methodology

**Window.** The 2026 award rewards the 2025/26 season, 1 August 2025 – 31 July 2026, including the 2026 World Cup. Every competition counts, friendlies included; trophies count only for official competitions.

**Players.** The top 10 of the vote; per-90 comparisons need at least 900 minutes.

**Definitions**
- *NP G+A* - non-penalty goals + assists. Used instead of G+A because penalty share varies from 0% to 27%.
- *Big games* - knockout matches of the Champions League and the World Cup (also Euro, Copa América, AFCON in other years).
- *Stage reached* - the furthest round a player played in; a won final is `Winner`.
- *Trophy score* - trophies weighted by importance (an assumption, in `etl/config.yaml`): Champions League and World Cup 3, Euro and Copa América 2.5, big-5 league 2, domestic cup 1, super cups and league cups 0.5.
- *Composite index* - `0.40 × Pctl(output) + 0.35 × Pctl(trophies) + 0.25 × Pctl(big games)`, each a percentile among the ten (0 = lowest, 1 = highest). The notebook tests all 231 weightings in steps of 5%.

**xG.** SofaScore publishes xG for leagues, the Champions League, the World Cup and MLS, not for most cups and friendlies - about 80% of the minutes. Comparisons with xG use the covered matches only. Season totals marked *incl. estimate* fill the gaps with a shot-based estimate (the player's npxG per shot, shrunk towards the average); they are labelled and never used for ranking.

**Limitations**
- One season and ten players: correlations are descriptive, none is statistically significant.
- SofaScore's API is unofficial; ratings are SofaScore's.
- Trophy and index weights are modelling choices.
- The vote also rewards reputation, position and narrative, which no match log records.
