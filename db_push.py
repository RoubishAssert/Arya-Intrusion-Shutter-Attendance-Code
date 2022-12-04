import json, boto3
import sqlite3
from utils import query_last_attendance_id, query_last_vehicle_id, query_last_intrusion_id, query_push_intrusion, \
    query_push_attendance, query_push_vehicle, query_push_log, query_all_data, get_mydb_cursor, commit_and_close, \
    upload_to_aws
from config import BUCKET_NAME, SECONDS_GAP_BEFORE_INTRUSION, FPS_INTRUSION, SECONDS_GAP_BEFORE_VEHICLE, FPS_VEHICLE

db_name = "arya_db.db"

from datetime import time
import requests
import json
#import time
from datetime import datetime
warehouse_name = 'Sandeep Warehouse'
# aws_arn = 'arn:aws:sns:ap-south-1:387137730207:intrusion-arya'
warehouse_id = "1"
start_1 = time(18, 0, 0)
end_1 = time(23, 59, 0)
start_2 = time(0, 1, 0)
end_2 = time(9, 0, 0)

def get_device_token(warehouseId):
    device_token_url = "https://app-assertai.com:5000/api/mobile/getDeviceTokens?wareHouseId={}".format(warehouseId)
    f = requests.get(device_token_url)
    data = json.loads(f.text)
    return data['data']


url = "https://fcm.googleapis.com/fcm/send"
serverToken = "AAAA4SK1m4o:APA91bGj-vh8Xh-wr4MS0z2JG4hERZjLAsSpQysRqfX4xxPCk58SSHJ3QMt02In-W3NBxEYVPSho8S5OtXJKggXwbTY3muPOgoEvMPArqt6AA-Pc-JZKCFBQF800WzD_sGl0BtZ9Ib9x"

headers = {
    'Authorization': 'key=' + serverToken,
    'Content-Type': 'application/json'
}

list_token = get_device_token(warehouse_id)

def insert_data_vehicle(frame_date, camera_id, frame_time, image_url, type_of_vehicle):
    mydb, cursor = get_mydb_cursor()
    params = (frame_date, camera_id, frame_time, image_url, None, None, type_of_vehicle, 'inward_outward', 'document')
    _ = query_all_data(cursor, query_push_vehicle, params)

    last_id = query_all_data(cursor, query_last_vehicle_id)
    mydb.commit()

    # # push log data
    params = (frame_date, frame_time, 'vehicle detected', 'action', camera_id, last_id)
    print(params)
    veh_event_id = query_all_data(cursor, query_push_log, params)
    mydb.commit()

    if mydb.is_connected():
        cursor.close()
        mydb.close()

    return veh_event_id


def insert_data_attend(frame_date, frame_time, camera_id, image_url, attendance_count):
    mydb, cursor = get_mydb_cursor()

    params = (frame_date, frame_time, camera_id, image_url, attendance_count)
    _ = query_all_data(cursor, query_push_attendance, params)

    last_id = query_all_data(cursor, query_last_attendance_id)
    mydb.commit()

    # # push log data
    params = (frame_date, frame_time, 'attendance detected', 'action', camera_id, last_id)
    print(params)
    attend_event_id = query_all_data(cursor, query_push_log, params)
    mydb.commit()

    if mydb.is_connected():
        cursor.close()
        mydb.close()

    return attend_event_id


def insert_data_intrusion(frame_date, frame_time, camera_id, image_url):
    mydb, cursor = get_mydb_cursor()

    params = (frame_date, frame_time, camera_id, image_url)

    _ = query_all_data(cursor, query_push_intrusion, params)

    last_id = query_all_data(cursor, query_last_intrusion_id)
    print(last_id)
    mydb.commit()

    # # push log data
    params = (frame_date, frame_time, 'intrusion detected', 'action', camera_id, last_id)
    print(params)
    intrusion_event_id = query_all_data(cursor, query_push_log, params)
    mydb.commit()

    if mydb.is_connected():
        cursor.close()
        mydb.close()

    return intrusion_event_id


def get_frame_name(img_path, img_date, img_time):
    # img_path = "2/stream_2/frame_56.jpg"
    # img_date = "2022-09-20"
    # img_time = "01:03:15"

    x = img_path.split('/')[0]
    # print(x)
    y = img_path.split('.')[0].split('/')[2]
    # print(y)

    img_org_path = x + y + "_" + img_date + "_" + img_time + ".jpg"
    # print(img_org_path)

    return img_org_path


#####  Code for vehicle db push #############

conn_create = sqlite3.connect(db_name)
cur = conn_create.cursor()
cur.execute("SELECT * FROM stats_vehicle")

rows = cur.fetchall()

for row in rows:
    print(row)
    data = get_frame_name(row[5], row[1], row[3])
    print(data)
    try:
        image_url = upload_to_aws(row[5], BUCKET_NAME, data)
        print(image_url)
        ## database push
        event_id = insert_data_vehicle(row[1], row[2], row[3], image_url, row[8])
        push_current_time = datetime.now().time()
        if (start_1 <= push_current_time and push_current_time <= end_1) or (start_2 <= push_current_time and push_current_time <= end_2):
            try:
                for i in list_token:
                    payload = json.dumps({
                        "to": i,
                        "notification": {
                            "body": warehouse_name,
                            "title": "Vehicle Detected",
                            "subtitle": f"Date: {row[1]} , Time: {row[3]}"
                        },
                        "data": {
                            "site_name": warehouse_name,
                            "event_id": event_id,
                            "camera_name": row[2],
                            "event_time": row[3],
                            "event_date": row[1],
                            "event_tag": "Vehicle Detected",
                            "image": image_url

                        }
                    })

                    response = requests.request("POST", url, headers=headers, data=payload)
                    print(response.text)
            except Exception as e:
                print(e)
        print("data uploaded successfully")
        ## delete from  local db (delete from stats_vehicle where id = row[0])
        conn_create = sqlite3.connect(db_name)
        c_create = conn_create.cursor()
        delete_record_sql = "DELETE FROM stats_vehicle WHERE id = ?"
        delete_id = c_create.execute(delete_record_sql, (row[0],))
        conn_create.commit()
    except Exception as e:
        print(e)
        continue

conn_create.close()

##### Code for attendance db push ###############

conn_create = sqlite3.connect(db_name)
cur = conn_create.cursor()
cur.execute("SELECT * FROM stats_attendance")

rows = cur.fetchall()

for row in rows:
    print(row)
    data = get_frame_name(row[4], row[1], row[2])
    print(data)
    try:
        if row[6] != '0/5':
            image_url = upload_to_aws(row[4], BUCKET_NAME, data)
            print(image_url)
        else:
            image_url = row[4]
        # database push
        event_id = insert_data_attend(row[1], row[2], row[3], image_url, row[6])
        push_current_time = datetime.now().time()
        if (start_1 <= push_current_time and push_current_time <= end_1) or (start_2 <= push_current_time and push_current_time <= end_2):
            try:
                for i in list_token:
                    payload = json.dumps({
                        "to": i,
                        "notification": {
                            "body": warehouse_name,
                            "title": "Attendance Detected",
                            "subtitle": f"Date: {row[1]} , Time: {row[2]}"
                        },
                        "data": {
                            "site_name": warehouse_name,
                            "event_id": event_id,
                            "camera_name": row[3],
                            "event_time": row[2],
                            "event_date": row[1],
                            "event_tag": "Attendance Detected",
                            "image": image_url

                        }
                    })

                    response = requests.request("POST", url, headers=headers, data=payload)
                    print(response.text)
            except Exception as e:
                print(e)
        print("data uploaded successfully")
        # delete from  local db (delete from stats_vehicle where id = row[0])
        conn_create = sqlite3.connect(db_name)
        c_create = conn_create.cursor()
        delete_record_sql = "DELETE FROM stats_attendance WHERE id = ?"
        delete_id = c_create.execute(delete_record_sql, (row[0],))
        conn_create.commit()
    except Exception as e:
        print(e)
        continue

conn_create.close()


######### Code for intrusion data push ##########

conn_create = sqlite3.connect(db_name)
cur = conn_create.cursor()
cur.execute("SELECT * FROM stats_intrusion")

rows = cur.fetchall()

for row in rows:
    print(row)
    data = get_frame_name(row[4], row[1], row[2])
    print(data)
    try:
        image_url = upload_to_aws(row[4], BUCKET_NAME, data)
        print(image_url)
        # database push
        event_id = insert_data_intrusion(row[1], row[2], row[3], image_url)
        push_current_time = datetime.now().time()
        if (start_1 <= push_current_time and push_current_time <= end_1) or (start_2 <= push_current_time and push_current_time <= end_2):
            try:
                for i in list_token:
                    payload = json.dumps({
                        "to": i,
                        "notification": {
                            "body": warehouse_name,
                            "title": "Intrusion Detected",
                            "subtitle": f"Date: {row[1]} , Time: {row[2]}"
                            # "Camera" : camera_id,
                            # "Image" : f"Image url is {image_url}"
                        },
                        "data": {
                            "site_name": warehouse_name,
                            "event_id": "event_id",
                            "camera_name": row[3],
                            "event_time": row[2],
                            "event_date": row[1],
                            "event_tag": "Intrusion Detected",
                            "image": image_url

                        }
                    })

                    response = requests.request("POST", url, headers=headers, data=payload)
                    print(response.text)
            except Exception as e:
                print(e)
        print("data uploaded successfully")
        # delete from  local db (delete from stats_vehicle where id = row[0])
        conn_create = sqlite3.connect(db_name)
        c_create = conn_create.cursor()
        delete_record_sql = "DELETE FROM stats_intrusion WHERE id = ?"
        delete_id = c_create.execute(delete_record_sql, (row[0],))
        conn_create.commit()
    except Exception as e:
        print(e)
        continue

conn_create.close()
