import os
import pandas as pd
import numpy as np
from demoparser2 import DemoParser
from typing import Dict, Tuple, Optional


def parse_demo_to_dataframes(demo_path: str, match_id: int = 1) -> Dict[str, pd.DataFrame]:
    """
    Parsuje plik demo (.dem) CS2 za pomocą biblioteki demoparser2
    i zwraca trzy DataFrame'y dopasowane do modeli bazy danych:
    1. df_match_rounds (MatchRound)
    2. df_player_round_stats (PlayerRoundStatistic)
    3. df_match_stats (MatchStatistic)
    """
    parser = DemoParser(demo_path)

    # 1. Określenie momentu rozpoczęcia właściwego meczu (pominięcie rozgrzewki / knife round)
    begin_matches = parser.parse_event('begin_new_match')
    match_start_tick = int(begin_matches['tick'].iloc[-1]) if not begin_matches.empty else 0

    # 2. Pobranie zakończeń rund
    round_ends = parser.parse_event('round_end', other=['total_rounds_played', 'is_warmup_period'])
    round_ends = round_ends[(round_ends['tick'] > match_start_tick) & (round_ends['winner'].notna())].reset_index(drop=True)
    round_ends['round_number'] = range(1, len(round_ends) + 1)

    # 3. Pobranie końców freeze time (początek poruszania się w rundzie)
    freeze_ends = parser.parse_event('round_freeze_end')
    freeze_ends = freeze_ends[freeze_ends['tick'] >= match_start_tick].reset_index(drop=True)

    # 4. Pobranie wszystkich kluczowych zdarzeń w trakcie meczu
    deaths = parser.parse_event('player_death', player=['team_name'], other=['total_rounds_played', 'is_warmup_period'])
    deaths = deaths[deaths['tick'] >= match_start_tick].sort_values('tick').reset_index(drop=True)

    hurt = parser.parse_event('player_hurt', player=['team_name'], other=['total_rounds_played', 'is_warmup_period'])
    hurt = hurt[hurt['tick'] >= match_start_tick].sort_values('tick').reset_index(drop=True)

    blind = parser.parse_event('player_blind', player=['team_name'], other=['total_rounds_played', 'is_warmup_period'])
    blind = blind[blind['tick'] >= match_start_tick].sort_values('tick').reset_index(drop=True)

    spawns = parser.parse_event('player_spawn', player=['team_name'], other=['total_rounds_played', 'is_warmup_period'])
    spawns = spawns.sort_values('tick').reset_index(drop=True)

    # Bronie klasyfikowane jako granaty / utility
    utl_weapons = {'hegrenade', 'inferno', 'molotov', 'incgrenade', 'flashbang', 'smokegrenade', 'decoy'}
    trade_window_ticks = 320  # ~5.0 sekund przy 64 tick (okno na trade kill)

    rounds_data = []
    player_round_stats_data = []

    # Słownik graczy: steam_id -> nick
    player_names = {}
    for _, sp in spawns.iterrows():
        sid = str(sp.get('user_steamid', ''))
        if sid and sid != '0':
            player_names[sid] = str(sp.get('user_name', sid))

    # =========================================================================
    # GŁÓWNA PĘTLA PO RUNDACH
    # =========================================================================
    for i, r_end in round_ends.iterrows():
        r_num = int(r_end['round_number'])
        end_tick = int(r_end['tick'])
        winning_side = str(r_end['winner'])
        win_reason = str(r_end['reason'])

        # Znalezienie startu rundy (freeze_end przed zakończeniem rundy)
        fe_cand = freeze_ends[freeze_ends['tick'] < end_tick]
        if not fe_cand.empty:
            start_tick = int(fe_cand['tick'].iloc[-1])
        else:
            start_tick = int(round_ends.iloc[i-1]['tick']) if i > 0 else match_start_tick

        duration_sec = round((end_tick - start_tick) / 64.0, 2)

        # 1. Rekord do MatchRound
        rounds_data.append({
            'match_id': match_id,
            'round_number': r_num,
            'winning_side': winning_side,
            'win_reason': win_reason,
            'duration_seconds': duration_sec,
            'start_tick': start_tick,
            'end_tick': end_tick
        })

        # 2. Ustalenie składów drużyn w tej rundzie ze spawnu
        r_spawns = spawns[spawns['tick'] <= start_tick + 64].groupby('user_steamid').last().reset_index()
        
        round_players = {}  # steamid -> {'name': name, 'side': 'CT' lub 'T'}
        for _, sp in r_spawns.iterrows():
            sid = str(sp['user_steamid'])
            if not sid or sid == '0':
                continue
            raw_team = str(sp.get('user_team_name', ''))
            team = 'CT' if raw_team == 'CT' else 'T'
            pname = str(sp.get('user_name', sid))
            player_names[sid] = pname
            round_players[sid] = {
                'name': pname,
                'side': team
            }

        # Wycinki zdarzeń dla tej konkretnej rundy
        r_deaths = deaths[(deaths['tick'] >= start_tick) & (deaths['tick'] <= end_tick)].sort_values('tick').reset_index(drop=True)
        r_hurt = hurt[(hurt['tick'] >= start_tick) & (hurt['tick'] <= end_tick)].sort_values('tick').reset_index(drop=True)
        r_blind = blind[(blind['tick'] >= start_tick) & (blind['tick'] <= end_tick)].sort_values('tick').reset_index(drop=True)

        # Inicjalizacja statystyk dla każdego gracza w rundzie
        r_stats = {
            sid: {
                'match_id': match_id,
                'round_number': r_num,
                'player_id': sid,  # steamid (można zmapować na ID z bazy)
                'steam_id': sid,
                'player_name': pinfo['name'],
                'side_played': pinfo['side'],
                'kills': 0,
                'assists': 0,
                'deaths': 0,
                'damage_dealt': 0.0,
                'utility_damage': 0.0,
                'enemies_flashed': 0,
                'trade_kills': 0,
                'was_entry_attempt': False,
                'was_entry_success': False,
                'clutch_scenario': None,
                'clutch_won': False,
                'clutchdata_rating_impact': 0.0
            }
            for sid, pinfo in round_players.items()
        }

        # --- A. OBLICZANIE OBRAŻEŃ (Damage & Utility Damage) ---
        victim_health = {sid: 100.0 for sid in round_players.keys()}
        for _, h in r_hurt.iterrows():
            att_id = str(h.get('attacker_steamid', ''))
            vic_id = str(h.get('user_steamid', ''))
            dmg = float(h.get('dmg_health', 0))
            weap = str(h.get('weapon', ''))
            att_team = str(h.get('attacker_team_name', ''))
            vic_team = str(h.get('user_team_name', ''))

            # Pomijamy friendly-fire oraz samouszkodzenia
            if att_team == vic_team or not att_id or att_id == '0' or att_id == vic_id:
                continue

            cur_hp = victim_health.get(vic_id, 100.0)
            eff_dmg = min(dmg, float(cur_hp))
            victim_health[vic_id] = max(0.0, cur_hp - eff_dmg)

            if att_id in r_stats:
                r_stats[att_id]['damage_dealt'] += eff_dmg
                if weap in utl_weapons:
                    r_stats[att_id]['utility_damage'] += eff_dmg

        # --- B. OŚLEPIENI PRZECIWNICY (Enemies Flashed) ---
        for _, b in r_blind.iterrows():
            att_id = str(b.get('attacker_steamid', ''))
            vic_id = str(b.get('user_steamid', ''))
            att_team = str(b.get('attacker_team_name', ''))
            vic_team = str(b.get('user_team_name', ''))
            b_dur = float(b.get('blind_duration', 0.0))

            if att_team != vic_team and att_id != vic_id and b_dur > 0 and att_id in r_stats:
                r_stats[att_id]['enemies_flashed'] += 1

        # --- C. ZABÓJSTWA, ASYSTY, ENTRY, TRADES I CLUTCHE ---
        alive_ct = set([s for s, p in round_players.items() if p['side'] == 'CT'])
        alive_t = set([s for s, p in round_players.items() if p['side'] == 'T'])

        opening_kill_found = False
        clutches_in_round = {}  # steamid -> {'side': side, 'scenario': '1vX'}

        for idx2, d in r_deaths.iterrows():
            att_id = str(d.get('attacker_steamid', ''))
            vic_id = str(d.get('user_steamid', ''))
            ass_id = str(d.get('assister_steamid', ''))
            att_team = str(d.get('attacker_team_name', ''))
            vic_team = str(d.get('user_team_name', ''))
            tick2 = int(d['tick'])

            # Zgon ofiary
            if vic_id in r_stats:
                r_stats[vic_id]['deaths'] = 1

            # Prawidłowe zabójstwo przeciwnika
            if att_team != vic_team and att_id and att_id != '0' and att_id != vic_id:
                if att_id in r_stats:
                    r_stats[att_id]['kills'] += 1

                # Asysta
                if ass_id and ass_id != '0' and ass_id in r_stats:
                    r_stats[ass_id]['assists'] += 1

                # 1. ENTRY KILL (Opening duel) - pierwsze zabójstwo w rundzie
                if not opening_kill_found:
                    opening_kill_found = True
                    if att_id in r_stats:
                        r_stats[att_id]['was_entry_attempt'] = True
                        r_stats[att_id]['was_entry_success'] = True
                    if vic_id in r_stats:
                        r_stats[vic_id]['was_entry_attempt'] = True
                        r_stats[vic_id]['was_entry_success'] = False

                # 2. TRADE KILL - zabójstwo przeciwnika, który zabił sojusznika w oknie trade_window
                for idx1 in range(idx2 - 1, -1, -1):
                    d1 = r_deaths.iloc[idx1]
                    tick1 = int(d1['tick'])
                    if tick2 - tick1 > trade_window_ticks:
                        break
                    killer1 = str(d1.get('attacker_steamid', ''))
                    victim1 = str(d1.get('user_steamid', ''))
                    team1 = str(d1.get('attacker_team_name', ''))

                    # Warunek trade kill:
                    # vic_id (nasz obecny cel) był killerem w poprzednim zabójstwie (killer1),
                    # a jego ofiarą (victim1) był nasz teammate (team1 != att_team)
                    if vic_id == killer1 and att_team != team1 and att_id != victim1:
                        if att_id in r_stats:
                            r_stats[att_id]['trade_kills'] += 1
                        break

            # Usunięcie zabitego ze zbioru żywych
            alive_ct.discard(vic_id)
            alive_t.discard(vic_id)

            # 3. WYKRYWANIE SYTUACJI CLUTCH (1vsX)
            # Sprawdzenie czy po tym zgonie CT został sam przeciwko X terrorystom
            if len(alive_ct) == 1 and len(alive_t) >= 1:
                ct_sole = list(alive_ct)[0]
                if ct_sole not in clutches_in_round:
                    clutches_in_round[ct_sole] = {
                        'side': 'CT',
                        'scenario': f'1v{len(alive_t)}',
                        'enemies': len(alive_t)
                    }

            # Sprawdzenie czy po tym zgonie T został sam przeciwko X antyterrorystom
            if len(alive_t) == 1 and len(alive_ct) >= 1:
                t_sole = list(alive_t)[0]
                if t_sole not in clutches_in_round:
                    clutches_in_round[t_sole] = {
                        'side': 'T',
                        'scenario': f'1v{len(alive_ct)}',
                        'enemies': len(alive_ct)
                    }

        # Przypisanie clutchy do statystyk rundowych
        for sid, cinfo in clutches_in_round.items():
            if sid in r_stats:
                r_stats[sid]['clutch_scenario'] = cinfo['scenario']
                r_stats[sid]['clutch_won'] = (cinfo['side'] == winning_side)

        # Obliczenie wpływu na rating w rundzie (clutchdata_rating_impact)
        for sid, pst in r_stats.items():
            impact = (
                (pst['kills'] * 0.45) +
                (pst['assists'] * 0.15) +
                (pst['trade_kills'] * 0.20) +
                (0.35 if pst['was_entry_success'] else (0.0 if not pst['was_entry_attempt'] else -0.15)) +
                (pst['damage_dealt'] / 200.0) +
                (1.0 if pst['clutch_won'] else 0.0) -
                (pst['deaths'] * 0.25)
            )
            pst['clutchdata_rating_impact'] = round(impact, 3)
            pst['damage_dealt'] = round(pst['damage_dealt'], 1)
            pst['utility_damage'] = round(pst['utility_damage'], 1)
            player_round_stats_data.append(pst)

    df_match_rounds = pd.DataFrame(rounds_data)
    df_player_round_stats = pd.DataFrame(player_round_stats_data)

    # =========================================================================
    # PODSUMOWANIE MECZU: MatchStatistic
    # =========================================================================
    # Zliczenie flash assists (zabójstwa, gdzie asystujący rzucił flasha)
    match_flash_assists = deaths[
        (deaths['assistedflash'] == True) & 
        (deaths['attacker_team_name'] != deaths['user_team_name'])
    ]
    fa_counts = match_flash_assists['assister_steamid'].astype(str).value_counts().to_dict()

    total_match_rounds = max(1, len(df_match_rounds))
    match_stats_data = []

    for sid, group in df_player_round_stats.groupby('steam_id'):
        pname = player_names.get(sid, sid)

        tot_k = int(group['kills'].sum())
        tot_d = int(group['deaths'].sum())
        tot_a = int(group['assists'].sum())
        tot_dmg = float(group['damage_dealt'].sum())
        tot_utl_dmg = float(group['utility_damage'].sum())
        tot_flashed = int(group['enemies_flashed'].sum())
        tot_trades = int(group['trade_kills'].sum())
        tot_fa = int(fa_counts.get(sid, 0))

        entry_att = int(group['was_entry_attempt'].sum())
        entry_succ = int(group['was_entry_success'].sum())

        # Rozbicie clutchy 1v1 - 1v5 (próby i wygrane)
        c_1v1_att = int(len(group[group['clutch_scenario'] == '1v1']))
        c_1v1_win = int(len(group[(group['clutch_scenario'] == '1v1') & (group['clutch_won'] == True)]))
        
        c_1v2_att = int(len(group[group['clutch_scenario'] == '1v2']))
        c_1v2_win = int(len(group[(group['clutch_scenario'] == '1v2') & (group['clutch_won'] == True)]))
        
        c_1v3_att = int(len(group[group['clutch_scenario'] == '1v3']))
        c_1v3_win = int(len(group[(group['clutch_scenario'] == '1v3') & (group['clutch_won'] == True)]))
        
        c_1v4_att = int(len(group[group['clutch_scenario'] == '1v4']))
        c_1v4_win = int(len(group[(group['clutch_scenario'] == '1v4') & (group['clutch_won'] == True)]))
        
        c_1v5_att = int(len(group[group['clutch_scenario'] == '1v5']))
        c_1v5_win = int(len(group[(group['clutch_scenario'] == '1v5') & (group['clutch_won'] == True)]))

        # Obliczenie ClutchRating / clutchdata_rating (formuła oparta na HLTV 2.0 / Impact / ADR)
        kpr = tot_k / total_match_rounds
        dpr = tot_d / total_match_rounds
        adr = tot_dmg / total_match_rounds
        apr = tot_a / total_match_rounds
        entry_rate = entry_succ / total_match_rounds

        impact_rating = (2.13 * kpr) + (0.42 * apr) + (0.40 * entry_rate) - 0.41
        clutch_rating = round((0.0073 * adr) + (0.3591 * kpr) - (0.5329 * dpr) + (0.2372 * impact_rating) + 0.37, 2)

        match_stats_data.append({
            'match_id': match_id,
            'player_id': sid,  # steamid do połączenia z tabelą players
            'player_name': pname,
            'steam_id': sid,
            'elo_history_id': None,
            'clutchdata_rating': clutch_rating,
            'entry_attempts': entry_att,
            'entry_success': entry_succ,
            'clutch_1v1_attempts': c_1v1_att,
            'clutch_1v2_attempts': c_1v2_att,
            'clutch_1v3_attempts': c_1v3_att,
            'clutch_1v4_attempts': c_1v4_att,
            'clutch_1v5_attempts': c_1v5_att,
            'clutch_1v1_wins': c_1v1_win,
            'clutch_1v2_wins': c_1v2_win,
            'clutch_1v3_wins': c_1v3_win,
            'clutch_1v4_wins': c_1v4_win,
            'clutch_1v5_wins': c_1v5_win,
            'trade_kills': tot_trades,
            'utility_damage': int(round(tot_utl_dmg)),
            'enemies_flashed': tot_flashed,
            'flash_assists': tot_fa,
            'total_damage' : tot_dmg,
            'kills': tot_k,
            'deaths': tot_d,
            'assists': tot_a,
            'adr': round(adr, 1)
        })

    df_match_stats = pd.DataFrame(match_stats_data).sort_values('clutchdata_rating', ascending=False).reset_index(drop=True)

    return {
        'match_rounds': df_match_rounds,
        'player_round_statistics': df_player_round_stats,
        'match_statistics': df_match_stats
    }



if __name__ == "__main__":
    demo_file = "replay.dem"
    if os.path.exists(demo_file):
        result = parse_demo_to_dataframes(demo_file, match_id=1)
        df_match_rounds = result['match_rounds']
        df_player_round_stats = result['player_round_statistics']
        df_match_stats = result['match_statistics']
