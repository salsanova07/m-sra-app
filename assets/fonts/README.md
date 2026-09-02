# PDF fontları

PDF üretiminde ([`app/pdf.py`](../../app/pdf.py)) kullanılan statik TTF'ler.
Hepsi Türkçe karakterleri (ç ğ ı İ ö ş ü) kapsar; Latin alt kümesine indirilmiştir.

| Aile | Kaynak | Lisans | Not |
|---|---|---|---|
| Merriweather | Google Fonts | OFL 1.1 | Arayüz fontuyla aynı |
| Tinos | Google Fonts (`ofl/tinos`) | Apache 2.0 | **Times New Roman** metrik eşi |
| Gelasio | Google Fonts (`ofl/gelasio`) | OFL 1.1 | **Georgia** metrik eşi; değişken fonttan wght 400/700'e sabitlendi |

Times New Roman ve Georgia tescillidir; sunucuya konamaz. Tinos ve Gelasio bu
fontlarla metrik uyumludur (aynı genişlik/satır dökümü), açık lisanslıdır.

Lisans metinleri: <https://openfontlicense.org> ve
<https://www.apache.org/licenses/LICENSE-2.0>.
