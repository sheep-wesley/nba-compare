from nba_api.stats.static import players
from nba_api.stats.endpoints import playercareerstats

def find_player(name):
    matches = players.find_players_by_full_name(name)
    return matches[0] if matches else None

player = find_player("LeBron James")
if player is None:
    raise SystemExit("Player not found")

career = playercareerstats.PlayerCareerStats(player_id=player["id"], timeout=60)
df = career.get_data_frames()[0]  # regular season, one row per season

print(player["full_name"])
#print(df.columns) stats could be used
print(df[["SEASON_ID", "TEAM_ABBREVIATION", "GP", "PTS", "REB", "AST"]].tail(5))