import time
import json
import random
import paho.mqtt.client as mqtt
from datetime import datetime

# Ayarlar
MQTT_BROKER = "localhost"
MQTT_PORT = 1883
MQTT_TOPIC = "factory/machine/01/sensor"

# Makine Durumları
NORMAL_MEAN_CURRENT = 12.0  # Normalde 12 Amper çekiyor
ANOMALY_MEAN_CURRENT = 18.0 # Anormal durumda 18 Amper çekiyor

client = mqtt.Client()

def connect_mqtt():
    try:
        client.connect(MQTT_BROKER, MQTT_PORT, 60)
        print("✅ MQTT Broker'a bağlanıldı!")
    except Exception as e:
        print(f"❌ Bağlantı hatası: {e}")

def generate_data():
    while True:
        # %10 ihtimalle anomali (kaçak/zorlanma) üretelim
        is_anomaly = random.random() < 0.10
        
        if is_anomaly:
            current = random.gauss(ANOMALY_MEAN_CURRENT, 2.0) # Yüksek akım, yüksek varyans
            status = "ANOMALY"
            print(f"⚠️ DİKKAT: Anomali simüle ediliyor! (Akım: {current:.2f} A)")
        else:
            current = random.gauss(NORMAL_MEAN_CURRENT, 0.5) # Normal akım, düşük varyans
            status = "NORMAL"

        # Voltaj genellikle sabittir ama hafif dalgalanır
        voltage = random.gauss(220, 1.0)
        
        # Güç Hesabı (P = V * I * cosPhi) - cosPhi 0.8 varsayalım
        power = (voltage * current * 0.8) / 1000 # kW cinsinden

        payload = {
            "timestamp": datetime.utcnow().isoformat(),
            "machine_id": "Press_01",
            "current_amp": round(current, 2),
            "voltage_v": round(voltage, 2),
            "power_kw": round(power, 3),
            "status_label": status # Bunu yapay zeka eğitiminde 'ground truth' olarak kullanabiliriz
        }

        # Veriyi JSON olarak gönder
        client.publish(MQTT_TOPIC, json.dumps(payload))
        
        if status == "NORMAL":
            print(f"📤 Veri gönderildi: {payload['current_amp']} A (Normal)")
            
        time.sleep(1) # Saniyede 1 veri

if __name__ == "__main__":
    connect_mqtt()
    generate_data()