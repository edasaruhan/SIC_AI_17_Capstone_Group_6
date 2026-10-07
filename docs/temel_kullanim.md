## Samsung Innovation Campus — AI in Marketing Capstone Projesi

**Retail Location Intelligence · Grup 6**

Kafe girişimcilerinin hedef müşteri çevresine erişim ve rekabet koşullarını karşılaştırarak aday bölgeleri daha hızlı seçmesini amaçlayan AI destekli pazar planlama aracı.

Nüfus, çevredeki kurumlar ve ulaşım müşteri çevresine erişimin dolaylı göstergeleridir. Gerçek müşteri profili, yaya sayısı, kârlılık veya başarı ölçülmez.

**Önerilen KPI:** Manuel harita incelemesine göre aday liste hazırlama süresi. Süre tasarrufu henüz ölçülmedi; pilotta aday kalitesiyle birlikte değerlendirilecek.

## Temel Kullanım

1. **Kapsam:** Çankaya ve kafe analizi kullanılır. Restoran seçeneği yakında.
2. **Verileri Güncelle:** OSM verilerini indirip analiz özelliklerini yeniden üretin. İnternet bağlantısı gerekir.
3. **Harita ve bölge:** Uygunluk, kafe rekabeti, benzer yer yoğunluğu veya OSM noktalarını seçin. Birden fazla mahalleyi filtreleyebilirsiniz; boş seçim tüm Çankaya’dır.
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
| Benzer yer yoğunluğu | +%5 | 500 m içindeki kafe sayısı / tüm Çankaya maksimumu. Yalnızca rekabet eşiği aşılmadığında en fazla +5 puan. |
| Rekabet | −%5 | Kafeler: merkez ≥2, 9 kare ≥6, 25 kare ≥13. Aşılan 0/1/2/3 eşik için 0/1,67/3,33/5 puan ceza. Eşik aşılırsa yoğunluk bonusu kapanır. |
| Popülerlik–mekân uyumluluğu | %10, kapalı | Veri yok; uygunluk puanına etki etmez. |

**Varsayılan hesap:** Temel puan = (0,45 × Talep + 0,25 × Erişim + 0,20 × Nüfus) / 0,90. Rekabet düzeyi 0 ise 0,05 × Yoğunluk eklenir; düzey 1–3 ise bonus verilmez ve 5 × düzey / 3 çıkarılır. Sonuç 0–100 aralığında tutulur.

Bileşenler 0–100 ölçeğindedir. Sonuç 0–100 arasında kalır; hiçbir hücrenin 100 alması zorunlu değildir. Popülerlik kapalıyken de olumlu katkılar 100 ölçeğine taşınır.

**Talep detayları:** Mevcut talep alt ağırlıkları üniversite %30, alışveriş %25, ortaokul/lise %15, park %10, ofis %10, devlet dairesi %5, kreş/anaokulu %5’tir. Eksik katmanlar açıkça belirtilir; mevcut göstergelerin alt ağırlıkları yeniden oranlanır. Ofis kayıtları beyaz yaka çalışan sayısı değildir. Kademesi bilinmeyen okullar yeni sayımdan çıkarılır; eski veri dosyasında genel okul sayısı kullanıldığı ayrıca belirtilir.

**Eksik veri:** Rekabet verisi eksikse bonus verilmez; eksik yoğunluk veya rekabet etkisi hesaplanamaz ve sonuç geçici olarak işaretlenir. Eksik veri, gerçek sıfır işletme anlamına gelmez. Popülerlik ayrı bir eksik veri bileşenidir ve şu an devre dışıdır.

**Yorumlama:** Yüksek puan, kullanılan göstergeler bakımından daha uygun konum demektir. Kira, hedef müşteri, görünürlük ve yaya hareketliliği sahada değerlendirilmelidir. OSM kayıtları eksik olabilir; ilçe sınırının dışındaki işletmeler sayılmaz.

Bu metin `docs/temel_kullanim.md` dosyasından okunur; güncellendiğinde ana ekran aynı metni gösterir.


**Market–user–konum yaklaşımı:** Pazar çevresi (talep oluşturan kurumlar, nüfus ve benzer işletmeler), kullanıcı (aday bölge seçen kafe girişimcisi ve ulaşmak istediği müşteri çevresi) ve konum (300 m hücreler, mahalle ve erişim) birlikte değerlendirilir. Ürün konum odaklı pazarlama karar desteğidir; bireysel müşteri takibi yapmaz.

### Birleşmiş Milletler hedefleriyle bağlantı

| Hedef | Projenin amaçladığı bağlantı |
| --- | --- |
| [Hedef 3: Sağlık ve Kaliteli Yaşam](https://sdgs.un.org/goals/goal3) | Her yaşta sağlıklı yaşamı ve refahı destekleme amacıyla, park ve yaya erişimi göstergelerini kullanarak erişilebilir sosyal mekân planlamasına dolaylı katkı. Sağlık etkisi ölçülmedi. |
| [Hedef 8: İnsana Yakışır İş ve Ekonomik Büyüme](https://sdgs.un.org/goals/goal8) | Sürdürülebilir, kapsayıcı ekonomik büyüme ve verimli istihdam amacıyla, girişimcilerin pazar ve rekabeti daha bilinçli değerlendirmesine destek. İstihdam artışı veya iş kalitesi ölçülmedi. |
| [Hedef 11: Sürdürülebilir Şehirler ve Topluluklar](https://sdgs.un.org/goals/goal11) | Kapsayıcı, güvenli, dayanıklı ve sürdürülebilir yerleşimler amacıyla, toplu taşıma, park ve mahalle erişimini konum kararlarında görünür kılma. Güvenlik ve dayanıklılık bu sürümde ölçülmez. |

Bu bağlantılar tasarım amaçlarıdır; doğrulanmış sürdürülebilirlik sonuçları değildir.

