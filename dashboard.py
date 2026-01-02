import time
import pandas as pd
import streamlit as st
import plotly.express as px
from influxdb_client import InfluxDBClient
from fpdf import FPDF
from datetime import datetime, timezone

# --- AYARLAR ---
INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "my-super-secret-auth-token"
INFLUX_ORG = "my-org"
INFLUX_BUCKET = "energy_data"

st.set_page_config(page_title="GreenTwin - SKDM Hazır Dijital İkiz", page_icon="🌿", layout="wide")

# CSS Düzenlemeleri
st.markdown("""
    <style>
        .block-container {padding-top: 1rem;}
        div[data-testid="stMetricValue"] {font-size: 24px;}
        .stButton button {width: 100%;}
    </style>
""", unsafe_allow_html=True)

# --- BAĞLANTI ---
@st.cache_resource
def get_client():
    return InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)

client = get_client()

# --- TÜRKÇE KARAKTER DÜZELTİCİ (CRASH ENGELLEYİCİ) ---
def tr_to_en(text):
    """PDF oluştururken latin-1 hatasını önlemek için Türkçe karakterleri değiştirir."""
    replacements = {
        'İ': 'I', 'ı': 'i', 'Ö': 'O', 'ö': 'o', 'Ü': 'U', 'ü': 'u',
        'Ş': 'S', 'ş': 's', 'Ğ': 'G', 'ğ': 'g', 'Ç': 'C', 'ç': 'c'
    }
    for tr, en in replacements.items():
        text = text.replace(tr, en)
    return text

# --- VERİ ÇEKME ---
def get_metrics_data(time_range="-15m"):
    query_api = client.query_api()
    query = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {time_range})
      |> filter(fn: (r) => r["_measurement"] == "machine_metrics")
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
      |> sort(columns: ["_time"], desc: false)
    '''
    df = query_api.query_data_frame(query)
    
    query_ai = f'''
    from(bucket: "{INFLUX_BUCKET}")
      |> range(start: {time_range})
      |> filter(fn: (r) => r["_measurement"] == "ai_analysis")
      |> filter(fn: (r) => r["_field"] == "is_anomaly")
      |> pivot(rowKey:["_time"], columnKey: ["_field"], valueColumn: "_value")
      |> sort(columns: ["_time"], desc: true) 
    '''
    df_ai = query_api.query_data_frame(query_ai)
    return df, df_ai

# --- PDF RAPORU ---
def create_skdm_report(df, total_co2, anomaly_count, order_info=None):
    pdf = FPDF()
    pdf.add_page()
    
    # Başlık
    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, tr_to_en("Urun Karbon Ayak Izi (SKDM) Raporu"), ln=True, align='C')
    pdf.ln(10)
    
    # Bilgiler
    pdf.set_font("Arial", '', 12)
    pdf.cell(0, 10, f"Rapor Tarihi: {datetime.now().strftime('%Y-%m-%d %H:%M')}", ln=True)
    
    if order_info and order_info['active']:
        pdf.set_font("Arial", 'B', 12)
        # tr_to_en fonksiyonunu burada kullanıyoruz
        pdf.cell(0, 10, tr_to_en(f"SIPARIS NO: {order_info['order_id']} | URUN: {order_info['product']}"), ln=True)
        pdf.set_font("Arial", '', 12)
        start_str = order_info['start_time'].strftime('%H:%M:%S')
        pdf.cell(0, 10, tr_to_en(f"Uretim Baslangic: {start_str}"), ln=True)
    else:
        pdf.cell(0, 10, tr_to_en("Kapsam: Genel Tesis Izleme (Son 15 Dakika)"), ln=True)
        
    pdf.ln(5)
    
    # Tablo
    pdf.set_font("Arial", 'B', 12)
    pdf.cell(0, 10, tr_to_en("Analiz Sonuclari:"), ln=True)
    pdf.set_font("Arial", '', 12)
    
    # Hesaplamalar
    avg_power = df['power_kw'].mean() if not df.empty else 0
    duration_minutes = 15
    if order_info and order_info['active'] and not df.empty:
        start_ts = pd.Timestamp(order_info['start_time']).tz_convert(None)
        if not df.empty:
            end_ts = df.iloc[-1]['_time'].tz_convert(None)
            duration_minutes = (end_ts - start_ts).total_seconds() / 60
        if duration_minutes < 0: duration_minutes = 0

    total_energy = (avg_power * duration_minutes) / 60 
    
    pdf.cell(100, 10, tr_to_en("Sure (Dakika):"), border=1)
    pdf.cell(0, 10, f"{duration_minutes:.2f} dk", border=1, ln=True)

    pdf.cell(100, 10, tr_to_en("Toplam Enerji:"), border=1)
    pdf.cell(0, 10, f"{total_energy:.4f} kWh", border=1, ln=True)
    
    pdf.cell(100, 10, tr_to_en("Toplam Karbon (PCF):"), border=1)
    pdf.cell(0, 10, f"{total_co2:.4f} kg CO2e", border=1, ln=True)
    
    pdf.cell(100, 10, tr_to_en("Anomali Sayisi:"), border=1)
    if anomaly_count > 0:
        pdf.set_text_color(255, 0, 0)
    else:
        pdf.set_text_color(0, 128, 0)
    pdf.cell(0, 10, tr_to_en(f"{anomaly_count} Adet"), border=1, ln=True)
    pdf.set_text_color(0, 0, 0)
    
    pdf.ln(10)
    pdf.set_font("Arial", 'I', 10)
    pdf.multi_cell(0, 10, tr_to_en("Bu rapor, TUBITAK Yesil Donusum projesi kapsaminda gelistirilen 'GreenTwin' yazilimi tarafindan otomatik olarak olusturulmustur."))
    
    return pdf.output(dest='S').encode('latin-1', 'ignore') 

# --- SESSION ---
if 'work_order' not in st.session_state:
    st.session_state.work_order = {'active': False, 'start_time': None, 'order_id': "", 'product': ""}

# --- SIDEBAR ---
with st.sidebar:
    st.header("🏭 Üretim Yönetimi")
    st.info("SKDM raporu için iş emri başlatın.")
    
    order_id = st.text_input("Sipariş No (Örn: WO-101)", value="WO-101")
    product_name = st.text_input("Ürün Tipi (Örn: Kapı Sacı)", value="Otomotiv Parçası A")
    
    col_btn1, col_btn2 = st.columns(2)
    
    if st.session_state.work_order['active']:
        st.success(f"✅ AKTİF: {st.session_state.work_order['order_id']}")
        if col_btn2.button("Bitir & Sıfırla", type="primary"):
            st.session_state.work_order = {'active': False, 'start_time': None, 'order_id': "", 'product': ""}
            st.rerun()
    else:
        if col_btn1.button("İş Emri Başlat"):
            st.session_state.work_order = {
                'active': True, 
                'start_time': datetime.now(timezone.utc), 
                'order_id': order_id, 
                'product': product_name
            }
            st.rerun()

# --- MAIN ---
st.title("🌿 GreenTwin: AI Destekli Karbon & Enerji İkizi")

tab1, tab2, tab3 = st.tabs(["⚡ Canlı Operasyon", "🌍 SKDM Karbon Raporu", "📋 Olay Günlüğü"])

with tab1:
    order_status_ph = st.empty()
    col1, col2, col3, col4 = st.columns(4)
    metric_ph1 = col1.empty()
    metric_ph2 = col2.empty()
    metric_ph3 = col3.empty()
    metric_ph4 = col4.empty()
    st.markdown("---")
    chart_ph = st.empty()

with tab2:
    st.info("Bu modül, aktif iş emrine veya son 15 dakikaya göre yasal uyumluluk raporu üretir.")
    co2_col1, co2_col2 = st.columns(2)
    co2_metric_ph = co2_col1.empty()
    report_btn_ph = co2_col2.empty() 
    st.markdown("---")
    co2_chart_ph = st.empty()

with tab3:
    log_ph = st.empty()

while True:
    try:
        if st.session_state.work_order['active']:
            df, df_ai = get_metrics_data(time_range="-1h")
            if not df.empty:
                mask = df['_time'] >= st.session_state.work_order['start_time']
                df = df.loc[mask]
            if not df_ai.empty:
                mask_ai = df_ai['_time'] >= st.session_state.work_order['start_time']
                df_ai = df_ai.loc[mask_ai]
            
            now_utc = datetime.now(timezone.utc)
            order_duration = now_utc - st.session_state.work_order['start_time']
            mins = int(order_duration.total_seconds() / 60)
            secs = int(order_duration.total_seconds() % 60)
            _ = order_status_ph.warning(f"🔨 ÜRETİM AKTİF: **{st.session_state.work_order['order_id']}** | Süre: {mins} dk {secs} sn")
        else:
            df, df_ai = get_metrics_data(time_range="-15m")
            _ = order_status_ph.empty()
        
        if not df.empty:
            last_rec = df.iloc[-1]
            _ = metric_ph1.metric("Anlık Akım", f"{last_rec['current']:.2f} A")
            _ = metric_ph2.metric("Anlık Güç", f"{last_rec['power_kw']:.2f} kW")
            
            status_text = "Bekleniyor..."
            if not df_ai.empty:
                last_status = df_ai.iloc[0]['is_anomaly']
                status_text = "🚨 KRİTİK" if last_status == 1 else "✅ NORMAL"
            _ = metric_ph3.metric("Sistem Durumu", status_text)
            _ = metric_ph4.metric("Maliyet", f"{last_rec['cost_kurus']:.2f} krş/sn")

            fig = px.line(df, x="_time", y="current", title=f"Akım Analizi ({'Sipariş Bazlı' if st.session_state.work_order['active'] else 'Son 15 Dk'})")
            _ = fig.update_traces(line_color='#00CC96')
            _ = fig.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
            _ = chart_ph.plotly_chart(fig, use_container_width=True, key=f"live_{time.time()}")

            total_co2_session = df['co2_grams'].sum() / 1000
            anomaly_count = df_ai[df_ai['is_anomaly'] == 1].shape[0] if not df_ai.empty else 0
            
            label_text = f"Toplam Karbon ({st.session_state.work_order['order_id']})" if st.session_state.work_order['active'] else "Toplam Karbon (Son 15 Dk)"
            _ = co2_metric_ph.metric(label_text, f"{total_co2_session:.4f} kg CO2e")
            
            # PDF BUTONU (ARTIK GÜVENLİ)
            pdf_data = create_skdm_report(df, total_co2_session, anomaly_count, st.session_state.work_order)
            _ = report_btn_ph.download_button(
                label=f"📄 Raporu İndir ({st.session_state.work_order['order_id'] or 'Genel'})",
                data=pdf_data,
                file_name=f"skdm_rapor_{int(time.time())}.pdf",
                mime="application/pdf",
                key=f"btn_{time.time()}"
            )

            fig_co2 = px.area(df, x="_time", y="co2_grams", title="Karbon Emisyon Birikimi", color_discrete_sequence=['#FF5733'])
            _ = fig_co2.update_layout(height=400, margin=dict(l=20, r=20, t=40, b=20))
            _ = co2_chart_ph.plotly_chart(fig_co2, use_container_width=True, key=f"co2_{time.time()}")

            if not df_ai.empty:
                anomalies = df_ai[df_ai['is_anomaly'] == 1].copy()
                if not anomalies.empty:
                    _ = log_ph.dataframe(anomalies.head(10)[['_time', 'machine_id', 'is_anomaly']], use_container_width=True)
                else:
                    _ = log_ph.success("Seçili aralıkta anomali yok.")
            
        time.sleep(1)

    except Exception as e:
        # Hata anında terminale bas, ekrana basma (döngü kopmasın)
        print(f"HATA: {e}")
        time.sleep(1)