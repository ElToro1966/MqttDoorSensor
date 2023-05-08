import simplelogger
import time
import network
import machine
from rp2 import PIO
import umqtt.simple
import json
import socket
import struct
        
# Configuration
try:
    config_file = open("config.json", "r")
except OSError as e:
    logger.add_log_message("ERROR",str(e))
    raise(e)

try:
    config = json.load(config_file)
except OSError as e:
    logger.add_log_message("ERROR",str(e))
    raise(e)

wifi_ssid = config['wifi']['ssid']
wifi_pw = config['wifi']['password']
wifi_retries = config['wifi']['retries']

mqtt_server = config['mqtt']['server']
client_id = config['mqtt']['client_id']
mqtt_topic = bytes(config['mqtt']['topic'], "utf-8")
mqtt_connection_check_topic = bytes(config['mqtt']['connection_check_topic'], "utf-8")
mqtt_bad_connection_flag = True

logger = simplelogger.SimpleLogger("detect.log")
log_messages_written = 0
logger.flush_logfile()
    
NTP_DELTA = config['time']['ntp_delta']   
ntp_host = config['time']['ntp_host']

msg_queue = []

led = machine.Pin(22, machine.Pin.OUT)
sensor = machine.Pin(5, machine.Pin.IN, machine.Pin.PULL_UP)

def warning_blink(warning_led):
    for i in range(10):
        warning_led.high()
        print(warning_led)
        time.sleep(0.5)
        warning_led.low()
        time.sleep(0.5)
        i =+ 1
        
            
def wlan_connect():
    i = 0
    wlan = network.WLAN(network.STA_IF)
    try:
        while (i <= wifi_retries) and (not wlan.isconnected()):
            wlan.active(True)
            wlan.connect(wifi_ssid, wifi_pw)
            time.sleep(1)
            i += 1
    except OSError as e:
        logger.add_log_message("ERROR",str(e))
    if not wlan.isconnected():
        logger.add_log_message("WARNING", "Cannot connect to WIFI. Status code: " + str(wlan.status()))
    if wlan.isconnected():
        logger.add_log_message("INFO", "Connected to WIFI")
    return wlan


def mqtt_connect():
    global mqtt_bad_connection_flag
    try:
        mqtt_client = umqtt.simple.MQTTClient(client_id, mqtt_server, port=1883, keepalive=3600)
        mqtt_client.set_last_will(mqtt_connection_check_topic, b"0", retain=True, qos=0)
        mqtt_client.connect()
    except OSError as e:
        logger.add_log_message("ERROR", str(e))
        mqtt_bad_connection_flag = True
    except:
        logger.add_log_message("WARNING", "Cannot connect to MQTT.")
        mqtt_bad_connection_flag = True
    try:
        mqtt_client.publish(mqtt_connection_check_topic, b"1", retain=True, qos=0)
        logger.add_log_message("INFO", "Connected to mqtt-server")
        mqtt_bad_connection_flag = False
    except OSError as e:
        logger.add_log_message("ERROR", str(e))
        mqtt_bad_connection_flag = True
    except:
        logger.add_log_message("WARNING", "Cannot publish to MQTT connection check topic.")
        mqtt_bad_connection_flag = True
    return mqtt_client


def transmit_mqtt_message():
    global mqtt_bad_connection_flag
    if msg_queue != []:
        wlan_client = wlan_connect()
        mqtt_client = mqtt_connect()
        if mqtt_bad_connection_flag == False:
            try:
                msg = msg_queue.pop()
                print("MESSAGE TO TRANSMIT: " + str(mqtt_topic) + " - " + str(msg))
                mqtt_client.publish(mqtt_topic, msg)
            except OSError as e:
                logger.add_log_message("ERROR", str(e))
                alarm(warning_led_name, leds_all)
            try:
                mqtt_client.disconnect()
                mqtt_bad_connection_flag = True
            except OSError as e:
                logger.add_log_message("ERROR", str(e))
        else:
            try:
                wlan_client.disconnect()
            except OSError as e:
                logger.add_log_message("ERROR", str(e))
        
        
def create_mqtt_message(msg, sensor_values):
    mqt_msg = str(msg + str(sensor_values))
    return bytes(mqt_msg, "utf-8")
        
        
def set_time(wlan, ntp_host, NTP_DELTA):
    NTP_QUERY = bytearray(48)
    NTP_QUERY[0] = 0x1B
    
    addr = socket.getaddrinfo(ntp_host, 123)[0][-1]
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.settimeout(1)
        res = s.sendto(NTP_QUERY, addr)
        msg = s.recv(48)
    except OSError as e:
        logger.add_log_message("ERROR", str(e))
        alarm(warning_led_name, leds_all)
    finally:
        s.close()
    val = struct.unpack("!I", msg[40:44])[0]
    t = val - NTP_DELTA    
    tm = time.gmtime(t)
    machine.RTC().datetime((tm[0], tm[1], tm[2], tm[6] + 1, tm[3], tm[4], tm[5], 0))
    
    
def write_to_log():
    global log_messages_written
    if logger.log_message_queue != []:
        logger.write_to_logfile()
        logger.flush_log_message_queue()
        log_messages_written =+ 1
    if log_messages_written > 1000:
        logger.flush_logfile()
        log_messages_written = 0
        

def sense_movement():
    led.low()
    sensor_value = 0
    sensor_value = sensor.value()
    print(sensor_value)
    # inverse button (warning when not pushed, i.e., door open
    if sensor_value == 1:
        warning_blink(led)
        mqtt_msg = create_mqtt_message(
            "Door open",
            [("client", client_id), ("value", sensor_value), ("time", time.time())]
        )
        msg_queue.append(mqtt_msg)
        time.sleep(10)
    else:
        time.sleep(60)
    
        
set_time(wlan_connect(), ntp_host, NTP_DELTA)
while True:
    sense_movement()
    transmit_mqtt_message()
    write_to_log()