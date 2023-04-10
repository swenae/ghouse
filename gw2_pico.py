#------------------------------------------------------------------------------#
#                                                                              #
# Project:           Greenhouse control with Raspberry Pi Pico W               #
# Module:            gw2_pico.py (all in one main module main.py)              #
# Author:            swen (Swen Hopfe, dj)                                     #
# Created:           22-12-02                                                  #
# Last updated:      23-04-10                                                  #
#                                                                              #
# This is the "greenhouse" script using RPi Pico W and Micropython,            #
# working with several hardware and providing a HTTP webserver.                #
# This source script comes with german comments.                               #
#                                                                              #
#------------------------------------------------------------------------------#

from machine import I2C, Pin, RTC
from micropython import const
import network
import uasyncio as asyncio
import time, ntptime
from time import sleep_ms
import onewire, ds18x20
from random import randint

#-------------------------------------------------------------------------------

GDEBUG           = False     # Debug-Modus (wirkt nur auf print-Ausgaben im Terminal an USB-Host)

NUM_I2C          = 3         # Anzahl der zu erwartenden I2C-Geraete

NUM_1W           = 2         # Anzahl der zu erwartenden 1W-Geraete

WRITE_EEPROM     = False     # EEPROM fest im Script schreiben (in der Entwicklungsphase)

WEB_PERMIT       = False     # Austausch mit Web abschalten (Trotzdem auf Internet-Zugang testen)

#-------------------------------------------------------------------------------
# globaler Counter fuer jeden Turn um 1 erhoeht

gc               = 0

# globales Error-Flag

efl = False

#-------------------------------------------------------------------------------
# Werte im EEPROM gespeichert

mot_duration     = 30        # Laufzeit Fensterheber (sec)

# Es darf mehr als der benoetigte Wert eingestellt werden, da die Fensterheber eigene Endschalter haben
# Aus Sicherheitsgruenden ist aktuell jedoch ein Wert knapp unterhalb der Ausschaltgrenze eingestellt

t_win_f_open     = 30.0      # Obere Temperatur zum Fenster oeffnen (Fruehling: 30.0)
t_win_f_close    = 22.0      # Untere Temperatur zum Fenster schliessen (Fruehling: 22.0)

t_win_s_open     = 32.0      # Obere Temperatur zum Fenster oeffnen (Sommer: 32.0)
t_win_s_close    = 24.0      # Untere Temperatur zum Fenster schliessen (Sommer: 24.0)

t_win_h_open     = 30.0      # Obere Temperatur zum Fenster oeffnen (Herbst: 30.0)
t_win_h_close    = 22.0      # Untere Temperatur zum Fenster schliessen (Herbst: 24.0)

t_wcut_close     = 13.0      # Schliessen der Fenster auf Grund Aussentemperatur (Waermespeicher tsave wird aktiviert)

t_heat_off       = 8.0       # Heizung aus
t_heat_on        = 6.0       # Heizung ein

t_vc_on          = 36.0      # Ventilator ein bei geschlossenem Oberlicht (Tuer)
t_vc_off         = 35.0      # Ventilator aus bei geschlossenem Oberlicht (Tuer)

t_vo_on          = 40.0      # Ventilator ein bei offenem Oberlicht (Tuer)
t_vo_off         = 39.0      # Ventilator aus bei offenem Oberlicht (Tuer)

# Im EEPROM werden fuer Temperaturen derzeit nur ganzzahlige Werte (0-255) gespeichert
# Im Winter (eigentlich ausser Betrieb) gelten die Herbst-Zeiten und -temperaturen

ct_hour          = 18        # Stunde zum unbedingten Schliessen der Fenster
ct_min           = 30        # Minute zum unbedingten Schliessen der Fenster

# Uhrzeit zum Schliessen der Fenster am Abend unabhaengig der Innentemperatur

tcorr_in         = 0.4       # Korrektur Temperatur Innenfuehler
tcorr_out        = 0.4       # Korrektur Temperatur Aussenfuehler

# Gespeichert wird ein Byte mit Addition von 3.0 und Multiplikator 10
# Es koennen Korrekturen von inklusive -3.0 bis +9.0 Grad vorgenommen werden

#-------------------------------------------------------------------------------
# Extremwerte zur Temperaturwarnung, die ins Error-Log geschrieben wird

ex_unten         = 2.0
ex_oben          = 45.0

# Aussentemperatur-Anstieg, der die Waermespeicher-Funktion wieder abschaltet

t_tsave          = 5.0

#-------------------------------------------------------------------------------
# Jahreszeit (zur Anpassung der Lueftungsfunktion)

year_time = 0

# 0 - Fruehjahr
# 1 - Sommer
# 2 - Herbst
# 3 - Winter

#-------------------------------------------------------------------------------
# WiFi-Verbindung

ssid = "swlan371"
password = "1461131146113145"

#-------------------------------------------------------------------------------
# Versionsbildschirm

shstr1 = "********************"
shstr2 = "* GHAUS  Steuerung *"
shstr3 = "* R2.0    10.04.23 *"
shstr4 = "********************"

#-------------------------------------------------------------------------------
# Stati

# Web-Verbindung
webcon           = False

# Von Heizung, Ventilator, Fenster
heat_on          = False
vent_on          = False
wins_open        = False

# Oberlicht (GPIO15, Tuer zu - 0 (GPIO auf Masse durch Taster), Tuer offen - 1 (GPIO auf 3V3 intern gepullt))
tval             = 1  # offen, Normalzustand

# Manuelle Schaltungen aktiv
heat_manu        = False
vent_manu        = False
wins_manu        = False

# obere oder untere Grad-Grenze erreicht
err_ugrad        = False
err_ograd        = False

# Sensorenwerte
temp_innen       = 00.0
temp_aussen      = 00.0

temp_min_innen   = 00.0
temp_max_innen   = 00.0

temp_ok          = True

# Waermespeicher (Fenster)
tsave            = False

# Schliesszeit Fenster erreicht
wdtime           = False

#-------------------------------------------------------------------------------
# GPIOs

# GPIO - Uebersicht
#
#  0  -  SDA (I2C-Bus)
#  1  -  SCL (I2C-Bus)
#
# 12  -  LED Rot
# 13  -  LED Gelb
# 14  -  LED Gruen
#
# 15  -  Tuerkontakt
# 17  -  OneWire (Tempsensoren)
#                           |-----------------|------------------|--------------------|
# 18  -  Relais1 Fenster 1a | ein = nach oben | aus = nach unten | aus = Ruhestellung |
# 19  -  Relais2 Fenster 1b | aus = nach oben | ein = nach unten | aus = Ruhestellung |
#                           |-----------------|------------------|--------------------|
# 20  -  Relais3 Fenster 2a | ein = nach oben | aus = nach unten | aus = Ruhestellung |
# 21  -  Relais4 Fenster 2b | aus = nach oben | ein = nach unten | aus = Ruhestellung |
#                           |-----------------|------------------|--------------------|
# 22  -  Relais5 Ventilator
# 26  -  Relais6 Heizung


# LEDs
led_r = Pin(12, Pin.OUT)
led_y = Pin(13, Pin.OUT)
led_g = Pin(14, Pin.OUT)

led_r.value(1)
led_y.value(1)
led_g.value(1)

# Tuerkontakt
tuer = Pin(15, Pin.IN, Pin.PULL_UP)

# Relais-Board
rel01 = Pin(18, Pin.OUT)
rel02 = Pin(19, Pin.OUT)
rel03 = Pin(20, Pin.OUT)
rel04 = Pin(21, Pin.OUT)
rel05 = Pin(22, Pin.OUT)
rel06 = Pin(26, Pin.OUT)

rel01.value(1)
rel02.value(1)
rel03.value(1)
rel04.value(1)
rel05.value(1)
rel06.value(1)

#-------------------------------------------------------------------------------
# Verschiedenes

# Speicherwerte Web-App - ausgewaehlter Parameter
psel = 0

# letzte Meldungen
msg_txt = ["","","","","","","","","",""]

# Fehlerspeicher
err_txt = ["","",""]

#-------------------------------------------------------------------------------
# Meldungsspeicher fuellen

def msg(msg_str, timeflag):

    # Im Gegensatz zum Fehlerspeicher gibt es hier keine kurze (20 Zeichen), sondern nur die Langversion (45 Zeichen),
    # da der Meldungspeicher nicht ueber LCD sondern nur ueber Web (und bei Bedarf ueber Terminal zu Debugzwecken) angezeigt werden soll.
    # Im LCD werden hingegen (derzeit) immer nur die aktuellen Aktionen angezeigt, zusaetzlich zum Status- und Fehlerbildschirm.

    msg_str = msg_str + "                                                  "
    if timeflag == 1:
        it = rtc.datetime()
        msgtime    ="{:02}.{:02}.{:04} {:02}:{:02}:{:02} ".format(it[2], it[1], it[0], it[4], it[5], it[6])
        # Log auf maximal 45 Zeichen kuerzen, Datum-String hat 20 Zeichen, bleiben 25 Zeichen Text.
        msg_txt.insert(0,msgtime + msg_str[:30])
    if timeflag == 0:
        msg_txt.insert(0,msg_str[:45])

    msg_txt.pop()

#-------------------------------------------------------------------------------
# Errorhandler, Fehlerspeicher fuellen

def err_hndl(err):

    global err_ograd, err_ugrad

    # Ins Fehler-Log (Liste err_txt mit drei Eintraegen) kommt die kurze Zeit (errlcdtime), damit es auch ueber LCD anzeigbar bleibt.
    # Fuer die print-Ausgaben ins Terminal (nur zu Debug-Zwecken) kommt der lange Zeitstring und es wird laenger formuliert mit Praefix "FEHLER".

    it = rtc.datetime()
    errtime    ="{:02}.{:02}.{:04} {:02}:{:02}:{:02} ".format(it[2], it[1], it[0], it[4], it[5], it[6])
    errlcdtime ="E{:02}{:02}{:02}{:02} ".format(it[2], it[1], it[4], it[5])

    if  err == 1:
        led_r.value(0)
        print("FEHLER: " + errtime + "I2C-Bus")
        # fuer LCD max 20 Zeichen inklusive Datum |1234567890| Es bleiben 10 Zeichen Text.
        err_txt.insert(0, errlcdtime +            "I2C-Bus   ")
        err_txt.pop()
    elif err == 2:
        led_r.value(0)      
        print("FEHLER: " + errtime + "OneWire-Bus/DS18B20")
        # fuer LCD max 20 Zeichen inklusive Datum |1234567890| Es bleiben 10 Zeichen Text.
        err_txt.insert(0, errlcdtime +            "1W/DS18B20")
        err_txt.pop()
    elif err == 3:
        led_y.value(0)
        print("WARNUNG: " + errtime + "Keine Verbindung zum Web")
        # fuer LCD max 20 Zeichen inklusive Datum |1234567890| Es bleiben 10 Zeichen Text.
        err_txt.insert(0, errlcdtime +            "Offline   ")
        err_txt.pop()
    elif err == 4:
      if err_ugrad == False:
        led_y.value(0)
        print("WARNUNG: " + errtime + "Untere Grad-Grenze erreicht")
        # fuer LCD max 20 Zeichen inklusive Datum |1234567890| Es bleiben 10 Zeichen Text.
        err_txt.insert(0, errlcdtime +            "< " + str(ex_unten) + " Grad  ")
        err_txt.pop()
        err_ugrad = True
    elif err == 5:
      if err_ograd == False:
        led_y.value(0)
        print("WARNUNG: " + errtime + "Obere Grad-Grenze erreicht")
        # fuer LCD max 20 Zeichen inklusive Datum |1234567890| Es bleiben 10 Zeichen Text.
        err_txt.insert(0, errlcdtime +            "> " + str(ex_oben) + " Grad ")
        err_txt.pop()
        err_ograd = True
    elif  err == 6:
        led_r.value(0)
        print("FEHLER: " + errtime + "Speicherfehler")
        # fuer LCD max 20 Zeichen inklusive Datum |1234567890| Es bleiben 10 Zeichen Text.
        err_txt.insert(0, errlcdtime +            "MEM-Error ")
        err_txt.pop()
    else :
        print("FEHLER: Unbekannter Fehler.")

    if temp_innen > ex_unten : err_ugrad = False
    if temp_innen < ex_oben  : err_ograd = False

#-------------------------------------------------------------------------------
# Logs bei Bedarf als Debugausgaben ins Terminal

def showlogs():

    global msg_txt, err_txt

    # Fehlertext ausgeben
    print("letzte Fehler:    | {} | {} | {} |".format(err_txt[0],err_txt[1],err_txt[2]))
    # Messages ausgeben
    print("letzte Meldungen: | {} | {} |".format(msg_txt[0],msg_txt[1]))
    print("letzte Meldungen: | {} | {} |".format(msg_txt[2],msg_txt[3]))
    print("letzte Meldungen: | {} | {} |".format(msg_txt[4],msg_txt[5]))
    print("letzte Meldungen: | {} | {} |".format(msg_txt[6],msg_txt[7]))
    print("letzte Meldungen: | {} | {} |".format(msg_txt[8],msg_txt[9]))

#-------------------------------------------------------------------------------
# Temperaturen der DS18B20-Sensoren abfragen

def read_temp(pr = True):

    global temp_innen, temp_aussen

    tc = 0
    ds.convert_temp()
    time.sleep_ms(750)
    for rom in roms:
        tc += 1
        if(tc == 1): temp_innen = round(ds.read_temp(rom),1) + tcorr_in
        if(tc == 2): temp_aussen = round(ds.read_temp(rom),1) + tcorr_out
    if pr: print("Innen-Temp: {}".format(temp_innen))
    if pr: print("Außen-Temp: {}".format(temp_aussen))

#-------------------------------------------------------------------------------
# Min/Max-Werte festhalten und Ueberschreitung Grenzwerte abfragen

def ex_vals():

    global temp_innen, ex_unten, ex_oben, temp_max_innen, temp_min_innen, temp_ok

    if temp_innen < temp_min_innen : temp_min_innen = temp_innen
    if temp_innen > temp_max_innen : temp_max_innen = temp_innen

    temp_ok = True

    if temp_innen < ex_unten :
        temp_ok = False
        print("Innentemperatur kleiner {} Grad.".format(ex_unten))
        err_hndl(4)

    if temp_innen > ex_oben :
        temp_ok = False
        print("Innentemperatur groesser {} Grad.".format(ex_oben))
        err_hndl(5)

#-------------------------------------------------------------------------------
# Fenstersteuerung

#                |-------------------|--------------------|----------------------|
# rel01.value()  | 0/ein = nach oben | 1/aus = nach unten | 1/aus = Ruhestellung |
# rel02.value()  | 1/aus = nach oben | 0/ein = nach unten | 1/aus = Ruhestellung |
#                |-------------------|--------------------|----------------------|
# rel03.value()  | 0/ein = nach oben | 1/aus = nach unten | 1/aus = Ruhestellung |
# rel04.value()  | 1/aus = nach oben | 0/ein = nach unten | 1/aus = Ruhestellung |
#                |-------------------|--------------------|----------------------|

def gh_win():

  global wins_open, t_wcut_close, tsave, t_tsave, wdtime
  global temp_innen, temp_aussen
  global t_win_f_open, t_win_f_close
  global t_win_s_open, t_win_s_close
  global t_win_h_open, t_win_h_close
  global ct_hour, ct_min, it

  # Pruefe, ob etwa Abendzeit zum Fensterschliessen erreicht
  if it[4] == ct_hour and it[5] >= ct_min : wdtime = True
  if it[4] == 23 : wdtime = False # Hebe Schliessen um 23Uhr auf
  if wdtime :
      if GDEBUG : print("Abendzeit, Fenster bleiben geschlossen.")

  if wins_manu == False:

    # Jahreszeitliche Abhaengigkeit
    if year_time == 0:
        t_win_open = t_win_f_open
        t_win_close = t_win_f_close
    elif year_time == 1:
        t_win_open = t_win_s_open
        t_win_close = t_win_s_close
    elif year_time == 2:
        t_win_open = t_win_h_open
        t_win_close = t_win_h_close
    elif year_time == 3:
        t_win_open = t_win_h_open
        t_win_close = t_win_h_close

    # Fenster oeffnen

    if temp_innen >= t_win_open and tsave == False and wdtime == False:
        if wins_open == False:
            print("Oeffne Fenster.")
            msg("Oeffne Fenster", 1)
            rel01.value(0)
            rel02.value(1)
            rel03.value(0)
            rel04.value(1)

            led_g.value(0)
            time.sleep(mot_duration)
            
            rel01.value(1)
            rel02.value(1)
            rel03.value(1)
            rel04.value(1)

            led_g.value(1)

        else:
            if GDEBUG: print("Fenster weiterhin offen.")
        wins_open = True

    # Fenster schliessen

    if temp_innen <= t_win_close or temp_aussen <= t_wcut_close or wdtime :
        if wins_open == True:

            if temp_aussen <= t_wcut_close :

                print("Schliesse Fenster auf Grund Aussentemperatur (Waermespeicher).")
                msg("Schliesse Fenster (Waermespeicher)", 1)
                # Waermespeicherfunktion
                # nun muss das Oeffnen pausieren (tsave), bis Aussentemperatur wieder
                # auf mehr als t_tsave (5) Grad steigt (siehe unten), damit die Fenster nicht gleich wieder aufgehen
                tsave = True

            elif wdtime :
                
                print("Schliesse Fenster auf Grund Abendzeit.")
                msg("Schliesse Fenster (Abendzeit)", 1)
                # auch hier soll nicht gleich wieder geoeffnet und Waerme gespeichert werden
                # deshalb steht das Flag wdtime wie tsave mit in der Oeffnen-Abfrage oben
                
            else:
                print("Schliesse Fenster.")
                msg("Schliesse Fenster", 1)
                
            rel01.value(1)
            rel02.value(0)
            rel03.value(1)
            rel04.value(0)
            
            led_g.value(0)           
            time.sleep(mot_duration)
            
            rel01.value(1)
            rel02.value(1)
            rel03.value(1)
            rel04.value(1)

            led_g.value(1)           

        else:
            if GDEBUG: print("Fenster weiterhin geschlossen.")
        wins_open = False
        
  # Waermespeicher-Flag loeschen, wenn Aussentemperatur t_tsave Grad hoeher als das Limit t_wcut_close ist 
  if temp_aussen >= t_wcut_close + t_tsave :
      tsave = False
  if tsave :
      if GDEBUG : print("Waermespeicher, Fenster bleiben geschlossen.")

#-------------------------------------------------------------------------------
# Ventilator (Relais5)

def gh_vent():

    global tval
    global vent_on
    global temp_innen
    global t_vc_on, t_vc_off
    global t_vo_on, t_vo_off

    if vent_manu == False:

        # Bei geschlossenem Oberlicht (Tuer zu)
        if tval:
            if temp_innen >= t_vc_on  :
                if vent_on == False:
                    print("Schalte Ventilator ein. (Tür zu).")
                    msg("Ventilator ein", 1)
                else:
                    if GDEBUG: print("Ventilator weiterhin an.")
                vent_on = True
                rel05.value(0)

            if temp_innen <= t_vc_off :
                if vent_on == True:
                    print("Schalte Ventilator aus. (Tür zu).")
                    msg("Ventilator aus", 1)
                else:
                    if GDEBUG: print("Ventilator weiterhin aus.")
                vent_on = False
                rel05.value(1)

        # Bei offenem Oberlicht (Tuer auf)
        else:
            if temp_innen >= t_vo_on  :
                if vent_on == False:
                    print("Schalte Ventilator ein. (Tür auf).")
                    msg("Ventilator ein", 1)
                else:
                    if GDEBUG: print("Ventilator weiterhin an.")
                vent_on = True
                rel05.value(0)

            if temp_innen <= t_vo_off :
                if vent_on == True:
                    print("Schalte Ventilator aus. (Tür auf).")
                    msg("Ventilator aus", 1)
                else:
                    if GDEBUG: print("Ventilator weiterhin aus.")
                vent_on = False
                rel05.value(1)

#-------------------------------------------------------------------------------
# Heizung (Relais6)

def gh_heat():

    global heat_on
    global temp_innen
    global t_heat_on, t_heat_off

    if heat_manu == False:

        if temp_innen <= t_heat_on  :
            if heat_on == False:
                print("Schalte Heizung ein.")
                msg("Heizung ein", 1)
            else:
                if GDEBUG: print("Heizung weiterhin an.")
            heat_on = True
            rel06.value(0)

        if temp_innen >= t_heat_off :
            if heat_on == True:
                print("Schalte Heizung aus.")
                msg("Heizung aus", 1)
            else:
                if GDEBUG: print("Heizung weiterhin aus.")
            heat_on = False
            rel06.value(1)

#-------------------------------------------------------------------------------
# Uhren aktualisieren, Jahreszeit-Ermittlung

def act_clocks():

    global webcon, year_time

    if webcon:
        # Wenn WLAN und folgend WWW praesent, dann interne und externe
        # Echtzeituhr nach Internetzeit per NTP-Server stellen
        try:
            ntptime.settime()
        except:
            print("[CLK xx] Fehler beim Zeit holen ueber NTP-Server, neuer Versuch (2)...")
            time.sleep(1)
            try:
                ntptime.settime()
            except:
                print("[CLK xx] Fehler beim Zeit holen ueber NTP-Server, neuer Versuch (3)...")
                time.sleep(1)
                try:
                    ntptime.settime()
                except:
                    print("[CLK xx] Fehler beim Zeit holen ueber NTP-Server, neuer Versuch (4)...")
                    time.sleep(1)
                    try:
                        ntptime.settime()
                    except:
                        print("[CLK xx] Fehler beim Zeit holen ueber NTP-Server (outtimed)...")

        UTC_OFFSET = +1 * 60 * 60 # Zeitzone fuer Deutschland (Winterzeit/Normalzeit)
        lt1 = time.localtime(time.time() + UTC_OFFSET)
        #datetime-Format    localtime-Format
        #dt Jahr         0  lt Jahr
        #dt Monat        1  lt Monat
        #dt Tag          2  lt Tag
        #dt Wochentag    3  lt Stunde
        #dt Stunde       4  lt Minute
        #dt Minute       5  lt Sekunde
        #dt Sekunde      6  lt Wochentag
        #dt Millisekunde 7  lt Millisekunde
        dt1 = [0, 0, 0, 0, 0, 0, 0, 0]
        dt1[0] = lt1[0]
        dt1[1] = lt1[1]
        dt1[2] = lt1[2]
        dt1[3] = lt1[6]
        dt1[4] = lt1[3]
        dt1[5] = lt1[4]
        dt1[6] = lt1[5]
        dt1[7] = lt1[7]
        now = (dt1[0], dt1[1], dt1[2], dt1[3], dt1[4], dt1[5], dt1[6], dt1[7])
        ertc.datetime(now)
        time.sleep(1)
        rtc.datetime(now)
        time.sleep(1)

    else:
        # Wenn kein Internet da, dann Basiszeit von externer RTC holen
        now = ertc.datetime()
        time.sleep(1)
        rtc.datetime(now)
        time.sleep(1)

    rtimelist=rtc.datetime()
    mon = int(rtimelist[1])
    if mon >= 3 and mon <= 5 :
        year_time = 0
        print("[CLK 08] Jahreszeit Frühling (3-5) ermittelt.")
    if mon >= 6 and mon <= 8 :
        year_time = 1
        print("[CLK 08] Jahreszeit Sommer (6-8) ermittelt.")
    if mon >= 9 and mon <= 11 :
        year_time = 2
        print("[CLK 08] Jahreszeit Herbst (9-11) ermittelt.")
    if mon == 12 or mon <= 2 :
        year_time = 3
        print("[CLK 08] Jahreszeit Winter (12-2) ermittelt.")

#-------------------------------------------------------------------------------
# LCD-Ausgabe per x/y-Koordinate mit Loeschung Screen bei Bedarf

def printlcd(lx, ly, lstr, lc):

    if lc == 1 : lcd.clear()
    lcd.move_to(lx, ly)
    lcd.putstr(lstr[:20])
    sleep_ms(300)

#-------------------------------------------------------------------------------
# Status per LCD, Standard-Bildschirm

def showlcd_stats():
    global tval, wins_open, vent_on, it
    global temp_innen, temp_aussen, heat_on

    ti = str(temp_innen)
    ta = str(temp_aussen)
    if len(ti) < 4: ti = " "+ti
    if len(ta) < 4: ti = " "+ta

    if wins_open:
        printlcd(0, 0, ti + " T-INN| FNST auf", 1)
    else:
        printlcd(0, 0, ti + " T-INN| FNST unt", 1)
    if vent_on:
        printlcd(0, 1, ta + " T-AUS| VENT ein", 0)
    else:
        printlcd(0, 1, ta + " T-AUS| VENT aus", 0)
    if heat_on:
        if tval:
            printlcd(0, 2, "TUER    zu| "    + "HEIZ ein", 0)
        else:
            printlcd(0, 2, "TUER offen| "    + "HEIZ ein", 0)
    else:
        if tval:
            printlcd(0, 2, "TUER    zu| "    + "HEIZ aus", 0)
        else:
            printlcd(0, 2, "TUER offen| "    + "HEIZ aus", 0)

    printlcd(0, 3, "GZeit {:02}.{:02}.{:02} {:02}:{:02}".format(it[2], it[1], str(it[0])[2:], it[4], it[5]), 0)

#-------------------------------------------------------------------------------
# Einstellwerte per LCD

def showlcd_params():

    global mot_duration, year_time
    global t_win_f_open, t_win_f_close
    global t_win_s_open, t_win_s_close
    global t_win_h_open, t_win_h_close
    global ct_hour, ctmin
    global t_heat_on, t_heat_off
    global t_vc_on, t_vc_off, t_wcut_close

    yts = "---"
    if year_time == 0 :
        yts = "FR"
    if year_time == 1 :
        yts = "SO"
    if year_time == 2 :
        yts = "HR"
    if year_time == 3 :
        yts = "WT"

    printlcd(13,  0, "|MZ {}".format(mot_duration), 1)
    printlcd(13,  1, "|JZ {}".format(yts), 0)
    printlcd(13,  2, "|WC {:0}".format(t_wcut_close), 0)
    printlcd(13,  3, "|C{}:{}".format(ct_hour, ct_min), 0)

    printlcd(0,  0, "WF {:0}".format(t_win_f_open), 0)
    printlcd(0,  1, "WS {:0}".format(t_win_s_open), 0)
    printlcd(0,  2, "WH {:0}".format(t_win_h_open), 0)
    printlcd(0,  3, "CR {:0}".format(tcorr_in), 0)

    printlcd(6, 0, "|VE {:0}".format(t_vc_on), 0)
    printlcd(6, 1, "|VA {:0}".format(t_vc_off), 0)
    printlcd(6, 2, "|HE {:0}".format(t_heat_on), 0)
    printlcd(6, 3, "|HA {:0}".format(t_heat_off), 0)

#-------------------------------------------------------------------------------
# Fehlerspeicher-Bildschirm per LCD

def errlcd():

    printlcd(0, 0, " FEHLER / WARNUNGEN", 1)
    printlcd(0, 1, err_txt[0], 0)
    printlcd(0, 2, err_txt[1], 0)
    printlcd(0, 3, err_txt[2], 0)

    if len(err_txt[0])<1 and len(err_txt[1])<1 and len(err_txt[2])<1:
        printlcd(0, 2, "       Keine.", 0)

#-------------------------------------------------------------------------------
# DS1307-RTC

DATETIME_REG = const(0) # 0x00-0x06
CHIP_HALT    = const(128)
CONTROL_REG  = const(7) # 0x07
RAM_REG      = const(8) # 0x08-0x3F

class DS1307(object):
    """Driver for the DS1307 RTC."""
    def __init__(self, i2c, addr=0x68):
        self.i2c = i2c
        self.addr = addr
        self.weekday_start = 1
        self._halt = False

    def _dec2bcd(self, value):
        """Convert decimal to binary coded decimal (BCD) format"""
        return (value // 10) << 4 | (value % 10)

    def _bcd2dec(self, value):
        """Convert binary coded decimal (BCD) format to decimal"""
        return ((value >> 4) * 10) + (value & 0x0F)

    def datetime(self, datetime=None):
        """Get or set datetime"""
        if datetime is None:
            buf = self.i2c.readfrom_mem(self.addr, DATETIME_REG, 7)
            return (
                self._bcd2dec(buf[6]) + 2000, # year
                self._bcd2dec(buf[5]), # month
                self._bcd2dec(buf[4]), # day
                self._bcd2dec(buf[3] - self.weekday_start), # weekday
                self._bcd2dec(buf[2]), # hour
                self._bcd2dec(buf[1]), # minute
                self._bcd2dec(buf[0] & 0x7F), # second
                0 # subseconds
            )
        buf = bytearray(7)
        buf[0] = self._dec2bcd(datetime[6]) & 0x7F # second, msb = CH, 1=halt, 0=go
        buf[1] = self._dec2bcd(datetime[5]) # minute
        buf[2] = self._dec2bcd(datetime[4]) # hour
        buf[3] = self._dec2bcd(datetime[3] + self.weekday_start) # weekday
        buf[4] = self._dec2bcd(datetime[2]) # day
        buf[5] = self._dec2bcd(datetime[1]) # month
        buf[6] = self._dec2bcd(datetime[0] - 2000) # year
        if (self._halt):
            buf[0] |= (1 << 7)
        self.i2c.writeto_mem(self.addr, DATETIME_REG, buf)

    def halt(self, val=None):
        """Power up, power down or check status"""
        if val is None:
            return self._halt
        reg = self.i2c.readfrom_mem(self.addr, DATETIME_REG, 1)[0]
        if val:
            reg |= CHIP_HALT
        else:
            reg &= ~CHIP_HALT
        self._halt = bool(val)
        self.i2c.writeto_mem(self.addr, DATETIME_REG, bytearray([reg]))

    def square_wave(self, sqw=0, out=0):
        """Output square wave on pin SQ at 1Hz, 4.096kHz, 8.192kHz or 32.768kHz,
        or disable the oscillator and output logic level high/low."""
        rs0 = 1 if sqw == 4 or sqw == 32 else 0
        rs1 = 1 if sqw == 8 or sqw == 32 else 0
        out = 1 if out > 0 else 0
        sqw = 1 if sqw > 0 else 0
        reg = rs0 | rs1 << 1 | sqw << 4 | out << 7
        self.i2c.writeto_mem(self.addr, CONTROL_REG, bytearray([reg]))

#-------------------------------------------------------------------------------
# EEPROM AT24C32N auf DS1307-RTC

class AT24C32N(object):

    def __init__(self, i2c, i2c_addr=0x50, pages=128, bpp=32):
        self.i2c = i2c
        self.i2c_addr = i2c_addr
        self.pages = pages
        self.bpp = bpp # bytes per page

    def capacity(self):
        """Storage capacity in bytes"""
        return self.pages * self.bpp

    def read(self, addr, nbytes):
        """Read one or more bytes from the EEPROM starting from a specific address"""
        return self.i2c.readfrom_mem(self.i2c_addr, addr, nbytes, addrsize=16)

    def write(self, addr, buf):
        """Write one or more bytes to the EEPROM starting from a specific address"""
        offset = addr % self.bpp
        partial = 0
        # partial page write
        if offset > 0:
            partial = self.bpp - offset
            self.i2c.writeto_mem(self.i2c_addr, addr, buf[0:partial], addrsize=16)
            time.sleep_ms(5)
            addr += partial
        # full page write
        for i in range(partial, len(buf), self.bpp):
            self.i2c.writeto_mem(self.i2c_addr, addr+i-partial, buf[i:i+self.bpp], addrsize=16)
            time.sleep_ms(5)

#-------------------------------------------------------------------------------
# I2C-LCD-Display

class LcdApi:
    # HD44780 LCD controller command set

    LCD_CLR = 0x01              # DB0: clear display
    LCD_HOME = 0x02             # DB1: return to home position

    LCD_ENTRY_MODE = 0x04       # DB2: set entry mode
    LCD_ENTRY_INC = 0x02        # --DB1: increment
    LCD_ENTRY_SHIFT = 0x01      # --DB0: shift

    LCD_ON_CTRL = 0x08          # DB3: turn lcd/cursor on
    LCD_ON_DISPLAY = 0x04       # --DB2: turn display on
    LCD_ON_CURSOR = 0x02        # --DB1: turn cursor on
    LCD_ON_BLINK = 0x01         # --DB0: blinking cursor

    LCD_MOVE = 0x10             # DB4: move cursor/display
    LCD_MOVE_DISP = 0x08        # --DB3: move display (0-> move cursor)
    LCD_MOVE_RIGHT = 0x04       # --DB2: move right (0-> left)

    LCD_FUNCTION = 0x20         # DB5: function set
    LCD_FUNCTION_8BIT = 0x10    # --DB4: set 8BIT mode (0->4BIT mode)
    LCD_FUNCTION_2LINES = 0x08  # --DB3: two lines (0->one line)
    LCD_FUNCTION_10DOTS = 0x04  # --DB2: 5x10 font (0->5x7 font)
    LCD_FUNCTION_RESET = 0x30   # See "Initializing by Instruction" section

    LCD_CGRAM = 0x40            # DB6: set CG RAM address
    LCD_DDRAM = 0x80            # DB7: set DD RAM address

    LCD_RS_CMD = 0
    LCD_RS_DATA = 1

    LCD_RW_WRITE = 0
    LCD_RW_READ = 1

    def __init__(self, num_lines, num_columns):
        self.num_lines = num_lines
        if self.num_lines > 4:
            self.num_lines = 4
        self.num_columns = num_columns
        if self.num_columns > 40:
            self.num_columns = 40
        self.cursor_x = 0
        self.cursor_y = 0
        self.implied_newline = False
        self.backlight = True
        self.display_off()
        self.backlight_on()
        self.clear()
        self.hal_write_command(self.LCD_ENTRY_MODE | self.LCD_ENTRY_INC)
        self.hide_cursor()
        self.display_on()

    def clear(self):
        """Clears the LCD display and moves the cursor to the top left
        corner.
        """
        self.hal_write_command(self.LCD_CLR)
        self.hal_write_command(self.LCD_HOME)
        self.cursor_x = 0
        self.cursor_y = 0

    def show_cursor(self):
        """Causes the cursor to be made visible."""
        self.hal_write_command(self.LCD_ON_CTRL | self.LCD_ON_DISPLAY |
                               self.LCD_ON_CURSOR)

    def hide_cursor(self):
        """Causes the cursor to be hidden."""
        self.hal_write_command(self.LCD_ON_CTRL | self.LCD_ON_DISPLAY)

    def blink_cursor_on(self):
        """Turns on the cursor, and makes it blink."""
        self.hal_write_command(self.LCD_ON_CTRL | self.LCD_ON_DISPLAY |
                               self.LCD_ON_CURSOR | self.LCD_ON_BLINK)

    def blink_cursor_off(self):
        """Turns on the cursor, and makes it no blink (i.e. be solid)."""
        self.hal_write_command(self.LCD_ON_CTRL | self.LCD_ON_DISPLAY |
                               self.LCD_ON_CURSOR)

    def display_on(self):
        """Turns on (i.e. unblanks) the LCD."""
        self.hal_write_command(self.LCD_ON_CTRL | self.LCD_ON_DISPLAY)

    def display_off(self):
        """Turns off (i.e. blanks) the LCD."""
        self.hal_write_command(self.LCD_ON_CTRL)

    def backlight_on(self):
        """Turns the backlight on.

        This isn't really an LCD command, but some modules have backlight
        controls, so this allows the hal to pass through the command.
        """
        self.backlight = True
        self.hal_backlight_on()

    def backlight_off(self):
        """Turns the backlight off.

        This isn't really an LCD command, but some modules have backlight
        controls, so this allows the hal to pass through the command.
        """
        self.backlight = False
        self.hal_backlight_off()

    def move_to(self, cursor_x, cursor_y):
        """Moves the cursor position to the indicated position. The cursor
        position is zero based (i.e. cursor_x == 0 indicates first column).
        """
        self.cursor_x = cursor_x
        self.cursor_y = cursor_y
        addr = cursor_x & 0x3f
        if cursor_y & 1:
            addr += 0x40    # Lines 1 & 3 add 0x40
        if cursor_y & 2:    # Lines 2 & 3 add number of columns
            addr += self.num_columns
        self.hal_write_command(self.LCD_DDRAM | addr)

    def putchar(self, char):
        """Writes the indicated character to the LCD at the current cursor
        position, and advances the cursor by one position.
        """
        if char == '\n':
            if self.implied_newline:
                # self.implied_newline means we advanced due to a wraparound,
                # so if we get a newline right after that we ignore it.
                self.implied_newline = False
            else:
                self.cursor_x = self.num_columns
        else:
            self.hal_write_data(ord(char))
            self.cursor_x += 1
        if self.cursor_x >= self.num_columns:
            self.cursor_x = 0
            self.cursor_y += 1
            self.implied_newline = (char != '\n')
        if self.cursor_y >= self.num_lines:
            self.cursor_y = 0
        self.move_to(self.cursor_x, self.cursor_y)

    def putstr(self, string):
        """Write the indicated string to the LCD at the current cursor
        position and advances the cursor position appropriately.
        """
        for char in string:
            self.putchar(char)

    def custom_char(self, location, charmap):
        """Write a character to one of the 8 CGRAM locations, available
        as chr(0) through chr(7).
        """
        location &= 0x7
        self.hal_write_command(self.LCD_CGRAM | (location << 3))
        self.hal_sleep_us(40)
        for i in range(8):
            self.hal_write_data(charmap[i])
            self.hal_sleep_us(40)
        self.move_to(self.cursor_x, self.cursor_y)

    def hal_backlight_on(self):
        """Allows the hal layer to turn the backlight on.

        If desired, a derived HAL class will implement this function.
        """
        pass

    def hal_backlight_off(self):
        """Allows the hal layer to turn the backlight off.

        If desired, a derived HAL class will implement this function.
        """
        pass

    def hal_write_command(self, cmd):
        """Write a command to the LCD.

        It is expected that a derived HAL class will implement this
        function.
        """
        raise NotImplementedError

    def hal_write_data(self, data):
        """Write data to the LCD.

        It is expected that a derived HAL class will implement this
        function.
        """
        raise NotImplementedError

    # This is a default implementation of hal_sleep_us which is suitable
    # for most micropython implementations. For platforms which don't
    # support `time.sleep_us()` they should provide their own implementation
    # of hal_sleep_us in their hal layer and it will be used instead.
    def hal_sleep_us(self, usecs):
        """Sleep for some time (given in microseconds)."""
        time.sleep_us(usecs)  # NOTE this is not part of Standard Python library, specific hal layers will need to override this

# The PCF8574 has a jumper selectable address: 0x20 - 0x27
DEFAULT_I2C_ADDR = 0x27

# Defines shifts or masks for the various LCD line attached to the PCF8574

MASK_RS = 0x01
MASK_RW = 0x02
MASK_E = 0x04
SHIFT_BACKLIGHT = 3
SHIFT_DATA = 4

class I2cLcd(LcdApi):
    """Implements a HD44780 character LCD connected via PCF8574 on I2C."""

    def __init__(self, i2c, i2c_addr, num_lines, num_columns):
        self.i2c = i2c
        self.i2c_addr = i2c_addr
        self.i2c.writeto(self.i2c_addr, bytearray([0]))
        sleep_ms(20)   # Allow LCD time to powerup
        # Send reset 3 times
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        sleep_ms(5)    # need to delay at least 4.1 msec
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        sleep_ms(1)
        self.hal_write_init_nibble(self.LCD_FUNCTION_RESET)
        sleep_ms(1)
        # Put LCD into 4 bit mode
        self.hal_write_init_nibble(self.LCD_FUNCTION)
        sleep_ms(1)
        LcdApi.__init__(self, num_lines, num_columns)
        cmd = self.LCD_FUNCTION
        if num_lines > 1:
            cmd |= self.LCD_FUNCTION_2LINES
        self.hal_write_command(cmd)

    def hal_write_init_nibble(self, nibble):
        """Writes an initialization nibble to the LCD.
        This particular function is only used during initialization.
        """
        byte = ((nibble >> 4) & 0x0f) << SHIFT_DATA
        self.i2c.writeto(self.i2c_addr, bytearray([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytearray([byte]))

    def hal_backlight_on(self):
        """Allows the hal layer to turn the backlight on."""
        self.i2c.writeto(self.i2c_addr, bytearray([1 << SHIFT_BACKLIGHT]))

    def hal_backlight_off(self):
        """Allows the hal layer to turn the backlight off."""
        self.i2c.writeto(self.i2c_addr, bytearray([0]))

    def hal_write_command(self, cmd):
        """Writes a command to the LCD.
        Data is latched on the falling edge of E.
        """
        byte = ((self.backlight << SHIFT_BACKLIGHT) | (((cmd >> 4) & 0x0f) << SHIFT_DATA))
        self.i2c.writeto(self.i2c_addr, bytearray([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytearray([byte]))
        byte = ((self.backlight << SHIFT_BACKLIGHT) | ((cmd & 0x0f) << SHIFT_DATA))
        self.i2c.writeto(self.i2c_addr, bytearray([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytearray([byte]))
        if cmd <= 3:
            # The home and clear commands require a worst case delay of 4.1 msec
            sleep_ms(5)

    def hal_write_data(self, data):
        """Write data to the LCD."""
        byte = (MASK_RS | (self.backlight << SHIFT_BACKLIGHT) | (((data >> 4) & 0x0f) << SHIFT_DATA))
        self.i2c.writeto(self.i2c_addr, bytearray([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytearray([byte]))
        byte = (MASK_RS | (self.backlight << SHIFT_BACKLIGHT) | ((data & 0x0f) << SHIFT_DATA))
        self.i2c.writeto(self.i2c_addr, bytearray([byte | MASK_E]))
        self.i2c.writeto(self.i2c_addr, bytearray([byte]))

#-------------------------------------------------------------------------------
# EEPROM schreiben
# Mit Werten vorbelegen (im Betrieb spaeter auskommentieren)

def wepr():

    global mot_duration
    global t_win_f_open, t_win_f_close
    global t_win_s_open, t_win_s_close
    global t_win_h_open, t_win_h_close
    global t_wcut_close
    global t_heat_off, t_heat_on
    global t_vc_off, t_vc_on
    global t_vo_off, t_vo_on
    global ct_hour, ct_min
    global tcorr_in, tcorr_out

    print("Schreibe EEPROM...")
    led_y.value(0)
    eeprom.write(1024,chr(int(mot_duration)))
    time.sleep(1)
    eeprom.write(1025,chr(int(t_win_f_open)))
    time.sleep(1)
    eeprom.write(1026,chr(int(t_win_f_close)))
    time.sleep(1)
    eeprom.write(1027,chr(int(t_win_s_open)))
    time.sleep(1)
    eeprom.write(1028,chr(int(t_win_s_close)))
    time.sleep(1)
    eeprom.write(1029,chr(int(t_win_h_open)))
    time.sleep(1)
    eeprom.write(1030,chr(int(t_win_h_close)))
    time.sleep(1)
    eeprom.write(1031,chr(int(t_wcut_close)))
    time.sleep(1)
    eeprom.write(1032,chr(int(t_heat_off)))
    time.sleep(1)
    eeprom.write(1033,chr(int(t_heat_on)))
    time.sleep(1)
    eeprom.write(1034,chr(int(t_vc_on)))
    time.sleep(1)
    eeprom.write(1035,chr(int(t_vc_off)))
    time.sleep(1)
    eeprom.write(1036,chr(int(t_vo_on)))
    time.sleep(1)
    eeprom.write(1037,chr(int(t_vo_off)))
    time.sleep(1)
    eeprom.write(1038,chr(int(ct_hour)))
    time.sleep(1)
    eeprom.write(1039,chr(int(ct_min)))
    time.sleep(1)
    s_tcorr_in = tcorr_in + 3.0
    eeprom.write(1040,chr(int(s_tcorr_in*10)))
    time.sleep(1)
    s_tcorr_out = tcorr_out + 3.0
    eeprom.write(1041,chr(int(s_tcorr_out*10)))
    time.sleep(1)
    led_y.value(1)
    print("...fertig.")

#-------------------------------------------------------------------------------
# Webserver

# asynchroner Server
async def serve_client(reader, writer):

  global rel01, rel02, rel03, rel04, rel05, rel06
  global tval, msg_txt
  global heat_on, vent_on, wins_open
  global wins_manu, vent_manu, heat_manu
  global temp_min_innen
  global temp_max_innen
  global temp_innen
  global msg_txt, err_txt

  global psel

  global mot_duration
  global t_win_f_open
  global t_win_f_close
  global t_win_s_open
  global t_win_s_close
  global t_win_h_open
  global t_win_h_close
  global t_wcut_close
  global t_heat_off
  global t_heat_on
  global t_vc_on
  global t_vc_off
  global t_vo_on
  global t_vo_off
  global ct_hour
  global ct_min
  global tcorr_in
  global tcorr_out
  
  f_status       = "ZU"        #alternativ "AUF"
  v_status       = "AUS"       #alternativ "EIN"
  h_status       = "AUS"       #alternativ "EIN"
  t_status       = "AUF"       #alternativ "ZU"

  f_hoch         = "HOCH"
  v_ein          = "EIN"
  h_ein          = "EIN"

  f_tief         = "TIEF"
  v_aus          = "AUS"
  h_aus          = "AUS"

  f_aktiv        = "AKTIV"
  v_aktiv        = "AKTIV"
  h_aktiv        = "AKTIV"

  f_red_inst     = "#504444"
  f_green_inst   = "#445044"
  f_blue_inst    = "#438596 style='border: 2px solid lightgrey;' "

  red_normal     = "#504444"
  green_normal   = "#445044"
  blue_normal    = "#444450"

  f_red_high     = "#997777 style='border: 2px solid lightgrey;' "
  f_green_high   = "#779977 style='border: 2px solid lightgrey;' "
  f_blue_high    = "#438596 style='border: 2px solid lightgrey;' "

  v_red_inst     = "#504444"
  v_green_inst   = "#445044"
  v_blue_inst    = "#438596 style='border: 2px solid lightgrey;' "

  v_red_high     = "#997777 style='border: 2px solid lightgrey;' "
  v_green_high   = "#779977 style='border: 2px solid lightgrey;' "
  v_blue_high    = "#438596 style='border: 2px solid lightgrey;' "

  h_red_inst     = "#504444"
  h_green_inst   = "#445044"
  h_blue_inst    = "#438596 style='border: 2px solid lightgrey;' "

  h_red_high     = "#997777 style='border: 2px solid lightgrey;' "
  h_green_high   = "#779977 style='border: 2px solid lightgrey;' "
  h_blue_high    = "#438596 style='border: 2px solid lightgrey;' "

  try:

    # Webclient starten...

    #print("----------- Webclient connected...")
    request_line = await reader.readline()
    if GDEBUG : print("Request:", request_line)

    # HTTP Request-Headers ueberspringen

    while await reader.readline() != b"\r\n":
       pass

    stateis = ""
    request = str(request_line)

    # Zufallszahl berechnen

    rand = randint(1, 100000)

    # Steuerung erkennen

    refresh_all = request.find('/refresh/all')
    minmax_erase = request.find('/minmax/erase')
    msglog_erase = request.find('/msglog/erase')
    errlog_erase = request.find('/errlog/erase')

    ws_on = request.find('/wins/on')
    ws_off = request.find('/wins/off')
    ws_auto = request.find('/winsauto/on')

    vt_on = request.find('/vent/on')
    vt_off = request.find('/vent/off')
    vt_auto = request.find('/ventauto/on')

    ht_on = request.find('/heat/on')
    ht_off = request.find('/heat/off')
    ht_auto = request.find('/heatauto/on')

    # Parameter erkennen

    p_selfor = request.find('/param/selfor')
    p_selback = request.find('/param/selback')
    p_minus = request.find('/param/minus')
    p_plus = request.find('/param/plus')
    p_clear = request.find('/param/clear')
    p_write = request.find('/param/write')

    # auf Steuerung reagieren

    if refresh_all == 6:
        print("Website neu laden")
    if minmax_erase == 6:
        print("Loesche Min/Max-Temperaturen")
        temp_min_innen = temp_innen
        temp_max_innen = temp_innen
    if msglog_erase == 6:
        print("Loesche Meldungs-Register")
        msg_txt[0] = ""
        msg_txt[1] = ""
        msg_txt[2] = ""
        msg_txt[3] = ""
        msg_txt[4] = ""
        msg_txt[5] = ""
        msg_txt[6] = ""
        msg_txt[7] = ""
        msg_txt[8] = ""
        msg_txt[9] = ""
    if errlog_erase == 6:
        print("Loesche Fehlerspeicher")
        err_txt[0] = ""
        err_txt[1] = ""
        err_txt[2] = ""
        led_r.value(1)
        led_y.value(1)

    if ws_on == 6:
        print("Fenster OEFFNEN")
        # keine sonstige Logik abgefragt, bis an den oberen Endschalter fahren
        # kein asynchrones sleep hier, fuer saubere Fahrt per mot_duration
        rel01.value(0)
        rel02.value(1)
        rel03.value(0)
        rel04.value(1)
        
        led_g.value(0)           
        time.sleep(mot_duration)

        rel01.value(1)
        rel02.value(1)
        rel03.value(1)
        rel04.value(1)
        
        led_g.value(1)           

        wins_open = True
        wins_manu = True
        f_aktiv = "AUS"
        f_tief = "TIEF"
        f_hoch = "FEST HOCH"
        f_red_inst = f_red_high
        f_green_inst = green_normal
        f_blue_inst = blue_normal
        msg("Fenster manuell oeffnen", 1)

    if ws_off == 6:
        print("Fenster SCHLIESSEN")
        # keine sonstige Logik abgefragt, bis an den unteren Endschalter fahren
        # kein asynchrones sleep hier, fuer saubere Fahrt per mot_duration
        rel01.value(1)
        rel02.value(0)
        rel03.value(1)
        rel04.value(0)
        
        led_g.value(0)           
        time.sleep(mot_duration)

        rel01.value(1)
        rel02.value(1)
        rel03.value(1)
        rel04.value(1)

        led_g.value(1)           

        wins_open = False
        wins_manu = True
        f_aktiv = "AUS"
        f_hoch = "HOCH"
        f_tief = "FEST TIEF"
        f_red_inst = red_normal
        f_green_inst = f_green_high
        f_blue_inst = blue_normal
        msg("Fenster manuell schliessen", 1)

    if ws_auto == 6:
        print("Fensterautomatik EIN")
        wins_manu = False
        f_aktiv = "AKTIV"
        f_tief = "TIEF"
        f_hoch = "HOCH"
        f_red_inst = red_normal
        f_green_inst = green_normal
        f_blue_inst = f_blue_high
        msg("Fensterautomatik ein", 1)

    if vt_on == 6:
        print("Ventilator EIN")
        rel05.value(0)
        vent_on = True
        vent_manu = True
        v_aktiv = "AUS"
        v_aus = "AUS"
        v_ein = "FEST EIN"
        v_red_inst = v_red_high
        v_green_inst = green_normal
        v_blue_inst = blue_normal
        msg("Ventilator manuell ein", 1)

    if vt_off == 6:
        print("Ventilator AUS")
        rel05.value(1)
        vent_on = False
        vent_manu = True
        v_aktiv = "AUS"
        v_ein = "EIN"
        v_aus = "FEST AUS"
        v_red_inst = red_normal
        v_green_inst = v_green_high
        v_blue_inst = blue_normal
        msg("Ventilator manuell aus", 1)

    if vt_auto == 6:
        print("Ventilatorautomatik EIN")
        vent_manu = False
        v_aktiv = "AKTIV"
        v_ein = "EIN"
        v_aus = "AUS"
        v_red_inst = red_normal
        v_green_inst = green_normal
        v_blue_inst = v_blue_high
        msg("Ventilatorautomatik ein", 1)

    if ht_on == 6:
        print("Heizung EIN")
        rel06.value(0)
        heat_on = True
        heat_manu = True
        h_aktiv = "AUS"
        h_aus = "AUS"
        h_ein = "FEST EIN"
        h_red_inst = h_red_high
        h_green_inst = green_normal
        h_blue_inst = blue_normal
        msg("Heizung manuell ein", 1)

    if ht_off == 6:
        print("Heizung AUS")
        rel06.value(1)
        heat_on = False
        heat_manu = True
        h_aktiv = "AUS"
        h_ein = "EIN"
        h_aus = "FEST AUS"
        h_red_inst = red_normal
        h_green_inst = h_green_high
        h_blue_inst = blue_normal
        msg("Heizung manuell aus", 1)

    if ht_auto == 6:
        print("Heizungsautomatik EIN")
        heat_manu = False
        h_aktiv = "AKTIV"
        h_ein = "EIN"
        h_aus = "AUS"
        h_red_inst = red_normal
        h_green_inst = green_normal
        h_blue_inst = h_blue_high
        msg("Heizungsautomatik ein", 1)

    if wins_open: f_status = "AUF"
    else: f_status = "ZU"
    if vent_on: v_status = "EIN"
    else: v_status = "AUS"
    if heat_on: h_status = "EIN"
    else: h_status = "AUS"
    if tval: t_status = "ZU"
    else: t_status = "AUF"

    if temp_ok: str_temp_ok = "OK"
    else : str_temp_ok = "NICHT OK"

    # auf Parameter reagieren

    if p_selfor > -1:
        psel = psel + 1
        if psel > 18: psel = 0
        print("Parameter ausgewaehlt (",psel,")...")

    if p_selback > -1:
        psel = psel - 1
        if psel < 0: psel = 18
        print("Parameter ausgewaehlt (",psel,")...")

    #------

    if p_minus > -1:
        print("Parameter wird erniedrigt...")

        if psel == 1:
            mot_duration = mot_duration - 1
            print("Stelle Motorzeit...")
        if psel == 2:
            t_win_f_open = t_win_f_open - 1
            print("Stelle Fenster offen im Fruehling...")
        if psel == 3:
            t_win_f_close = t_win_f_close - 1
            print("Stelle Fenster zu im Fruehling...")
        if psel == 4:
            t_win_s_open = t_win_s_open - 1
            print("Stelle Fenster offen im Sommer...")
        if psel == 5:
            t_win_s_close = t_win_s_close - 1
            print("Stelle Fenster zu im Sommer...")
        if psel == 6:
            t_win_h_open = t_win_h_open - 1
            print("Stelle Fenster offen im Herbst...")
        if psel == 7:
            t_win_h_close = t_win_h_close - 1
            print("Stelle Fenster zu im Herbst...")
        if psel == 8:
            t_wcut_close = t_wcut_close - 1
            print("Stelle Schliessen auf Grund Aussentemp...")
        if psel == 9:
            t_heat_off = t_heat_off - 1
            print("Stelle Heizung aus...")
        if psel == 10:
            t_heat_on = t_heat_on - 1
            print("Stelle Heizung ein...")
        if psel == 11:
            t_vc_on = t_vc_on - 1
            print("Stelle Venti ein bei Tuer zu...")
        if psel == 12:
            t_vc_off = t_vc_off - 1
            print("Stelle Venti aus bei Tuer zu...")
        if psel == 13:
            t_vo_on = t_vo_on - 1
            print("Stelle Venti ein bei Tuer offen...")
        if psel == 14:
            t_vo_off = t_vo_off - 1
            print("Stelle Venti aus bei Tuer offen...")
        if psel == 15:
            ct_hour = ct_hour - 1
            print("Stelle Stunde zu per Zeit...")
        if psel == 16:
            ct_min = ct_min - 1
            print("Stelle Minute zu per Zeit...")
        if psel == 17:
            t_corr_in = t_corr_in - 0.1
            print("Stelle Korrektur TFuehler innen...")
        if psel == 18:
            print("Stelle Korrektur TFuehler aussen...")
            t_corr_out = t_corr_out - 0.1

    #---

    if p_plus > -1:
        print("Parameter wird erhoeht...")

        if psel == 1:
            mot_duration = mot_duration + 1
            print("Stelle Motorzeit...")
        if psel == 2:
            t_win_f_open = t_win_f_open + 1
            print("Stelle Fenster offen im Fruehling...")
        if psel == 3:
            t_win_f_close = t_win_f_close + 1
            print("Stelle Fenster zu im Fruehling...")
        if psel == 4:
            t_win_s_open = t_win_s_open + 1
            print("Stelle Fenster offen im Sommer...")
        if psel == 5:
            t_win_s_close = t_win_s_close + 1
            print("Stelle Fenster zu im Sommer...")
        if psel == 6:
            t_win_h_open = t_win_h_open + 1
            print("Stelle Fenster offen im Herbst...")
        if psel == 7:
            t_win_h_close = t_win_h_close + 1
            print("Stelle Fenster zu im Herbst...")
        if psel == 8:
            t_wcut_close = t_wcut_close + 1
            print("Stelle Schliessen auf Grund Aussentemp...")
        if psel == 9:
            t_heat_off = t_heat_off + 1
            print("Stelle Heizung aus...")
        if psel == 10:
            t_heat_on = t_heat_on + 1
            print("Stelle Heizung ein...")
        if psel == 11:
            t_vc_on = t_vc_on + 1
            print("Stelle Venti ein bei Tuer zu...")
        if psel == 12:
            t_vc_off = t_vc_off + 1
            print("Stelle Venti aus bei Tuer zu...")
        if psel == 13:
            t_vo_on = t_vo_on + 1
            print("Stelle Venti ein bei Tuer offen...")
        if psel == 14:
            t_vo_off = t_vo_off + 1
            print("Stelle Venti aus bei Tuer offen...")
        if psel == 15:
            ct_hour = ct_hour + 1
            print("Stelle Stunde zu per Zeit...")
        if psel == 16:
            ct_min = ct_min + 1
            print("Stelle Minute zu per Zeit...")
        if psel == 17:
            tcorr_in = tcorr_in + 0.1
            print("Stelle Korrektur TFuehler innen...")
        if psel == 18:
            print("Stelle Korrektur TFuehler aussen...")
            tcorr_out = tcorr_out + 0.1

    #------
            
    if p_clear > -1:
        psel = 0
        print("Cursor fuer Parameter ruecksetzen...")

    if p_write > -1:
        wepr()
        
    # Hintergruende der Speicherwerte setzen

    hsw = ["#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA", "#A3BFAA"]

    hsw[psel] = "#C4C044"

    # HTML

    writer.write('HTTP/1.0 200 OK\r\nContent-type: text/html\r\n\r\n')

    html = """<!DOCTYPE html>

    <html>
        <style>
            body      {background-image: url('https://www.smartewelt.de/ghaus/bgr4.jpg');}
            body      {margin-left: 35px; padding: 5px; font-family: sans-serif, serif;}
            h1        {color: #fff; font-family: Georgia, Verdana, Tahoma, serif, sans-serif;}
            .u2a      {color: #ccc; font-size:14.0pt;}
            .u2d      {color: #222; font-size:14.0pt;}
            .u3       {color: #ffb; text-align: center; font-size:14pt;}
            .u3a      {color: #bff; text-align: center; font-size:14pt;}
            .stext    {color: #bdb; text-align: center; font-size:18pt;}
            .atext    {color: #ffb; text-align: center; font-size:20pt;}
            .a1text   {color: lightgreen; text-align: center; font-size:28pt;}
            .a2text   {color: #ffb; text-align: center; font-size:14pt;}
            .astext   {color: #ffb; text-align: center; font-size:11pt;}
            .mbox     {color: #333; font-size: 12.0pt; width='70%';}
            .ebox     {color: #F33; font-size: 14.0pt; width='50%';}
            .tbox     {color: #333; font-size: 13.0pt;}
            .table    {background: #6667; border: 1px solid #aaa; border-radius: 5px;}
            th        {height: 3em;}
            td        {height: 3em; padding: 10px; border-radius: 10px; text-align: center;}
            .tdp      {height: 2em; padding: 5px; border-radius: 0px; text-align: center;}
            .tdt      {font-size: 16.0pt; color: #DDD; height: 1.6em; padding: 5px; border-radius: 0px; text-align: center;}
            a         {color: #bff; text-decoration: none;}
        </style>

        <head> <title>Gewaechshaus</title> </head>
        <body>

            <p><h1>Gew&auml;chshaus</h1></p>
            <br/>
            <span class='u2a'>Status</span>
            <br/>
            <br/>

            <table width='95%' cellspacing='10' class='table'>
                <col style='width:25%'>
                <col style='width:25%'>
                <col style='width:25%'>
                <col style='width:25%'>
                <tr>
                    <th><span class='u3'>Fenster</span></th>
                    <th><span class='u3'>Venti</span></th>
                    <th><span class='u3'>Heiz</span></th>
                    <th><span class='u3'>Tuer</span></th>
                </tr>
                <tr>
                    <td><img src="https://www.smartewelt.de/ghaus/fenst_""" + f_status + """.png" width='80' height='80'></td>
                    <td><img src="https://www.smartewelt.de/ghaus/venti_""" + v_status + """.png" width='80' height='80'></td>
                    <td><img src="https://www.smartewelt.de/ghaus/heiz_""" + h_status + """.png" width='80' height='80'></td>
                    <td><img src="https://www.smartewelt.de/ghaus/tuer_""" + t_status + """.png" width='80' height='80'></td>
                </tr>
                <tr>
                    <td><span class='stext'>""" + f_status + """</span></td>
                    <td><span class='stext'>""" + v_status + """</span></td>
                    <td><span class='stext'>""" + h_status + """</span></td>
                    <td><span class='stext'>""" + t_status + """</span></td>
                </tr>
            </table>
            """
    writer.write(html)

    html = """<!DOCTYPE html>
            <br/>
            <br/>
            <span class='u2a'>Aktuelle Werte</span>
            <br/>
            <br/>

            <table width='95%' cellspacing='12' class='table'>
                <col style='width:25%'>
                <col style='width:25%'>
                <col style='width:25%'>
                <col style='width:25%'>
                <tr>
                    <th><span class='u3a'>Innen</span></th>
                    <th><span class='u3a'>Min/Max</span></th>
                    <th><span class='u3a'>TempOK</span></th>
                    <th><span class='u3a'>Aussen</span></th>
                </tr>
                <tr>
                    <td><span class='a1text'><b>""" + str(temp_innen) + """</b></span></td>
                    <td><span class='a2text'>""" + str(temp_min_innen) + "/" + str(temp_max_innen) + """</span></td>
                    <td><span class='atext'>""" + str_temp_ok + """</span></td>
                    <td><span class='atext'>""" + str(temp_aussen) + """</span></td>
                </tr>
            </table>

            <br/>
            <br/>
            <span class='u2a' id='a01'>Schalten</span>
            <br/>
            <br/>
            """

    writer.write(html)

    html = """<!DOCTYPE html>

            <table width='95%' cellspacing='42' class='table'>
                <col style='width:33%'>
                <col style='width:33%'>
                <col style='width:34%'>
                <tr>
                    <th><span class='u3'>Fenster</span></th>
                    <th><span class='u3'>Ventilator</span></th>
                    <th><span class='u3'>Heizung</span></th>
                </tr>
                <tr>
                    <td bgcolor=""" + f_red_inst + """><a href='/wins/on#a01'>Fenster <b>""" + f_hoch + """</b></a></td>
                    <td bgcolor=""" + v_red_inst + """><a href='/vent/on#a01'>Ventilator <b>""" + v_ein + """</b></a></td>
                    <td bgcolor=""" + h_red_inst + """><a href='/heat/on#a01'>Heizung <b>""" + h_ein + """</b></a></td>
                </tr>
                <tr>
                    <td bgcolor=""" + f_green_inst + """><a href='/wins/off#a01'>Fenster <b>""" + f_tief + """</b></a></td>
                    <td bgcolor=""" + v_green_inst + """><a href='/vent/off#a01'>Ventilator <b>""" + v_aus + """</b></a></td>
                    <td bgcolor=""" + h_green_inst + """><a href='/heat/off#a01'>Heizung <b>""" + h_aus + """</b></a></td>
                </tr>
                <tr>
                    <td bgcolor=""" + f_blue_inst + """><a href='/winsauto/on#a01'>Auto <b>""" + f_aktiv + """</b></a></td>
                    <td bgcolor=""" + v_blue_inst + """><a href='/ventauto/on#a01'>Auto <b>""" + v_aktiv + """</b></a></td>
                    <td bgcolor=""" + h_blue_inst + """><a href='/heatauto/on#a01'>Auto <b>""" + h_aktiv + """</b></a></td>
                </tr>
            </table>
            """

    writer.write(html)

    html = """<!DOCTYPE html>

            <br/>
            <br/>
            <span class='u2d' id='a02'>Meldungen/Fehler</span>
            <br/>
            <br/>

            <table width='95%' cellspacing='0' class='table'>
                <col style='width:33%'>
                <col style='width:33%'>
                <col style='width:34%'>
                <tr>
                    <td>
                    &nbsp;
                    </td>
                    <td>
                    <textarea id='t1' name='t1' rows='12' cols='46' class='mbox' readonly='True'>
                    """ + '\n' + msg_txt[0] + '\n' + msg_txt[1] + '\n' +  msg_txt[2] + '\n' +  msg_txt[3] + '\n' +  msg_txt[4] + '\n' +  msg_txt[5] + '\n' +  msg_txt[6] + '\n' +  msg_txt[7] + '\n' +  msg_txt[8] + '\n' +  msg_txt[9] + """
                    </textarea>
                    </td>
                    <td>
                    &nbsp;
                    </td>
                </tr>
                <tr>
                    <td>
                    &nbsp;
                    </td>
                    <td>
                    <textarea id='t2' name='t2' rows='5' cols='39' class='ebox' readonly='True'>
                    """ + '\n' + err_txt[0] + '\n' + err_txt[1] + '\n' +  err_txt[2] + """
                    </textarea>
                    </td>
                    <td>
                    &nbsp;
                    </td>
                </tr>
            </table>

            <br/>
            <br/>
            <span class='u2d'>L&ouml;schen</span>
            <br/>
            <br/>
            """

    writer.write(html)

    html = """<!DOCTYPE html>

            <table width='95%' cellspacing='28' class='table'>
                <col style='width:25%'>
                <col style='width:25%'>
                <col style='width:25%'>
                <col style='width:25%'>
                <tr>
                    <td bgcolor='#4E934E'><a href='/refresh/all#a02'><b>Refresh</b></a></td>
                    <td bgcolor='#4F604E'><a href='/minmax/erase#a02'><b>MinMax</b></a></td>
                    <td bgcolor='#4F604E'><a href='/msglog/erase#a02'><b>MSG-Log</b></a></td>
                    <td bgcolor='#4F604E'><a href='/errlog/erase#a02'><b>ERR-Log</b></a></td>
                </tr>
            </table>

            <br/>
            <br/>
            <span class='u2d' id='a03'>Temperaturverlauf</span>
            <br/>
            <br/>

            <table width='95%' cellspacing='0' class='table'>
                <col style='width:100%'>
                <tr>
                    <td>
                    <a href='https://www.smartewelt.de/statcam/ghausa.png#a03'>
                    <img src='https://www.smartewelt.de/statcam/ghausa.png' width='100%' />
                    </a>
                    </td>
                </tr>
            </table>
            <br/>
            <table width='95%' cellspacing='0' class='table'>
                <col style='width:100%'>
                <tr>
                    <td>
                    <a href='https://www.smartewelt.de/statcam/ghausc.png#a03'>
                    <img src='https://www.smartewelt.de/statcam/ghausc.png' width='100%' />
                    </td>
                </tr>
            </table>
                """

    writer.write(html)

    html = """<!DOCTYPE html>

            <br/>
            <br/>
            <span class='u2d' id='a04'>Speicherwerte</span>
            <br/>
            <br/>

            <table width='95%' cellspacing='13' class='table'>
                <col style='width:16.6%'>
                <col style='width:16.6%'>
                <col style='width:16.6%'>
                <col style='width:16.6%'>
                <col style='width:16.6%'>
                <col style='width:16.6%'>
                <tr>
                    <td class='tdp' bgcolor=""" + str(hsw[1]) + """>Motor Zeit</td>
                    <td class='tdp' bgcolor=""" + str(hsw[2]) + """>OT Fruehl</td>
                    <td class='tdp' bgcolor=""" + str(hsw[3]) + """>UT Fruehl</td>
                    <td class='tdp' bgcolor=""" + str(hsw[4]) + """>OT Sommer</td>
                    <td class='tdp' bgcolor=""" + str(hsw[5]) + """>UT Sommer</td>
                    <td class='tdp' bgcolor=""" + str(hsw[6]) + """>OT Herbst</td>
                </tr>
                <tr>
                    <td class='tdt' >""" + str(mot_duration) + """</td>
                    <td class='tdt' >""" + str(t_win_f_open) + """</td>
                    <td class='tdt' >""" + str(t_win_f_close) + """</td>
                    <td class='tdt' >""" + str(t_win_s_open) + """</td>
                    <td class='tdt' >""" + str(t_win_s_close) + """</td>
                    <td class='tdt' >""" + str(t_win_h_open) + """</td>
                </tr>
                """

    writer.write(html)

    html = """<!DOCTYPE html>
                <tr>
                    <td class='tdp' bgcolor=""" + str(hsw[7]) + """>UT Herbst</td>
                    <td class='tdp' bgcolor=""" + str(hsw[8]) + """>Schl Auss</td>
                    <td class='tdp' bgcolor=""" + str(hsw[9]) + """>Heiz Aus</td>
                    <td class='tdp' bgcolor=""" + str(hsw[10]) + """>Heiz Ein</td>
                    <td class='tdp' bgcolor=""" + str(hsw[11]) + """>VEin TZu</td>
                    <td class='tdp' bgcolor=""" + str(hsw[12]) + """>VAus TZu</td>
                </tr>
                <tr>
                    <td class='tdt' >""" + str(t_win_h_close) + """</td>
                    <td class='tdt' >""" + str(t_wcut_close) + """</td>
                    <td class='tdt' >""" + str(t_heat_off) + """</td>
                    <td class='tdt' >""" + str(t_heat_on) + """</td>
                    <td class='tdt' >""" + str(t_vc_on) + """</td>
                    <td class='tdt' >""" + str(t_vc_off) + """</td>
                </tr>
                """

    writer.write(html)

    html = """<!DOCTYPE html>
                <tr>
                    <td class='tdp' bgcolor=""" + str(hsw[13]) + """>VEin TAuf</a></td>
                    <td class='tdp' bgcolor=""" + str(hsw[14]) + """>VAus TAuf</a></td>
                    <td class='tdp' bgcolor=""" + str(hsw[15]) + """>AZeit Std</a></td>
                    <td class='tdp' bgcolor=""" + str(hsw[16]) + """>AZeit Min</a></td>
                    <td class='tdp' bgcolor=""" + str(hsw[17]) + """>Korr Inn</a></td>
                    <td class='tdp' bgcolor=""" + str(hsw[18]) + """>Korr Auss</a></td>
                </tr>
                <tr>
                    <td class='tdt' >""" + str(t_vo_on) + """</td>
                    <td class='tdt' >""" + str(t_vo_off) + """</td>
                    <td class='tdt' >""" + str(ct_hour) + """</td>
                    <td class='tdt' >""" + str(ct_min) + """</td>
                    <td class='tdt' >""" + str(tcorr_in)[:4] + """</td>
                    <td class='tdt' >""" + str(tcorr_out)[:4] + """</td>
                </tr>
                <tr>
                    <td bgcolor='#4E934E'><a href="/param/selback""" + str(rand) + """#a04"><b><<</b></a></td>
                    <td bgcolor='#4E934E'><a href="/param/selfor""" + str(rand) + """#a04"><b>>></b></a></td>
                    <td bgcolor='#5062B2'><a href="/param/minus""" + str(rand) + """#a04"><b>--</b></a></td>
                    <td bgcolor='#5062B2'><a href="/param/plus""" + str(rand) + """#a04"><b>++</b></a></td>
                    <td bgcolor='#888'><a href="/param/clear""" + str(rand) + """#a04"><b>Clear</b></a></td>
                    <td bgcolor='#AF833E'><a href="/param/write""" + str(rand) + """#a04"><b>Write</b></a></td>
                </tr>

            </table>

            <br/>
            <br/>

         </body>
      </html>
    """

    writer.write(html)

    await writer.drain()
    await writer.wait_closed()
    
    html = ""
    
    #print("----------- disconnected.")
    
  except MemoryError as e:
    print(e)
    err_hndl(6)

#-------------------------------------------------------------------------------
# Verbindung zum heimischen WLAN und damit Internet herstellen

def wconnect(pr = True):
    
    global webcon, efl
    
    if not pr: print("Netzwerk neu kontaktieren...")
    
    if pr: print("[WEB 04] Netzwerk kontaktieren...")
    if pr: msg("Netzwerk kontaktieren...", 0)
    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(ssid, password)
    max_wait = 10
    while max_wait > 0:
        if wlan.status() < 0 or wlan.status() >= 3:
            break
        max_wait -= 1
        if pr: print("[WEB xx] .")
        time.sleep(1)
    if wlan.status() != 3:
        err_hndl(3)
        if pr: print("[WEB xx] Keine Netzwerkverbindung.")
        if pr: msg("Keine Netzwerkverbindung.", 0)
        #              |                    |
        if pr: printlcd(0, 1, "WARNUNG: Kein WLAN!", 0)
        efl = True
        webcon = False
    else:
        status = wlan.ifconfig()
        if pr: print("[WEB 05] Verbunden an " + status[0] + ".")
        if pr: msg("Verbunden an " + status[0], 0)
        #              |                    |
        if pr: printlcd(0, 1, "WLAN - Verbunden.", 0)
        webcon = True

#-------------------------------------------------------------------------------
# main
#-------------------------------------------------------------------------------

led_r.value(0)
time.sleep(2)

print("")
print(shstr2)
print(shstr3)
print("")

# Initialisieren
led_r.value(1)
led_y.value(0)

# Interne Echtzeituhr initialisieren
rtc = RTC()

# GPIO 0 und 1 als I2C-Bus verwenden und scannen
print("[I2C 01] Scanne nach Geräten auf I2C-Bus...")
sda=machine.Pin(0)
scl=machine.Pin(1)
i2c=machine.I2C(0, sda=sda, scl=scl, freq=400000)
i2cdevs = i2c.scan()
i2cdevs_len = len(i2cdevs)
print("[I2C 02] ...{} von {} gefunden.".format(i2cdevs_len, NUM_I2C))
msg("{} von {} I2C-Geraeten gefunden.".format(i2cdevs_len, NUM_I2C), 0)

if i2cdevs_len < NUM_I2C:
    err_hndl(1)
    print("[I2C 03] ERROR - Display nicht bereit.")
    msg("Display (I2C) nicht bereit.", 0)
    efl = True
else:
    msg("Display (I2C) bereit.", 0)
    print("[I2C 03] Display bereit.")
    # LCD-Display initialisieren, Gruesse uebermitteln
    lcd = I2cLcd(i2c, 0x27, 4, 20)
    time.sleep(4)
    printlcd(0, 0, shstr1, 1)
    printlcd(0, 1, shstr2, 0)
    printlcd(0, 2, shstr3, 0)
    printlcd(0, 3, shstr4, 0)
    time.sleep(5)  
    printlcd(0, 0, "I2C-Geraete - OK.", 1)

# WLAN aktivieren, mit Internet verbinden
wconnect()

if(WEB_PERMIT):
    print("[WEB xx] Webzugang manuell ausgesetzt.")
    webcon = False

if webcon:
    print('[WEB 06] Setze Webserver auf...')
    asyncio.create_task(asyncio.start_server(serve_client, "0.0.0.0", 80))
stateis = ""

# Tuerstatus
tval = tuer.value()

# Externe Echtzeituhr initialisieren
print("[CLK 07] Initialisiere Echtzeituhr...")
ertc = DS1307(i2c)
time.sleep(1)
ertc.halt(False) # Oszillator einschalten
time.sleep(1)

# Uhren stellen und Jahreszeit ermitteln
act_clocks()
printlcd(0, 2, "Echtzeituhr - OK.", 0)
msg("Echtzeituhr (I2C) gestellt.", 0)
print("[CLK 09] ...Echtzeituhr gestellt.")

# EEPROM auf Echtzeituhr initialisieren
print("[EPR 10] Initialisiere EEPROM...")
eeprom = AT24C32N(i2c)
time.sleep(1)

if WRITE_EEPROM :
    wepr()

print("[EPR 11] Lese EEPROM...")
if GDEBUG :
    print(eeprom.read(1024, 40))

ere = eeprom.read(1024, 1)
mot_duration = int(ere[0])
if GDEBUG : print("mot_duration: {}".format(mot_duration))

ere = eeprom.read(1025, 1)
t_win_f_open = int(ere[0])
if GDEBUG : print("t_win_f_open: {}".format(t_win_f_open))

ere = eeprom.read(1026, 1)
t_win_f_close = int(ere[0])
if GDEBUG : print("t_win_f_close: {}".format(t_win_f_close))

ere = eeprom.read(1027, 1)
t_win_s_open = int(ere[0])
if GDEBUG : print("t_win_s_open: {}".format(t_win_s_open))

ere = eeprom.read(1028, 1)
t_win_s_close = int(ere[0])
if GDEBUG : print("t_win_s_close: {}".format(t_win_s_close))

ere = eeprom.read(1029, 1)
t_win_h_open = int(ere[0])
if GDEBUG : print("t_win_h_open: {}".format(t_win_h_open))

ere = eeprom.read(1030, 1)
t_win_h_close = int(ere[0])
if GDEBUG : print("t_win_h_close: {}".format(t_win_h_close))

ere = eeprom.read(1031, 1)
t_wcut_close = int(ere[0])
if GDEBUG : print("t_wcut_close: {}".format(t_wcut_close))

ere = eeprom.read(1032, 1)
t_heat_off = int(ere[0])
if GDEBUG : print("t_heat_off: {}".format(t_heat_off))

ere = eeprom.read(1033, 1)
t_heat_on = int(ere[0])
if GDEBUG : print("t_heat_on: {}".format(t_heat_on))

ere = eeprom.read(1034, 1)
t_vc_on = int(ere[0])
if GDEBUG : print("t_vc_on: {}".format(t_vc_on))

ere = eeprom.read(1035, 1)
t_vc_off = int(ere[0])
if GDEBUG : print("t_vc_off: {}".format(t_vc_off))

ere = eeprom.read(1036, 1)
t_vo_on = int(ere[0])
if GDEBUG : print("t_vo_on: {}".format(t_vo_on))

ere = eeprom.read(1037, 1)
t_vo_off = int(ere[0])
if GDEBUG : print("t_vo_off: {}".format(t_vo_off))

ere = eeprom.read(1038, 1)
ct_hour = int(ere[0])
if GDEBUG : print("ct_hour: {}".format(ct_hour))

ere = eeprom.read(1039, 1)
ct_min = int(ere[0])
if GDEBUG : print("ct_min: {}".format(ct_min))

ere = eeprom.read(1040, 1)
s_t_corr_in = float(int(ere[0]))/10
t_corr_in = s_t_corr_in - 3.0
if GDEBUG : print("t_corr_in: {:1}".format(t_corr_in))

ere = eeprom.read(1041, 1)
s_t_corr_out = float(int(ere[0]))/10
t_corr_out = s_t_corr_out - 3.0
if GDEBUG : print("t_corr_out: {:1}".format(t_corr_out))

# OneWire-Bus an GPIO17 anlegen und nach DS18B20-Sensoren suchen
print("[TMP 12] Scanne nach Tempsensoren auf 1Wire-Bus...")
ow = onewire.OneWire(Pin(17))
ow.scan()
ds = ds18x20.DS18X20(ow)
roms = ds.scan()
roms_len = len(roms)
print("[TMP 13] ...{} von {} gefunden.".format(roms_len, NUM_1W))
msg("{} von {} Tempsensoren (1W) gefunden.".format(roms_len, NUM_1W), 0)
if roms_len < NUM_1W:
    err_hndl(2)
    printlcd(0, 3, "1W-Sensoren - NOK.", 0)
    print("[TMP 14] ERROR - 1W-Sensoren - NOK.")
    efl = True
else:
    printlcd(0, 3, "1W-Sensoren - OK.", 0)
    print("[TMP 14] 1W-Sensoren - OK.")
time.sleep(1)
if efl:
    print("[RNL 15] Runlevel bedingt erreicht.")
else:
    print("[RNL 15] Runlevel erreicht.")

# Min/Max-Werte initialisieren
read_temp(False)
temp_min_innen = temp_innen
temp_max_innen = temp_innen
time.sleep(1)

#-------------------------------------------------------------------------------

print("")
#print("-------------------------------------------")
print("Starte...")
msg("Starte...", 1)
lcd.clear()
printlcd(0, 0, "Starte...", 1)
#print("-------------------------------------------")
print("")
time.sleep(4)
lcd.clear()
led_y.value(1)
led_g.value(0)

#-------------------------------------------------------------------------------
# Main loop

async def main():

    global wins_open, vent_on, heat_on, tval, tuer, msg_txt, err_txt, it, gc

    while True:
        
        #-------------------------------------------------

        # Counter
        gc = gc + 1
        print("[",gc,"]")
        # ein Durchlauf ohne Fensterheber ist etwa 1 Minute
        # nach 7 Tagen ruecksetzen und Fehlerspeicher wie LEDs loeschen
        if gc > 60 * 24 * 7 :
            gc = 0
            
            err_txt[0] = ""
            err_txt[1] = ""
            err_txt[2] = ""
        
            led_r.value(1)
            led_y.value(1)
            led_g.value(1)

        await asyncio.sleep(2)

        #-------------------------------------------------

        # Zeitstempel holen
        it = rtc.datetime()
        print("GHaus-RTC: {:02}.{:02}.{:04} {:02}:{:02}:{:02}".format(it[2], it[1], it[0], it[4], it[5], it[6]))

        #-------------------------------------------------

        # Tuerstand holen
        tval = not(tuer.value())

        # Stell-Stati (FVHT) im Log anzeigen
        print("Fenst:{} Venti:{} Heiz:{} Tuer:{} ".format(int(wins_open), int(vent_on), int(heat_on), int(not(tval))))

        #-------------------------------------------------

        # Temperatur holen
        read_temp()

        #-------------------------------------------------

        # aktuelle Werte auf LCD anzeigen (1)
        showlcd_stats()
        await asyncio.sleep(18)

        #-------------------------------------------------

        # Einstellparameter auf LCD zeigen
        showlcd_params()
        await asyncio.sleep(5)

        #-------------------------------------------------

        # Aktion (FVH) notwendig?

        # Grenzwerte und Min/Max ueberpruefen
        ex_vals()

        # Fensteroeffnung
        gh_win()

        # Ventilator
        gh_vent()

        # Heizung
        gh_heat()

        await asyncio.sleep(4)

        #-------------------------------------------------

        # Debug-Ausgaben der Logs ins Terminal bei Bedarf
        if GDEBUG: showlogs()

        # Terminalausgaben abschliessen
        print("")
        print("----")
        print("")

        #-------------------------------------------------

        # Tuerstand holen
        tval = not(tuer.value())

        # aktuelle Werte auf LCD anzeigen (2)
        showlcd_stats()
        await asyncio.sleep(17)

        #-------------------------------------------------

        # Fehler-Bildschirm auf LCD anzeigen
        errlcd()
        await asyncio.sleep(5)

        #-------------------------------------------------

        # Falls nicht im WLAN und nicht permitted, hier versuchen
        # wieder Verbindung aufzunehmen, still und nur mit Wiederholungsmeldung in der Konsole
        if webcon == False and WEB_PERMIT == False:
            wconnect(False)

        led_g.value(1)

try:
    asyncio.run(main())
finally:
    asyncio.new_event_loop()

#-------------------------------------------------------------------------------
# physical end 
#-------------------------------------------------------------------------------
