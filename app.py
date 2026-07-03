import sys
import re

def parse_bet365_file(filepath):
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            raw_data = f.read()
    except FileNotFoundError:
        print(f"Error: Could not find file '{filepath}'")
        sys.exit(1)

    if "<html" in raw_data.lower() or "cloudflare" in raw_data.lower():
        print("ERROR: It looks like you saved the Cloudflare 'Blocked' HTML page instead of the Bet365 data!")
        print("Please copy the data from the 'Response' tab in your browser's Developer Tools as explained earlier.")
        sys.exit(1)

    # 1. Extract all players and map their ID to their Name
    player_map = {}
    
    # Sometimes ID has 'PC' prefix, sometimes it doesn't.
    player_matches = re.finditer(r'\|PA;ID=(?:PC)?(\d+);NA=([^;]+);', raw_data)
    for match in player_matches:
        player_id = match.group(1)
        player_name = match.group(2)
        # Avoid overriding real names with empty/dummy names if they appear later
        if player_id not in player_map or player_name != " ":
            player_map[player_id] = player_name
            
    if not player_map:
        print("DEBUG: Could not find any player definitions in the file.")
        print("Make sure the text contains the '|PA;ID=...' format.")
        sys.exit(1)
        
    # 2. Split the text by '|CO;' to separate the lines (1+, 2+, 3+, etc.)
    columns = raw_data.split('|CO;')
    if len(columns) <= 1:
        print("DEBUG: Could not find any columns/lines (like 1+, 2+) in the file.")
        print("Make sure the text contains the '|CO;...NA=1+;' format.")
        sys.exit(1)

    results = {}
    all_lines = []

    for col in columns[1:]:
        parts = col.split('|')
        
        co_header = parts[0]
        line_match = re.search(r'NA=([^;]+);', co_header)
        if not line_match:
            continue
        line = line_match.group(1)
        if line not in all_lines:
            all_lines.append(line)
        
        for part in parts[1:]:
            if part.startswith('PA;'):
                p_id_match = re.search(r'ID=(?:PC)?(\d+);', part)
                odds_match = re.search(r'OD=([^;]+);', part)
                
                if p_id_match and odds_match:
                    p_id = p_id_match.group(1)
                    odds = odds_match.group(1)
                    
                    if p_id in player_map:
                        player_name = player_map[p_id]
                        if player_name not in results:
                            results[player_name] = {}
                        results[player_name][line] = odds

    return results, all_lines

def print_table(parsed_data, all_lines):
    if not parsed_data:
        print("No player odds found in the file.")
        return

    header = f"{'Player Name':<25}"
    for line in all_lines:
        header += f" | {line + ' Tackles':<12}"
    
    print(header)
    print("-" * len(header))
    
    for player, lines in parsed_data.items():
        row = f"{player:<25}"
        for line in all_lines:
            odds = lines.get(line, 'N/A')
            row += f" | {odds:<12}"
        print(row)

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python app.py <data_file.txt>")
        sys.exit(1)
        
    filepath = sys.argv[1]
    parsed_data, all_lines = parse_bet365_file(filepath)
    print_table(parsed_data, all_lines)
