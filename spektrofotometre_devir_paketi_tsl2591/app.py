import csv
import os
import threading
import time
from datetime import datetime

import serial
from flask import Flask, jsonify, request, send_file, Response

# =========================================================
# SPEKTROFOTOMETRE WEB PANELİ - TSL2591
# Arduino seri port çıktısı şu formatta olmalı:
# Eski format desteklenir:
# DATA,RawVisible,Transmittance,Absorbance,AverageAbsorbance
# Yeni önerilen format desteklenir:
# DATA,RawVisible,Transmittance,Absorbance,AverageAbsorbance,DarkRaw,BlankRaw
# Komutlar:
# SET_DARK   -> ışık kapalı + kutu kapalı iken darkRaw alır
# SET_BLANK  -> ışık açık + kör/blank küvet varken blankRaw alır
# GET_REF    -> Arduino'daki darkRaw ve blankRaw değerlerini ister
# RESET_AVG  -> Arduino ortalama tamponlarını sıfırlar
# =========================================================

PORT = "COM6"       # Arduino hangi COM porttaysa burayı değiştir
BAUD = 9600

RUN_TIMESTAMP = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
CSV_FILE = f"spektrofotometre_olcumleri_{RUN_TIMESTAMP}.csv"

app = Flask(__name__)

latest_data = {
    # Web panelde gösterilecek son ölçüm zamanı.
    "time": "-",

    # Ölçümün hangi örnek adına ait olduğunu tutar.
    "sample": "-",

    # TSL2591 sensöründen gelen ham görünür ışık değeri.
    "raw": 0.0,

    # Numuneden geçen ışık yüzdesi.
    "transmittance": 0.0,

    # Anlık absorbans değeri.
    "absorbance": 0.0,

    # Arduino tarafında hesaplanan ortalama absorbans değeri.
    "average_absorbance": 0.0,

    # Işık kapalı + kutu kapalı durumunda alınan karanlık referans.
    "dark_raw": 0.7,

    # Işık açık + kör/blank küvet durumunda alınan referans ışık değeri.
    "blank_raw": 1138.0,

    # Kullanıcıya gösterilecek sistem durumu.
    "status": "Arduino bağlantısı bekleniyor...",

    # Arduino bağlantısının aktif olup olmadığını gösterir.
    "connected": False,

    # CSV kayıt durumunu gösterir.
    "measuring": False,
}

# Web tabloda ve özet grafikte tutulacak ölçüm satırları.
data_rows = []

# Kullanıcının panelden seçtiği/girdiği güncel örnek adı.
current_sample_name = "Boş Küvet"

# Ölçüm kaydının aktif olup olmadığını gösterir.
measurement_enabled = False

# Arduino seri port nesnesi burada global tutulur.
# Böylece web paneldeki butonlar Arduino'ya SET_DARK / SET_BLANK komutu gönderebilir.
arduino_ser = None

# latest_data ve data_rows gibi ortak verileri thread çakışmasından korur.
state_lock = threading.Lock()

# Seri porta aynı anda birden fazla yazma/erişim olmaması için kullanılır.
serial_lock = threading.Lock()


# =========================================================
# CSV İŞLEMLERİ
# =========================================================

def prepare_csv():
    if not os.path.exists(CSV_FILE):
        with open(CSV_FILE, mode="w", newline="", encoding="utf-8-sig") as file:
            writer = csv.writer(file)
            writer.writerow([
                "Tarih-Saat",
                "Örnek Adı",
                "Raw Visible",
                "Transmittance (%)",
                "Absorbance",
                "Average Absorbance",
                "Dark Raw",
                "Blank Raw"
            ])


def save_to_csv(row):
    with open(CSV_FILE, mode="a", newline="", encoding="utf-8-sig") as file:
        writer = csv.writer(file)
        writer.writerow([
            row["time"],
            row["sample"],
            row["raw"],
            row["transmittance"],
            row["absorbance"],
            row["average_absorbance"],
            row.get("dark_raw", 0.0),
            row.get("blank_raw", 0.0)
        ])


def reset_csv():
    if os.path.exists(CSV_FILE):
        os.remove(CSV_FILE)
    prepare_csv()




# =========================================================
# ARDUINO KOMUT GÖNDERME VE REFERANS PARSE İŞLEMLERİ
# =========================================================

def send_arduino_command(command):
    """
    Web panelden gelen bir komutu Arduino'ya seri port üzerinden gönderir.

    Örnek komutlar:
    - SET_DARK  : Arduino ışık kapalıyken darkRaw değerini alır.
    - SET_BLANK : Arduino kör/blank küvet varken blankRaw değerini alır.
    - GET_REF   : Arduino mevcut darkRaw ve blankRaw değerlerini gönderir.
    - RESET_AVG : Arduino ortalama hesaplama tamponunu sıfırlar.
    """
    global arduino_ser

    # Seri port işlemleri aynı anda çakışmasın diye kilit kullanılır.
    with serial_lock:
        # Arduino henüz bağlı değilse komut gönderilemez.
        if arduino_ser is None or not arduino_ser.is_open:
            return False, "Arduino seri port bağlantısı yok."

        try:
            # Komut sonuna yeni satır eklenir. Arduino readStringUntil('\n') ile okur.
            arduino_ser.write((command.strip() + "\n").encode("utf-8"))

            # Komutun seri porta hemen gönderilmesi sağlanır.
            arduino_ser.flush()

            # Başarılı cevap döndürülür.
            return True, f"{command} komutu Arduino'ya gönderildi."

        except Exception as e:
            # Hata varsa kullanıcıya anlaşılır şekilde döndürülür.
            return False, f"Arduino'ya komut gönderilemedi: {e}"


def update_reference_from_status(line):
    """
    Arduino'dan gelen STATUS satırlarından darkRaw ve blankRaw değerlerini yakalar.

    Desteklenen örnek satırlar:
    STATUS,DARK_SET,0.70
    STATUS,BLANK_SET,379.70
    STATUS,REF,DARK=0.70,BLANK=379.70
    """
    # Referans değerlerini global latest_data içinde güncellemek için kullanılır.
    global latest_data

    try:
        # Arduino SET_DARK sonrası bu formatı gönderir.
        if line.startswith("STATUS,DARK_SET,"):
            dark_value = float(line.split(",")[2])
            latest_data["dark_raw"] = dark_value
            latest_data["status"] = f"Dark referansı alındı: {dark_value:.2f}"
            return True

        # Arduino SET_BLANK sonrası bu formatı gönderir.
        if line.startswith("STATUS,BLANK_SET,"):
            blank_value = float(line.split(",")[2])
            latest_data["blank_raw"] = blank_value
            latest_data["status"] = f"Kör / blank referansı alındı: {blank_value:.2f}"
            return True

        # Arduino GET_REF sonrası bu formatı gönderebilir.
        if line.startswith("STATUS,REF,"):
            # STATUS,REF,DARK=0.70,BLANK=379.70
            parts = line.split(",")

            for part in parts:
                if part.startswith("DARK="):
                    latest_data["dark_raw"] = float(part.replace("DARK=", ""))

                elif part.startswith("BLANK="):
                    latest_data["blank_raw"] = float(part.replace("BLANK=", ""))

            latest_data["status"] = (
                f"Referanslar güncellendi. Dark: {latest_data['dark_raw']:.2f}, "
                f"Blank: {latest_data['blank_raw']:.2f}"
            )
            return True

    except Exception as e:
        # Parse hatası olursa sistem durumu güncellenir ama uygulama çökmez.
        latest_data["status"] = f"Referans bilgisi okunamadı: {e}"
        return True

    # Bu STATUS satırı referans bilgisi içermiyorsa False döndürülür.
    return False

# =========================================================
# ARDUINO OKUMA THREAD
# =========================================================

def read_arduino():
    """
    Arduino'dan gelen seri port verilerini sürekli okuyan arka plan thread fonksiyonudur.

    Bu fonksiyonun görevleri:
    1. Arduino seri portuna bağlanmak.
    2. READY / STATUS / ERROR / DATA satırlarını okumak.
    3. DATA satırlarını sayısal değerlere dönüştürmek.
    4. Web panelde gösterilecek latest_data sözlüğünü güncellemek.
    5. Kayıt aktifse ölçüm satırlarını tabloya ve CSV dosyasına yazmak.
    """
    global latest_data, data_rows, arduino_ser

    # Bağlantı koparsa tekrar bağlanabilmek için sonsuz döngü kullanılır.
    while True:
        # Bu döngüde kullanılacak yerel seri port nesnesi.
        ser = None

        try:
            # Arduino'nun bağlı olduğu COM port açılır.
            ser = serial.Serial(PORT, BAUD, timeout=1)

            # Web endpointlerinin de kullanabilmesi için seri port global değişkene aktarılır.
            with serial_lock:
                arduino_ser = ser

            # Arduino reset sonrası hazır hale gelsin diye kısa bekleme yapılır.
            time.sleep(2)

            # Bağlantı başarılı bilgisi web panele yazılır.
            with state_lock:
                latest_data["status"] = f"Arduino bağlı: {PORT}"
                latest_data["connected"] = True

            # Arduino'daki mevcut referans değerlerini istemek için GET_REF gönderilir.
            # Arduino kodunda GET_REF varsa darkRaw ve blankRaw panele otomatik gelir.
            send_arduino_command("GET_REF")

            # Seri port açık kaldığı sürece veri okunur.
            while True:
                # Arduino'dan bir satır okunur.
                line = ser.readline().decode("utf-8", errors="ignore").strip()

                # Boş satır geldiyse işlem yapılmaz.
                if not line:
                    continue

                # Terminalde hata ayıklama için gelen ham satır yazdırılır.
                print(line)

                # Ortak veri alanları güvenli şekilde güncellenir.
                with state_lock:

                    # Arduino hazır mesajı geldiyse durum güncellenir.
                    if line.startswith("READY"):
                        latest_data["status"] = "TSL2591 hazır."
                        latest_data["connected"] = True

                    # Arduino'dan STATUS satırı geldiyse önce referans bilgisi içerip içermediği kontrol edilir.
                    elif line.startswith("STATUS"):
                        handled = update_reference_from_status(line)

                        # STATUS satırı referansla ilgili değilse genel durum mesajı olarak gösterilir.
                        if not handled:
                            latest_data["status"] = line
                            latest_data["connected"] = True

                    # Arduino hata mesajı gönderdiyse web panelde gösterilir.
                    elif line.startswith("ERROR"):
                        latest_data["status"] = line
                        latest_data["connected"] = True

                    # Ölçüm verisi DATA ile başlıyorsa parse edilir.
                    elif line.startswith("DATA,"):
                        parts = line.split(",")

                        # Eski Arduino kodu 5 parça gönderir:
                        # DATA,Raw,T%,Abs,AvgAbs
                        # Yeni Arduino kodu 7 parça gönderir:
                        # DATA,Raw,T%,Abs,AvgAbs,DarkRaw,BlankRaw
                        if len(parts) >= 5:
                            now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

                            try:
                                # Ham görünür ışık değeri alınır.
                                raw = float(parts[1])

                                # Transmittance yüzdesi alınır.
                                transmittance = float(parts[2])

                                # Anlık absorbans alınır.
                                absorbance = float(parts[3])

                                # Ortalama absorbans alınır.
                                average_absorbance = float(parts[4])

                                # Yeni formatta Arduino darkRaw ve blankRaw değerlerini de gönderir.
                                if len(parts) >= 7:
                                    dark_raw = float(parts[5])
                                    blank_raw = float(parts[6])
                                else:
                                    # Eski format kullanılıyorsa paneldeki son referans değerleri korunur.
                                    dark_raw = float(latest_data.get("dark_raw", 0.7))
                                    blank_raw = float(latest_data.get("blank_raw", 1138.0))

                            except ValueError:
                                # Sayıya çevrilemeyen bozuk satırlar yok sayılır.
                                continue

                            # Web panele ve tabloya yazılacak ölçüm satırı hazırlanır.
                            row = {
                                "time": now,
                                "sample": current_sample_name,
                                "raw": raw,
                                "transmittance": transmittance,
                                "absorbance": absorbance,
                                "average_absorbance": average_absorbance,
                                "dark_raw": dark_raw,
                                "blank_raw": blank_raw,
                                "status": "Ölçüm aktif." if measurement_enabled else "Veri izleniyor, kayıt pasif.",
                                "connected": True,
                                "measuring": measurement_enabled,
                            }

                            # Son ölçüm verisi güncellenir.
                            latest_data = row

                            # Ölçüm kaydı aktifse satır tabloya ve CSV dosyasına eklenir.
                            if measurement_enabled:
                                data_rows.append(row)

                                # Belleğin gereksiz büyümemesi için son 500 satır tutulur.
                                if len(data_rows) > 500:
                                    data_rows = data_rows[-500:]

                                # Satır CSV dosyasına yazılır.
                                save_to_csv(row)

        except Exception as e:
            # Bağlantı hatası durumunda web panel bilgilendirilir.
            with state_lock:
                latest_data["status"] = f"Bağlantı hatası: {e}"
                latest_data["connected"] = False
                latest_data["measuring"] = False

            # Seri port global referansı temizlenir.
            with serial_lock:
                if arduino_ser is ser:
                    arduino_ser = None

            # Açık seri port varsa kapatılır.
            try:
                if ser is not None:
                    ser.close()
            except Exception:
                pass

            # Yeniden bağlanmadan önce kısa bekleme yapılır.
            time.sleep(3)


# =========================================================
# WEB SAYFASI
# =========================================================

@app.route("/")
def index():
    return Response("""
<!DOCTYPE html>
<html lang="tr" class="scroll-smooth">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Spektrofotometre Canlı Ölçüm Paneli</title>

    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800;900&display=swap" rel="stylesheet">

    <script src="https://cdn.tailwindcss.com"></script>

    <script>
        tailwind.config = {
            darkMode: "class",
            theme: {
                extend: {
                    fontFamily: {
                        inter: ["Inter", "sans-serif"]
                    },
                    boxShadow: {
                        soft: "0 20px 60px rgba(15, 23, 42, 0.08)",
                        glow: "0 0 0 1px rgba(16, 185, 129, 0.08), 0 20px 50px rgba(16, 185, 129, 0.08)"
                    }
                }
            }
        }
    </script>

    <script>
        (function () {
            const savedTheme = localStorage.getItem("theme");
            if (savedTheme === "light") {
                document.documentElement.classList.remove("dark");
            } else {
                document.documentElement.classList.add("dark");
            }
        })();
    </script>

    <script src="https://cdn.jsdelivr.net/npm/chart.js"></script>

    <link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.5.0/css/all.min.css">

    <style>
        select option {
            background: #ffffff !important;
            color: #0f172a !important;
        }

        input,
        select {
            color: #0f172a !important;
            background-color: #ffffff !important;
        }

        html.dark input,
        html.dark select {
            color: #ffffff !important;
            background-color: #020617 !important;
        }

        input::placeholder {
            color: #64748b !important;
        }

        html.dark input::placeholder {
            color: #94a3b8 !important;
        }

        body {
            overflow-x: hidden;
        }

        ::selection {
            background: rgba(16, 185, 129, 0.25);
        }
    </style>
</head>

<body class="font-inter bg-slate-100 text-slate-900 dark:bg-slate-950 dark:text-slate-100">

    <div class="min-h-screen">

        <header class="sticky top-0 z-40 border-b border-slate-200/70 bg-white/90 backdrop-blur-xl dark:border-slate-800 dark:bg-slate-950/90">
            <div class="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8">
                <div class="flex items-center gap-4">
                    <div class="flex h-12 w-12 items-center justify-center rounded-2xl bg-slate-900 text-white shadow-lg dark:bg-emerald-500">
                        <i class="fa-solid fa-microscope text-xl"></i>
                    </div>

                    <div>
                        <h1 class="text-xl font-extrabold tracking-tight text-slate-950 dark:text-white md:text-2xl">
                            Spektrofotometre Canlı Ölçüm Paneli
                        </h1>
                        <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                            TSL2591 tabanlı canlı absorbans, geçirgenlik ve ham ışık takibi
                        </p>
                    </div>
                </div>

                <div class="flex items-center gap-3">
                    <div id="topConnectionBadge" class="hidden items-center gap-2 rounded-full border border-amber-200 bg-amber-50 px-4 py-2 text-sm font-semibold text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/50 dark:text-amber-300 md:inline-flex">
                        <span class="h-2.5 w-2.5 rounded-full bg-amber-500"></span>
                        Bağlantı bekleniyor
                    </div>

                    <button id="themeToggle" onclick="toggleTheme()" class="inline-flex items-center gap-2 rounded-full border border-slate-300 bg-white px-4 py-2 text-sm font-extrabold text-slate-800 shadow-sm transition hover:bg-slate-50 dark:border-slate-700 dark:bg-slate-900 dark:text-white dark:hover:bg-slate-800">
                        <i id="themeIcon" class="fa-solid fa-sun"></i>
                        <span id="themeText" class="hidden sm:inline">Açık Tema</span>
                    </button>
                </div>
            </div>
        </header>

        <main class="mx-auto max-w-7xl px-5 py-6 lg:px-8">

            <section class="mb-6 overflow-hidden rounded-3xl border border-slate-200 bg-white shadow-soft dark:border-slate-800 dark:bg-slate-900">
                <div class="grid gap-0 lg:grid-cols-[1.35fr_0.65fr]">
                    <div class="p-6 lg:p-8">
                        <div class="mb-4 inline-flex items-center gap-2 rounded-full bg-emerald-50 px-4 py-2 text-sm font-extrabold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                            <i class="fa-solid fa-wave-square"></i>
                            Canlı veri izleme aktif
                        </div>

                        <h2 class="text-2xl font-black tracking-tight text-slate-950 dark:text-white md:text-3xl">
                            Optik ölçümleri anlık izle, kaydet ve karşılaştır.
                        </h2>

                        <p class="mt-3 max-w-3xl text-sm leading-6 text-slate-600 dark:text-slate-400 md:text-base">
                            Bu panel Arduino üzerinden gelen TSL2591 görünür ışık verisini okuyarak
                            Raw Visible, Transmittance, Absorbance ve Average Absorbance değerlerini canlı olarak gösterir.
                            Ölçümler örnek adına göre kaydedilir ve CSV/Excel uyumlu çıktı alınabilir.
                        </p>

                        <div class="mt-5 flex flex-wrap gap-3">
                            <div id="connectionPill" class="inline-flex items-center gap-2 rounded-2xl bg-slate-100 px-4 py-2 text-sm font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                                <span class="h-2.5 w-2.5 rounded-full bg-amber-500"></span>
                                Bağlantı bekleniyor
                            </div>

                            <div id="measurePill" class="inline-flex items-center gap-2 rounded-2xl bg-slate-100 px-4 py-2 text-sm font-bold text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                                <span class="h-2.5 w-2.5 rounded-full bg-amber-500"></span>
                                Kayıt pasif
                            </div>

                            <div class="inline-flex items-center gap-2 rounded-2xl bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700 dark:bg-blue-950/50 dark:text-blue-300">
                                <i class="fa-solid fa-lightbulb"></i>
                                Yeşil LED manuel
                            </div>

                            <div class="inline-flex items-center gap-2 rounded-2xl bg-violet-50 px-4 py-2 text-sm font-bold text-violet-700 dark:bg-violet-950/50 dark:text-violet-300">
                                <i class="fa-solid fa-ruler-combined"></i>
                                Yaklaşık 550 nm bandı
                            </div>
                        </div>
                    </div>

                    <div class="border-t border-slate-200 bg-slate-50 p-6 dark:border-slate-800 dark:bg-slate-950/60 lg:border-l lg:border-t-0 lg:p-8">
                        <h3 class="text-sm font-black uppercase tracking-wider text-slate-500 dark:text-slate-400">
                            Sistem Durumu
                        </h3>

                        <div class="mt-4 rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                            <div class="flex items-start gap-3">
                                <div class="mt-1 flex h-9 w-9 items-center justify-center rounded-xl bg-slate-900 text-white dark:bg-emerald-500">
                                    <i class="fa-solid fa-terminal"></i>
                                </div>

                                <div>
                                    <p id="statusText" class="text-sm font-semibold leading-6 text-slate-700 dark:text-slate-200">
                                        Durum: bekleniyor...
                                    </p>
                                    <p class="mt-1 text-xs leading-5 text-slate-500 dark:text-slate-400">
                                        Ölçüm sırasında Serial Monitor kapalı, Flask panel açık olmalıdır.
                                    </p>
                                </div>
                            </div>
                        </div>

                        <div class="mt-4 grid grid-cols-2 gap-3 text-sm">
                            <div class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                                <p class="text-xs font-black uppercase tracking-wider text-slate-500 dark:text-slate-400">Dark</p>
                                <p id="darkRawValue" class="mt-1 text-xl font-black text-slate-950 dark:text-white">0.70</p>
                            </div>

                            <div class="rounded-2xl border border-slate-200 bg-white p-4 dark:border-slate-800 dark:bg-slate-900">
                                <p class="text-xs font-black uppercase tracking-wider text-slate-500 dark:text-slate-400">Blank</p>
                                <p id="blankRawValue" class="mt-1 text-xl font-black text-slate-950 dark:text-white">1138.00</p>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            <div class="grid gap-6 lg:grid-cols-[360px_1fr]">

                <aside class="space-y-6">

                    <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                        <div class="mb-5 flex items-center justify-between">
                            <div>
                                <h2 class="text-lg font-black text-slate-950 dark:text-white">
                                    Ölçüm Kontrolü
                                </h2>
                                <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                    Örnek seç, kaydet ve ölçümü başlat.
                                </p>
                            </div>

                            <div class="flex h-11 w-11 items-center justify-center rounded-2xl bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-200">
                                <i class="fa-solid fa-sliders"></i>
                            </div>
                        </div>

                        <label class="mb-2 block text-sm font-extrabold text-slate-700 dark:text-slate-300">
                            Hazır örnek seçimi
                        </label>

                        <select id="samplePreset" onchange="applyPreset()" class="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm font-extrabold outline-none transition focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 dark:border-slate-700 dark:focus:border-emerald-400">
                            <option style="background:#ffffff;color:#0f172a;" value="Kör / Blank">Kör / Blank</option>
                            <option style="background:#ffffff;color:#0f172a;" value="0.002 g Grup">0.002 g Grup</option>
                            <option style="background:#ffffff;color:#0f172a;" value="0.004 g Grup">0.004 g Grup</option>
                            <option style="background:#ffffff;color:#0f172a;" value="0.006 g Grup">0.006 g Grup</option>
                            <option style="background:#ffffff;color:#0f172a;" value="0.008 g Grup">0.008 g Grup</option>
                            <option style="background:#ffffff;color:#0f172a;" value="0.010 g Grup">0.010 g Grup</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Boş Küvet">Boş Küvet</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Su">Su</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Vişne Suyu">Vişne Suyu</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Az Seyreltilmiş - 5 pipet su">Az Seyreltilmiş - 5 pipet su</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Orta Seyreltilmiş - 10 pipet su">Orta Seyreltilmiş - 10 pipet su</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Çok Seyreltilmiş - 15 pipet su">Çok Seyreltilmiş - 15 pipet su</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Aşırı Seyreltilmiş - 20 pipet su">Aşırı Seyreltilmiş - 20 pipet su</option>
                            <option style="background:#ffffff;color:#0f172a;" value="Diğer">Diğer</option>
                        </select>

                        <label class="mb-2 mt-4 block text-sm font-extrabold text-slate-700 dark:text-slate-300">
                            Örnek adı
                        </label>

                        <input id="sampleName" value="Kör / Blank" autocomplete="off" class="w-full rounded-2xl border border-slate-300 px-4 py-3 text-sm font-extrabold outline-none transition focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 dark:border-slate-700 dark:focus:border-emerald-400">

                        <button onclick="setSample()" class="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-900 px-4 py-3 text-sm font-black text-white shadow-lg shadow-slate-900/10 transition hover:-translate-y-0.5 hover:bg-slate-800 dark:bg-slate-100 dark:text-slate-950 dark:hover:bg-white">
                            <i class="fa-solid fa-tag"></i>
                            Örnek Adını Kaydet
                        </button>

                        <div class="mt-4 rounded-2xl border border-slate-200 bg-slate-50 p-3 dark:border-slate-800 dark:bg-slate-950/60">
                            <p class="mb-3 text-xs font-black uppercase tracking-wider text-slate-500 dark:text-slate-400">
                                Referans Kalibrasyonu
                            </p>

                            <div class="grid grid-cols-2 gap-3">
                                <button onclick="setDarkReference()" class="flex items-center justify-center gap-2 rounded-2xl bg-slate-700 px-3 py-3 text-xs font-black text-white shadow-lg shadow-slate-700/10 transition hover:-translate-y-0.5 hover:bg-slate-800">
                                    <i class="fa-solid fa-moon"></i>
                                    Dark Al
                                </button>

                                <button onclick="setBlankReference()" class="flex items-center justify-center gap-2 rounded-2xl bg-purple-600 px-3 py-3 text-xs font-black text-white shadow-lg shadow-purple-600/20 transition hover:-translate-y-0.5 hover:bg-purple-700">
                                    <i class="fa-solid fa-vial-circle-check"></i>
                                    Kör / Blank Al
                                </button>
                            </div>

                            <button onclick="resetAverageBuffer()" class="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-slate-200 px-3 py-2.5 text-xs font-black text-slate-800 transition hover:bg-slate-300 dark:bg-slate-800 dark:text-slate-100 dark:hover:bg-slate-700">
                                <i class="fa-solid fa-rotate-left"></i>
                                Ortalama Tamponunu Sıfırla
                            </button>

                            <p class="mt-3 text-xs leading-5 text-slate-500 dark:text-slate-400">
                                Dark: ışık kapalı + kutu kapalı. Blank: ışık açık + kör küvet + kutu kapalı.
                            </p>
                        </div>

                        <div class="mt-4 grid grid-cols-2 gap-3">
                            <button onclick="startMeasurement()" class="flex items-center justify-center gap-2 rounded-2xl bg-emerald-600 px-4 py-3 text-sm font-black text-white shadow-lg shadow-emerald-600/20 transition hover:-translate-y-0.5 hover:bg-emerald-700">
                                <i class="fa-solid fa-play"></i>
                                Başlat
                            </button>

                            <button onclick="stopMeasurement()" class="flex items-center justify-center gap-2 rounded-2xl bg-rose-600 px-4 py-3 text-sm font-black text-white shadow-lg shadow-rose-600/20 transition hover:-translate-y-0.5 hover:bg-rose-700">
                                <i class="fa-solid fa-stop"></i>
                                Durdur
                            </button>
                        </div>

                        <button onclick="clearData()" class="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-amber-500 px-4 py-3 text-sm font-black text-white shadow-lg shadow-amber-500/20 transition hover:-translate-y-0.5 hover:bg-amber-600">
                            <i class="fa-solid fa-trash-can"></i>
                            Tabloyu Temizle
                        </button>

                        <button onclick="downloadCSV()" class="mt-3 flex w-full items-center justify-center gap-2 rounded-2xl bg-blue-600 px-4 py-3 text-sm font-black text-white shadow-lg shadow-blue-600/20 transition hover:-translate-y-0.5 hover:bg-blue-700">
                            <i class="fa-solid fa-file-arrow-down"></i>
                            CSV / Excel İndir
                        </button>
                    </section>

                    <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                        <div class="flex items-center gap-3">
                            <div class="flex h-10 w-10 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                                <i class="fa-solid fa-clipboard-check"></i>
                            </div>

                            <div>
                                <h2 class="text-lg font-black text-slate-950 dark:text-white">
                                    Ölçüm Protokolü
                                </h2>
                                <p class="text-sm text-slate-500 dark:text-slate-400">
                                    Kısa uygulama sırası
                                </p>
                            </div>
                        </div>

                        <ol class="mt-5 space-y-3 text-sm leading-6 text-slate-600 dark:text-slate-300">
                            <li class="flex gap-3">
                                <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-black text-white dark:bg-emerald-500">1</span>
                                Yeşil LED’i manuel olarak aç ve 20–30 saniye bekle.
                            </li>
                            <li class="flex gap-3">
                                <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-black text-white dark:bg-emerald-500">2</span>
                                Işık kapalıyken Dark Al, kör küvet varken Kör / Blank Al.
                            </li>
                            <li class="flex gap-3">
                                <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-black text-white dark:bg-emerald-500">3</span>
                                Numuneleri düşük dozdan yüksek doza doğru ölç.
                            </li>
                            <li class="flex gap-3">
                                <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-black text-white dark:bg-emerald-500">4</span>
                                Her numunede 5–10 satır veri kaydet.
                            </li>
                            <li class="flex gap-3">
                                <span class="flex h-6 w-6 shrink-0 items-center justify-center rounded-full bg-slate-900 text-xs font-black text-white dark:bg-emerald-500">5</span>
                                CSV dosyasını indirip analiz için sakla.
                            </li>
                        </ol>
                    </section>

                </aside>

                <section class="space-y-6">

                    <div class="grid gap-4 md:grid-cols-2 xl:grid-cols-4">

                        <div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                            <div class="flex items-center justify-between">
                                <div class="flex h-11 w-11 items-center justify-center rounded-2xl bg-blue-50 text-blue-700 dark:bg-blue-950/50 dark:text-blue-300">
                                    <i class="fa-solid fa-sun"></i>
                                </div>
                                <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-500 dark:bg-slate-800 dark:text-slate-400">RAW</span>
                            </div>
                            <p class="mt-5 text-sm font-bold text-slate-500 dark:text-slate-400">Raw Visible</p>
                            <p id="raw" class="mt-1 text-3xl font-black tracking-tight text-slate-950 dark:text-white">0.00</p>
                            <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">TSL2591 görünür kanal</p>
                        </div>

                        <div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                            <div class="flex items-center justify-between">
                                <div class="flex h-11 w-11 items-center justify-center rounded-2xl bg-emerald-50 text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                                    <i class="fa-solid fa-percent"></i>
                                </div>
                                <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-500 dark:bg-slate-800 dark:text-slate-400">T%</span>
                            </div>
                            <p class="mt-5 text-sm font-bold text-slate-500 dark:text-slate-400">Transmittance</p>
                            <p id="transmittance" class="mt-1 text-3xl font-black tracking-tight text-slate-950 dark:text-white">0.00%</p>
                            <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">Örnekten geçen ışık</p>
                        </div>

                        <div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                            <div class="flex items-center justify-between">
                                <div class="flex h-11 w-11 items-center justify-center rounded-2xl bg-rose-50 text-rose-700 dark:bg-rose-950/50 dark:text-rose-300">
                                    <i class="fa-solid fa-chart-simple"></i>
                                </div>
                                <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-500 dark:bg-slate-800 dark:text-slate-400">ABS</span>
                            </div>
                            <p class="mt-5 text-sm font-bold text-slate-500 dark:text-slate-400">Absorbance</p>
                            <p id="absorbance" class="mt-1 text-3xl font-black tracking-tight text-slate-950 dark:text-white">0.0000</p>
                            <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">Anlık absorbans</p>
                        </div>

                        <div class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                            <div class="flex items-center justify-between">
                                <div class="flex h-11 w-11 items-center justify-center rounded-2xl bg-violet-50 text-violet-700 dark:bg-violet-950/50 dark:text-violet-300">
                                    <i class="fa-solid fa-gauge-high"></i>
                                </div>
                                <span class="rounded-full bg-slate-100 px-3 py-1 text-xs font-black text-slate-500 dark:bg-slate-800 dark:text-slate-400">AVG</span>
                            </div>
                            <p class="mt-5 text-sm font-bold text-slate-500 dark:text-slate-400">Average Absorbance</p>
                            <p id="avgAbs" class="mt-1 text-3xl font-black tracking-tight text-slate-950 dark:text-white">0.0000</p>
                            <p class="mt-2 text-xs text-slate-500 dark:text-slate-400">Ortalama absorbans</p>
                        </div>

                    </div>

                    <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                        <div class="mb-5 flex flex-col gap-4 md:flex-row md:items-center md:justify-between">
                            <div>
                                <h2 id="chartTitle" class="text-lg font-black text-slate-950 dark:text-white">
                                    Canlı Average Absorbance Grafiği
                                </h2>
                                <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                    Son 80 ölçüm Chart.js ile canlı olarak güncellenir.
                                </p>
                            </div>

                            <select id="graphMode" onchange="setGraphMode()" class="rounded-2xl border border-slate-300 px-4 py-3 text-sm font-extrabold outline-none transition focus:border-emerald-500 focus:ring-4 focus:ring-emerald-500/10 dark:border-slate-700 dark:focus:border-emerald-400">
                                <option style="background:#ffffff;color:#0f172a;" value="average_absorbance">Average Absorbance</option>
                                <option style="background:#ffffff;color:#0f172a;" value="absorbance">Absorbance</option>
                                <option style="background:#ffffff;color:#0f172a;" value="transmittance">Transmittance (%)</option>
                                <option style="background:#ffffff;color:#0f172a;" value="raw">Raw Visible</option>
                            </select>
                        </div>

                        <div class="h-[360px]">
                            <canvas id="liveChart"></canvas>
                        </div>
                    </section>

                    <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                        <div class="mb-5 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                            <div>
                                <h2 class="text-lg font-black text-slate-950 dark:text-white">
                                    Örneklerin Ortalama Absorbans Karşılaştırması
                                </h2>
                                <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                    Kayıtlı ölçümler örnek adına göre gruplanır ve ortalama absorbansları karşılaştırılır.
                                </p>
                            </div>

                            <div class="inline-flex items-center gap-2 rounded-full bg-emerald-50 px-4 py-2 text-sm font-bold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300">
                                <i class="fa-solid fa-layer-group"></i>
                                Örnek bazlı özet
                            </div>
                        </div>

                        <div id="summaryEmpty" class="hidden rounded-2xl border border-dashed border-slate-300 bg-slate-50 p-6 text-center text-sm font-semibold text-slate-500 dark:border-slate-700 dark:bg-slate-950 dark:text-slate-400">
                            Henüz kayıtlı ölçüm yok. Ölçümü Başlat butonuyla veri kaydedin.
                        </div>

                        <div class="h-[360px]">
                            <canvas id="summaryChart"></canvas>
                        </div>
                    </section>

                    <section class="rounded-3xl border border-slate-200 bg-white p-5 shadow-soft dark:border-slate-800 dark:bg-slate-900">
                        <div class="mb-5 flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
                            <div>
                                <h2 class="text-lg font-black text-slate-950 dark:text-white">
                                    Canlı Veri Tablosu
                                </h2>
                                <p class="mt-1 text-sm text-slate-500 dark:text-slate-400">
                                    Kayıt sadece Ölçümü Başlat sonrası tabloya eklenir.
                                </p>
                            </div>

                            <div class="rounded-full bg-slate-100 px-4 py-2 text-sm font-bold text-slate-600 dark:bg-slate-800 dark:text-slate-300">
                                <i class="fa-solid fa-table mr-2"></i>
                                Son 100 kayıt
                            </div>
                        </div>

                        <div class="max-h-[440px] overflow-auto rounded-2xl border border-slate-200 dark:border-slate-800">
                            <table class="min-w-full divide-y divide-slate-200 text-sm dark:divide-slate-800">
                                <thead class="sticky top-0 z-10 bg-slate-900 text-white dark:bg-slate-800">
                                    <tr>
                                        <th class="px-4 py-3 text-left font-black">Zaman</th>
                                        <th class="px-4 py-3 text-left font-black">Örnek</th>
                                        <th class="px-4 py-3 text-right font-black">Raw Visible</th>
                                        <th class="px-4 py-3 text-right font-black">Transmittance (%)</th>
                                        <th class="px-4 py-3 text-right font-black">Absorbance</th>
                                        <th class="px-4 py-3 text-right font-black">Average Absorbance</th>
                                    </tr>
                                </thead>

                                <tbody id="dataTable" class="divide-y divide-slate-100 bg-white dark:divide-slate-800 dark:bg-slate-900"></tbody>
                            </table>
                        </div>
                    </section>

                </section>
            </div>
        </main>
    </div>

<script>
    let graphHistory = [];
    let graphMode = "average_absorbance";
    let liveChart = null;
    let summaryChart = null;

    const graphLabels = {
        raw: "Raw Visible",
        transmittance: "Transmittance (%)",
        absorbance: "Absorbance",
        average_absorbance: "Average Absorbance"
    };

    const graphColors = {
        raw: {
            border: "rgb(37, 99, 235)",
            background: "rgba(37, 99, 235, 0.12)"
        },
        transmittance: {
            border: "rgb(22, 163, 74)",
            background: "rgba(22, 163, 74, 0.12)"
        },
        absorbance: {
            border: "rgb(225, 29, 72)",
            background: "rgba(225, 29, 72, 0.12)"
        },
        average_absorbance: {
            border: "rgb(124, 58, 237)",
            background: "rgba(124, 58, 237, 0.12)"
        }
    };

    const summaryColors = [
        "rgba(37, 99, 235, 0.85)",
        "rgba(22, 163, 74, 0.85)",
        "rgba(225, 29, 72, 0.85)",
        "rgba(217, 119, 6, 0.85)",
        "rgba(124, 58, 237, 0.85)",
        "rgba(8, 145, 178, 0.85)",
        "rgba(190, 18, 60, 0.85)",
        "rgba(71, 85, 105, 0.85)"
    ];

    function isDarkMode() {
        return document.documentElement.classList.contains("dark");
    }

    function chartTextColor() {
        return isDarkMode() ? "#cbd5e1" : "#475569";
    }

    function chartGridColor() {
        return isDarkMode() ? "rgba(148, 163, 184, 0.16)" : "rgba(148, 163, 184, 0.28)";
    }

    function applyChartTheme(chart) {
        if (!chart) return;

        chart.options.plugins.legend.labels.color = chartTextColor();

        if (chart.options.scales && chart.options.scales.x) {
            chart.options.scales.x.ticks.color = chartTextColor();
            chart.options.scales.x.grid.color = chartGridColor();
        }

        if (chart.options.scales && chart.options.scales.y) {
            chart.options.scales.y.ticks.color = chartTextColor();
            chart.options.scales.y.grid.color = chartGridColor();
        }

        chart.update();
    }

    function updateThemeButton() {
        const themeIcon = document.getElementById("themeIcon");
        const themeText = document.getElementById("themeText");

        if (!themeIcon || !themeText) return;

        if (isDarkMode()) {
            themeIcon.className = "fa-solid fa-sun";
            themeText.innerText = "Açık Tema";
        } else {
            themeIcon.className = "fa-solid fa-moon";
            themeText.innerText = "Koyu Tema";
        }
    }

    function toggleTheme() {
        const html = document.documentElement;
        const willBeDark = !html.classList.contains("dark");

        html.classList.toggle("dark", willBeDark);
        localStorage.setItem("theme", willBeDark ? "dark" : "light");

        updateThemeButton();
        applyChartTheme(liveChart);
        applyChartTheme(summaryChart);
    }

    function loadTheme() {
        const savedTheme = localStorage.getItem("theme");

        if (savedTheme === "light") {
            document.documentElement.classList.remove("dark");
        } else {
            document.documentElement.classList.add("dark");
        }

        updateThemeButton();
    }

    function applyPreset() {
        const preset = document.getElementById("samplePreset").value;

        if (preset !== "Diğer") {
            document.getElementById("sampleName").value = preset;
        }
    }

    function setGraphMode() {
        graphMode = document.getElementById("graphMode").value;
        document.getElementById("chartTitle").innerText = "Canlı " + graphLabels[graphMode] + " Grafiği";
        updateLiveChart();
    }

    function initCharts() {
        const liveCtx = document.getElementById("liveChart").getContext("2d");

        liveChart = new Chart(liveCtx, {
            type: "line",
            data: {
                labels: [],
                datasets: [
                    {
                        label: graphLabels[graphMode],
                        data: [],
                        borderColor: graphColors[graphMode].border,
                        backgroundColor: graphColors[graphMode].background,
                        borderWidth: 3,
                        pointRadius: 3,
                        pointHoverRadius: 6,
                        pointBackgroundColor: graphColors[graphMode].border,
                        fill: true,
                        tension: 0.38
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 450,
                    easing: "easeOutQuart"
                },
                interaction: {
                    mode: "index",
                    intersect: false
                },
                plugins: {
                    legend: {
                        display: true,
                        labels: {
                            color: chartTextColor(),
                            usePointStyle: true,
                            boxWidth: 8,
                            font: {
                                family: "Inter",
                                weight: "700"
                            }
                        }
                    },
                    tooltip: {
                        backgroundColor: "rgba(15, 23, 42, 0.95)",
                        titleFont: {
                            family: "Inter",
                            weight: "700"
                        },
                        bodyFont: {
                            family: "Inter"
                        },
                        padding: 12,
                        cornerRadius: 12
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false,
                            color: chartGridColor()
                        },
                        ticks: {
                            color: chartTextColor(),
                            maxTicksLimit: 8,
                            font: {
                                family: "Inter"
                            }
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: chartGridColor()
                        },
                        ticks: {
                            color: chartTextColor(),
                            font: {
                                family: "Inter"
                            }
                        }
                    }
                }
            }
        });

        const summaryCtx = document.getElementById("summaryChart").getContext("2d");

        summaryChart = new Chart(summaryCtx, {
            type: "bar",
            data: {
                labels: [],
                datasets: [
                    {
                        label: "Ortalama Absorbans",
                        data: [],
                        backgroundColor: [],
                        borderRadius: 14,
                        borderSkipped: false
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                animation: {
                    duration: 550,
                    easing: "easeOutQuart"
                },
                plugins: {
                    legend: {
                        display: true,
                        labels: {
                            color: chartTextColor(),
                            usePointStyle: true,
                            boxWidth: 8,
                            font: {
                                family: "Inter",
                                weight: "700"
                            }
                        }
                    },
                    tooltip: {
                        backgroundColor: "rgba(15, 23, 42, 0.95)",
                        titleFont: {
                            family: "Inter",
                            weight: "700"
                        },
                        bodyFont: {
                            family: "Inter"
                        },
                        padding: 12,
                        cornerRadius: 12
                    }
                },
                scales: {
                    x: {
                        grid: {
                            display: false,
                            color: chartGridColor()
                        },
                        ticks: {
                            color: chartTextColor(),
                            font: {
                                family: "Inter",
                                weight: "600"
                            },
                            maxRotation: 35,
                            minRotation: 0
                        }
                    },
                    y: {
                        beginAtZero: true,
                        grid: {
                            color: chartGridColor()
                        },
                        ticks: {
                            color: chartTextColor(),
                            font: {
                                family: "Inter"
                            }
                        }
                    }
                }
            }
        });
    }

    function updateLiveChart() {
        if (!liveChart) return;

        const labels = graphHistory.map(item => item.timeLabel);
        const values = graphHistory.map(item => Number(item[graphMode]));

        liveChart.data.labels = labels;
        liveChart.data.datasets[0].label = graphLabels[graphMode];
        liveChart.data.datasets[0].data = values;
        liveChart.data.datasets[0].borderColor = graphColors[graphMode].border;
        liveChart.data.datasets[0].backgroundColor = graphColors[graphMode].background;
        liveChart.data.datasets[0].pointBackgroundColor = graphColors[graphMode].border;

        liveChart.update();
    }

    function updateSummaryChart(summary) {
        if (!summaryChart) return;

        const emptyBox = document.getElementById("summaryEmpty");

        if (!summary || summary.length === 0) {
            emptyBox.classList.remove("hidden");
            summaryChart.data.labels = [];
            summaryChart.data.datasets[0].data = [];
            summaryChart.update();
            return;
        }

        emptyBox.classList.add("hidden");

        const labels = summary.map(item => {
            const name = item.sample || "Numune";
            return name.length > 20 ? name.slice(0, 20) + "…" : name;
        });

        const values = summary.map(item => Number(item.avg_absorbance));

        summaryChart.data.labels = labels;
        summaryChart.data.datasets[0].data = values;
        summaryChart.data.datasets[0].backgroundColor = summary.map((_, index) => summaryColors[index % summaryColors.length]);

        summaryChart.options.plugins.tooltip.callbacks.label = function(context) {
            const item = summary[context.dataIndex];
            return [
                "Ortalama Absorbans: " + Number(item.avg_absorbance).toFixed(4),
                "Ortalama Raw: " + Number(item.avg_raw).toFixed(2),
                "Ortalama T%: " + Number(item.avg_transmittance).toFixed(2),
                "Ölçüm sayısı: " + item.count
            ];
        };

        summaryChart.update();
    }

    async function fetchLatest() {
        const res = await fetch("/api/latest");
        const data = await res.json();

        document.getElementById("raw").innerText = Number(data.raw).toFixed(2);
        document.getElementById("transmittance").innerText = Number(data.transmittance).toFixed(2) + "%";
        document.getElementById("absorbance").innerText = Number(data.absorbance).toFixed(4);
        document.getElementById("avgAbs").innerText = Number(data.average_absorbance).toFixed(4);

        // Arduino'dan gelen veya panelde tutulan darkRaw değeri güncellenir.
        if (document.getElementById("darkRawValue")) {
            document.getElementById("darkRawValue").innerText = Number(data.dark_raw || 0).toFixed(2);
        }

        // Arduino'dan gelen veya panelde tutulan blankRaw değeri güncellenir.
        if (document.getElementById("blankRawValue")) {
            document.getElementById("blankRawValue").innerText = Number(data.blank_raw || 0).toFixed(2);
        }

        document.getElementById("statusText").innerText = "Durum: " + data.status;

        const connectionPill = document.getElementById("connectionPill");
        const topConnectionBadge = document.getElementById("topConnectionBadge");

        if (data.connected) {
            connectionPill.className = "inline-flex items-center gap-2 rounded-2xl bg-emerald-50 px-4 py-2 text-sm font-bold text-emerald-700 dark:bg-emerald-950/50 dark:text-emerald-300";
            connectionPill.innerHTML = '<span class="h-2.5 w-2.5 rounded-full bg-emerald-500"></span> Arduino bağlı';

            if (topConnectionBadge) {
                topConnectionBadge.className = "hidden items-center gap-2 rounded-full border border-emerald-200 bg-emerald-50 px-4 py-2 text-sm font-semibold text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/50 dark:text-emerald-300 md:inline-flex";
                topConnectionBadge.innerHTML = '<span class="h-2.5 w-2.5 rounded-full bg-emerald-500"></span> Arduino bağlı';
            }
        } else {
            connectionPill.className = "inline-flex items-center gap-2 rounded-2xl bg-rose-50 px-4 py-2 text-sm font-bold text-rose-700 dark:bg-rose-950/50 dark:text-rose-300";
            connectionPill.innerHTML = '<span class="h-2.5 w-2.5 rounded-full bg-rose-500"></span> Arduino bağlantısı yok';

            if (topConnectionBadge) {
                topConnectionBadge.className = "hidden items-center gap-2 rounded-full border border-rose-200 bg-rose-50 px-4 py-2 text-sm font-semibold text-rose-700 dark:border-rose-900/60 dark:bg-rose-950/50 dark:text-rose-300 md:inline-flex";
                topConnectionBadge.innerHTML = '<span class="h-2.5 w-2.5 rounded-full bg-rose-500"></span> Bağlantı yok';
            }
        }

        const measurePill = document.getElementById("measurePill");

        if (data.measuring) {
            measurePill.className = "inline-flex items-center gap-2 rounded-2xl bg-blue-50 px-4 py-2 text-sm font-bold text-blue-700 dark:bg-blue-950/50 dark:text-blue-300";
            measurePill.innerHTML = '<span class="h-2.5 w-2.5 rounded-full bg-blue-500"></span> Kayıt aktif';
        } else {
            measurePill.className = "inline-flex items-center gap-2 rounded-2xl bg-amber-50 px-4 py-2 text-sm font-bold text-amber-700 dark:bg-amber-950/50 dark:text-amber-300";
            measurePill.innerHTML = '<span class="h-2.5 w-2.5 rounded-full bg-amber-500"></span> Kayıt pasif';
        }

        const now = new Date();

        graphHistory.push({
            timeLabel: now.toLocaleTimeString("tr-TR", {hour: "2-digit", minute: "2-digit", second: "2-digit"}),
            raw: Number(data.raw),
            transmittance: Number(data.transmittance),
            absorbance: Number(data.absorbance),
            average_absorbance: Number(data.average_absorbance)
        });

        if (graphHistory.length > 80) {
            graphHistory.shift();
        }

        updateLiveChart();
    }

    async function fetchTable() {
        const res = await fetch("/api/data");
        const rows = await res.json();

        const table = document.getElementById("dataTable");
        table.innerHTML = "";

        if (!rows || rows.length === 0) {
            table.innerHTML = `
                <tr>
                    <td colspan="6" class="px-4 py-8 text-center text-sm font-semibold text-slate-500 dark:text-slate-400">
                        Henüz kayıtlı ölçüm yok. Ölçümü Başlat butonuyla veri kaydedin.
                    </td>
                </tr>`;
            return;
        }

        rows.slice().reverse().forEach(row => {
            table.innerHTML += `
                <tr class="transition hover:bg-slate-50 dark:hover:bg-slate-800/60">
                    <td class="whitespace-nowrap px-4 py-3 text-left font-medium text-slate-600 dark:text-slate-300">${row.time}</td>
                    <td class="whitespace-nowrap px-4 py-3 text-left font-bold text-slate-900 dark:text-white">${row.sample}</td>
                    <td class="whitespace-nowrap px-4 py-3 text-right font-mono text-slate-700 dark:text-slate-200">${Number(row.raw).toFixed(2)}</td>
                    <td class="whitespace-nowrap px-4 py-3 text-right font-mono text-emerald-700 dark:text-emerald-300">${Number(row.transmittance).toFixed(2)}</td>
                    <td class="whitespace-nowrap px-4 py-3 text-right font-mono text-rose-700 dark:text-rose-300">${Number(row.absorbance).toFixed(4)}</td>
                    <td class="whitespace-nowrap px-4 py-3 text-right font-mono text-violet-700 dark:text-violet-300">${Number(row.average_absorbance).toFixed(4)}</td>
                </tr>`;
        });
    }

    async function fetchSummary() {
        const res = await fetch("/api/summary");
        const summary = await res.json();

        updateSummaryChart(summary);
    }

    async function postCalibrationCommand(url, confirmMessage) {
        // Kullanıcı yanlış koşulda referans almasın diye onay penceresi açılır.
        if (!confirm(confirmMessage)) {
            return;
        }

        // Flask API endpointine POST isteği gönderilir.
        const response = await fetch(url, {
            method: "POST"
        });

        // API cevabı JSON olarak okunur.
        const result = await response.json();

        // Kullanıcıya işlem sonucu gösterilir.
        alert(result.message);

        // Son durumu hemen yenilemek için latest verisi tekrar çekilir.
        await fetchLatest();
    }

    async function setDarkReference() {
        // Dark alma işlemi ışık kapalı ve kutu kapalıyken yapılmalıdır.
        await postCalibrationCommand(
            "/api/set_dark",
            "Dark alınacak. Işık kapalı ve kutu kapalı mı?"
        );
    }

    async function setBlankReference() {
        // Blank alma işlemi ışık açık ve kör/blank küvet takılıyken yapılmalıdır.
        await postCalibrationCommand(
            "/api/set_blank",
            "Kör / Blank alınacak. Işık açık, kör küvet takılı ve kutu kapalı mı?"
        );
    }

    async function resetAverageBuffer() {
        // Arduino tarafındaki ortalama hesaplama tamponunu sıfırlar.
        const response = await fetch("/api/reset_average", {
            method: "POST"
        });

        // API cevabı okunur.
        const result = await response.json();

        // Kullanıcıya bilgi verilir.
        alert(result.message);

        // Ekrandaki durum güncellenir.
        await fetchLatest();
    }

    async function setSample() {
        const name = document.getElementById("sampleName").value;

        await fetch("/api/sample", {
            method: "POST",
            headers: {"Content-Type": "application/json"},
            body: JSON.stringify({sample: name})
        });
    }

    async function startMeasurement() {
        await setSample();

        await fetch("/api/start", {
            method: "POST"
        });
    }

    async function stopMeasurement() {
        await fetch("/api/stop", {
            method: "POST"
        });
    }

    async function clearData() {
        if (!confirm("Tablo ve CSV kayıtları temizlensin mi?")) {
            return;
        }

        graphHistory = [];

        await fetch("/api/clear", {
            method: "POST"
        });

        await fetchTable();
        await fetchSummary();
        updateLiveChart();
    }

    function downloadCSV() {
        window.location.href = "/download";
    }

    document.addEventListener("DOMContentLoaded", () => {
        loadTheme();
        initCharts();

        fetchLatest();
        fetchTable();
        fetchSummary();

        setInterval(fetchLatest, 1000);
        setInterval(fetchTable, 2000);
        setInterval(fetchSummary, 2000);
    });
</script>

</body>
</html>
    """, mimetype="text/html")


# =========================================================
# API ENDPOINTLERİ
# =========================================================

@app.route("/api/latest")
def api_latest():
    with state_lock:
        return jsonify(latest_data)


@app.route("/api/data")
def api_data():
    with state_lock:
        return jsonify(data_rows[-100:])


@app.route("/api/summary")
def api_summary():
    with state_lock:
        grouped = {}

        for row in data_rows:
            sample = row.get("sample", "Numune")

            if sample not in grouped:
                grouped[sample] = {
                    "sample": sample,
                    "count": 0,
                    "sum_raw": 0.0,
                    "sum_transmittance": 0.0,
                    "sum_absorbance": 0.0,
                    "sum_average_absorbance": 0.0,
                }

            grouped[sample]["count"] += 1
            grouped[sample]["sum_raw"] += float(row.get("raw", 0.0))
            grouped[sample]["sum_transmittance"] += float(row.get("transmittance", 0.0))
            grouped[sample]["sum_absorbance"] += float(row.get("absorbance", 0.0))
            grouped[sample]["sum_average_absorbance"] += float(row.get("average_absorbance", 0.0))

        summary = []

        for item in grouped.values():
            count = max(item["count"], 1)

            summary.append({
                "sample": item["sample"],
                "count": count,
                "avg_raw": item["sum_raw"] / count,
                "avg_transmittance": item["sum_transmittance"] / count,
                "avg_absorbance": item["sum_average_absorbance"] / count,
            })

        return jsonify(summary)


@app.route("/api/set_dark", methods=["POST"])
def api_set_dark():
    """
    Web paneldeki Dark Al butonuna basıldığında çalışır.

    Kullanım koşulu:
    - LED/ışık kapalı olmalı.
    - Kutu kapağı kapalı olmalı.
    - Küvet yerleşimi ölçüm düzenini bozmayacak şekilde sabit olmalı.

    Bu endpoint Arduino'ya SET_DARK komutu gönderir.
    Arduino, o anki ortalama Raw Visible değerini darkRaw olarak kaydeder.
    """
    ok, message = send_arduino_command("SET_DARK")

    with state_lock:
        latest_data["status"] = message

    status_code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message}), status_code


@app.route("/api/set_blank", methods=["POST"])
def api_set_blank():
    """
    Web paneldeki Kör / Blank Al butonuna basıldığında çalışır.

    Kullanım koşulu:
    - LED/ışık açık olmalı.
    - Kör/blank küvet takılı olmalı.
    - Kutu kapağı kapalı olmalı.

    Bu endpoint Arduino'ya SET_BLANK komutu gönderir.
    Arduino, o anki ortalama Raw Visible değerini blankRaw olarak kaydeder.
    """
    ok, message = send_arduino_command("SET_BLANK")

    with state_lock:
        latest_data["status"] = message

    status_code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message}), status_code


@app.route("/api/get_ref", methods=["POST"])
def api_get_ref():
    """
    Arduino'da kayıtlı mevcut darkRaw ve blankRaw referanslarını istemek için kullanılır.
    Arduino GET_REF komutunu destekliyorsa STATUS,REF,DARK=...,BLANK=... formatında cevap verir.
    """
    ok, message = send_arduino_command("GET_REF")

    with state_lock:
        latest_data["status"] = message

    status_code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message}), status_code


@app.route("/api/reset_average", methods=["POST"])
def api_reset_average():
    """
    Arduino tarafındaki ortalama hesaplama tamponunu sıfırlar.
    Numune değiştirirken ilk birkaç eski değerin ortalamayı etkilemesini azaltmak için kullanılır.
    """
    ok, message = send_arduino_command("RESET_AVG")

    with state_lock:
        latest_data["status"] = message

    status_code = 200 if ok else 500
    return jsonify({"ok": ok, "message": message}), status_code


@app.route("/api/sample", methods=["POST"])
def api_sample():
    global current_sample_name

    data = request.get_json() or {}
    current_sample_name = data.get("sample", "Numune")

    return jsonify({
        "ok": True,
        "sample": current_sample_name
    })


@app.route("/api/start", methods=["POST"])
def api_start():
    global measurement_enabled

    measurement_enabled = True

    with state_lock:
        latest_data["measuring"] = True
        latest_data["status"] = "Ölçüm kaydı başlatıldı."

    return jsonify({
        "ok": True,
        "measuring": True
    })


@app.route("/api/stop", methods=["POST"])
def api_stop():
    global measurement_enabled

    measurement_enabled = False

    with state_lock:
        latest_data["measuring"] = False
        latest_data["status"] = "Ölçüm kaydı durduruldu."

    return jsonify({
        "ok": True,
        "measuring": False
    })


@app.route("/api/clear", methods=["POST"])
def api_clear():
    global data_rows

    with state_lock:
        data_rows = []
        reset_csv()
        latest_data["status"] = "Tablo ve CSV kayıtları temizlendi."

    return jsonify({
        "ok": True
    })


@app.route("/download")
def download():
    prepare_csv()
    return send_file(CSV_FILE, as_attachment=True)


# =========================================================
# UYGULAMA BAŞLATMA
# =========================================================

if __name__ == "__main__":
    prepare_csv()

    thread = threading.Thread(target=read_arduino, daemon=True)
    thread.start()

    app.run(host="127.0.0.1", port=5000, debug=False)