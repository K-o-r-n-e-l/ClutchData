import httpx
import asyncio

async def main():
    headers = {"Authorization": "Bearer d04481b6-e532-4e99-8aef-c99427d7b5e1"}
    async with httpx.AsyncClient() as client:
        # Get ropz player ID
        url = "https://open.faceit.com/data/v4/players?nickname=ropz"
        res = await client.get(url, headers=headers)
        if res.status_code == 200:
            player_id = res.json()["player_id"]
            stats_url = f"https://open.faceit.com/data/v4/players/{player_id}/stats/cs2"
            stats_res = await client.get(stats_url, headers=headers)
            if stats_res.status_code == 200:
                data = stats_res.json()
                segments = data.get("segments", [])
                for seg in segments:
                    if seg.get("type") == "Map":
                        print("Map Segment keys:", seg.get("stats").keys())
                        for k, v in seg.get("stats").items():
                            print(f"{k}: {v}")
                        break

asyncio.run(main())
