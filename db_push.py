import json, boto3
import sqlite3
from utils import query_last_attendance_id, query_last_vehicle_id, query_last_intrusion_id, query_push_intrusion, \
    query_push_attendance, query_push_vehicle, query_push_log, query_all_data, get_mydb_cursor, commit_and_close, \
    upload_to_aws
from config import BUCKET_NAME, SECONDS_GAP_BEFORE_INTRUSION, FPS_INTRUSION, SECONDS_GAP_BEFORE_VEHICLE, FPS_VEHICLE

db_name = "arya_db.db"


def insert_data_vehicle(frame_date, camera_id, frame_time, image_url, type_of_vehicle):
    mydb, cursor = get_mydb_cursor()
    params = (frame_date, camera_id, frame_time, image_url, None, None, type_of_vehicle, 'inward_outward', 'document')
    _ = query_all_data(cursor, query_push_vehicle, params)

    last_id = query_all_data(cursor, query_last_vehicle_id)
    mydb.commit()

    # # push log data
    params = (frame_date, frame_time, 'vehicle detected', 'action', camera_id, last_id)
    print(params)
    _ = query_all_data(cursor, query_push_log, params)
    mydb.commit()

    if mydb.is_connected():
        cursor.close()
        mydb.close()

    return


def insert_data_attend(frame_date, frame_time, camera_id, image_url, attendance_count):
    mydb, cursor = get_mydb_cursor()

    params = (frame_date, frame_time, camera_id, image_url, attendance_count)
    _ = query_all_data(cursor, query_push_attendance, params)

    last_id = query_all_data(cursor, query_last_attendance_id)
    mydb.commit()

    # # push log data
    params = (frame_date, frame_time, 'attendance detected', 'action', camera_id, last_id)
    print(params)
    _ = query_all_data(cursor, query_push_log, params)
    mydb.commit()

    if mydb.is_connected():
        cursor.close()
        mydb.close()

    return


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
    _ = query_all_data(cursor, query_push_log, params)
    mydb.commit()

    if mydb.is_connected():
        cursor.close()
        mydb.close()

    return


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
        insert_data_vehicle(row[1], row[2], row[3], image_url)
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
        insert_data_attend(row[1], row[2], row[3], image_url, row[6])
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
        insert_data_intrusion(row[1], row[2], row[3], image_url)
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
