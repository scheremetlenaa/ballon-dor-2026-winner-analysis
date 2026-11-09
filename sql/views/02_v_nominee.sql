-- One row per nominee with season statistics (the top 10 of the vote).
CREATE OR REPLACE VIEW v_nominee AS
WITH trophies AS (
    SELECT PlayerID,
           count(*) FILTER (WHERE IsWinner)                          AS trophies_won,
           count(*) FILTER (WHERE IsWinner AND TrophyTier = 'Major') AS major_trophies,
           coalesce(sum(TrophyWeight) FILTER (WHERE IsWinner), 0)    AS trophy_score
    FROM FactPlayerCompetition
    GROUP BY PlayerID
)
SELECT
    p.PlayerName                                            AS player,
    p.PositionGroup                                         AS position,
    p.Nationality                                           AS nation,
    t.TeamName                                              AS club,
    v.Rank                                                  AS vote_rank,
    TRY_CAST(v.Points AS INTEGER)                           AS points,
    s.Matches                                               AS matches,
    s.Minutes                                               AS minutes,
    s.Goals                                                 AS goals,
    s.PenaltyGoals                                          AS penalty_goals,
    s.Assists                                               AS assists,
    s.Goals - s.PenaltyGoals + s.Assists                    AS np_ga,
    (s.Goals - s.PenaltyGoals + s.Assists) * 90.0 / s.Minutes AS np_ga_per90,
    s.npxGIncEst                                            AS npxg_incl_estimate,
    s.BigStageKnockoutGA                                    AS big_stage_ko_ga,
    coalesce(tr.trophies_won, 0)                            AS trophies_won,
    coalesce(tr.major_trophies, 0)                          AS major_trophies,
    coalesce(tr.trophy_score, 0)                            AS trophy_score
FROM FactPlayerSeason s
JOIN DimPlayer  p  ON p.PlayerID = s.PlayerID
JOIN FactVoting v  ON v.PlayerID = s.PlayerID AND v.SeasonID = s.SeasonID
LEFT JOIN DimTeam  t  ON t.TeamID  = s.TeamID
LEFT JOIN trophies tr ON tr.PlayerID = s.PlayerID;
