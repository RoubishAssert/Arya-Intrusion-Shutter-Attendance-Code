#!/usr/bin/env python3

import sys

sys.path.append('../')
import gi
import configparser

gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst
from gi.repository import GLib
from ctypes import *
import time
import sys
import math
import platform
from common.is_aarch_64 import is_aarch64
from common.bus_call import bus_call
from common.FPS import GETFPS
import numpy as np
import pyds
import cv2
import os
import os.path
from os import path
from utils import query_push_vehicle, query_push_log, query_all_data, get_mydb_cursor, commit_and_close, upload_to_aws
from datetime import datetime
import datetime as dt
from utils import query_push_vehicle, query_push_log, query_all_data, get_mydb_cursor, commit_and_close, upload_to_aws
from config import BUCKET_NAME, SECONDS_GAP_BEFORE_VEHICLE, FPS_VEHICLE
import json
import boto3
import requests
import yaml
from yaml.loader import SafeLoader
import csv
import pandas as pd

with open('shutter_config.yml') as f:
    cdata = yaml.load(f, Loader=SafeLoader)
streams_type = cdata['streams_type']
No_of_Shutter_Streams = cdata["No_of_Shutter_Streams"]
No_of_Vehicle_Streams = cdata["No_of_Vehicle_Streams"]
camera_id_dict = cdata["camera_id_dict"]
fps_streams = {}
frame_count = {}
saved_count = {}
print(camera_id_dict)
global PGIE_CLASS_ID_CLOSE
global PGIE_CLASS_ID_OPEN
PGIE_CLASS_ID_CLOSE = 0
PGIE_CLASS_ID_OPEN = 1

MAX_DISPLAY_LEN = 64
MUXER_OUTPUT_WIDTH = 1920
MUXER_OUTPUT_HEIGHT = 1080
TILED_OUTPUT_WIDTH = 1920
TILED_OUTPUT_HEIGHT = 1080
GST_CAPS_FEATURES_NVMM = "memory:NVMM"
pgie_classes_str = ["Close", "Open"]
perf_data = None

#global detected_cls
#detected_cls = []
#global event
#event = "first_status"
streams_dict = {}

MIN_CONFIDENCE = 0.000001
MAX_CONFIDENCE = 1.0

#For previous status confirmation
status = [{}]
#global status
filename ="Shutter_status.csv"
with open(filename, 'r') as data:

    for line in csv.DictReader(data):
        status=line
data.close()

def backup_status(streamNo, prev_status, cur_status):
    df = pd.read_csv("Shutter_status.csv")
    # updating the column value/data
    df[str(streamNo)] = df[str(streamNo)].replace({str(prev_status) : str(cur_status)})
    # writing into the file
    df.to_csv("Shutter_status.csv", index=False)
    with open(filename, 'r') as data:
        for line in csv.DictReader(data):
            status=line
    data.close()
    print(status)


perf_data = None
# wh_name = 'Arya_Churas_Farmer_Producer_Company_Warehouse'
#aws_arn = 'arn:aws:sns:ap-south-1:387137730207:WH-43'
# aws_arn = 'arn:aws:sns:ap-south-1:387137730207:WH-43'
event = ''
global cmr_id
cmr_id = ''

from datetime import time
import requests
import json
warehouse_name = 'Sandeep Warehouse'
warehouse_id = "1"
start_1 = time(18, 0, 0)
end_1 = time(23, 59, 0)
start_2 = time(0, 1, 0)
end_2 = time(9, 0, 0)

from utils import query_push_log, query_all_data, get_mydb_cursor, commit_and_close, SHUTTER_OPEN, \
    SHUTTER_CLOSE
from datetime import datetime

mydb, cursor = get_mydb_cursor()
#global camera_id
#camera_id = '45_4'
query_last_shutter_id = 'SELECT id FROM stats_shutter ORDER BY id DESC LIMIT 1'

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

def push_data_to_log_and_shutter(cursor, date_now, time_now, image_url,event):
    global cmr_id
    camera_id = cmr_id
    print(camera_id, " : ", event)
    query = 'SELECT * FROM stats_shutter WHERE date = %s'
    params = (date_now,)
    data = query_all_data(cursor, query, params)
    #print(data)
    #if not data:
    query = 'INSERT INTO stats_shutter (date, shutter_camera_id, shutter_open_time, shutter_close_time, image) ' \
            'VALUES (%s, %s, %s, %s, %s);'
    if event == SHUTTER_OPEN:
        params = (date_now, camera_id, time_now, None, image_url)
    elif event == SHUTTER_CLOSE:
        print("Hi")
        params = (date_now, camera_id, None, time_now, image_url)
    query_all_data(cursor, query, params)
    mydb.commit()
    last_id = query_all_data(cursor, query_last_shutter_id)
    params = (date_now, time_now, event, 'action', camera_id, last_id)
    shutter_event_id = query_all_data(cursor, query_push_log, params)
    mydb.commit()
    return shutter_event_id

def check_location(roi, detections):
    if int(detections[1]) in range(roi['xmin'] , roi['xmax'] ) and int(detections[3]) in range(roi['xmin'] ,roi['xmax'] ):
        if int(detections[0]) in range(roi['ymin'] , roi['ymax'] ) and int(detections[2]) in range(roi['ymin'] , roi['ymax'] ):
            return True
        else:
            return False
    return False

# tiler_sink_pad_buffer_probe  will extract metadata received on tiler src pad
# and update params for drawing rectangle, object information etc.
def tiler_sink_pad_buffer_probe(pad, info, u_data):
    # stopping code
    global status
    global cmr_id
    now = dt.datetime.now()

    frame_number = 0
    num_rects = 0
    gst_buffer = info.get_buffer()
    if not gst_buffer:
        print("Unable to get GstBuffer ")
        return

    # Retrieve batch metadata from the gst_buffer
    # Note that pyds.gst_buffer_get_nvds_batch_meta() expects the
    # C address of gst_buffer as input, which is obtained with hash(gst_buffer)
    batch_meta = pyds.gst_buffer_get_nvds_batch_meta(hash(gst_buffer))


    l_frame = batch_meta.frame_meta_list
    while l_frame is not None:
        print("Inside l_frame")
        try:
            # Note that l_frame.data needs a cast to pyds.NvDsFrameMeta
            # The casting is done by pyds.NvDsFrameMeta.cast()
            # The casting also keeps ownership of the underlying memory
            # in the C code, so the Python garbage collector will leave
            # it alone.
            frame_meta = pyds.NvDsFrameMeta.cast(l_frame.data)
        except StopIteration:
            break
        fps_streams["stream{0}".format(frame_meta.pad_index)].get_fps()
        source_num = frame_meta.pad_index
        meta = streams_dict[camera_id_dict[source_num]]
        #print("meta: ", source_num)
        camera_id = camera_id_dict[source_num]

        frame_number = frame_meta.frame_num
        l_obj = frame_meta.obj_meta_list
        num_rects = frame_meta.num_obj_meta
        is_first_obj = True
        save_image = False
        obj_counter = {
            PGIE_CLASS_ID_CLOSE: 0,
            PGIE_CLASS_ID_OPEN: 0,
        }
        while l_obj is not None:
            
            #camera_id = camera_id_dict[source_num]
            #print(camera_id)
            try:
                # Casting l_obj.data to pyds.NvDsObjectMeta
                obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break
            obj_counter[obj_meta.class_id] += 1

            rect_params = obj_meta.rect_params
            top = int(rect_params.top)
            left = int(rect_params.left)
            width = int(rect_params.width)
            height = int(rect_params.height)

            #Shutter
            if source_num < No_of_Shutter_Streams:
                if obj_meta.obj_label == "Close" and meta["MIN_CONFIDENCE"] < obj_meta.confidence < meta["MAX_CONFIDENCE"] and (check_location(meta["roi"], [top, left, top + height, left + width]) == True):
                    meta["detected_cls"].append("close")
                elif obj_meta.obj_label == "Open"  and meta["MIN_CONFIDENCE"] < obj_meta.confidence < meta["MAX_CONFIDENCE"] and (check_location(meta["roi"], [top, left, top + height, left + width]) == True):
                    meta["detected_cls"].append("open")

                if "open" not in meta["detected_cls"][-meta["Shutter_Status_confirm"]:] and len(meta["detected_cls"]) >= meta["Shutter_Status_confirm"] and (meta["event"] == SHUTTER_OPEN or status[str(source_num)] == "open"):
                #if "open" not in meta["detected_cls"][-FPS_SHUTTER*5:] and len(meta["detected_cls"]) >=5 and meta["event"] == "SHUTTER_OPEN":
                    print("SHUTTER_CLOSE")
                    meta["event"]  = SHUTTER_CLOSE
                    today = datetime.now()
                    cmr_id = camera_id_dict[source_num]
                    date_now, time_now = today.date(), today.time()
                    n_frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
                    #n_frame = draw_bounding_boxes(n_frame, obj_meta, obj_meta.confidence)
                    # convert python array into numpy array format in the copy mode.
                    frame_copy = np.array(n_frame, copy=True, order='C')
                    # convert the array into cv2 default color format
                    frame_copy = cv2.cvtColor(frame_copy, cv2.COLOR_RGBA2BGRA)
                    img_path = "{}/stream_{}/frame_{}.jpg".format(folder_name, frame_meta.pad_index, frame_number)
                    #cv2.imwrite(img_path, frame_copy)
                    cv2.imwrite(img_path, frame_copy, [int(cv2.IMWRITE_JPEG_QUALITY), 10])
                    frame_name = folder_name + "frame_{}_{}_{}.jpg".format(frame_number, date_now, time_now)
                    image_url = upload_to_aws(img_path, BUCKET_NAME, frame_name)
                    event_id = push_data_to_log_and_shutter(cursor, date_now, time_now,image_url,event = meta["event"] )
                    push_current_time = datetime.now().time()
                    if (start_1 <= push_current_time and push_current_time <= end_1) or (start_2 <= push_current_time and push_current_time <= end_2):
                        try:
                            for i in list_token:
                                payload = json.dumps({
                                    "to": i,
                                    "notification": {
                                        "body": warehouse_name,
                                        "title": meta["event"],
                                        "subtitle": f"Date: {str(date_now)} , Time: {str(time_now)}"
                                    },
                                    "data": {
                                        "site_name": warehouse_name,
                                        "event_id": event_id,
                                        "camera_name": cmr_id,
                                        "event_time": str(time_now),
                                        "event_date": str(date_now),
                                        "event_tag": meta["event"],
                                        "image": image_url

                                    }
                                })

                                response = requests.request("POST", url, headers=headers, data=payload)
                                print(response.text)
                        except Exception as e:
                            print(e)
                    
                    streamNo = source_num
                    prev_status = status[str(source_num)]
                    cur_status = "close"
                    backup_status(streamNo, prev_status, cur_status)
                    with open(filename, 'r') as data:
                        for line in csv.DictReader(data):
                            status=line
                    data.close()



                #if "close" not in meta["detected_cls"][-FPS_SHUTTER*5:] and len(meta["detected_cls"]) >= 25 and(meta["event"] == SHUTTER_CLOSE or meta["event"] == "first_status"):
                if "close" not in meta["detected_cls"][-meta["Shutter_Status_confirm"]:] and len(meta["detected_cls"]) >= meta["Shutter_Status_confirm"] and (meta["event"] == SHUTTER_CLOSE or meta["event"] == "first_status") and (status[str(source_num)] == "first" or status[str(source_num)] == "close"):
                    print("SHUTTER_OPEN")
                    meta["event"] = SHUTTER_OPEN
                    today = datetime.now()
                    date_now, time_now = today.date(), today.time()
                    cmr_id = camera_id_dict[source_num]
                    n_frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
                    #n_frame = draw_bounding_boxes(n_frame, obj_meta, obj_meta.confidence)
                    # convert python array into numpy array format in th, where ee copy mode.
                    frame_copy = np.array(n_frame, copy=True, order='C')
                    # convert the array into cv2 default color format
                    frame_copy = cv2.cvtColor(frame_copy, cv2.COLOR_RGBA2BGRA)
                    img_path = "{}/stream_{}/frame_{}.jpg".format(folder_name, frame_meta.pad_index, frame_number)
                    #cv2.imwrite(img_path, frame_copy)
                    cv2.imwrite(img_path, frame_copy, [int(cv2.IMWRITE_JPEG_QUALITY), 10])
                    frame_name = folder_name + "frame_{}_{}_{}.jpg".format(frame_number, date_now, time_now)
                    image_url = upload_to_aws(img_path, BUCKET_NAME, frame_name)
                    event_id = push_data_to_log_and_shutter(cursor, date_now, time_now , image_url,event = meta["event"])
                    push_current_time = datetime.now().time()
                    if (start_1 <= push_current_time and push_current_time <= end_1) or (start_2 <= push_current_time and push_current_time <= end_2):
                        try:
                            for i in list_token:
                                payload = json.dumps({
                                    "to": i,
                                    "notification": {
                                        "body": warehouse_name,
                                        "title": meta["event"],
                                        "subtitle": f"Date: {str(date_now)} , Time: {str(time_now)}"
                                    },
                                    "data": {
                                        "site_name": warehouse_name,
                                        "event_id": event_id,
                                        "camera_name": cmr_id,
                                        "event_time": str(time_now),
                                        "event_date": str(date_now),
                                        "event_tag": meta["event"],
                                        "image": image_url

                                    }
                                })

                                response = requests.request("POST", url, headers=headers, data=payload)
                                print(response.text)
                        except Exception as e:
                            print(e)
                            
                    streamNo = source_num
                    prev_status = status[str(source_num)]
                    cur_status = "open"
                    backup_status(streamNo, prev_status, cur_status)

                    with open(filename, 'r') as data:
                        for line in csv.DictReader(data):
                            status=line
                    data.close()



                if len(meta["detected_cls"]) >= meta["Shutter_Status_confirm"] + 15:
                    meta["detected_cls"].pop(0)

            #Vehicle



            try:
                l_obj = l_obj.next
            except StopIteration:
                break



        #print("Frame Number=", frame_number, "Number of Objects=", num_rects, "Shutter_Close_count=",
        #      obj_counter[PGIE_CLASS_ID_CLOSE])

        # Get frame rate through this probe
        #fps_streams["stream{0}".format(source_num)] = PERF_DATA.perf_print_callback(source_num)
        stream_index = "stream{0}".format(frame_meta.pad_index)
        #global perf_data
        #perf_data.update_fps(stream_index)

        try:
            l_frame = l_frame.next
        except StopIteration:
            break

    return Gst.PadProbeReturn.OK


def draw_bounding_boxes(image, obj_meta, confidence):
    confidence = '{0:.2f}'.format(confidence)
    rect_params = obj_meta.rect_params
    top = int(rect_params.top)
    left = int(rect_params.left)
    width = int(rect_params.width)
    height = int(rect_params.height)
    obj_name = pgie_classes_str[obj_meta.class_id]
    # image = cv2.rectangle(image, (left, top), (left + width, top + height), (0, 0, 255, 0), 2, cv2.LINE_4)
    color = (0, 0, 255, 0)
    w_percents = int(width * 0.05) if width > 100 else int(width * 0.1)
    h_percents = int(height * 0.05) if height > 100 else int(height * 0.1)
    linetop_c1 = (left + w_percents, top)
    linetop_c2 = (left + width - w_percents, top)
    image = cv2.line(image, linetop_c1, linetop_c2, color, 6)
    linebot_c1 = (left + w_percents, top + height)
    linebot_c2 = (left + width - w_percents, top + height)
    image = cv2.line(image, linebot_c1, linebot_c2, color, 6)
    lineleft_c1 = (left, top + h_percents)
    lineleft_c2 = (left, top + height - h_percents)
    image = cv2.line(image, lineleft_c1, lineleft_c2, color, 6)
    lineright_c1 = (left + width, top + h_percents)
    lineright_c2 = (left + width, top + height - h_percents)
    image = cv2.line(image, lineright_c1, lineright_c2, color, 6)
    # Note that on some systems cv2.putText erroneously draws horizontal lines across the image
    image = cv2.putText(image, obj_name + ',C=' + str(confidence), (left - 10, top - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                        (0, 0, 255, 0), 2)
    return image


def cb_newpad(decodebin, decoder_src_pad, data):
    print("In cb_newpad\n")
    caps = decoder_src_pad.get_current_caps()
    gststruct = caps.get_structure(0)
    gstname = gststruct.get_name()
    source_bin = data
    features = caps.get_features(0)

    # Need to check if the pad created by the decodebin is for video and not
    # audio.
    if (gstname.find("video") != -1):
        # Link the decodebin pad only if decodebin has picked nvidia
        # decoder plugin nvdec_*. We do this by checking if the pad caps contain
        # NVMM memory features.
        if features.contains("memory:NVMM"):
            # Get the source bin ghost pad
            bin_ghost_pad = source_bin.get_static_pad("src")
            if not bin_ghost_pad.set_target(decoder_src_pad):
                sys.stderr.write("Failed to link decoder src pad to source bin ghost pad\n")
        else:
            sys.stderr.write(" Error: Decodebin did not pick nvidia decoder plugin.\n")


def decodebin_child_added(child_proxy, Object, name, user_data):
    print("Decodebin child added:", name, "\n")
    if name.find("decodebin") != -1:
        Object.connect("child-added", decodebin_child_added, user_data)


def create_source_bin(index, uri):
    print("Creating source bin")

    # Create a source GstBin to abstract this bin's content from the rest of the
    # pipeline
    bin_name = "source-bin-%02d" % index
    print(bin_name)
    nbin = Gst.Bin.new(bin_name)
    if not nbin:
        sys.stderr.write(" Unable to create source bin \n")

    # Source element for reading from the uri.
    # We will use decodebin and let it figure out the container format of the
    # stream and the codec and plug the appropriate demux and decode plugins.
    uri_decode_bin = Gst.ElementFactory.make("uridecodebin", "uri-decode-bin")
    if not uri_decode_bin:
        sys.stderr.write(" Unable to create uri decode bin \n")
    # We set the input uri to the source element
    uri_decode_bin.set_property("uri", uri)
    # Connect to the "pad-added" signal of the decodebin which generates a
    # callback once a new pad for raw data has beed created by the decodebin
    uri_decode_bin.connect("pad-added", cb_newpad, nbin)
    uri_decode_bin.connect("child-added", decodebin_child_added, nbin)

    # We need to create a ghost pad for the source bin which will act as a proxy
    # for the video decoder src pad. The ghost pad will not have a target right
    # now. Once the decode bin creates the video decoder and generates the
    # cb_newpad callback, we will set the ghost pad target to the video decoder
    # src pad.
    Gst.Bin.add(nbin, uri_decode_bin)
    bin_pad = nbin.add_pad(Gst.GhostPad.new_no_target("src", Gst.PadDirection.SRC))
    if not bin_pad:
        sys.stderr.write(" Failed to add ghost pad in source bin \n")
        return None
    return nbin


def main(args, roi, Shutter_Status_confirm, arg_list, MIN_CONFIDENCE , MAX_CONFIDENCE):
    global camera_id_dict
    camera_id_dict = camera_id_dict
    # Check input arguments

    if streams_type == 0:
        if len(args) < 2:
            sys.stderr.write("usage: %s <uri1> [uri2] ... [uriN] <folder to save frames>\n" % args[0])
            sys.exit(1)
    if streams_type == 1:
        if len(args) < 1:
            sys.stderr.write("usage: %s <uri1> [uri2] ... [uriN] <folder to save frames>\n" % args[0])
            sys.exit(1)
    global perf_data


    if streams_type == 1:
        for i in range(0, len(arg_list)):
            #perf_data = PERF_DATA(len(args) - 2)
            fps_streams["stream{0}".format(i)] = GETFPS(i)
            streams_dict[camera_id_dict[i]] = {"detected_cls": [], "event":"first_status", "camera_id": '', "roi":roi[i] , "Shutter_Status_confirm": Shutter_Status_confirm[i], "MAX_CONFIDENCE": MAX_CONFIDENCE[i], "MIN_CONFIDENCE": MIN_CONFIDENCE[i]}
            number_sources = len(arg_list)
    if streams_type == 0:
        for i in range(0, len(args) - 2):
            #perf_data = PERF_DATA(len(args) - 2)
            fps_streams["stream{0}".format(i)] = GETFPS(i)
            streams_dict[camera_id_dict[i]] = {"detected_cls": [], "event":"first_status", "camera_id": '', "roi":roi[i] , "Shutter_Status_confirm": Shutter_Status_confirm[i], "MAX_CONFIDENCE": MAX_CONFIDENCE[i], "MIN_CONFIDENCE": MIN_CONFIDENCE[i]}
            number_sources = len(args) - 2

    global folder_name
    global push_data_dict
    global last_push_frame_number_dict
    global last_n_objs
    global count_increase_n_obj
    global count_decrease_n_obj
    global query_last_vehicle_id

    folder_name = args[-1]
    if path.exists(folder_name):
        sys.stderr.write("The output folder %s already exists. Please remove it first.\n" % folder_name)
        sys.exit(1)

    global mydb
    global cursor
    mydb, cursor = get_mydb_cursor()

    assert number_sources <= 3, 'Number of sources must be at most 3'

    get_init_dict = lambda value: {k: v for k, v in zip(list(range(number_sources)), [value] * number_sources)}
    # frame_count_dict = get_init_dict(0)
    push_data_dict = get_init_dict(True)
    last_push_frame_number_dict = get_init_dict(-30 * 25)
    last_n_objs = get_init_dict(0)
    count_increase_n_obj = get_init_dict(0)
    count_decrease_n_obj = get_init_dict(0)
    query_last_vehicle_id = 'SELECT id FROM stats_vehicle ORDER BY id DESC LIMIT 1'

    os.mkdir(folder_name)
    print("Frames will be saved in ", folder_name)
    # Standard GStreamer initialization
    GObject.threads_init()
    Gst.init(None)

    # Create gstreamer elements */
    # Create Pipeline element that will form a connection of other elements
    print("Creating Pipeline \n ")
    pipeline = Gst.Pipeline()
    is_live = False

    if not pipeline:
        sys.stderr.write(" Unable to create Pipeline \n")
    print("Creating streamux \n ")

    # Create nvstreammux instance to form batches from one or more sources.
    streammux = Gst.ElementFactory.make("nvstreammux", "Stream-muxer")
    if not streammux:
        sys.stderr.write(" Unable to create NvStreamMux \n")

    pipeline.add(streammux)
    for i in range(number_sources):
        os.mkdir(folder_name + "/stream_" + str(i))
        frame_count["stream_" + str(i)] = 0
        saved_count["stream_" + str(i)] = 0
        print("Creating source_bin ", i, " \n ")
        if streams_type == 1:#For RTSP_type input
            uri_name = arg_list[i]
        if streams_type == 0:#For File_type input
            uri_name = args[i + 1]
        if uri_name.find("rtsp://") == 0:
            is_live = True
        source_bin = create_source_bin(i, uri_name)
        if not source_bin:
            sys.stderr.write("Unable to create source bin \n")
        pipeline.add(source_bin)
        padname = "sink_%u" % i
        sinkpad = streammux.get_request_pad(padname)
        if not sinkpad:
            sys.stderr.write("Unable to create sink pad bin \n")
        srcpad = source_bin.get_static_pad("src")
        if not srcpad:
            sys.stderr.write("Unable to create src pad bin \n")
        srcpad.link(sinkpad)
    print("Creating Pgie \n ")
    pgie = Gst.ElementFactory.make("nvinfer", "primary-inference")
    if not pgie:
        sys.stderr.write(" Unable to create pgie \n")
    # Add nvvidconv1 and filter1 to convert the frames to RGBA
    # which is easier to work with in Python.
    print("Creating nvvidconv1 \n ")
    nvvidconv1 = Gst.ElementFactory.make("nvvideoconvert", "convertor1")
    if not nvvidconv1:
        sys.stderr.write(" Unable to create nvvidconv1 \n")
    print("Creating filter1 \n ")
    caps1 = Gst.Caps.from_string("video/x-raw(memory:NVMM), format=RGBA")
    filter1 = Gst.ElementFactory.make("capsfilter", "filter1")
    if not filter1:
        sys.stderr.write(" Unable to get the caps filter1 \n")
    filter1.set_property("caps", caps1)
    # print("Creating tiler \n ")
    # tiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
    # if not tiler:
    #    sys.stderr.write(" Unable to create tiler \n")
    # print("Creating nvvidconv \n ")
    # nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    # if not nvvidconv:
    #    sys.stderr.write(" Unable to create nvvidconv \n")
    print("Creating nvosd \n ")
    nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
    if not nvosd:
        sys.stderr.write(" Unable to create nvosd \n")
    # if (is_aarch64()):
    #    print("Creating transform \n ")
    #    transform = Gst.ElementFactory.make("nvegltransform", "nvegl-transform")
    #    if not transform:
    #        sys.stderr.write(" Unable to create transform \n")

    print("Creating EGLSink \n")
    sink = Gst.ElementFactory.make("fakesink", "fakesink")
    #sink = Gst.ElementFactory.make("nveglglessink", "nvvideo-renderer")
    if not sink:
        sys.stderr.write(" Unable to create egl sink \n")

    if is_live:
        print("Atleast one of the sources is live")
        streammux.set_property('live-source', 1)

    streammux.set_property('width', 1920)
    streammux.set_property('height', 1080)
    streammux.set_property('batch-size', 1)
    streammux.set_property('batched-push-timeout', 25000)
    pgie.set_property('config-file-path', 'shutter_pgie.txt')
    # tiler_rows = int(math.sqrt(number_sources))
    # tiler_columns = int(math.ceil((1.0 * number_sources) / tiler_rows))
    # tiler.set_property("rows", tiler_rows)
    # tiler.set_property("columns", tiler_columns)
    # tiler.set_property("width", TILED_OUTPUT_WIDTH)
    # tiler.set_property("height", TILED_OUTPUT_HEIGHT)

    sink.set_property("sync", 0)
    sink.set_property("qos", 0)

    if not is_aarch64():
        # Use CUDA unified memory in the pipeline so frames
        # can be easily accessed on CPU in Python.
        mem_type = int(pyds.NVBUF_MEM_CUDA_UNIFIED)
        streammux.set_property("nvbuf-memory-type", mem_type)
        # nvvidconv.set_property("nvbuf-memory-type", mem_type)
        nvvidconv1.set_property("nvbuf-memory-type", mem_type)
        # tiler.set_property("nvbuf-memory-type", mem_type)

    print("Adding elements to Pipeline \n")
    pipeline.add(pgie)
    # pipeline.add(tiler)
    # pipeline.add(nvvidconv)
    pipeline.add(filter1)
    pipeline.add(nvvidconv1)
    pipeline.add(nvosd)
    # if is_aarch64():
    #    pipeline.add(transform)
    pipeline.add(sink)

    print("Linking elements in the Pipeline \n")
    streammux.link(pgie)
    pgie.link(nvvidconv1)
    nvvidconv1.link(filter1)
    filter1.link(nvosd)
    # filter1.link(tiler)
    # tiler.link(nvvidconv)
    # nvvidconv.link(nvosd)
    # if is_aarch64():
    #    nvosd.link(transform)
    #    transform.link(sink)
    # else:
    #    nvosd.link(sink)
    nvosd.link(sink)

    # create an event loop and feed gstreamer bus mesages to it
    loop = GObject.MainLoop()
    bus = pipeline.get_bus()
    bus.add_signal_watch()
    bus.connect("message", bus_call, loop)

    tiler_sink_pad = nvosd.get_static_pad("sink")
    if not tiler_sink_pad:
        sys.stderr.write(" Unable to get src pad \n")
    else:
        tiler_sink_pad.add_probe(Gst.PadProbeType.BUFFER, tiler_sink_pad_buffer_probe, 0)
        #GLib.timeout_add(5000, perf_data.perf_print_callback)

    # List the sources
    print("Now playing...")
    if streams_type == 0:
        for i, source in enumerate(args[:-1]):
            if i != 0:
                print(i, ": ", source)
    if streams_type == 1:
        for i, source in enumerate(arg_list):
            print(i, ": ", source)


    print("Starting pipeline \n")
    # start play back and listed to events		
    pipeline.set_state(Gst.State.PLAYING)
    try:
        loop.run()
    except:
        pass
    # cleanup
    print("Exiting app\n")
    pipeline.set_state(Gst.State.NULL)
    commit_and_close(mydb, cursor)
def get_rtsp():
    args = []
    roi = []
    Shutter_Status_confirm = []
    MIN_CONFIDENCE = []
    MAX_CONFIDENCE = []
    for i in range(cdata['number_of_streams']):
        args.append(cdata['cameras'][f"cam{i+1}"]["inputs"])
        roi.append(cdata['cameras'][f"cam{i+1}"]["roi"])
        MIN_CONFIDENCE.append(cdata['cameras'][f"cam{i+1}"]["MIN_CONFIDENCE"])
        MAX_CONFIDENCE.append(cdata['cameras'][f"cam{i+1}"]["MAX_CONFIDENCE"])
        Shutter_Status_confirm.append(cdata['cameras'][f"cam{i+1}"]["Shutter_Status_confirm"])
    return args, roi, Shutter_Status_confirm, MIN_CONFIDENCE, MAX_CONFIDENCE



if __name__ == '__main__':
    arg_list, roi, Shutter_Status_confirm, MIN_CONFIDENCE , MAX_CONFIDENCE = get_rtsp()
    main(sys.argv,roi , Shutter_Status_confirm, arg_list, MIN_CONFIDENCE , MAX_CONFIDENCE)
    sys.exit(main(sys.argv))
