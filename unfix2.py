import sys

def fix_last_indent():
    with open("server.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if "async def _scrape_stats_from_dom" in line:
            start_idx = i
            break
            
    if start_idx == -1:
        print("Could not find start")
        return
        
    end_idx = -1
    for i in range(start_idx, len(lines)):
        if "# Global browser instance" in lines[i]:
            end_idx = i
            break
            
    if end_idx == -1:
        print("Could not find end")
        return
        
    # Unindent everything from start_idx to end_idx - 1 by 4 spaces
    for i in range(start_idx, end_idx):
        if lines[i].startswith("    "):
            lines[i] = lines[i][4:]
            
    with open("server.py", "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"Fixed lines {start_idx} to {end_idx - 1}")

if __name__ == "__main__":
    fix_last_indent()
