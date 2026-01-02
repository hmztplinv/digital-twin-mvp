import json
import os
import joblib  # Modeli kaydetmek/yüklemek için
import numpy as np
import paho.mqtt.client as mqtt
from influxdb_client import InfluxDBClient, Point, WriteOptions
from influxdb_client.client.write_api import SYNCHRONOUS
from sklearn.ensemble import IsolationForest
import warnings
from datetime import datetime, timezone

warnings.filterwarnings("ignore")

# --- AYARLAR ---
MQTT_BROKER = "localhost"
MQTT_TOPIC = "factory/machine/01/sensor"

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "my-super-secret-auth-token"
INFLUX_ORG = "my-org"
INFLUX_BUCKET = "energy_data"

# AI Modeli Dosya Yolu
MODEL_FILE = "ai_model.pkl"

# Yeşil Dönüşüm Parametreleri
EMISSION_FACTOR_TR = 0.44
ELECTRICITY_COST_TL = 4.50

# Global Değişkenler
TRAINING_SIZE = 30
data_buffer = []
model = None
is_model_trained = False

# --- BAĞLANTILAR ---
db_client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
write_api = db_client.write_api(write_options=SYNCHRONOUS)

# --- MODEL YÜKLEME FONKSİYONU ---
def load_or_initialize_model():
    global model, is_model_trained
    if os.path.exists(MODEL_FILE):
        print(f"💾 Kayıtlı model bulundu: {MODEL_FILE}")
        try:
            model = joblib.load(MODEL_FILE)
            is_model_trained = True
            print("✅ Model başarıyla yüklendi! Eğitim aşaması atlanıyor.")
        except Exception as e:
            print(f"⚠️ Model yüklenirken hata oluştu: {e}")
            is_model_trained = False
    else:
        print("🆕 Kayıtlı model bulunamadı. Sıfırdan eğitim yapılacak.")
        is_model_trained = False

def on_connect(client, userdata, flags, rc, properties=None):
    print("✅ AI Engine: MQTT Broker'a bağlandı!")
    client.subscribe(MQTT_TOPIC)

def on_message(client, userdata, msg):
    global is_model_trained, model, data_buffer

    try:
        payload = json.loads(msg.payload.decode())
        current_amp = payload["current_amp"]
        power_kw = payload["power_kw"]
        machine_id = payload["machine_id"]
        now = datetime.now(timezone.utc)

        # 1. SKDM Hesaplamaları
        energy_kwh_per_sec = power_kw / 3600 
        instant_co2_grams = energy_kwh_per_sec * EMISSION_FACTOR_TR * 1000 
        instant_cost_kurus = energy_kwh_per_sec * ELECTRICITY_COST_TL * 100

        # 2. Metrik Kaydı
        point = Point("machine_metrics") \
            .tag("machine_id", machine_id) \
            .field("current", float(current_amp)) \
            .field("power_kw", float(power_kw)) \
            .field("co2_grams", float(instant_co2_grams)) \
            .field("cost_kurus", float(instant_cost_kurus)) \
            .time(now)
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=point)

        # 3. AI Süreci
        ai_status = 0 

        if not is_model_trained:
            # Eğitim Modu
            data_buffer.append([current_amp])
            print(f"🔄 Model Eğitiliyor... Veri: {len(data_buffer)}/{TRAINING_SIZE}")
            
            if len(data_buffer) >= TRAINING_SIZE:
                print("🤖 Yeterli veri toplandı. Model eğitiliyor...")
                model = IsolationForest(contamination=0.1, random_state=42)
                model.fit(data_buffer)
                
                # Modeli Diske Kaydet
                joblib.dump(model, MODEL_FILE)
                print(f"💾 Model diske kaydedildi: {MODEL_FILE}")
                
                is_model_trained = True
                data_buffer = [] # Buffer'ı temizle
        else:
            # Tahmin Modu
            prediction = model.predict([[current_amp]])[0]
            if prediction == -1:
                ai_status = 1
                print(f"🚨 ANOMALİ! {current_amp} A")
            else:
                ai_status = 0
                print(f"🆗 Normal: {current_amp} A")

        # 4. AI Sonucu Kaydı
        ai_point = Point("ai_analysis") \
            .tag("machine_id", machine_id) \
            .field("is_anomaly", int(ai_status)) \
            .time(now)
        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=ai_point)

    except Exception as e:
        print(f"Hata: {e}")

# --- BAŞLATMA ---
load_or_initialize_model() # Başlarken modeli kontrol et

mqtt_client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
mqtt_client.on_connect = on_connect
mqtt_client.on_message = on_message

print("⏳ GreenTwin AI Engine başlatılıyor...")
mqtt_client.connect(MQTT_BROKER, 1883, 60)
mqtt_client.loop_forever()