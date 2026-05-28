"""
MQTT-Client – optionale Anbindung an einen lokalen MQTT-Broker.

Topics:
  heta/filter/status       – aktueller Filterstatus (periodisch)
  heta/filter/measurements – Messwerte (periodisch)
  heta/filter/service      – Servicepaket (bei Ereignissen)
  heta/filter/alarm        – Alarme (bei Statusänderung)
"""

import json
import logging
import time

logger = logging.getLogger(__name__)


class MQTTClient:
    """
    Optionaler MQTT-Client basierend auf paho-mqtt.
    Wird nur gestartet wenn mqtt_enabled=true in settings.json.
    """

    TOPIC_STATUS       = "heta/filter/status"
    TOPIC_MEASUREMENTS = "heta/filter/measurements"
    TOPIC_SERVICE      = "heta/filter/service"
    TOPIC_ALARM        = "heta/filter/alarm"

    def __init__(self, broker: str = "localhost", port: int = 1883,
                 client_id: str = "heta_monitor"):
        self._broker = broker
        self._port = port
        self._client_id = client_id
        self._client = None
        self._connected = False

    def connect(self) -> bool:
        """Verbindet mit dem MQTT-Broker."""
        try:
            import paho.mqtt.client as mqtt  # type: ignore
            self._client = mqtt.Client(client_id=self._client_id)
            self._client.on_connect = self._on_connect
            self._client.on_disconnect = self._on_disconnect
            self._client.connect(self._broker, self._port, keepalive=60)
            self._client.loop_start()
            logger.info("MQTT verbunden mit %s:%d", self._broker, self._port)
            return True
        except Exception as e:
            logger.warning("MQTT-Verbindung fehlgeschlagen: %s", e)
            return False

    def disconnect(self):
        """Trennt die MQTT-Verbindung."""
        if self._client:
            self._client.loop_stop()
            self._client.disconnect()
            logger.info("MQTT getrennt.")

    def _on_connect(self, client, userdata, flags, rc):
        self._connected = (rc == 0)
        if self._connected:
            logger.info("MQTT verbunden (rc=%d).", rc)
        else:
            logger.warning("MQTT Verbindungsfehler rc=%d.", rc)

    def _on_disconnect(self, client, userdata, rc):
        self._connected = False
        logger.info("MQTT getrennt (rc=%d).", rc)

    def publish(self, topic: str, payload: dict, qos: int = 0, retain: bool = False) -> bool:
        """Veröffentlicht eine Nachricht auf einem MQTT-Topic."""
        if not self._connected or self._client is None:
            return False
        try:
            msg = json.dumps(payload, ensure_ascii=False)
            result = self._client.publish(topic, msg, qos=qos, retain=retain)
            return result.rc == 0
        except Exception as e:
            logger.error("MQTT publish Fehler: %s", e)
            return False

    def publish_status(self, filter_state, heta_code: str):
        """Veröffentlicht den aktuellen Filterstatus."""
        payload = {
            "timestamp": time.time(),
            "heta_code": heta_code,
            "status": filter_state.status,
            "filter_health_percent": filter_state.filter_health_percent,
            "dp_bar": filter_state.dp_bar,
        }
        self.publish(self.TOPIC_STATUS, payload)

    def publish_measurements(self, filter_state, heta_code: str):
        """Veröffentlicht die aktuellen Messwerte."""
        payload = {
            "timestamp": time.time(),
            "heta_code": heta_code,
            "p1_bar": filter_state.p1_bar,
            "p2_bar": filter_state.p2_bar,
            "dp_bar": filter_state.dp_bar,
            "flow_l_min": filter_state.flow_l_min,
            "temperature_c": filter_state.temperature_c,
            "r_eff": filter_state.r_eff,
        }
        self.publish(self.TOPIC_MEASUREMENTS, payload)

    def publish_alarm(self, alarm_type: str, message: str, heta_code: str):
        """Veröffentlicht einen Alarm."""
        payload = {
            "timestamp": time.time(),
            "heta_code": heta_code,
            "alarm_type": alarm_type,
            "message": message,
        }
        self.publish(self.TOPIC_ALARM, payload, qos=1)

    def publish_service(self, service_payload: dict):
        """Veröffentlicht ein Service-Datenpaket."""
        self.publish(self.TOPIC_SERVICE, service_payload, qos=1)

    @property
    def is_connected(self) -> bool:
        return self._connected
