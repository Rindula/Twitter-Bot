import time
from datetime import datetime
import sqlite3
from pprint import pprint

import requests
import tweepy

import secrets

# Abfrage des 3D Druckers nach aktuellem Status als Generator (weil ich Lust dazu hatte :P)
def get_printer_status():
    url = "http://192.168.1.14/printer/list/"

    payload = {}
    headers = {
        'x-api-key': secrets.repetier_key
    }
    while True:
        response = requests.request("GET", url, headers=headers, data=payload).json()['data'][0]
        img = requests.get("http://192.168.1.14:8080/?action=snapshot")
        if response['job'] != "none":
            prev = requests.get(
                f"http://192.168.1.14/dyn/render_image?q=jobs&id={response['jobid']}&slug=Ender_3_Pro&t=m&tm={round(time.time())}")
            yield {'data': response, 'img': img.content, 'prev': prev.content}
        else:
            yield {'data': response, 'img': img.content, 'prev': None}


if __name__ == '__main__':
    # Lokale Datenbank zum Speichern der Posts/Druckids
    conn = sqlite3.connect("infos.db")
    with conn as db:
        db.execute("""CREATE TABLE IF NOT EXISTS "repetier_infos" (
            "jobid" INTEGER NOT NULL,
            "job" VARCHAR(255) NOT NULL,
            "printStart" DATETIME NOT NULL,
            "job_time" INTEGER NOT NULL,
            "active" TINYINT NOT NULL,
            PRIMARY KEY ("jobid")
        )
        ;
        """)
        db.execute("""CREATE TABLE IF NOT EXISTS "tweets" (
            "id" VARCHAR(255) NOT NULL,
            "repetier_id" INTEGER NOT NULL unique,
	        PRIMARY KEY ("id"),
            CONSTRAINT "0" FOREIGN KEY ("repetier_id") 
            REFERENCES "repetier_infos" ("jobid") ON UPDATE CASCADE ON DELETE CASCADE
        )
        ;
        """)

    # Twitter API Schlüssel
    consumer_key = secrets.twitter_keys['consumer_key']
    consumer_secret = secrets.twitter_keys['consumer_secret']

    key = secrets.twitter_keys['key']
    secret = secrets.twitter_keys['secret']

    # Homeassistant Schlüssel (Licht steuerung)
    ha_token = secrets.home_assistant_key

    # Initialisierung
    ps = get_printer_status()
    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(key, secret)
    api = tweepy.API(auth, wait_on_rate_limit=True)

    # Checkloop
    while True:
        d = next(ps)
        # Hole den aktiven Job/letzten Tweet aus der Datenbank (wird weiter unten geschrieben)
        with conn as db:
            data = db.execute(
                "SELECT r.jobid, t.id FROM repetier_infos r LEFT JOIN tweets t ON r.jobid = t.repetier_id WHERE r.active = 1;")
            active_job, active_tweet = data.fetchone() or (None, None)

        if d['data']['job'] != "none" and d['data']['printTime'] > 7200:
            # Es existiert ein Druckauftrag, der länger als 2 Stunden dauert

            # Trage den Druckauftrag als aktiv in die Datenbank ein
            with conn as db:
                db.execute("REPLACE INTO repetier_infos (jobid, job, printStart, job_time, active) VALUES"
                           f"({d['data']['jobid']}, '{d['data']['job']}', '{datetime.fromtimestamp(d['data']['printStart']).isoformat()}', {int(d['data']['printTime'])}, 1)")
            # Speichere das vorgerenderte Bild (wird vom Druckserver zur verfügung gestellt)
            with open("tmp.jpg", "wb") as f:
                f.write(d['prev'])
            if active_tweet is None and d['data']['analysed'] == 1:
                # Es gibt noch keinen Tweet zu dem Druck

                # ETE berechnen
                seconds = int(d['data']['printTime'])

                hours = int(seconds / (60 * 60))
                minutes = int(seconds / 60 - 60 * hours)

                ete = f"{hours}:{minutes}"

                # Tweet mit ETE und Bild im Anhang posten
                tweet = api.update_with_media(f"{d['data']['jobid']}.jpg", file=open("tmp.jpg", "rb"),
                                              status=f"Ein weiterer #3ddruck läuft ... ~{ete} Std.")
                
                # Tweet ID in der Datenbank speichern
                tweet: tweepy.Status
                with conn as db:
                    db.execute("REPLACE INTO tweets (id, repetier_id) VALUES"
                               f"('{tweet.id}', {d['data']['jobid']})")

        else:
            # Es existiert kein aktiver Druckauftrag
            if active_job is not None:
                # In der Datenbank gab es noch einen aktiven Auftrag -> der Druck ist abgeschlossen

                # Home Assistant das Licht im Raum anschalten lassen
                url = "http://192.168.1.127:8123/api/services/light/turn_on"

                payload="{\"entity_id\":\"light.computerraum\", \"brightness\": 255, \"kelvin\":4000}"
                headers = {
                'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI1ZTFkNTg5ZGY5Njg0MjAzYTM5NjQ2NTI2YjI2OWU4YyIsImlhdCI6MTYxMTUyODQ5MiwiZXhwIjoxOTI2ODg4NDkyfQ.Yjn3sLXxl1m3fU8us2oiLx6VxCEh5iW8UeNs42u8MAg',
                'Content-Type': 'application/json'
                }

                requests.request("POST", url, headers=headers, data=payload)

                time.sleep(3)

                # Bild von Druck aufnehmen und zwischenspeichern                
                d = next(ps)

                with open("tmp.jpg", "wb") as f:
                    f.write(d['img'])

                # Bild des fertigen Drucks auf Twitter posten
                api.update_with_media(f"{active_job}_done.jpg", file=open("tmp.jpg", "rb"),
                                      status=f"Und so sieht's aus",
                                      in_reply_to_status_id=active_tweet)

                # Licht wieder ausschalten
                # TODO: Statusabfrage des Lichts und zustand wiederherstellen
                url = "http://192.168.1.127:8123/api/services/light/turn_off"

                payload="{\"entity_id\":\"light.computerraum\"}"
                headers = {
                'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI1ZTFkNTg5ZGY5Njg0MjAzYTM5NjQ2NTI2YjI2OWU4YyIsImlhdCI6MTYxMTUyODQ5MiwiZXhwIjoxOTI2ODg4NDkyfQ.Yjn3sLXxl1m3fU8us2oiLx6VxCEh5iW8UeNs42u8MAg',
                'Content-Type': 'application/json'
                }

                requests.request("POST", url, headers=headers, data=payload)

                # Alle in der Datenbank als aktiv markierte Jobs als inaktiv kennzeichnen
                with conn as db:
                    db.execute(f"UPDATE repetier_infos SET active=0 WHERE jobid = {active_job};")
        # Delay zwischen den Checks
        time.sleep(60)
