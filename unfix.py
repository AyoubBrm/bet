import sys

def unfix_server():
    with open("server.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    start_idx = -1
    for i, line in enumerate(lines):
        if "page = await context.new_page()" in line and "try:" in lines[i+1]:
            start_idx = i
            break
            
    if start_idx == -1:
        print("Could not find start")
        return
        
    # Remove the `try:` that was added
    lines.pop(start_idx + 1)
    
    end_idx = -1
    for i in range(start_idx + 1, len(lines)):
        if "return matches" in lines[i]:
            end_idx = i
            break
            
    if end_idx == -1:
        print("Could not find end")
        return
        
    # Unindent everything from start_idx + 1 to end_idx by 4 spaces
    for i in range(start_idx + 1, end_idx + 1):
        if lines[i].startswith("    "):
            lines[i] = lines[i][4:]
            
    # Find the newly added finally block and remove it
    finally_start = -1
    for i in range(end_idx + 1, len(lines)):
        if "finally:" in lines[i]:
            finally_start = i
            break
            
    if finally_start != -1:
        # The finally block was 8 lines long
        del lines[finally_start:finally_start+8]
        
    with open("server.py", "w", encoding="utf-8") as f:
        f.writelines(lines)
    print(f"Reversed lines {start_idx} to {end_idx}")

if __name__ == "__main__":
    unfix_server()
