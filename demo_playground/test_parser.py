import pandas as pd
from demoparser2 import DemoParser
import sys
import os

def analyze_demo(demo_path):
    print(f"====================================")
    print(f"🎮 Rozpoczynam analizę dema: {demo_path}")
    print(f"====================================\n")
    
    if not os.path.exists(demo_path):
        print(f"❌ Nie znaleziono pliku: {demo_path}")
        print("Pamiętaj, by pobrać demo z Faceita (.dem.gz), ROZPAKOWAĆ je (np. WinRarem)")
        print("i wrzucić tutaj jako 'test.dem'.")
        return

    # Inicjalizujemy najszybszy dostępny na rynku parser CS2 (napisany w Rust, używany przez HLTV)
    parser = DemoParser(demo_path)
    
    # ---------------------------------------------------------
    # 1. POBIERAMY ZABÓJSTWA ('player_death')
    # Każdy ważny moment w CS2 to tzw. event (wydarzenie).
    # Parser pozwala nam wyciągnąć wszystkie eventy zabójstwa z całego meczu
    # i zamienia je w potężną tabelę Pandas (DataFrame).
    # ---------------------------------------------------------
    print("⏳ Wyciągam z pliku wszystkie zabójstwa...")
    events_df = parser.parse_events("player_death")
    
    total_kills = len(events_df)
    print(f"✅ Znaleziono łącznie zabójstw w tym meczu: {total_kills}\n")
    
    # ---------------------------------------------------------
    # 2. JAKIE DANE MA PARSER Z POJEDYNCZEGO ZABÓJSTWA?
    # Wypiszmy, co dokładnie znajdziemy o PIERWSZYM zabójstwie w meczu.
    # ---------------------------------------------------------
    if total_kills > 0:
        first_kill = events_df.iloc[0] # Pierwszy wiersz
        print("🔍 Co znajduje się w pojedynczym zapisie zabójstwa z dema (event 'player_death'):")
        
        # Pokażmy tylko najważniejsze kolumny żeby na start nie było śmietnika
        columns_to_show = [
            'attacker_name', 'user_name', 'weapon', 
            'headshot', 'assistedflash', 'attacker_health', 'attacker_armor'
        ]
        
        for col in columns_to_show:
            if col in events_df.columns:
                print(f"  - {col}: {first_kill[col]}")
            
    print("\n------------------------------------")
    print("Widzisz? Demko to nic innego, jak ogromna log-tabela.")
    print("Teraz wyobraź sobie, że piszemy kod, który np. liczy ile razy:")
    print("`attacker_name` zabił kogoś mając `assistedflash` == True.")
    print("W ten sposób wyciągniemy statystyki do bazy danych ClutchData!")

if __name__ == "__main__":
    analyze_demo("test.dem")
