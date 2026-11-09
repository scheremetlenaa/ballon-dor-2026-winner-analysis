-- One row per player × match, with names instead of keys.
CREATE OR REPLACE VIEW v_match AS
SELECT
    m.MatchID,
    CAST(m.Date AS DATE)                       AS match_date,
    p.PlayerName                               AS player,
    c.CompetitionName                          AS competition,
    c.CompetitionType                          AS competition_type,
    c.IsBigStage                               AS is_big_stage,
    m.Stage                                    AS stage,
    m.IsKnockout                               AS is_knockout,
    m.IsVsTop6                                 AS is_vs_top6,
    o.TeamName                                 AS opponent,
    m.Result                                   AS result,
    m.Minutes                                  AS minutes,
    m.Goals                                    AS goals,
    m.PenaltyGoals                             AS penalty_goals,
    m.Assists                                  AS assists,
    m.Goals - m.PenaltyGoals + m.Assists       AS np_ga,
    m.xG, m.npxG, m.xA,
    m.Rating                                   AS rating
FROM FactPlayerMatch m
JOIN DimPlayer      p ON p.PlayerID      = m.PlayerID
JOIN DimCompetition c ON c.CompetitionID = m.CompetitionID
LEFT JOIN DimTeam   o ON o.TeamID        = m.OpponentTeamID;
