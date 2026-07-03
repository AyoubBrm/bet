"""
Debug script using curl_cffi to hit the bet365 API directly.
"""
import asyncio
from curl_cffi.requests import AsyncSession
import logging

logging.basicConfig(level=logging.INFO)

async def main():
    proxy = "http://19d5d5ecee19c4e2:MUSRJBNjWVZAmzfd@res.geonix.com:10000"
    
    # But proxy is US-based. Let's try without proxy first.
    proxy_config = None

    url = "https://www.bet365.com/splashcontentapi/changefixture?lid=1&zid=0&pd=%23AC%23B1%23C1%23D8%23E197138029%23F3%23I17%23&cid=198&cgid=1&ctid=198"
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36",
        "Accept": "*/*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bet365.com/",
        "X-Requested-With": "XMLHttpRequest",
    }

    async with AsyncSession(impersonate="chrome120") as s:
        logging.info("Fetching API directly...")
        try:
            resp = await s.get(url, headers=headers, proxies={"http": proxy_config, "https": proxy_config} if proxy_config else None)
            logging.info(f"Status: {resp.status_code}")
            logging.info(f"Body: {resp.text[:1000]}")
            
            if "|PA;" in resp.text:
                logging.info("🎯 FOUND PLAYER DATA IN DIRECT API CALL!")
        except Exception as e:
            logging.error(f"Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
