"""
Canlı RedisBloom doğrulama scripti (test paketinin parçası değil; elle çalıştırılır).

Amaç: core/dedup.py'ın GERÇEK RedisBloom yoluna (BF.RESERVE / BF.ADD / BF.EXISTS)
bağlandığını ve mantığın doğru çalıştığını canlı bir Redis Stack'e karşı kanıtlamak.

Kanıtladıkları:
  1. dedup.backend == "redis-bloom"  -> in-memory fallback'e DÜŞMEDİ, gerçek Redis'e bağlandı.
  2. check_and_mark(url): ilk görüşte False (yeni), ikinci görüşte True (görüldü).
  3. Düşük seviye: BF.ADD/BF.EXISTS komutlarını doğrudan çalıştırıp Redis'in
     Bloom modülünü gerçekten tanıdığını gösterir.

Kullanım:
    # Önce bir Redis Stack ayakta olmalı (docker compose up -d redis  ya da redis-stack-server)
    REDIS_URL=redis://localhost:6379/0 python tests/verify_bloom.py
"""
from __future__ import annotations
import os
import sys
import time

# Proje kökünü import yoluna ekle (script doğrudan çalıştırılınca da bulsun).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.config import settings          # noqa: E402
from core.dedup import dedup, _key        # noqa: E402


def main() -> int:
    failures: list[str] = []

    print(f"REDIS_URL      : {settings.redis_url}")
    print(f"dedup.backend  : {dedup.backend}")

    # --- Kanıt 1: gerçek RedisBloom yoluna bağlandık mı? ---
    if dedup.backend != "redis-bloom":
        failures.append(
            f"backend 'redis-bloom' bekleniyordu ama '{dedup.backend}' bulundu "
            f"(Redis Stack ayakta mı? REDIS_URL doğru mu?)"
        )
        print("\n[X] Redis'e bağlanılamadı, in-memory fallback'e düşüldü.")
        # Bağlanamadıysak alt testlerin anlamı kalmaz; yine de fallback mantığını gösterelim.

    # Her çalıştırmada taze bir URL kullan ki 'ilk görüş' garanti yeni olsun.
    test_url = f"https://books.toscrape.com/catalogue/verify-{os.getpid()}-{int(time.time())}.html"
    print(f"\nTest URL       : {test_url}")
    print(f"SHA1 anahtarı  : {_key(test_url)}")

    # --- Kanıt 2: ilk görüş False, ikinci görüş True ---
    first = dedup.check_and_mark(test_url)
    second = dedup.check_and_mark(test_url)
    print(f"\ncheck_and_mark #1 (yeni URL)      -> {first}   (beklenen: False)")
    print(f"check_and_mark #2 (aynı URL)      -> {second}   (beklenen: True)")
    if first is not False:
        failures.append("İlk check_and_mark False dönmeliydi (URL yeni).")
    if second is not True:
        failures.append("İkinci check_and_mark True dönmeliydi (URL zaten görüldü).")

    # --- Kanıt 3: düşük seviye BF.ADD / BF.EXISTS doğrudan çalışıyor mu? ---
    if dedup._client is not None:
        raw_key = f"verify:bf:{os.getpid()}"
        try:
            dedup._client.execute_command("BF.RESERVE", raw_key, 0.001, 1000)
        except Exception:
            pass  # zaten varsa
        exists_before = dedup._client.execute_command("BF.EXISTS", raw_key, "item-A")
        added = dedup._client.execute_command("BF.ADD", raw_key, "item-A")
        exists_after = dedup._client.execute_command("BF.EXISTS", raw_key, "item-A")
        dedup._client.delete(raw_key)  # temizlik
        print(f"\nBF.EXISTS (eklemeden önce)        -> {exists_before}   (beklenen: 0)")
        print(f"BF.ADD                            -> {added}   (beklenen: 1)")
        print(f"BF.EXISTS (ekledikten sonra)      -> {exists_after}   (beklenen: 1)")
        if not (int(exists_before) == 0 and int(added) == 1 and int(exists_after) == 1):
            failures.append("Düşük seviye BF.ADD/BF.EXISTS beklenen değerleri vermedi.")
    else:
        print("\n[i] Düşük seviye BF testi atlandı (Redis istemcisi yok).")

    # --- Sonuç ---
    print("\n" + "=" * 50)
    if failures:
        print("SONUÇ: BAŞARISIZ")
        for f in failures:
            print(f"  - {f}")
        return 1
    print("SONUC: BASARILI  Gercek RedisBloom yolu dogrulandi.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
