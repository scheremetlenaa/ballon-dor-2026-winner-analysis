-- Q1. Did the winner have the best season, or just the biggest one?
-- Volume (goals, NP G+A) against efficiency (NP G+A per 90) and penalty dependence.
SELECT
    vote_rank,
    player,
    goals,
    penalty_goals,
    round(100.0 * penalty_goals / nullif(goals, 0), 1)          AS penalty_share_pct,
    np_ga,
    round(np_ga_per90, 2)                                       AS np_ga_per90,
    rank() OVER (ORDER BY goals DESC)                           AS goals_rank,
    rank() OVER (ORDER BY np_ga DESC)                           AS np_ga_rank,
    rank() OVER (ORDER BY np_ga_per90 DESC)                     AS per90_rank,
    rank() OVER (ORDER BY penalty_goals * 1.0 / nullif(goals, 0) DESC) AS penalty_share_rank
FROM v_nominee
ORDER BY vote_rank;
