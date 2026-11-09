-- Q7. How close was the vote?
-- Points, share of the top-10 points and the gap to the next player.
SELECT
    vote_rank,
    player,
    points,
    round(100.0 * points / sum(points) OVER (), 1)          AS share_of_top10_pct,
    points - lead(points) OVER (ORDER BY vote_rank)         AS lead_over_next,
    round(100.0 * (points - lead(points) OVER (ORDER BY vote_rank))
          / lead(points) OVER (ORDER BY vote_rank), 1)      AS lead_over_next_pct
FROM v_nominee
ORDER BY vote_rank;
