import sqlite3
import json
from datetime import datetime, timedelta

from fastapi import FastAPI, HTTPException
from nba_api.stats.static import players
from nba_api.stats.endpoints import playercareerstats

app = FastAPI()

from fastapi.middleware.cors import CORSMiddleware

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
        "SELECT data, fetched_at FROM player_cache WHERE player_name = ?", (name,)
    ).fetchone()
    conn.close()
    if row is None:
        return None
    data, fetched_at = row
    if datetime.fromisoformat(fetched_at) < datetime.now() - timedelta(hours=24):
        return None  # stale, treat as not cached
    return json.loads(data)


def save_cache(name, data):
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        "INSERT OR REPLACE INTO player_cache (player_name, data, fetched_at) VALUES (?, ?, ?)",
        (name, json.dumps(data), datetime.now().isoformat())
    )
    conn.commit()
    conn.close()


def find_player(name):
    matches = players.find_players_by_full_name(name)
    return matches[0] if matches else None


@app.get("/player/{name}")
def get_player_stats(name: str):
    cached = get_cached(name)
    if cached is not None:
        return {**cached, "source": "cache"}

    player = find_player(name)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player '{name}' not found")

    career = playercareerstats.PlayerCareerStats(player_id=player["id"], timeout=60)
    df = career.get_data_frames()[0]
    stats = df[["SEASON_ID", "TEAM_ABBREVIATION", "GP", "PTS", "REB", "AST"]].tail(5)

    result = {
        "player": player["full_name"],
        "seasons": stats.to_dict(orient="records")
    }
    save_cache(name, result)
    return {**result, "source": "api"}