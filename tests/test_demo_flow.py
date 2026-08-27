import json
import asyncio
import pandas as pd
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool
from app.db.session import Base
from app.db.crud import save_analyzed_demo_data, get_full_analyzed_match_data, is_match_analyzed

def test_demo_save_and_retrieve():
    async def _test():
        test_engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
        )
        TestSession = sessionmaker(bind=test_engine, class_=AsyncSession, expire_on_commit=False)

        async with test_engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)

        async with TestSession() as db:
            test_match_id = "test-match-12345"
            
            # Prepare sample dataframes mimicking Demo_parser output
            df_rounds = pd.DataFrame([{
                'match_id': 1,
                'round_number': 1,
                'winning_side': 'CT',
                'win_reason': 'ct_win_elimination',
                'duration_seconds': 55.4,
                'start_tick': 100,
                'end_tick': 3600
            }])

            df_player_round_stats = pd.DataFrame([{
                'match_id': 1,
                'round_number': 1,
                'player_id': '76561198000000001',
                'steam_id': '76561198000000001',
                'player_name': 'TestPlayer',
                'side_played': 'CT',
                'kills': 2,
                'assists': 1,
                'deaths': 0,
                'damage_dealt': 185.0,
                'utility_damage': 45.0,
                'enemies_flashed': 2,
                'trade_kills': 1,
                'was_entry_attempt': True,
                'was_entry_success': True,
                'clutch_scenario': '1v2',
                'clutch_won': True,
                'clutchdata_rating_impact': 1.85
            }])

            df_match_stats = pd.DataFrame([{
                'match_id': 1,
                'player_id': '76561198000000001',
                'player_name': 'TestPlayer',
                'steam_id': '76561198000000001',
                'elo_history_id': None,
                'clutchdata_rating': 1.45,
                'entry_attempts': 5,
                'entry_success': 4,
                'clutch_1v1_attempts': 1,
                'clutch_1v2_attempts': 1,
                'clutch_1v3_attempts': 0,
                'clutch_1v4_attempts': 0,
                'clutch_1v5_attempts': 0,
                'clutch_1v1_wins': 1,
                'clutch_1v2_wins': 1,
                'clutch_1v3_wins': 0,
                'clutch_1v4_wins': 0,
                'clutch_1v5_wins': 0,
                'trade_kills': 3,
                'utility_damage': 120,
                'enemies_flashed': 6,
                'flash_assists': 2,
                'total_damage': 2450.0,
                'kills': 24,
                'deaths': 12,
                'assists': 6,
                'adr': 98.5
            }])

            parsed_data = {
                'match_rounds': df_rounds,
                'player_round_statistics': df_player_round_stats,
                'match_statistics': df_match_stats
            }

            match_info = {
                "voting": {"map": {"pick": ["de_mirage"]}},
                "started_at": 1710000000,
                "finished_at": 1710002400
            }

            # 1. Save data
            saved_match = await save_analyzed_demo_data(db, test_match_id, match_info, parsed_data)
            assert saved_match is not None
            assert saved_match.is_analyzed is True

            # 2. Check is_match_analyzed
            analyzed = await is_match_analyzed(db, test_match_id)
            assert analyzed is True

            # 3. Retrieve full analyzed match data
            data = await get_full_analyzed_match_data(db, test_match_id)
            assert data is not None
            assert len(data['player_stats']) == 1
            p_stat = data['player_stats'][0]
            assert p_stat['persona_name'] == 'TestPlayer'
            assert p_stat['clutchdata_rating'] == 1.45
            assert p_stat['kills'] == 24
            assert p_stat['clutches_won'] == 2
            assert len(data['rounds']) == 1
            # 4. Verify JSON serializability
            serialized = json.dumps(data)
            assert serialized is not None
            assert "TestPlayer" in serialized

            # 5. Verify enrich_analyzed_teams
            from app.services.demo_service import enrich_analyzed_teams
            match_info_with_captains = {
                "voting": {"map": {"pick": ["de_mirage"]}},
                "started_at": 1710000000,
                "finished_at": 1710002400,
                "teams": {
                    "faction1": {
                        "name": "Team Alpha",
                        "leader": "p1_faceit_id",
                        "avatar": "https://example.com/team1_fallback.png",
                        "roster": [
                            {
                                "player_id": "p1_faceit_id",
                                "nickname": "CaptainAlpha",
                                "avatar": "https://example.com/cap1.jpg",
                                "game_player_id": "76561198000000001",
                                "game_player_name": "TestPlayer"
                            }
                        ]
                    },
                    "faction2": {
                        "name": "Team Beta",
                        "leader": "p2_faceit_id",
                        "avatar": "",
                        "roster": [
                            {
                                "player_id": "p2_faceit_id",
                                "nickname": "CaptainBeta",
                                "avatar": "https://example.com/cap2.jpg",
                                "game_player_id": "76561198000000002",
                                "game_player_name": "Player2"
                            }
                        ]
                    }
                }
            }
            enriched = enrich_analyzed_teams(data, match_info_with_captains)
            assert "teams" in enriched
            assert len(enriched["teams"]) == 2
            assert enriched["teams"][0]["team_name"] == "Team Alpha"
            assert enriched["teams"][0]["captain_name"] == "CaptainAlpha"
            assert enriched["teams"][0]["captain_avatar"] == "https://example.com/cap1.jpg"
            assert enriched["teams"][0]["captain_id"] == "p1_faceit_id"
            assert enriched["teams"][0]["players"][0]["persona_name"] == "TestPlayer"
            assert enriched["teams"][0]["players"][0]["avatar"] == "https://example.com/cap1.jpg"
            assert enriched["teams"][0]["players"][0]["c_1v1_wins"] == 1
            assert enriched["teams"][0]["players"][0]["c_1v2_wins"] == 1

            assert enriched["teams"][1]["team_name"] == "Team Beta"
            assert enriched["teams"][1]["captain_name"] == "CaptainBeta"
            assert enriched["teams"][1]["captain_avatar"] == "https://example.com/cap2.jpg"

            # 6. Verify match.html template rendering with captain avatar
            from jinja2 import Environment, FileSystemLoader, select_autoescape
            env = Environment(loader=FileSystemLoader('app/templates'), autoescape=select_autoescape(['html']))
            t = env.get_template('match.html')
            rendered = t.render(
                request=type('R', (), {'session': {'logged_steam_id': '76561198000000001'}})(),
                logged_player_summary={'personaname': 'TestPlayer', 'avatar': ''},
                steam_id='76561198000000001',
                player_summary={'personaname': 'TestPlayer', 'avatar': ''},
                match_id=test_match_id,
                match_info=match_info_with_captains,
                match_stats={'rounds': [{'round_stats': {'Map': 'de_mirage', 'Score': '13 - 10'}}]},
                avatars={'p1_faceit_id': 'https://example.com/cap1.jpg'},
                clutchdata_plus=True,
                is_analyzed=True,
                analysis_data=enriched,
                has_demo=True
            )
            assert "https://example.com/cap1.jpg" in rendered
            assert "CaptainAlpha" in rendered
            assert "Team Alpha" in rendered

    asyncio.run(_test())

