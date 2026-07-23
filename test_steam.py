import httpx
import asyncio

async def main():
    api_key = "30D841019E0749D532CA34472CD43290"
    steam_id = "76561198036573130" # s1mple
    url = f"http://api.steampowered.com/ISteamUserStats/GetUserStatsForGame/v0002/?appid=730&key={api_key}&steamid={steam_id}"
    
    async with httpx.AsyncClient() as client:
        res = await client.get(url)
        if res.status_code == 200:
            stats = res.json().get("playerstats", {}).get("stats", [])
            # Filter weapon stats for ak47 to see what's available
            for stat in stats:
                if "ak47" in stat["name"]:
                    print(f"{stat['name']}: {stat['value']}")
        else:
            print("Failed to fetch")

asyncio.run(main())
