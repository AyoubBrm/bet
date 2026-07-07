import sys

def fix_server():
    with open("server.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    start_idx = -1
    end_idx = -1
    for i, line in enumerate(lines):
        if "page = await context.new_page()" in line and "goto" not in line:
            start_idx = i
            break
            
    if start_idx == -1:
        print("Could not find start")
        return
        
    for i in range(start_idx, len(lines)):
        if "return matches" in lines[i]:
            end_idx = i
            break
            
    if end_idx == -1:
        print("Could not find end")
        return
        
    # We will insert a `try:` AFTER `page = await context.new_page()`
    # And then indent everything from start_idx + 1 to end_idx by 4 spaces.
    # And then add the `finally:` block.
    
    new_lines = lines[:start_idx + 1]
    
    # Get the indentation of `page = await context.new_page()`
    base_indent = len(lines[start_idx]) - len(lines[start_idx].lstrip())
    indent_str = " " * base_indent
    
    new_lines.append(indent_str + "try:\n")
    
    for i in range(start_idx + 1, end_idx + 1):
        line = lines[i]
        if line.strip():
            new_lines.append("    " + line)
        else:
            new_lines.append("\n")
            
    # Now add the finally block
    finally_code = f"""{indent_str}finally:
{indent_str}    if page:
{indent_str}        try:
{indent_str}            await page.close()
{indent_str}        except Exception as e:
{indent_str}            logger.warning(f"Failed to close tab: {{e}}")
{indent_str}    await browser.close()
"""
    new_lines.append(finally_code)
    
    # Check if there is already a finally block after end_idx that we should skip
    skip_lines = 0
    for i in range(end_idx + 1, len(lines)):
        if "finally:" in lines[i] or "if page:" in lines[i] or "await page.close()" in lines[i] or "await browser.close()" in lines[i] or "logger.warning(f\"Failed to close tab: {e}\")" in lines[i] or "except Exception as e:" in lines[i]:
            skip_lines += 1
        else:
            if not lines[i].strip() and skip_lines > 0:
                skip_lines += 1
            else:
                break
                
    new_lines.extend(lines[end_idx + 1 + skip_lines:])
    
    with open("server.py", "w", encoding="utf-8") as f:
        f.writelines(new_lines)
    print(f"Fixed lines {start_idx} to {end_idx}, skipped {skip_lines} old finally lines")

if __name__ == "__main__":
    fix_server()
