import json
import os
import time

from dotenv import load_dotenv
import paho.mqtt.client as mqtt
import pandas as pd

load_dotenv()

# ==========================================
# ⚙️ CONFIGURATION
# ==========================================
# ตั้งค่าให้ตรงกับ MQTT Broker ที่ Ingestion Bridge ของคุณไปเกาะอยู่
MQTT_BROKER = os.getenv("MQTT_BROKER")
MQTT_PORT = int(os.getenv("MQTT_PORT", 8883))
MQTT_USERNAME = os.getenv("MQTT_PUB_USERNAME")  # ใช้ Publish credentials
MQTT_PASSWORD = os.getenv("MQTT_PUB_PASSWORD")

if not all([MQTT_BROKER, MQTT_USERNAME, MQTT_PASSWORD]):
    raise ValueError("Missing required MQTT configurations. Please check your .env file.")

# Topic ต้องตรงกับ Format "gait/telemetry/<user_id>"
MQTT_TOPIC = "gait/telemetry/user_test_01"

# ตัวคูณความเร็ว (1.0 = ความเร็วเท่าเดินจริง, 10.0 = เร็วขึ้น 10 เท่า)
SPEED_MULTIPLIER = 10.0
CHUNK_SIZE = 100  # ส่งทีละ 100 ค่า (เท่ากับ 1 วินาทีในโลกจริง)

# ==========================================


def on_connect(client, userdata, flags, reason_code, properties):
    if reason_code == 0:
        print("✅ เชื่อมต่อ MQTT Broker สำเร็จ!")
    else:
        print(f"❌ เชื่อมต่อล้มเหลว Code: {reason_code}")


def simulate_walk(client, csv_path, description):
    print(f"\n🚀 เริ่มสตรีม: {description}")
    print(f"📁 ไฟล์: {csv_path}")

    df = pd.read_csv(csv_path)
    gyro_z_data = df["gyro_z"].tolist()
    total_chunks = len(gyro_z_data) // CHUNK_SIZE

    print(f"📦 เตรียมส่งข้อมูลทั้งหมด {total_chunks} แพ็กเกจ (แพ็กเกจละ {CHUNK_SIZE} ค่า)")
    print(f"⏩ ความเร็วจำลอง: {SPEED_MULTIPLIER}x")

    # คำนวณเวลาที่ต้องรอในแต่ละรอบ
    sleep_time = 1.0 / SPEED_MULTIPLIER

    for i in range(0, len(gyro_z_data), CHUNK_SIZE):
        chunk = gyro_z_data[i : i + CHUNK_SIZE]

        # ปั้น Payload ให้เหมือนของจริง
        payload = {"gyro_z": chunk}

        # แปลงเป็น JSON String
        payload_json = json.dumps(payload)

        # ยิงเข้า MQTT
        client.publish(MQTT_TOPIC, payload_json, qos=1)

        # Print progress ทุกๆ 10 แพ็กเกจ (เพื่อไม่ให้ Log รกเกินไป)
        chunk_num = (i // CHUNK_SIZE) + 1
        if chunk_num % 10 == 0 or chunk_num == total_chunks:
            print(f"   📤 ส่งแพ็กเกจที่ {chunk_num}/{total_chunks} สำเร็จ...")

        time.sleep(sleep_time)


if __name__ == "__main__":
    client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2)
    if MQTT_USERNAME and MQTT_PASSWORD:
        client.username_pw_set(MQTT_USERNAME, MQTT_PASSWORD)

    client.on_connect = on_connect

    # เปิดใช้งาน TLS สำหรับพอร์ต 8883
    if MQTT_PORT == 8883:
        client.tls_set()

    print("⏳ กำลังเชื่อมต่อ MQTT Broker...")
    client.connect(MQTT_BROKER, MQTT_PORT, 60)

    # รัน Loop ใน Background เพื่อให้เชื่อมต่อได้
    client.loop_start()
    time.sleep(1)  # รอให้ Connect เสร็จ

    try:
        # 1. เทสไฟล์เดินปกติ (เทรน Model)
        simulate_walk(client, "data/gyro_shank_100hz2.csv", "เดินปกติ (Calibration)")

        # 2. เทสไฟล์เจ็บขา (ทดสอบ Anomaly)
        simulate_walk(client, "data/gyro_shank_100hz2_inj_right.csv", "เจ็บขาขวา (Anomaly Detection)")

        print("\n🎉 ส่งข้อมูลเสร็จสิ้นทั้งหมด!")
    except KeyboardInterrupt:
        print("\n🛑 หยุดการส่งข้อมูลจำลอง")
    finally:
        client.loop_stop()
        client.disconnect()
