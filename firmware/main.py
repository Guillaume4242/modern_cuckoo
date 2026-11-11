# ==============================================================================
#
#                           🕰️ MODERN CUCKOO 🐦
#
#                     Build Your Own Cuckoo Character
#                Customize Its Look, Sound and Behavior
#
#                         ESP32 • MicroPython • Wi‑Fi • 3D Print your Own Cuckoo
# ==============================================================================
#
#  Features:
#
#   ✅ Servo Animation
#   ✅ Customize Your Cuckoo Figure
#   ✅ Web Configuration Interface
#   ✅ Custom Sound Editor
#   ✅ Night Mode
#   ✅ Timer / Countdown
#   ✅ Wi‑Fi Access Point Fallback
#   ✅ Lifetime Cuckoo Statistics
#   ✅ Flying Distance Statistics
#   ✅ OLED Display Support
#   ✅ Weather Information
#
#  Hardware:
#
#   • ESP32
#   • SG90 Servo
#   • Passive Buzzer
#   • Optional SSD1306 OLED
#
#  Author: Guillaume Anfroy
#
# =====================================================================

import machine
import esp32             # To get ESP32 temperature
from machine import RTC  #allow to set time from the website
import os, gc
import sys
import network
import ntptime           # auto time from internet
import urequests         # For the func auto_timezone()
import ujson
import time
import math
import socket            #website
import _thread
from machine import Pin, PWM, I2C
from ssd1306 import SSD1306_I2C

import secrets

#TODO

# Roadmap V2
#
# More funny music ?
# Mode éco energie aller plus loin ? Ca risque que de ne pas être compatible powerbank. La théorie: Peu importe le temps qu'a pris l'ESP32 pour démarrer et faire chanter le coucou, dès qu'il a fini, il regarde l'heure exacte et calcule le temps exact qu'il reste jusqu'au prochain palier (ex: :00 ou :30).
# WIFI_POWERSAVE = True to be added or not in the web site ?
# Temps de sortie du coucou ?
# Vitesse de sortie du coucou ?
# Alarm ?
# Other informations such as 
# weather et geoloc a conserver ou virer ?
# Cover Design

#+--------------------------+------------------------------+--------------------------------+
#| Component / State        | Status / Configuration       | Current (mA)                   |
#+--------------------------+------------------------------+--------------------------------+
#| ESP32 Core + Wi-Fi (STA) | 160 MHz                      | ~100 - 150 mA  / Hour          |
#| ESP32 Core + Wi-Fi (STA) | 160 MHz + WiFi Power Save    | ~25 - 45 mA  / Hour            |
#| OLED Screen (On)         | Active                       | ~10 - 20 mA  / Hour            |
#| OLED Screen (Off)        | Standby                      | < 1 mA       / Hour            |
#| AP Mode (Cuckoo_Config)  | Active (Offline)             | ~120 - 200 mA   each time      |
#| Servo + Buzzer           | In action (Chimes)           | ~200 - 500 mA (peak) each time |
#+--------------------------+------------------------------+--------------------------------+

# ============================================================
#                 Global Var & Oled Init if there is one
# ============================================================

SSID = secrets.SSID
PASSWORD = secrets.PASSWORD

CONFIG_FILE = "config.json"
OLED_ENABLED = True       #Enable or disable OLED
WEATHER_ENABLED = True    #Enable or disable Getting local Weather
NIGHT_MODE = True         # Enable or disable Night mode. Night mode disable Cuckoo at night between 23:00 and 7:00
NIGHT_START = 23
NIGHT_END = 7
COUCOU_HALF_HOUR = True   # True : Cuckoo goes out also at half time or not
BUZZER_VOLUME = 400       # FROM to 1023 #usually 400
LOCALMDNSNAME= "cuckoo"  # DO NOT ADD .local. It is added automatically by mDNS protocol. Change the name if more than one cuckoo on the same network.
BEEP1 = 262
BEEP2 = 262
BEEP3 = 262
BEEP4 = 146
WIFI_POWERSAVE = True
#--- END VARIABLES ---#

# PIN
SERVO_PIN = 15 # --- Servo ---
SERVO_FREQ = 50
BUZZER_PIN = 13 # --- Buzzer Passif --- Double check it is a passif buzzer
OLED_SCL = 22
OLED_SDA = 21
OLED_WIDTH = 128
OLED_HEIGHT = 64

try:
    i2c = I2C(0, scl=Pin(OLED_SCL), sda=Pin(OLED_SDA)) #Init OLED
    oled = SSD1306_I2C(OLED_WIDTH, OLED_HEIGHT, i2c)
    print("OLED initialized")
except Exception as e:
    OLED_ENABLED = False
    oled = None
    print("OLED init failed:", e)
    
offsets = {"UTC":0,"Europe/Paris":3600,"Europe/Berlin":3600,"Europe/Madrid":3600,"Europe/Rome":3600,"Europe/London":0,"Europe/Lisbon":0,"Europe/Athens":7200,"Europe/Helsinki":7200,"Europe/Moscow":10800,"Africa/Casablanca":0,"Africa/Algiers":3600,"Africa/Tunis":3600,"Africa/Cairo":7200,"Asia/Jerusalem":7200,"Asia/Dubai":14400,"Asia/Kolkata":19800,"Asia/Shanghai":28800,"Asia/Tokyo":32400,"Asia/Singapore":28800,"Asia/Seoul":32400,"Australia/Sydney":36000,"Australia/Perth":28800,"America/New_York":-18000,"America/Chicago":-21600,"America/Denver":-25200,"America/Los_Angeles":-28800,"America/Toronto":-18000,"America/Vancouver":-28800,"America/Sao_Paulo":-10800,"America/Mexico_City":-21600}
#4 values below should stay at None
city = None
temp_ext = None
hum_ext = None
last_weather_hour = None
UNIX_TO_MP = 946684800  # MicroPython ESP32 compte depuis 2000, pas 1970
utc_offset = 0          # décalage horaire, mis à jour dans main()
uptime_ms = 0
_last_tick = time.ticks_ms()   #uptime
TIMER_MAX_MIN = 600
SERVO_IN = 170           # coucou rentré
SERVO_OUT = 0            # coucou sorti
timer_deadline = None    # échéance en ticks_ms, None = pas de minuteur
cuckoo_pos = None        # 'in', 'out' ou None (position inconnue)
chime_lock = _thread.allocate_lock()
TOTAL_CUCKOOS = 0
COUCOU_TRAVEL_CM = 10

# ============================================================
#                 FONCTIONS
# ============================================================

def sound_timer():
    try:
        for _ in range(6):              # 3 séries de 4 bips aigus rapides
            for _ in range(4):
                pitch(1568, 90, 140)     # fréquence, durée (ms), silence (ms)
            pitch(0, 350, 0)            # pause entre les séries
    except Exception as e:
        print("Error timer sound:", e)

def set_timer(minutes):
    global timer_deadline
    if minutes <= 0:
        timer_deadline = None
        return
    minutes = min(minutes, TIMER_MAX_MIN)
    timer_deadline = time.ticks_add(time.ticks_ms(), minutes * 60000)

def timer_left():
    if timer_deadline is None:
        return 0
    return max(0, time.ticks_diff(timer_deadline, time.ticks_ms()) // 1000)

def get_cpu_temp():
    try:
        if hasattr(esp32, "mcu_temperature"):
            return round(esp32.mcu_temperature(), 1)             # déjà en °C
        if hasattr(esp32, "raw_temperature"):
            return round((esp32.raw_temperature() - 32) / 1.8, 1)  # °F -> °C
    except Exception as e:
        print("CPU temp error:", e)
    return None

def update_uptime():
    global uptime_ms, _last_tick
    now = time.ticks_ms()
    uptime_ms += time.ticks_diff(now, _last_tick)
    _last_tick = now

def save_secrets(ssid, password):
    try:
        with open("secrets.py", "w") as f:
            f.write("SSID = {!r}\n".format(ssid))
            f.write("PASSWORD = {!r}\n".format(password))
        print("Secrets saved")
    except Exception as e:
        print("Error saving secrets:", e)

def save_config():
    config = {
        "OLED_ENABLED": OLED_ENABLED,
        "WEATHER_ENABLED": WEATHER_ENABLED,
        "NIGHT_MODE": NIGHT_MODE,
        "COUCOU_HALF_HOUR": COUCOU_HALF_HOUR,
        "BUZZER_VOLUME": BUZZER_VOLUME,
        "LOCALMDNSNAME": LOCALMDNSNAME,
        "BEEP1": BEEP1, "BEEP2": BEEP2, "BEEP3": BEEP3, "BEEP4": BEEP4,
        "NIGHT_START": NIGHT_START,
        "NIGHT_END": NIGHT_END,
        "TOTAL_CUCKOOS": TOTAL_CUCKOOS,
    }
    tmp = CONFIG_FILE + ".tmp"
    try:
        gc.collect()
        data = ujson.dumps(config)          # si ça plante, rien n'est modifié
        with open(tmp, "w") as f:
            f.write(data)
        try:
            os.rename(tmp, CONFIG_FILE)
        except OSError:                     # système de fichiers FAT : pas d'écrasement
            os.remove(CONFIG_FILE)
            os.rename(tmp, CONFIG_FILE)
        print("Configuration saved")
    except Exception as e:
        print("Error saving config:", e)

def load_config():
    global OLED_ENABLED
    global WEATHER_ENABLED
    global NIGHT_MODE
    global NIGHT_START
    global NIGHT_END
    global COUCOU_HALF_HOUR
    global BUZZER_VOLUME
    global LOCALMDNSNAME
    global BEEP1, BEEP2, BEEP3, BEEP4
    global TOTAL_CUCKOOS

    try:
        with open(CONFIG_FILE, "r") as f:
            cfg = ujson.load(f)

        OLED_ENABLED      = cfg.get("OLED_ENABLED", OLED_ENABLED)
        WEATHER_ENABLED   = cfg.get("WEATHER_ENABLED", WEATHER_ENABLED)
        NIGHT_MODE        = cfg.get("NIGHT_MODE", NIGHT_MODE)
        NIGHT_START       = cfg.get("NIGHT_START", NIGHT_START)
        NIGHT_END         = cfg.get("NIGHT_END", NIGHT_END)
        COUCOU_HALF_HOUR  = cfg.get("COUCOU_HALF_HOUR", COUCOU_HALF_HOUR)
        BUZZER_VOLUME     = cfg.get("BUZZER_VOLUME", BUZZER_VOLUME)
        LOCALMDNSNAME     = cfg.get("LOCALMDNSNAME", LOCALMDNSNAME)
        BEEP1             = cfg.get("BEEP1", BEEP1)
        BEEP2             = cfg.get("BEEP2", BEEP2)
        BEEP3             = cfg.get("BEEP3", BEEP3)
        BEEP4             = cfg.get("BEEP4", BEEP4)
        TOTAL_CUCKOOS     = cfg.get("TOTAL_CUCKOOS", 0)

        print("Configuration loaded")

    except OSError:
        print("config.json not found, using defaults")

    except ValueError:
       print("config.json corrompu, suppression")
       try: os.remove(CONFIG_FILE)
       except OSError: pass

    except Exception as e:
        print("Error loading config:", e)

def apply_settings(query):
    for p in query.split("&"):
        if "=" not in p:
            continue
        key, val = p.split("=", 1)
        try:
            if key == "b1":
                globals()["BEEP1"] = int(val)
            elif key == "b2":
                globals()["BEEP2"] = int(val)
            elif key == "b3":
                globals()["BEEP3"] = int(val)
            elif key == "b4":
                globals()["BEEP4"] = int(val)
            elif key == "volume":
                v = int(val)
                globals()["BUZZER_VOLUME"] = max(0, min(v, 1022))
            elif key == "night":
                globals()["NIGHT_MODE"] = (val == "1")
            elif key == "ns":
                globals()["NIGHT_START"] = max(0, min(int(val), 23))
            elif key == "ne":
                globals()["NIGHT_END"] = max(0, min(int(val), 23))
            elif key == "half":
                globals()["COUCOU_HALF_HOUR"] = (val == "1")
            elif key == "oled":
                globals()["OLED_ENABLED"] = (val == "1")
                if oled is not None:
                    if OLED_ENABLED:
                        oled.poweron()
                    else:
                        oled.poweroff() # To save energy
            elif key == "weather":
                globals()["WEATHER_ENABLED"] = (val == "1")
        except ValueError:
            # Champ vide ou valeur invalide : on ignore ce paramètre
            pass

def start_webserver():
    addr = socket.getaddrinfo("0.0.0.0", 80)[0][-1]
    s = socket.socket()
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(addr)
    s.listen(1)
    print("Webserver started on http://", addr)

    while True:
        cl = None
        try:
            cl, addr = s.accept()
            cl.settimeout(5)
            request = cl.recv(1024).decode('utf-8', 'ignore')
            if not request:
                cl.close()
                continue
            
            # --- Sortie du coucou ---
            if "GET /coucou" in request:
                sort_coucou_sound(1)
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
                cl.send("<h1>Cuckoo triggered!</h1><a href='/'>Back</a>")
                     
            # --- Test des sons (sans enregistrer) ---
            elif "GET /test?" in request:
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK")
                cl.close()
                cl = None
                try:
                    params = request.split("GET /test?")[1].split(" ")[0]
                    names = ("BEEP1", "BEEP2", "BEEP3", "BEEP4", "BUZZER_VOLUME")
                    old = {n: globals()[n] for n in names}
                    try:
                        apply_settings(params)
                        sort_coucou_sound(1)
                    finally:
                        globals().update(old)
                except Exception as e:
                    print("test error:", e)
                continue
            
            elif "GET /starwars" in request:
                BuzzerStarWars()
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
                cl.send("<h1>Star Wars music played!</h1><a href='/'>Back</a>")

            # --- État du coucou pour la page d'accueil ---
            elif "GET /status" in request:
                update_uptime()
                sta_if = network.WLAN(network.STA_IF)
                rssi = None
                if sta_if.isconnected():
                    try:
                        rssi = sta_if.status("rssi")
                    except Exception:
                        pass
                lt = time.localtime(time.time() + utc_offset)
                body = ujson.dumps({
                    "time": "{:02d}:{:02d}".format(lt[3], lt[4]),
                    "temp": temp_ext if WEATHER_ENABLED else None,
                    "hum": hum_ext if WEATHER_ENABLED else None,
                    "cpu": get_cpu_temp(),
                    "rssi": rssi,
                    "up": uptime_ms // 1000,
                    "total": TOTAL_CUCKOOS,
                    "distance_km": round((TOTAL_CUCKOOS * COUCOU_TRAVEL_CM) / 100000, 2),
                })
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n")
                cl.send(body)
            
            elif "GET /timer" in request:
                try:
                    if "GET /timer?" in request:
                        params = request.split("GET /timer?")[1].split(" ")[0]
                        for p in params.split("&"):
                            if p.startswith("min="):
                                set_timer(int(p[4:]))
                    cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\nCache-Control: no-store\r\n\r\n")
                    cl.send(ujson.dumps({"left": timer_left()}))
                except Exception as e:
                    print("timer error:", e)
                    cl.send("HTTP/1.0 400 Bad Request\r\nContent-Type: text/plain\r\n\r\nBad request")
            
            elif "GET /cuckoo_out" in request:
                cuckoo_hold_out()
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK")

            elif "GET /cuckoo_in" in request:
                cuckoo_pull_in()
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK")
            
            # --- API JSON pour envoyer la config à l'interface web ---
            elif "GET /config" in request:
                sta_if = network.WLAN(network.STA_IF)
                is_ap = not sta_if.isconnected()
                
                config_data = ujson.dumps({
                    "ssid": SSID,
                    "password": PASSWORD,
                    "host": LOCALMDNSNAME,
                    "b1": BEEP1, "b2": BEEP2, "b3": BEEP3, "b4": BEEP4,
                    "volume": BUZZER_VOLUME,
                    "night": 1 if NIGHT_MODE else 0,
                    "half": 1 if COUCOU_HALF_HOUR else 0,
                    "oled": 1 if OLED_ENABLED else 0,
                    "weather": 1 if WEATHER_ENABLED else 0,
                    "ns": NIGHT_START,
                    "ne": NIGHT_END,
                    "ap_mode": is_ap
                })
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: application/json\r\n\r\n")
                cl.send(config_data)
            
             # --- Réglage de l'heure depuis le téléphone ---
            elif "GET /settime?" in request:
                try:
                    params = request.split("GET /settime?")[1].split(" ")[0]
                    q = {}
                    for p in params.split("&"):
                        if "=" in p:
                            k, v = p.split("=", 1)
                            q[k] = int(v)
                    if q.get("t", 0) < UNIX_TO_MP:
                        raise ValueError("t invalide")
                    set_time_from_phone(q["t"], q.get("tz", 0))
                    cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/plain\r\n\r\nOK")
                except Exception as e:
                    print("settime error:", e)
                    cl.send("HTTP/1.0 400 Bad Request\r\nContent-Type: text/plain\r\n\r\nBad request")
            
            # --- Mise à jour des paramètres ---
            elif "GET /set?" in request:
                try:
                    params = request.split("GET /set?")[1].split(" ")[0]
                    apply_settings(params)
                    save_config()
                    cl.send("HTTP/1.0 303 See Other\r\nLocation: /\r\n\r\n")
                except Exception as e:
                    print("set error:", e)
                    cl.send("HTTP/1.0 400 Bad Request\r\nContent-Type: text/plain\r\n\r\nBad request")
                    
            # --- Mise à jour WiFi ---
            elif "GET /setwifi?" in request:
                try:
                    params = request.split("GET /setwifi?")[1].split(" ")[0]
                    new_ssid = SSID
                    new_password = PASSWORD
                    for p in params.split("&"):
                        if "=" in p:
                            key, val = p.split("=", 1)
                            if key == "ssid":
                                new_ssid = val
                            elif key == "password":
                                new_password = val
                    save_secrets(new_ssid, new_password)
                    cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
                    cl.send("<h1>WiFi settings saved. Rebooting...</h1>")
                    cl.close()
                    time.sleep(2)
                    machine.reset()
                except Exception as e:
                    print("setwifi error:", e)
                    
            # --- Reboot ESP32 ---
            elif "GET /reboot" in request:
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
                cl.send("<h1>Rebooting...</h1>")
                cl.close()
                machine.reset()

            # --- Page principale (Lecture de index.html par blocs de 512 octets) ---
            else:
                gc.collect()
                cl.send("HTTP/1.0 200 OK\r\nContent-Type: text/html\r\n\r\n")
                try:
                    with open("index.html", "rb") as f:
                        while True:
                            chunk = f.read(512)
                            if not chunk:
                                break
                            cl.send(chunk)
                except Exception as e:
                    print("Error sending index.html:", e)
        
        except Exception as e:
            print("Webserver error:", e)
        finally:
            if cl:
                try:
                    cl.close()
                except:
                    pass
            gc.collect()
            
def set_time_from_phone(t, tz_minutes):
    RTC_IN_UTC = False
    # t = epoch Unix en secondes (UTC), tz_minutes = décalage du téléphone
    secs = t - UNIX_TO_MP + tz_minutes * 60   # heure locale
    y, mo, d, h, mi, s, wd, _ = time.gmtime(secs)
    RTC().datetime((y, mo, d, wd, h, mi, s, 0))

def show_msgoled(message):
    max_chars = 16
    ligne = 0
    
    print (message) #Print serial
    if not OLED_ENABLED or oled is None:
        return 
    
    oled.fill(0) #Print oled then split in 16 chars messages. 16 chars is the max per line
    for i in range(0, len(message), max_chars):  
        morceau = message[i:i+max_chars]
        oled.text(morceau, 0, ligne)
        ligne += 10   # Goes down 10 pixels for next line
    oled.show()

def start_ap_mode():
    sta = network.WLAN(network.STA_IF)
    network.hostname(LOCALMDNSNAME)
    sta.active(False)   # Disable standard Wifi
    
    ap = network.WLAN(network.AP_IF)
    ap.active(True)
    ap.config(essid="Cuckoo_Config", password="12345678")
    ip = ap.ifconfig()[0]   # <-- Récupération de l'IP AP
    show_msgoled("AP Mode: Cuckoo_Config Password 12345678 IP:" + str(ap.ifconfig()[0]))
    time.sleep(2)
    return ap

def connect_wifi(ssid, password):
    wifi = network.WLAN(network.STA_IF)
    
    wifi.active(False)  # reset WiFi
    time.sleep(0.5)
    network.hostname(LOCALMDNSNAME)
    wifi.active(True)
    wifi.config(hostname=LOCALMDNSNAME)  
      
    show_msgoled("Connecting WiFi:")
    wifi.connect(ssid, password) 
    
    timeout = 0
    while not wifi.isconnected():
        time.sleep(0.2)
        timeout += 1

        # --- TIMEOUT : bascule en mode AP ---
        if timeout > 100:   # 20 secondes
            show_msgoled("WiFi FAIL -> AP mode")
            return start_ap_mode()
    
    try:
        if WIFI_POWERSAVE:
            mode = network.WLAN.PM_POWERSAVE
            print("Enabling WLAN Power Save")
        else:
            mode = network.WLAN.PM_NONE
            print("NO WLAN Power Save")
        wifi.config(pm=mode)
    except Exception as e:
        print("Error power saving :", e)
    
    # --- CONNECTÉ ---
    show_msgoled("Connected to internet: " + str(wifi.ifconfig()) + " http://" + str(network.hostname()) + ".local")
    time.sleep(2)
    return wifi

#True if europoean summer timer is active UTC as input
def eu_dst(utc_secs):
    y = time.gmtime(utc_secs)[0]
    def last_sunday(month):
        t = time.mktime((y, month, 31, 1, 0, 0, 0, 0))     # Days of the week for the 31 (0 = Monday)
        wd = time.gmtime(t)[6]
        return t - ((wd + 1) % 7) * 86400
    return last_sunday(3) <= utc_secs < last_sunday(10)

def get_offset_from_timezone(tz):
    base = offsets.get(tz, 0)
    if tz.startswith("Europe/") and eu_dst(time.time()):
        base += 3600
    return base

def auto_timezone():
    try:
        r = urequests.get("http://ipinfo.io/json")
        data = r.json()
        r.close()

        timezone = data.get("timezone", "UTC")   # ex: "Europe/Paris"
        show_msgoled("Timezone détected :" + str(timezone))

        ntptime.settime()

        # Convert time zone to oddset         # Exemple: Europe/Paris → UTC+1 ou UTC+2
        offset = get_offset_from_timezone(timezone)
        show_msgoled("Offset:" + str(offset))
        return offset

    except Exception as e:
        show_msgoled("Error auto_timezone and setting time:" + str(e))
        return None

def update_weather():
    global city, temp_ext, hum_ext, lat, lon
    lat = None
    lon = None

    try:
        r = urequests.get("http://ip-api.com/json")     # --- Géolocalisation ---
        geo = r.json()
        r.close()

        city = geo.get("city", "?")
        lat  = geo.get("lat", None)
        lon  = geo.get("lon", None)
        print(f"{city} {lat} {lon}")
    except Exception as e:
        show_msgoled("GeoLoc Error :" + str(e))
        return city, None, None

    if lat is not None and lon is not None:
        try:
            url = ("http://api.open-meteo.com/v1/forecast?" 
                f"latitude={lat}&longitude={lon}&current=temperature_2m,relative_humidity_2m")
            r2 = urequests.get(url)
            meteo = r2.json()
            r2.close()
            print(meteo)  # debug
            temp_ext = meteo["current"]["temperature_2m"]
            hum_ext  = meteo["current"]["relative_humidity_2m"]
            print("OK météo :", city, temp_ext, hum_ext)
        except Exception as e:
            show_msgoled("Weather Error :" + str(e))
            return
    return

def display_time_date_weather(offset):
    global last_weather_hour
    
    t = time.localtime(time.time() + offset)
    hour, minute, second = t[3], t[4], t[5]
    day, month, year = t[2], t[1], t[0]

    # Weather once per hour at minute 1
    if minute == 1 and hour != last_weather_hour and WEATHER_ENABLED:
        update_weather()
        last_weather_hour = hour

    oled.fill(0)
    oled.text(f"{hour:02d}:{minute:02d}:{second:02d}", 0, 0)
    oled.text(f"{day:02d}/{month:02d}/{year}", 0, 18)
    if temp_ext is not None and hum_ext is not None and city is not None and WEATHER_ENABLED:
        oled.text(city[:16], 0, 30)
        oled.text(f"{temp_ext}C  {hum_ext}%", 0, 42)
    elif WEATHER_ENABLED:
        oled.text("Weather unavail.", 0, 42)
    oled.show()

def set_angle(servo, angle):
    pulse_ms = 0.5 + (angle / 180) * 2.0     #PPut the servo between 0 and 180 deg
    duty = int((pulse_ms / 20.0) * 65535)
    servo.duty_u16(duty)

# Sinusoid movement for the servo
def move_servo_sinus(servo, start, end, duration=0.8, steps=80):
    for i in range(steps + 1):
        t = i / steps
        s = 0.5 - 0.5 * math.cos(math.pi * t)         # interpolation sinusoidale (ease-in / ease-out)
        angle = start + (end - start) * s
        set_angle(servo, angle)
        time.sleep(duration / steps)

def sound_cuckoo():
    buz = None
    try:
        buz = PWM(Pin(BUZZER_PIN))
        for freq, pause in ((BEEP1, 90), (BEEP2, 260), (BEEP3, 90), (BEEP4, 0)):
            buz.freq(freq)
            buz.duty(BUZZER_VOLUME)
            time.sleep_ms(150)
            buz.duty(0)
            time.sleep_ms(pause)
    except Exception as e:
        print("Error buzzer (bad PIN or PWM) :", e)
    finally:
        if buz:
            try:
                buz.deinit()
            except:
                passv
                
def _servo_open():
    s = machine.PWM(machine.Pin(SERVO_PIN))
    s.freq(SERVO_FREQ)
    return s

def _servo_close(s):
    if s:
        try:
            s.deinit()
        except:
            pass
                
#Takeout cuckoo as many time as requested
def sort_coucou_sound(heure, sound=None):
    global cuckoo_pos
    global TOTAL_CUCKOOS
    
    if sound is None:
        sound = sound_cuckoo
    with chime_lock:                     # une seule action servo à la fois
        servo = None
        try:
            servo = _servo_open()
            if heure > 12:
                heure -= 12
            show_msgoled("Cuckoo in action")
            if cuckoo_pos != 'in':       # remise en place si dehors ou inconnu
                move_servo_sinus(servo, SERVO_OUT, SERVO_IN, duration=0.8)
                cuckoo_pos = 'in'
                time.sleep(1)
            for i in range(heure):
                move_servo_sinus(servo, SERVO_IN, SERVO_OUT, duration=0.8)
                cuckoo_pos = 'out'
                sound()
                TOTAL_CUCKOOS += 1
                if TOTAL_CUCKOOS % 10 == 0:
                    save_config()
                time.sleep(1)
                move_servo_sinus(servo, SERVO_OUT, SERVO_IN, duration=0.8)
                cuckoo_pos = 'in'
                if i < heure - 1:
                    time.sleep(1)
        except Exception as e:
            cuckoo_pos = None
            print("Erreur servo coucou :", e)
        finally:
            try:
                move_servo_sinus(servo, SERVO_OUT, SERVO_IN, duration=0.5) #force at the end the cuockoo to come back 
                cuckoo_pos = 'in'
            except:
                pass
            _servo_close(servo)

def cuckoo_hold_out():
    global cuckoo_pos
    with chime_lock:
        if cuckoo_pos == 'out':
            return
        servo = None
        try:
            servo = _servo_open()
            move_servo_sinus(servo, SERVO_IN, SERVO_OUT, duration=0.8)
            cuckoo_pos = 'out'
        except Exception as e:
            cuckoo_pos = None
            print("Erreur sortie coucou :", e)
        finally:
            _servo_close(servo)

def cuckoo_pull_in():
    global cuckoo_pos
    with chime_lock:
        if cuckoo_pos == 'in':
            return
        servo = None
        try:
            servo = _servo_open()
            move_servo_sinus(servo, SERVO_OUT, SERVO_IN, duration=0.8)
            cuckoo_pos = 'in'
        except Exception as e:
            cuckoo_pos = None
            print("Erreur rentrée coucou :", e)
        finally:
            _servo_close(servo)

def pitch(noteFrequency, noteDuration, silence_ms=10):
    buz = Pin(BUZZER_PIN, Pin.OUT)

    if noteFrequency != 0:
        period_us = int(1000000 / noteFrequency)
        high_us = period_us * BUZZER_VOLUME // 1023   # 0 = muet, 512 = 50 % (max)
        low_us = period_us - high_us
        cycles = int(noteDuration * noteFrequency / 1000)
        for _ in range(cycles):
            buz.on()
            time.sleep_us(high_us)
            buz.off()
            time.sleep_us(low_us)
    else:
        time.sleep_ms(noteDuration)
    time.sleep_ms(silence_ms)

#Other way to play music. DOES NOT ALLOW EASY VOLUME CHANGE
def BuzzerStarWars():
  NOTES = [293.66, 293.66, 293.66, 392.0, 622.25, 554.37, 523.25, 454, 932.32, 622.25, 554.37, 523.25, 454, 932.32, 622.25, 554.37, 523.25, 554.37, 454]
  DURATIONS = [180, 180, 180, 800, 800, 180, 180, 180, 800, 400, 180, 180, 180, 800, 400, 180, 180, 180, 1000]
  SILENCE_DELAYS = [40, 40, 40, 100, 100, 40, 40, 40, 100, 50, 40, 40, 40, 100, 50, 40, 40, 40, 100]
  for i in range(len(NOTES)):
    pitch(NOTES[i], DURATIONS[i], SILENCE_DELAYS[i])

def main():
    global utc_offset
    last_hour_triggered = -1
    last_half_triggered = -1
    
    load_config()
    
    sort_coucou_sound(1) # Take cuckoo one time at starting
    
    net = connect_wifi(SSID, PASSWORD)
    offset = auto_timezone()
    if offset is None:
        offset = 0
    utc_offset = offset
    _thread.start_new_thread(start_webserver, ())
    
    if WEATHER_ENABLED:
        update_weather()
     
    while True:
        try:
            update_uptime()
            if oled and OLED_ENABLED:
                display_time_date_weather(offset)
        
            t = time.localtime(time.time() + offset)
            hour = t[3]
            minute = t[4]
            second = t[5]
            if hour == 0 :
                hour = 24
            
            if timer_deadline is not None and time.ticks_diff(time.ticks_ms(), timer_deadline) >= 0:
                set_timer(0)
                sort_coucou_sound(1, sound_timer)
            
            if NIGHT_MODE:
                if NIGHT_START <= hour <= 24 or 1 <= hour < NIGHT_END:
                    time.sleep(1)
                    continue
                
            if minute == 0 and hour != last_hour_triggered:
                sort_coucou_sound(hour)
                last_hour_triggered = hour
                try:
                    ntptime.settime()
                    print("NTP resync")
                except OSError as e:
                    print("NTP Sync failure :", e)
                
            if COUCOU_HALF_HOUR and minute == 30 and hour != last_half_triggered:
                sort_coucou_sound(1)
                last_half_triggered = hour

            time.sleep(0.5)
            
        except Exception as e:
            print("Error Main loop:")
            sys.print_exception(e)
            if OLED_ENABLED and oled:
                oled.fill(0)
                oled.text("Error Main loop", 0, 0)
                oled.text(str(e)[:16], 0, 12)   # évite dépassement
                oled.show()
            time.sleep(0.5)
        
# Point d'entrée
main()