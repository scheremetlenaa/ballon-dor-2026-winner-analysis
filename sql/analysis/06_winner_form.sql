-- Q6. How did the winner's season unfold?
-- Rolling five-match G+A and cumulative goals, match by match (window functions).
SELECT
    match_date,
    competition,
    opponent,
    result,
    goals,
    assists,
    round(avg(goals + assists) OVER w5, 2)                                   AS ga_rolling_5,
    (sum(goals) OVER (ORDER BY match_date ROWS UNBOUNDED PRECEDING))::INT      AS goals_cumulative,
    rating
FROM v_match
WHERE player = (SELECT player FROM v_nominee WHERE vote_rank = 1)
WINDOW w5 AS (ORDER BY match_date ROWS BETWEEN 4 PRECEDING AND CURRENT ROW)
ORDER BY match_date;
