-- Q4. Can a simple index predict the vote?
-- Percentile of each nominee on output, trophies and big games (0 = lowest, 1 = highest of the ten),
-- weighted by IndexWeights, ranked and compared with the actual ranking. Same logic as the DAX measures.
WITH pct AS (
    SELECT player, vote_rank,
           percent_rank() OVER (ORDER BY np_ga)           AS pctl_output,
           percent_rank() OVER (ORDER BY trophy_score)    AS pctl_trophies,
           percent_rank() OVER (ORDER BY big_stage_ko_ga) AS pctl_big_games
    FROM v_nominee
),
w AS (
    SELECT max(Weight) FILTER (WHERE Component = 'Output')   AS w_output,
           max(Weight) FILTER (WHERE Component = 'Trophies') AS w_trophies,
           max(Weight) FILTER (WHERE Component = 'BigGames') AS w_big_games
    FROM IndexWeights
),
idx AS (
    SELECT pct.*,
           w_output * pctl_output + w_trophies * pctl_trophies + w_big_games * pctl_big_games AS bdo_index
    FROM pct CROSS JOIN w
)
SELECT
    vote_rank,
    player,
    round(pctl_output, 3)                                 AS pctl_output,
    round(pctl_trophies, 3)                               AS pctl_trophies,
    round(pctl_big_games, 3)                              AS pctl_big_games,
    round(bdo_index, 3)                                   AS bdo_index,
    dense_rank() OVER (ORDER BY round(bdo_index, 6) DESC) AS index_rank,
    dense_rank() OVER (ORDER BY round(bdo_index, 6) DESC) - vote_rank AS rank_gap
FROM idx
ORDER BY vote_rank;
