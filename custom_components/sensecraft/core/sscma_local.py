import logging

from homeassistant.core import HomeAssistant

from sscma.micro.client import Client
from sscma.micro.device import Device
from sscma.hook.supervision import ClassAnnotartor
from sscma.utils.image import  (
    image_from_base64,
    image_to_base64
)


import supervision as sv

from .mqtt_client import MQTTClient
import threading
from ..const import (
    DOMAIN,
)
_LOGGER = logging.getLogger(__name__)

class SScmaLocal():

    def __init__(self, hass: HomeAssistant, config: dict):
        self.hass = hass
        self.deviceName = config.get('device_name')
        self.deviceId = config.get('device_id')

        self.mqttBroker = config.get('mqtt_broker')
        self.mqttPort = config.get('mqtt_port')
        self.mqttUsername = config.get('mqtt_username')
        self.mqttPassword = config.get('mqtt_password')
        self.mqttTopic = config.get('mqtt_topic')
        if self.mqttTopic is not None:
            self.rx_topic = self.mqttTopic+"/tx"
            self.tx_topic = self.mqttTopic+"/rx"
        else:
            self.rx_topic = ""
            self.tx_topic = ""

        self.mqttClient = None
        self.sscmaClient = None
        self.stream_callback = None
        self.device = None
        self.connected = False
        self.connectEvent = threading.Event()
        self.classes = []
        
        self.tracker = sv.ByteTrack()
        self.label_annotator = sv.LabelAnnotator(text_scale=0.4, text_padding=2)
        self.box_annotator = sv.BoundingBoxAnnotator()
        self.trace_annotator = sv.TraceAnnotator()
        self.heat_map_annotator = sv.HeatMapAnnotator()
        
        self.trace = False
        self.heatmap = False
        
    def to_config(self):
        return {
            'device_name': self.deviceName,
            'device_id': self.deviceId,
            'mqtt_broker': self.mqttBroker,
            'mqtt_port': self.mqttPort,
            'mqtt_username': self.mqttUsername,
            'mqtt_password': self.mqttPassword,
            'mqtt_topic': self.mqttTopic,
        }

    @staticmethod
    def from_config(hass: HomeAssistant, config: dict):
        # 从字典创建对象
        local = SScmaLocal(hass, config)
        return local

    def setMqtt(self):
        try:
            mqtt = MQTTClient(
                self.mqttBroker,
                int(self.mqttPort),
                self.mqttUsername,
                self.mqttPassword
            )
            self.sscmaClient = Client(
                lambda msg: mqtt.publish(self.tx_topic, msg)
            )
            self.device = Device(
                self.sscmaClient
            )
            if mqtt.connect():
                self.device.on_connect = self.on_device_connect
                self.device.loop_start()
                self.mqttClient = mqtt
                self.mqttClient.subscribe(self.rx_topic)
                self.mqttClient.message_received = self.on_message
                # 等待连接结果
                if self.connectEvent.wait(timeout=30):
                    self.device.on_monitor = self.on_monitor
                    self.connected = True
                    return True
                else:
                    self.connected = False
                    return False
        except Exception as e:
            _LOGGER.error("MQTT setup failed")
            self.connected = False
            return False

    def on_device_connect(self, device):
        _LOGGER.info("Device connected")
        self.device.Invoke(-1, False, True)
        self.device.tscore = 70
        self.device.tiou = 45
        self.classes = self.device.model.classes
        self.connectEvent.set()

    def stop(self):
        self.device.loop_stop()
        if self.mqttClient:
            self.mqttClient.loop_stop()
            self.mqttClient.disconnect()
            self.connected = False

    def on_message(self, msg):
        self.sscmaClient.on_recieve(msg.payload)

    def on_monitor(self, device, message):
        image = message.get('image')
        # [[137, 95, 180, 165, 83, 0]]
        boxes = message.get('boxes')
        # [[137, 95, 83, 0]]
        points = message.get('points')
        # [[83, 0]]
        classes = message.get('classes')

        counts = {}
        length = len(self.classes)
        for index in range(length):
            counts[index] = 0

        if boxes is not None:
            for box in boxes:
                if len(box) == 6:
                    classId = box[5]
                    if classId < length:
                        counts[classId] += 1
        if points is not None:
            for point in points:
                if len(point) == 4:
                    classId = point[3]
                    if classId < length:
                        counts[classId] += 1
        if classes is not None:
            for cla in classes:
                if len(cla) == 2:
                    classId = cla[1]
                    if classId < length:
                        counts[classId] += 1

        for index in counts:
            if(len(self.classes) > index):
                name = self.classes[index]
                _event_type = ("{domain}_inference_{deviceId}_{name}").format(
                    domain=DOMAIN,
                    deviceId=self.deviceId,
                    name=name.lower()
                )
                self.hass.bus.fire(_event_type, {"value": counts[index]})
        
        if image is not None and self.stream_callback is not None:
            
            frame = image_from_base64(image)
            annotated_frame = frame.copy()
            
            if boxes is not None:
                detections = sv.Detections.from_sscma_micro(message)
                if self.trace:
                    detections = self.tracker.update_with_detections(detections)
                    labels = [
                        f"#{tracker_id} {device.model.classes[class_id]}:{confidence:.2f}"
                            for class_id, tracker_id, confidence 
                            in zip(detections.class_id, detections.tracker_id, detections.confidence)
                        ]
                else:
                    labels = [
                    f"{device.model.classes[class_id]}:{confidence:.2f}"
                        for class_id, confidence
                        in zip(detections.class_id, detections.confidence)
                    ] 
                    
                annotated_frame = self.box_annotator.annotate(
                        annotated_frame, detections=detections)
                
                annotated_frame = self.label_annotator.annotate(
                        annotated_frame, detections=detections, labels=labels)
                
                if self.trace:
                    annotated_frame = self.trace_annotator.annotate(
                            annotated_frame, detections=detections)
                
                if self.heatmap:
                    annotated_frame = self.heat_map_annotator.annotate(
                                annotated_frame, detections=detections)
            
            if classes is not None:
                classifications  = sv.Classifications.from_sscma_micro_cls(message)
                
                annotated_frame = self.class_annotator.annotate(
                        scene=annotated_frame, classifications=classifications, labels=device.model.classes
                    )
            
            self.stream_callback(image_to_base64(annotated_frame))

        
    def on_monitor_stream(self, callback):
        if not self.connected:
            self.setMqtt()

        self.stream_callback = callback
