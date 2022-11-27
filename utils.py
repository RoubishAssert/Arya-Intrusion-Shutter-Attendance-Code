import mysql.connector
import boto3
from config import *
from botocore.exceptions import NoCredentialsError

query_last_intrusion_id = 'SELECT id FROM stats_intrusion ORDER BY id DESC LIMIT 1'
query_last_attendance_id = 'SELECT id FROM stats_attendance ORDER BY id DESC LIMIT 1'
query_last_vehicle_id = 'SELECT id FROM stats_vehicle ORDER BY id DESC LIMIT 1'

query_push_intrusion = 'INSERT INTO stats_intrusion (date, time, intrusion_camera_id, image) ' \
                       'VALUES (%s, %s, %s, %s);'

query_push_attendance = 'INSERT INTO stats_attendance (date, time, attendance_camera_id, image, attendance_count) ' \
                        'VALUES (%s, %s, %s, %s, %s);'

query_push_log = 'INSERT INTO log (event_date, event_time, event_tag, action, log_camera_id, id_reference) ' \
                 'VALUES (%s, %s, %s, %s, %s, %s);'

query_push_vehicle = 'INSERT INTO stats_vehicle (date, vehicle_camera_id, time, image, truck_in_time, truck_out_time, vehicle_type, inward_outward, document) ' \
                     'VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s);'

SHUTTER_OPEN = 'shutter open'
SHUTTER_CLOSE = 'shutter close'


def query_all_data(cursor, query, params=()):
    cursor.execute(query, params)
    print('query all data')
    data = cursor.lastrowid
    return data



def commit_and_close(mydb, cursor):
    mydb.commit()
    if mydb.is_connected():
        cursor.close()
        mydb.close()


def get_mydb_cursor():
    mydb = mysql.connector.connect(
        host=HOST,
        user="hb",
        password=str(PASSWORD),
        port=PORT,
        database=DATABASE
    )
    cursor = mydb.cursor(buffered=True)
    return mydb, cursor


get_url = lambda s3_file_name: f'https://{BUCKET_NAME}.s3.ap-south-1.amazonaws.com/{s3_file_name}'


def upload_to_aws(frame_path, bucket, s3_file_name):
    s3 = boto3.client('s3', aws_access_key_id=ACCESS_KEY,
                      aws_secret_access_key=SECRET_KEY)

    try:
        s3.upload_file(str(frame_path), bucket, s3_file_name)
        print("Upload Successful")
        return get_url(s3_file_name)
    except FileNotFoundError:
        print("The file was not found")
        return ''
    except NoCredentialsError:
        print("Credentials not available")
        return ''
