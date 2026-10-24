import sqlite3
import json
from datetime import datetime, timedelta

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from nba_api.stats.static import players
from nba_api.stats.endpoints import playercareerstats

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # fine for local dev, tighten later for production
    allow_methods=["*"],
    allow_headers=["*"],
)

DB_PATH = "cache.db"


def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS player_cache (
            player_name TEXT PRIMARY KEY,
            data TEXT,
            fetched_at TEXT
        )
    """)
    conn.commit()
    conn.close()


init_db()


def get_cached(name):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute(
        "SELECT data, fetched_at FROM player_cache WHERE player_name = ?", (name.lower(),)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    data, fetched_at = row
    if datetime.fromisoformat(fetched_at) < datetime.now() - timedelta(hours=24):
        return None  # stale
    return json.loads(data)


def save_cache(name, data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO player_cache (player_name, data, fetched_at) VALUES (?, ?, ?)",
        (name.lower(), json.dumps(data), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def find_player(name):
    matches = players.find_players_by_full_name(name)
    return matches[0] if matches else None


STAT_COLUMNS = [
    "SEASON_ID", "TEAM_ABBREVIATION", "GP",
    "PTS", "REB", "AST", "STL", "BLK",
    "FGA", "FTA",
    "FG_PCT", "FG3_PCT", "FT_PCT"
]


def compute_stats(row):
    """Turn one raw season row (totals) into per-game averages + shooting %."""
    gp = row["GP"] if row["GP"] else 1  # avoid divide-by-zero

    def pct(value):
        return round(value * 100, 1) if value is not None else None

    pts = row["PTS"] or 0
    fga = row["FGA"] or 0
    fta = row["FTA"] or 0
    ts_denominator = 2 * (fga + 0.44 * fta)
    ts_pct = round((pts / ts_denominator) * 100, 1) if ts_denominator > 0 else None

    return {
        "season": row["SEASON_ID"],
        "team": row["TEAM_ABBREVIATION"],
        "games_played": int(row["GP"]),
        "ppg": round(pts / gp, 1),
        "rpg": round((row["REB"] or 0) / gp, 1),
        "apg": round((row["AST"] or 0) / gp, 1),
        "spg": round((row["STL"] or 0) / gp, 1),
        "bpg": round((row["BLK"] or 0) / gp, 1),
        "fg_pct": pct(row["FG_PCT"]),
        "fg3_pct": pct(row["FG3_PCT"]),
        "ft_pct": pct(row["FT_PCT"]),
        "ts_pct": ts_pct,
    }


def get_career_data(name):
    """Returns {"player": full_name, "seasons": [raw season rows]}, from cache or API."""
    cached = get_cached(name)
    if cached is not None:
        return cached, "cache"

    player = find_player(name)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player '{name}' not found")

    career = playercareerstats.PlayerCareerStats(player_id=player["id"], timeout=60)
    df = career.get_data_frames()[0]

    if df.empty:
        raise HTTPException(
            status_code=404,
            detail=f"{player['full_name']} has no NBA regular season stats yet"
        )

    stat_df = df[STAT_COLUMNS]
    stat_df = stat_df.astype(object).where(pd.notnull(stat_df), None)  # NaN -> None (JSON-safe)

    career_data = {
        "player": player["full_name"],
        "seasons": stat_df.to_dict(orient="records")
    }
    save_cache(name, career_data)
    return career_data, "api"


@app.get("/players/search")
def search_players(q: str):
    q = q.strip().lower()
    if len(q) < 2:
        return {"results": []}

    all_players = players.get_players()
    matches = [p["full_name"] for p in all_players if q in p["full_name"].lower()]
    matches.sort(key=lambda n: (not n.lower().startswith(q), n))  # prefix matches first
    return {"results": matches[:10]}


@app.get("/player/{name}")
def get_player_stats(name: str, season: str | None = None):
    career_data, source = get_career_data(name)
    seasons = career_data["seasons"]
    available_seasons = [s["SEASON_ID"] for s in seasons]

    if season:
        row = next((s for s in seasons if s["SEASON_ID"] == season), None)
        if row is None:
            raise HTTPException(
                status_code=404,
                detail=f"No data for {career_data['player']} in {season}"
            )
    else:
        row = seasons[-1]  # most recent season

    stats = compute_stats(row)
    return {
        "player": career_data["player"],
        "available_seasons": available_seasons,
        "source": source,
        **stats
    }