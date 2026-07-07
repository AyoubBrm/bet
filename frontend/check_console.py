from playwright.sync_api import sync_playwright

def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        
        # Listen to console events
        page.on("console", lambda msg: print(f"BROWSER CONSOLE: {msg.text}"))
        page.on("pageerror", lambda err: print(f"BROWSER ERROR: {err}"))
        
        try:
            print("Navigating to http://localhost:5173/")
            page.goto("http://localhost:5173/", timeout=10000)
            page.wait_for_timeout(3000)
            print("Content length:", len(page.content()))
        except Exception as e:
            print(f"Playwright error: {e}")
            
        browser.close()

if __name__ == "__main__":
    main()
