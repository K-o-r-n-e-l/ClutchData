from jinja2 import Environment, FileSystemLoader, select_autoescape
import re

env = Environment(loader=FileSystemLoader('app/templates'), autoescape=select_autoescape(['html']))
t = env.get_template('stats.html')
result = t.render(
    request=type('R', (), {'session': {'logged_steam_id': '123'}})(),
    logged_player_summary={'personaname': 'Swagnel', 'avatar': ''},
    steam_id='76561198115572404',
    player_summary={'personaname': 'Swagnel', 'avatarfull': ''},
    faceit_data={'games': {'cs2': {'skill_level': 7, 'faceit_elo': 1388}}, 'nickname': 'K_O_R_N_E_L'},
    faceit_lifetime={'Average K/D Ratio': '1.35', 'Win Rate %': '55', 'Matches': '38', 'ADR': '90.2', 'Average Headshots %': '34', 'Average K/R Ratio': '0.88'},
    map_segments=[],
    weapon_stats=[]
)

# Check for Tailwind CDN
if 'cdn.tailwindcss.com' in result:
    print('WARNING - Tailwind CDN still included!')
else:
    print('OK - No Tailwind CDN script')

# Check for problematic Tailwind utility classes that won't resolve without JIT
tw_patterns = ['max-w-[', 'sm:block', 'md:flex', 'lg:px', 'hidden sm:', 'flex-1 justify']
found = [p for p in tw_patterns if p in result]
if found:
    print('WARNING - Tailwind patterns found:', found)
else:
    print('OK - No Tailwind utility patterns found')

print('Rendered length:', len(result))
print('Template renders OK!')
