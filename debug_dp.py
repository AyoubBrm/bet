from DrissionPage import ChromiumPage, ChromiumOptions
import time
import logging

logging.basicConfig(level=logging.INFO)

def main():
    fixture_url = "https://www.bet365.com/#/AC/B1/C1/D8/E197138029/F3/I17/"
    co = ChromiumOptions()
    co.headless(True)
    page = ChromiumPage(co)
    
    page.get(fixture_url)
    time.sleep(10)
    
    # Take screenshot to see if it bypassed the spinner
    page.get_screenshot(path="screenshot_dp.png", full_page=True)
    logging.info("Saved screenshot_dp.png")
    
    page.quit()

if __name__ == "__main__":
    main()
