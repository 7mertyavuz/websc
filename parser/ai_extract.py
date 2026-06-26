"""
Katman 5.5: Yapay Zeka Destekli (Otonom) Parser.
Lokalde (Ollama) çalışan Llama-3 modelini kullanarak, CSS yapısı tamamen
bilinmeyen sitelerden JSON verisi çeker.
"""
import json
import requests
from bs4 import BeautifulSoup
from parser.extract import Book
from core.config import settings
from core.logging import get_logger

logger = get_logger(__name__)

def parse_with_llama(html: str, url: str) -> Book | None:
    # LLM Context Window'u şişirmemek için HTML'i saf metne çeviriyoruz
    soup = BeautifulSoup(html, "html.parser")
    text_content = soup.get_text(separator=" ", strip=True)
    
    # Çok uzun sayfaları keselim (Llama 8k context)
    text_content = text_content[:6000]

    prompt = f"""
    Sen usta bir veri mühendisisin. Aşağıdaki karmakarışık e-ticaret sayfası metninden kitap bilgilerini bul ve SADECE JSON formatında döndür. Hiçbir ekstra metin yazma.
    İstenen JSON formatı:
    {{"title": "Kitap Adı", "price": 15.5, "availability": "In stock", "rating": 4, "description": "Özet metin"}}
    Bulamadığın alanlara null yazabilirsin.
    
    METİN:
    {text_content}
    """

    try:
        logger.info(f"Local Llama3'e istek atılıyor ({settings.ollama_url})...")
        resp = requests.post(
            f"{settings.ollama_url}/api/generate",
            json={
                "model": "llama3",
                "prompt": prompt,
                "stream": False,
                "format": "json" # Sadece JSON döndürmeye zorla
            },
            timeout=45
        )
        resp.raise_for_status()
        
        ai_response = resp.json().get("response", "{}")
        result_json = json.loads(ai_response)
        
        return Book(
            title=result_json.get("title") or "Bilinmeyen Başlık",
            price=float(result_json.get("price") or 0.0),
            availability=result_json.get("availability") or "unknown",
            rating=int(result_json.get("rating") or 0),
            url=url,
            description=result_json.get("description") or ""
        )
    except Exception as e:
        logger.error(f"[AI Parser Hatası] Llama ile parse başarısız: {e}")
        return None
