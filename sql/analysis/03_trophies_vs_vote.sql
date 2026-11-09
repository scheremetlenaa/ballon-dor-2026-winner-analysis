-- Q3. Did trophies decide the vote?
-- Trophies, weighted trophy score and how far the player got in the two big tournaments.
WITH stage AS (
    SELECT p.PlayerName AS player,
           max(CASE WHEN c.CompetitionName = 'UEFA Champions League' THEN pc.StageReached END) AS ucl_stage,
           max(CASE WHEN c.CompetitionName = 'FIFA World Cup'        THEN pc.StageReached END) AS world_cup_stage
    FROM FactPlayerCompetition pc
    JOIN DimPlayer      p ON p.PlayerID      = pc.PlayerID
    JOIN DimCompetition c ON c.CompetitionID = pc.CompetitionID
    GROUP BY p.PlayerName
)
SELECT
    n.vote_rank,
    n.player,
    n.trophies_won,
    n.major_trophies,
    n.trophy_score,
    rank() OVER (ORDER BY n.trophy_score DESC) AS trophy_rank,
    s.ucl_stage,
    s.world_cup_stage
FROM v_nominee n
LEFT JOIN stage s ON s.player = n.player
ORDER BY n.vote_rank;
