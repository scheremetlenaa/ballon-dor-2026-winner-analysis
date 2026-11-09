"""Load the ETL workbook into a DuckDB warehouse and run the SQL in sql/."""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
WORKBOOK = ROOT / "data" / "processed" / "BallonDor_Data.xlsx"
DATABASE = ROOT / "data" / "processed" / "ballondor.duckdb"
SQL_DIR = ROOT / "sql"

TABLES = [
    "DimPlayer", "DimTeam", "DimCompetition", "DimSeason",
    "FactPlayerMatch", "FactPlayerSeason", "FactVoting", "FactPlayerCompetition", "IndexWeights",
]


def connect(workbook: Path = WORKBOOK, database: Path | str = ":memory:") -> duckdb.DuckDBPyConnection:
    """Open DuckDB, load every model table from the workbook and create the views in sql/views/."""
    con = duckdb.connect(str(database))
    sheets = pd.read_excel(workbook, sheet_name=TABLES)
    for name, df in sheets.items():
        con.register("_df", df)
        con.execute(f'CREATE OR REPLACE TABLE "{name}" AS SELECT * FROM _df')
        con.unregister("_df")
    for path in sorted((SQL_DIR / "views").glob("*.sql")):
        con.execute(path.read_text(encoding="utf-8"))
    return con


def analysis_queries() -> dict[str, Path]:
    """sql/analysis/NN_name.sql keyed by NN."""
    return {p.name[:2]: p for p in sorted((SQL_DIR / "analysis").glob("*.sql"))}


def run(con: duckdb.DuckDBPyConnection, key: str) -> pd.DataFrame:
    return con.execute(analysis_queries()[key].read_text(encoding="utf-8")).df()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--query", help="number of a file in sql/analysis/, e.g. 04")
    args = parser.parse_args()
    if args.query:
        with pd.option_context("display.width", 200, "display.max_columns", 30):
            print(run(connect(), args.query).to_string(index=False))
        return
    DATABASE.unlink(missing_ok=True)
    con = connect(database=DATABASE)
    for name in TABLES:
        print(f"{name:<24}{con.execute(f'SELECT count(*) FROM {name}').fetchone()[0]:>6} rows")
    con.close()
    print(f"-> {DATABASE.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
