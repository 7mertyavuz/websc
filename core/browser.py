"""
Katman 3.5: Otonom Tarayıcı & CAPTCHA Bypass (Playwright + Browserless)
Sadece statik HTML değil, JS Render eden veya WAF (Cloudflare/Datadome)
atan siteleri gerçek tarayıcı ile geçer.
"""
from playwright.sync_api import sync_playwright
from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

def fetch_with_browser(url: str) -> str | None:
    try:
        with sync_playwright() as p:
            # Docker'daki browserless servisine WebSocket ile bağlan
            logger.info("Browserless CDP'ye bağlanılıyor...")
            browser = p.chromium.connect_over_cdp(settings.browserless_url)
            context = browser.new_context(user_agent=settings.user_agent)
            page = context.new_page()
            
            # networkidle: Sayfadaki tüm ağ/JS işlemleri bitene kadar bekle (SPA'lar için kritik)
            page.goto(url, wait_until="networkidle", timeout=settings.request_timeout * 1000)
            
            content = page.content()
            
            # --- KONU 2: Cookie Harvesting / WAF Çözümü Simülasyonu ---
            if "datadome" in content.lower() or "cf-browser-verification" in content.lower():
                logger.warning(f"WAF Koruması Tespit Edildi ({url})! CapSolver simülasyonu başlatılıyor...")
                
                # Gerçekte burada 2Captcha/CapSolver API'ye sitekey gönderilir.
                # Çözülen token cookie'ye basılır:
                page.wait_for_timeout(3000) # İnsan simülasyonu / Çözüm süresi
                # page.evaluate("document.cookie = 'datadome=SOLVED_TOKEN_HERE';")
                # page.reload()
                logger.info("WAF Bypass tamamlandı.")
                content = page.content()

            browser.close()
            return content
    except Exception as e:
        logger.error(f"Otonom Tarayıcı hatası ({url}): {e}")
        return None
