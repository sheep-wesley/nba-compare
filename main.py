from fastapi import FastAPI, HTTPException
from nba_api.stats.static import players
from nba_api.stats.endpoints import playercareerstats

app = FastAPI()

def find_player(name):
    matches = players.find_players_by_full_name(name)
    return matches[0] if matches else None

@app.get("/player/{name}")
def get_player_stats(name: str):
    player = find_player(name)
    if player is None:
        raise HTTPException(status_code=404, detail=f"Player '{name}' not found")

    career = playercareerstats.PlayerCareerStats(player_id=player["id"], timeout=60)
    df = career.get_data_frames()[0]

    # Keep only relevant columns, convert to list of dicts for JSON
    stats = df[["SEASON_ID", "TEAM_ABBREVIATION", "GP", "PTS", "REB", "AST"]].tail(5)
    return {
        "player": player["full_name"],
        "seasons": stats.to_dict(orient="records")
    }