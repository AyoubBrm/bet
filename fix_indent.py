import sys

def fix_server_py():
    with open("server.py", "r", encoding="utf-8") as f:
        lines = f.readlines()
        
    # We need to find `page = None\n            try:\n                page = await context.new_page()`
    # And then we need to restore the inner `try:` that was on line 744
    
    # 1. Restore the original structure around page creation
    for i, line in enumerate(lines):
        if "page = None" in line and "try:" in lines[i+1]:
            # Change it back to create a nested try block
            lines[i] = "            page = None\n"
            lines[i+1] = "            try:\n"
            lines[i+2] = "                page = await context.new_page()\n"
            lines.insert(i+3, "                try:\n")
            
            # Now we must indent everything from i+4 until `except Exception as e:` (which was around 893)
            j = i + 4
            while j < len(lines):
                if "except Exception as e:" in lines[j] and "Timeout or error" in lines[j+1]:
                    # This is the end of the inner try block. We need to indent this except block too.
                    lines[j] = "                " + lines[j].lstrip()
                    lines[j+1] = "                    " + lines[j+1].lstrip()
                    break
                lines[j] = "    " + lines[j] if lines[j].strip() else lines[j]
                j += 1
                
            # Now we must indent everything AFTER the except block until `finally:`
            k = j + 2
            while k < len(lines):
                if "finally:" in lines[k]:
                    break
                lines[k] = "    " + lines[k] if lines[k].strip() else lines[k]
                k += 1
                
            break
            
    with open("server.py", "w", encoding="utf-8") as f:
        f.writelines(lines)
        
if __name__ == "__main__":
    fix_server_py()
    print("Fixed indentation.")
