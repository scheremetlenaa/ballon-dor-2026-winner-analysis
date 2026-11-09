-- Q5. Who finished above expectation?
-- Matches with xG only, so that goals and expected goals cover the same minutes.
SELECT
    n.vote_rank,
    m.player,
    sum(m.minutes)::INT                                               AS minutes_with_xg,
    round(100.0 * sum(m.minutes) / any_value(n.minutes), 1)          AS xg_coverage_pct,
    sum(m.goals - m.penalty_goals)::INT                               AS np_goals,
    round(sum(m.npxG), 1)                                             AS npxg,
    round(sum(m.goals - m.penalty_goals) - sum(m.npxG), 1)            AS np_goals_minus_npxg,
    sum(m.assists)::INT                                               AS assists,
    round(sum(m.xA), 1)                                               AS xa,
    round(sum(m.assists) - sum(m.xA), 1)                              AS assists_minus_xa
FROM v_match m
JOIN v_nominee n ON n.player = m.player
WHERE m.xG IS NOT NULL
GROUP BY n.vote_rank, m.player
ORDER BY np_goals_minus_npxg DESC;
