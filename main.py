import time
from datetime import datetime
import sqlite3
from pprint import pprint

import requests
import tweepy


def get_printer_status():
    url = "http://192.168.1.14/printer/list/"

    payload = {}
    headers = {
        'x-api-key': '54294070-6761-4fb9-8937-1ba1bd8094e2'
    }
    while True:
        response = requests.request("GET", url, headers=headers, data=payload).json()['data'][0]
        img = requests.get("http://192.168.1.14:8080/?action=snapshot")
        print(response)
        if response['job'] != "none":
            prev = requests.get(
                f"http://192.168.1.14/dyn/render_image?q=jobs&id={response['jobid']}&slug=Ender_3_Pro&t=m&tm={round(time.time())}")
            yield {'data': response, 'img': img.content, 'prev': prev.content}
        else:
            yield {'data': response, 'img': img.content, 'prev': None}


if __name__ == '__main__':
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

    consumer_key = "zarMTv7kAtOKPyHQzdXU5uPI7"
    consumer_secret = "2AfimBG5KN2JoK4fr6mzBwTak1yabDcm4e43L156P6ipjMTaZc"

    key = "1353106843963432965-kbI8evj4LWDfic4o5HEk6usTgCPrS2"
    secret = "A2SJIqGbyOaCo8MFQxaU36JMilnOm6GK0OzKbbsDER6o3"

    ha_token = "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI1ZTFkNTg5ZGY5Njg0MjAzYTM5NjQ2NTI2YjI2OWU4YyIsImlhdCI6MTYxMTUyODQ5MiwiZXhwIjoxOTI2ODg4NDkyfQ.Yjn3sLXxl1m3fU8us2oiLx6VxCEh5iW8UeNs42u8MAg"

    ps = get_printer_status()
    auth = tweepy.OAuthHandler(consumer_key, consumer_secret)
    auth.set_access_token(key, secret)
    api = tweepy.API(auth, wait_on_rate_limit=True)

    while True:
        d = next(ps)
        with conn as db:
            data = db.execute(
                "SELECT r.jobid, t.id FROM repetier_infos r LEFT JOIN tweets t ON r.jobid = t.repetier_id WHERE r.active = 1;")
            active_job, active_tweet = data.fetchone() or (None, None)

        if d['data']['job'] != "none" and d['data']['printTime'] > 7200:
            with conn as db:
                db.execute("REPLACE INTO repetier_infos (jobid, job, printStart, job_time, active) VALUES"
                           f"({d['data']['jobid']}, '{d['data']['job']}', '{datetime.fromtimestamp(d['data']['printStart']).isoformat()}', {int(d['data']['printTime'])}, 1)")
            with open("tmp.jpg", "wb") as f:
                f.write(d['prev'])
            if active_tweet is None and d['data']['analysed'] == 1:

                seconds = int(d['data']['printTime'])

                hours = int(seconds / (60 * 60))
                minutes = int(seconds / 60 - 60 * hours)

                ete = f"{hours}:{minutes}"

                tweet = api.update_with_media(f"{d['data']['jobid']}.jpg", file=open("tmp.jpg", "rb"),
                                              status=f"Ein weiterer #3ddruck läuft ... ~{ete} Std.")
                tweet: tweepy.Status
                with conn as db:
                    db.execute("REPLACE INTO tweets (id, repetier_id) VALUES"
                               f"('{tweet.id}', {d['data']['jobid']})")

        #         time.sleep(max((d['data']['printTime'] - d['data']['printedTimeComp']) * 0.7, 5))
        else:
            if active_job is not None:
                url = "http://192.168.1.127:8123/api/services/light/turn_on"

                payload="{\"entity_id\":\"light.computerraum\", \"brightness\": 255, \"kelvin\":4000}"
                headers = {
                'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI1ZTFkNTg5ZGY5Njg0MjAzYTM5NjQ2NTI2YjI2OWU4YyIsImlhdCI6MTYxMTUyODQ5MiwiZXhwIjoxOTI2ODg4NDkyfQ.Yjn3sLXxl1m3fU8us2oiLx6VxCEh5iW8UeNs42u8MAg',
                'Content-Type': 'application/json'
                }

                requests.request("POST", url, headers=headers, data=payload)

                time.sleep(3)

                
                d = next(ps)

                with open("tmp.jpg", "wb") as f:
                    f.write(d['img'])
                api.update_with_media(f"{active_job}_done.jpg", file=open("tmp.jpg", "rb"),
                                      status=f"Und so sieht's aus",
                                      in_reply_to_status_id=active_tweet)

                url = "http://192.168.1.127:8123/api/services/light/turn_off"

                payload="{\"entity_id\":\"light.computerraum\"}"
                headers = {
                'Authorization': 'Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJpc3MiOiI1ZTFkNTg5ZGY5Njg0MjAzYTM5NjQ2NTI2YjI2OWU4YyIsImlhdCI6MTYxMTUyODQ5MiwiZXhwIjoxOTI2ODg4NDkyfQ.Yjn3sLXxl1m3fU8us2oiLx6VxCEh5iW8UeNs42u8MAg',
                'Content-Type': 'application/json'
                }

                requests.request("POST", url, headers=headers, data=payload)

                with conn as db:
                    db.execute(f"UPDATE repetier_infos SET active=0 WHERE jobid = {active_job};")
        time.sleep(60)
