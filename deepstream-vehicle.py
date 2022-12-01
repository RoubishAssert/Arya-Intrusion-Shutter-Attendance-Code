#!/usr/bin/env python3

import sys
sys.path.append('../')
import gi
gi.require_version('Gst', '1.0')
from gi.repository import GObject, Gst
import time
import sys
import configparser
from common.is_aarch_64 import is_aarch64
from common.bus_call import bus_call
from common.FPS import GETFPS
import numpy as np
import pyds
import cv2
import os
import os.path
from os import path
from datetime import datetime
import datetime as dt
from utils import query_last_attendance_id, query_last_vehicle_id, query_last_intrusion_id, query_push_intrusion, query_push_attendance, query_push_vehicle, query_push_log, query_all_data, get_mydb_cursor, commit_and_close, upload_to_aws
from config import BUCKET_NAME, SECONDS_GAP_BEFORE_INTRUSION, FPS_INTRUSION, SECONDS_GAP_BEFORE_VEHICLE, FPS_VEHICLE
import yaml
from yaml.loader import SafeLoader
import json, boto3
import yaml
from yaml.loader import SafeLoader

with open('vehicle_config.yml') as f:
    cdata = yaml.load(f, Loader=SafeLoader)
streams_type = cdata['streams_type']
camera_id_dict = cdata["camera_id_dict"]


fps_streams = {}
frame_count = {}
saved_count = {}
streams_dict = {}
global PGIE_CLASS_ID_BICYCLE
PGIE_CLASS_ID_BICYCLE = 1
global PGIE_CLASS_ID_CAR
PGIE_CLASS_ID_CAR = 2
global PGIE_CLASS_ID_MOTORBIKE
PGIE_CLASS_ID_MOTORBIKE = 3
global PGIE_CLASS_ID_BUS
PGIE_CLASS_ID_BUS = 5
global PGIE_CLASS_ID_TRUCK
PGIE_CLASS_ID_TRUCK = 7

MAX_DISPLAY_LEN = 64
MUXER_OUTPUT_WIDTH = 1920
MUXER_OUTPUT_HEIGHT = 1080
MUXER_BATCH_TIMEOUT_USEC = 4000000
TILED_OUTPUT_WIDTH = 1920
TILED_OUTPUT_HEIGHT = 1080
flip = 2
dispW = 640
dispH = 480
GST_CAPS_FEATURES_NVMM = "memory:NVMM"
pgie_classes_str = [ "bicycle", "car", "motorbike", "bus", "truck"]
streams_dict = {}

blank_image = "https://at-arya-bucket.s3.ap-south-1.amazonaws.com/1frame_99_2022-07-05_08_20_33.png"

# wh_name = 'MangalkumarIND_A-56-57'
# aws_arn = 'arn:aws:sns:ap-south-1:387137730207:intrusion-arya'



# Function for message sent when vehicle detected.
# Parameter : 3
# arn : Amazon resource names  value: aws_arn
# image_url : url of screenshot
# def publish_message(arn, warehouse_name, image_url):
#     sns = boto3.resource('sns', aws_access_key_id="AKIAVUIZU62PUNXPFZVS",
#                          aws_secret_access_key="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", region_name='ap-south-1')
#     topic = sns.Topic(arn)
#     x = dt.datetime.now()
#     message = {
#         "default": "Sample fallback message",
#         "email": "Vehicle Alert\nWarehouse Name: {}\nTime: {}\nDate: {}\nImage: {}".format(warehouse_name,
#                                                                                            x.strftime("%X"),
#                                                                                            x.strftime("%d/%m/%Y"),
#                                                                                            image_url),
#         "sms": "Vehicle Alert\nWarehouse Name: {}\nTime: {}\nDate: {}\nImage: {}".format(warehouse_name,
#                                                                                          x.strftime("%X"),
#                                                                                          x.strftime("%d/%m/%Y"),
#                                                                                          image_url),
#     }
#     response = topic.publish(Message=str(json.dumps(message)), Subject="Vehicle Alert", MessageStructure='json')
#     return response


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
    # Switch off condition
    
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

        source_num = frame_meta.pad_index
        meta = streams_dict[camera_id_dict[source_num]]
        camera_id = camera_id_dict[source_num]

        frame_number = frame_meta.frame_num
        l_obj = frame_meta.obj_meta_list
        num_rects = frame_meta.num_obj_meta
        obj_counter = {
            PGIE_CLASS_ID_BICYCLE: 0,
            PGIE_CLASS_ID_CAR: 0,
            PGIE_CLASS_ID_MOTORBIKE: 0,
            PGIE_CLASS_ID_BUS: 0,
            PGIE_CLASS_ID_TRUCK: 0

        }

        while l_obj is not None:
            try:
                # Casting l_obj.data to pyds.NvDsObjectMeta
                obj_meta = pyds.NvDsObjectMeta.cast(l_obj.data)
            except StopIteration:
                break
            if obj_meta.class_id < 5:
                obj_counter[obj_meta.class_id] += 1
            # Periodically check for objects with borderline confidence value that may be false positive detections.
            # If such detections are found, annotate the frame with bboxes and confidence value.
            # Save the annotated frame to file.


            # Vehicle Code
            rect_params = obj_meta.rect_params
            top = int(rect_params.top)
            left = int(rect_params.left)
            width = int(rect_params.width)
            height = int(rect_params.height)

            if meta["MIN_CONFIDENCE"] < obj_meta.confidence < meta["MAX_CONFIDENCE"] and (check_location(meta["roi"], [top, left, top + height, left + width]) == True):
                if obj_meta.object_id not in meta["vehicle_id"]:
                    meta["vehicle_id"].append(obj_meta.object_id)
                    print(obj_meta.obj_label)
                    frame_time_and_date = datetime.fromtimestamp(frame_meta.ntp_timestamp / 1000000000).strftime(
                        '%Y-%m-%d %H:%M:%S')
                    frame_date = frame_time_and_date[0:10]
                    frame_time = frame_time_and_date[-8:]
                    # Getting Image data using nvbufsurface
                    # the input should be address of buffer and batch_id
                    n_frame = pyds.get_nvds_buf_surface(hash(gst_buffer), frame_meta.batch_id)
                    #n_frame = draw_bounding_boxes(n_frame, obj_meta, obj_meta.confidence)
                    # convert python array into numpy array format in the copy mode.
                    frame_copy = np.array(n_frame, copy=True, order='C')
                    # convert the array into cv2 default color format
                    frame_copy = cv2.cvtColor(frame_copy, cv2.COLOR_RGBA2BGRA)
                    number_of_white_pix = np.sum(frame_copy == 255)
                    number_of_black_pix = np.sum(frame_copy == 0)
                    print('Number of white pixels:', number_of_white_pix)
                    print('Number of black pixels:', number_of_black_pix)
                    if number_of_black_pix < 6220000:
                        img_path = "{}/stream_{}/frame_{}.jpg".format(folder_name, frame_meta.pad_index, frame_number)
                        cv2.imwrite(img_path, frame_copy, [int(cv2.IMWRITE_JPEG_QUALITY), 10])
                        frame_name = folder_name + "frame_{}_{}_{}.jpg".format(frame_number, frame_date, frame_time)
                        image_url = upload_to_aws(img_path, BUCKET_NAME, frame_name)
                        if obj_meta.obj_label == "truck":
                            insert_data_vehicle(frame_date, camera_id, frame_time, image_url, "Truck")
                        elif obj_meta.obj_label == "car":
                            insert_data_vehicle(frame_date, camera_id, frame_time, image_url, "Car")
                        else:
                            continue
                    else:
                        continue
                    
                        
            try:
                l_obj = l_obj.next
            except StopIteration:
                break


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


# def decodebin_child_added(child_proxy, Object, name, user_data):
#     print("Decodebin child added:", name, "\n")
#     if name.find("decodebin") != -1:
#         Object.connect("child-added", decodebin_child_added, user_data)

def decodebin_child_added(child_proxy,Object,name,user_data):
    print("Decodebin child added:", name, "\n")
    if(name.find("decodebin") != -1):
        Object.connect("child-added",decodebin_child_added,user_data)
    if(name.find("nvv4l2decoder") != -1):
        if (is_aarch64()):
            Object.set_property("enable-max-performance", True)
            Object.set_property("drop-frame-interval", 0)
            Object.set_property("num-extra-surfaces", 0)
        else:
            Object.set_property("gpu_id", GPU_ID)
    if "source" in name:
            source_element = child_proxy.get_by_name("source")
            if source_element.find_property("drop-on-latency") != None:
                Object.set_property("drop-on-latency", True)


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


def main(args, roi , arg_list, MIN_CONFIDENCE , MAX_CONFIDENCE):
    # Check input arguments
    global number_sources
    global camera_id_dict
    camera_id_dict = camera_id_dict
    if streams_type == 0:
        if len(args) < 2:
            sys.stderr.write("usage: %s <uri1> [uri2] ... [uriN] <folder to save frames>\n" % args[0])
            sys.exit(1)
    if streams_type == 1:
        if len(args) < 1:
            sys.stderr.write("usage: %s <uri1> [uri2] ... [uriN] <folder to save frames>\n" % args[0])
            sys.exit(1)


    if streams_type == 1:
        for i in range(0, len(arg_list)):
            fps_streams["stream{0}".format(i)] = GETFPS(i)
            streams_dict[camera_id_dict[i]] = { "roi":roi[i] ,  "MAX_CONFIDENCE": MAX_CONFIDENCE[i], "MIN_CONFIDENCE": MIN_CONFIDENCE[i], "save_image": False , "vehicle_id": []}
            number_sources = len(arg_list)
    if streams_type == 0:
        for i in range(0, len(args) - 2):
            fps_streams["stream{0}".format(i)] = GETFPS(i)
            streams_dict[camera_id_dict[i]] = {"roi":roi[i] ,  "MAX_CONFIDENCE": MAX_CONFIDENCE[i], "MIN_CONFIDENCE": MIN_CONFIDENCE[i], "save_image": False , "vehicle_id": []}
            number_sources = len(args) - 2
    
    global folder_name
    global frame_count_dict
    global push_data_dict
    global last_push_frame_number_dict
    global last_push_frame_number_dict_vehicle
    #global camera_id_dict
    global last_push_n_objs
    global last_n_objs
    global count_increase_n_obj
    global count_decrease_n_obj
    # global query_last_intrusion_id
    #global number_sources
    global upload_check
    global last_push_at
    
    upload_check = [False, False, False, False, False]
    
    

    #number_sources = len(args) - 2
    last_push_at = [float('-inf')]*(number_sources - 1)
    folder_name = args[-1]
    if path.exists(folder_name):
        sys.stderr.write("The output folder %s already exists. Please remove it first.\n" % folder_name)
        sys.exit(1)

    assert number_sources <= 7, 'Number of sources must be at most 5'

    get_init_dict = lambda value: {k: v for k, v in zip(list(range(number_sources)), [value] * number_sources)}
    frame_count_dict = get_init_dict(0)
    push_data_dict = get_init_dict(True)
    last_push_frame_number_dict = get_init_dict(-FPS_INTRUSION * SECONDS_GAP_BEFORE_INTRUSION)
    last_push_frame_number_dict_vehicle = get_init_dict(-30 * 25)
    #camera_id_dict = {0: '5_3', 1: '5_4',2:'5_1'}
    last_n_objs = get_init_dict(0)
    last_push_n_objs = get_init_dict(0)
    count_increase_n_obj = get_init_dict(0)
    count_decrease_n_obj = get_init_dict(0)
    # query_last_intrusion_id = 'SELECT id FROM stats_intrusion ORDER BY id DESC LIMIT 1'

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
        source_folder = "stream_" + str(i)
        frame_count[source_folder] = 0
        saved_count[source_folder] = 0
        print("Creating source_bin ", i, " \n ")
        #uri_name = args[i + 1]
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
    

    tracker = Gst.ElementFactory.make("nvtracker", "tracker")
    if not tracker:
        sys.stderr.write(" Unable to create tracker \n")
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
#     print("Creating tiler \n ")
#     tiler = Gst.ElementFactory.make("nvmultistreamtiler", "nvtiler")
#     if not tiler:
#        sys.stderr.write(" Unable to create tiler \n")
    print("Creating nvvidconv \n ")
    nvvidconv = Gst.ElementFactory.make("nvvideoconvert", "convertor")
    if not nvvidconv:
       sys.stderr.write(" Unable to create nvvidconv \n")
    print("Creating nvosd \n ")
    nvosd = Gst.ElementFactory.make("nvdsosd", "onscreendisplay")
    if not nvosd:
        sys.stderr.write(" Unable to create nvosd \n")
    if (is_aarch64()):
       print("Creating transform \n ")
       transform = Gst.ElementFactory.make("nvegltransform", "nvegl-transform")
       if not transform:
           sys.stderr.write(" Unable to create transform \n")

    print("Creating EGLSink \n")
    sink = Gst.ElementFactory.make("fakesink", "nvvideo-renderer")
    #sink = Gst.ElementFactory.make("nveglglessink", "nvvideo-renderer")
    if not sink:
        sys.stderr.write(" Unable to create egl sink \n")

    if is_live:
        print("Atleast one of the sources is live")
        streammux.set_property('live-source', 1)

    streammux.set_property('width', 1920)
    streammux.set_property('height', 1080)
    streammux.set_property('batch-size', number_sources)
    streammux.set_property('batched-push-timeout', 40000)
    pgie.set_property('config-file-path', "vehicle_pgie.txt")
    pgie_batch_size = pgie.get_property("batch-size")
    if (pgie_batch_size != number_sources):
        print("WARNING: Overriding infer-config batch-size", pgie_batch_size, " with number of sources ",
              number_sources, " \n")
        pgie.set_property("batch-size", number_sources)
#     tiler_rows = int(math.sqrt(number_sources))
#     tiler_columns = int(math.ceil((1.0 * number_sources) / tiler_rows))
#     tiler.set_property("rows", tiler_rows)
#     tiler.set_property("columns", tiler_columns)
#     tiler.set_property("width", TILED_OUTPUT_WIDTH)
#     tiler.set_property("height", TILED_OUTPUT_HEIGHT)

    sink.set_property("sync", 0)
    sink.set_property("qos", 0)
    
    #Set properties of tracker
    config = configparser.ConfigParser()
    config.read('dsnvanalytics_tracker_config.txt')
    config.sections()

    for key in config['tracker']:
        if key == 'tracker-width' :
            tracker_width = config.getint('tracker', key)
            tracker.set_property('tracker-width', tracker_width)
        if key == 'tracker-height' :
            tracker_height = config.getint('tracker', key)
            tracker.set_property('tracker-height', tracker_height)
        if key == 'gpu-id' :
            tracker_gpu_id = config.getint('tracker', key)
            tracker.set_property('gpu_id', tracker_gpu_id)
        if key == 'll-lib-file' :
            tracker_ll_lib_file = config.get('tracker', key)
            tracker.set_property('ll-lib-file', tracker_ll_lib_file)
        if key == 'll-config-file' :
            tracker_ll_config_file = config.get('tracker', key)
            tracker.set_property('ll-config-file', tracker_ll_config_file)
        if key == 'enable-batch-process' :
            tracker_enable_batch_process = config.getint('tracker', key)
            tracker.set_property('enable_batch_process', tracker_enable_batch_process)
        if key == 'enable-past-frame' :
            tracker_enable_past_frame = config.getint('tracker', key)
            tracker.set_property('enable_past_frame', tracker_enable_past_frame)


    if not is_aarch64():
        # Use CUDA unified memory in the pipeline so frames
        # can be easily accessed on CPU in Python.
        mem_type = int(pyds.NVBUF_MEM_CUDA_UNIFIED)
        streammux.set_property("nvbuf-memory-type", mem_type)
        nvvidconv.set_property("nvbuf-memory-type", mem_type)
        nvvidconv1.set_property("nvbuf-memory-type", mem_type)
#         tiler.set_property("nvbuf-memory-type", mem_type)

    print("Adding elements to Pipeline \n")
    pipeline.add(pgie)
    pipeline.add(tracker)
#     pipeline.add(tiler)
#     pipeline.add(nvvidconv)
    pipeline.add(filter1)
    pipeline.add(nvvidconv1)
    pipeline.add(nvosd)
    if is_aarch64():
       pipeline.add(transform)
    pipeline.add(sink)
    print("Linking elements in the Pipeline \n")
    streammux.link(pgie)
    pgie.link(tracker)
    tracker.link(nvvidconv1)
    #pgie.link(nvvidconv1)
    nvvidconv1.link(filter1)
    filter1.link(nvosd)
#     filter1.link(tiler)
#     tiler.link(nvvidconv)
#     nvvidconv.link(nvosd)
#     if is_aarch64():
#        nvosd.link(transform)
#        transform.link(sink)
#     else:
#        nvosd.link(sink)
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

def get_rtsp():
    args = []
    roi = []
    MIN_CONFIDENCE = []
    MAX_CONFIDENCE = []
    for i in range(cdata['number_of_streams']):
        args.append(cdata['cameras'][f"cam{i+1}"]["inputs"])
        roi.append(cdata['cameras'][f"cam{i+1}"]["roi"])
        MIN_CONFIDENCE.append(cdata['cameras'][f"cam{i+1}"]["MIN_CONFIDENCE"])
        MAX_CONFIDENCE.append(cdata['cameras'][f"cam{i+1}"]["MAX_CONFIDENCE"])
    return args, roi, MIN_CONFIDENCE, MAX_CONFIDENCE



if __name__ == '__main__':
    arg_list, roi, MIN_CONFIDENCE , MAX_CONFIDENCE = get_rtsp()
    main(sys.argv, roi , arg_list, MIN_CONFIDENCE , MAX_CONFIDENCE)
    sys.exit(main(sys.argv))
