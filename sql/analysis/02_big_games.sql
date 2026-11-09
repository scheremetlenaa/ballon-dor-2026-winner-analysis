-- Q2. Who delivered on the big stage?
-- G+A in Champions League and World Cup knockouts and the rating there against the season rating.
WITH ko AS (
    SELECT player,
           count(*)                         AS ko_matches,
           sum(goals + assists)             AS ko_ga,
           avg(rating)                      AS ko_rating
    FROM v_match
    WHERE is_big_stage AND is_knockout
    GROUP BY player
),
season AS (
    SELECT player, avg(rating) AS season_rating
    FROM v_match
    GROUP BY player
)
SELECT
    n.vote_rank,
    n.player,
    coalesce(ko.ko_matches, 0)::INT                     AS big_stage_ko_matches,
    coalesce(ko.ko_ga, 0)::INT                          AS big_stage_ko_ga,
    rank() OVER (ORDER BY coalesce(ko.ko_ga, 0) DESC)   AS ko_ga_rank,
    round(s.season_rating, 2)                           AS season_rating,
    round(ko.ko_rating, 2)                              AS ko_rating,
    round(ko.ko_rating - s.season_rating, 2)            AS rating_uplift
FROM v_nominee n
LEFT JOIN ko     ON ko.player = n.player
LEFT JOIN season s ON s.player = n.player
ORDER BY n.vote_rank;
