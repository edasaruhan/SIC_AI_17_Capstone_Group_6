# TÜİK — senden tek dosya

Kodu veya mahalle sınırını senden istemiyorum. Sadece nüfus tablosu.

## Dosya adı (birebir bu)

```text
cankaya_mahalle_nufus.csv
```

veya Excel ise:

```text
cankaya_mahalle_nufus.xlsx
```

## Nereye koyacaksın

```text
retail-location-intelligence/data/raw/tuik/cankaya_mahalle_nufus.csv
```

Şablon hazır: aynı klasördeki `cankaya_mahalle_nufus.template.csv` (123 Çankaya mahallesi yazılı, nüfus boş).  
Excel’de aç → `pop_total` doldur → **Farklı Kaydet** ile adı `cankaya_mahalle_nufus.csv` yap.

## Sütunlar

| Sütun | Zorunlu mu | Ne yazacaksın |
| --- | --- | --- |
| mahalle_name | evet | Bahçelievler Mahallesi |
| pop_total | evet | 16500 |
| pop_15_34 | hayır | 15–19+20–24+25–29+30–34 toplamı; yoksa boş |

TÜİK Excel’inde sütun adları `Mahalle Adı` / `Toplam Nüfus` olsa da olur.

## Örnek (ilk üç satır)

```csv
mahalle_name,pop_total,pop_15_34,year,source
Bahçelievler Mahallesi,16500,4800,2025,TUIK ADNKS
Ayrancı Mahallesi,17847,5200,2025,TUIK ADNKS
Alacaatlı Mahallesi,46632,,2025,TUIK ADNKS
```

## Nereden alacaksın

[TÜİK Nüfus İstatistikleri Portalı — ADNKS](https://nip.tuik.gov.tr/Home/Adnks)  
Ankara → Çankaya → **mahalle satırları**. İlçe toplamı (952.198) yetmez.

`pop_15_34` mahallede yoksa boş bırak; ilçe yaş payını sonra ekleriz.

Dosyayı koyduktan sonra:

```powershell
python -m src.build_features
```
