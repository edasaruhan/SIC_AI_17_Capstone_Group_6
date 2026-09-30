## Temel Kullanım
Bu uygulama Çankaya’da kafe konumlarını karşılaştıran açıklanabilir bir karar destek sistemidir. Kârlılık veya başarı tahmini yapmaz.

1. **Kapsam:** Çankaya ve kafe analizi kullanılır. Restoran seçeneği yakında.
2. **Verileri Güncelle:** OSM verilerini indirip analiz özelliklerini yeniden üretin. İnternet bağlantısı gerekir.
3. **Harita ve bölge:** Uygunluk, kafe rekabeti, restoran doygunluğu veya OSM noktalarını seçin. Birden fazla mahalleyi filtreleyebilirsiniz; boş seçim tüm Çankaya’dır.
4. **Puan Ağırlıkları:** Başlangıç tercihlerini ihtiyacınıza göre değiştirin. Olumlu katkılar kendi toplamına oranlanır; cezalar ayrıca çıkarılır.
5. **Min uygunluk:** Minimum puanın altındaki hücreleri gizleyin.
6. **OSM Katmanları:** Nokta haritasında görmek istediğiniz katmanları açın.
7. **Hücre seçimi:** 300 × 300 metre hücreyi veya öneri tablosundaki satırı seçip puan gerekçesini inceleyin.

## Uygunluk nasıl belirlenir?
| Bileşen | Varsayılan ağırlık | Açıklama |
|---|---:|---|
| Potansiyel talep | +%45 | Üniversite, alışveriş, ortaokul/lise, park, ofis, devlet dairesi ve kreş/anaokulu göstergeleri. Kafe ve restoranlar dahil edilmez. |
| Erişim | +%25 | Duraklar, metro yakınlığı ve yol bağlantıları. |
| Nüfus | +%20 | Mahalle nüfusunun hücrelere alansal dağıtımı. |
| Doygunluk | −%3 | 500 metredeki restoran ve fast food sayısı; tüm Çankaya üzerinden 0–100’e ölçeklenir. |
| Rekabet | −%7 | Kafeler: merkez ≥2, 9 kare ≥6, 25 kare ≥13. Aşılan 0/1/2/3 eşik için 0/2,33/4,67/7 puan ceza. |
| Popülerlik–mekân uyumluluğu | %10, kapalı | Veri yok; uygunluk puanına etki etmez. |

**Varsayılan hesap:** Uygunluk = max(0; (0,45 × Talep + 0,25 × Erişim + 0,20 × Nüfus) / 0,90 − 0,03 × Doygunluk − 0,07 × Rekabet).

Bileşenler 0–100 ölçeğindedir. Sonuç 0–100 arasında kalır; hiçbir hücrenin 100 alması zorunlu değildir. Popülerlik kapalıyken de olumlu katkılar 100 ölçeğine taşınır.

**Talep detayları:** Mevcut talep alt ağırlıkları üniversite %30, alışveriş %25, ortaokul/lise %15, park %10, ofis %10, devlet dairesi %5, kreş/anaokulu %5’tir. Eksik katmanlar açıkça belirtilir; mevcut göstergelerin alt ağırlıkları yeniden oranlanır. Ofis kayıtları beyaz yaka çalışan sayısı değildir. Kademesi bilinmeyen okullar yeni sayımdan çıkarılır; eski veri dosyasında genel okul sayısı kullanıldığı ayrıca belirtilir.

**Eksik veri:** Rekabet/doygunluk verisi eksikse ilgili ceza hesaplanamaz; sonuç geçici olarak işaretlenir. Eksik veri, gerçek sıfır işletme anlamına gelmez. Popülerlik ayrı bir eksik veri bileşenidir ve şu an devre dışıdır.

**Yorumlama:** Yüksek puan, kullanılan göstergeler bakımından daha uygun konum demektir. Kira, hedef müşteri, görünürlük ve yaya hareketliliği sahada değerlendirilmelidir. OSM kayıtları eksik olabilir; ilçe sınırının dışındaki işletmeler sayılmaz.

Bu metin `docs/temel_kullanim.md` dosyasından okunur; güncellendiğinde ana ekran aynı metni gösterir.
