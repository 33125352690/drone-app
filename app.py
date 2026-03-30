import streamlit as st
import time
import random
from datetime import datetime
import folium
from streamlit_folium import st_folium
from folium.plugins import Draw

# 页面配置
st.set_page_config(
    page_title="无人机智能化应用",
    page_icon="✈️",
    layout="wide"
)

# 初始化会话状态
if "drone_status" not in st.session_state:
    st.session_state.drone_status = "离线"
if "heartbeat_logs" not in st.session_state:
    st.session_state.heartbeat_logs = []
if "coord_system" not in st.session_state:
    st.session_state.coord_system = "GCJ-02"
if "point_A" not in st.session_state:
    st.session_state.point_A = [32.2267, 118.7255]
if "point_B" not in st.session_state:
    st.session_state.point_B = [32.2270, 118.7260]
if "obstacles" not in st.session_state:
    st.session_state.obstacles = []

# 坐标系转换（简化版）
def convert_coord(lat, lon, from_sys, to_sys):
    if from_sys == to_sys:
        return lat, lon
    if from_sys == "WGS-84" and to_sys == "GCJ-02":
        return lat + 0.0002, lon + 0.0003
    if from_sys == "GCJ-02" and to_sys == "WGS-84":
        return lat - 0.0002, lon - 0.0003
    return lat, lon

# 侧边栏导航
with st.sidebar:
    st.title("导航")
    page = st.radio("功能页面", ["航线规划", "飞行监控"])
    st.divider()
    st.subheader("坐标系设置")
    coord_sys = st.radio("输入坐标系", ["WGS-84", "GCJ-02(高德/百度)"])
    st.session_state.coord_system = "GCJ-02" if "GCJ" in coord_sys else "WGS-84"

# 页面1：航线规划（3D地图 + 障碍物圈选）
if page == "航线规划":
    st.title("✈️ 航线规划（3D地图）")
    st.subheader("南京科技职业学院")

    col1, col2 = st.columns(2)
    with col1:
        st.subheader("起点 A")
        lat_A = st.number_input("纬度 A", value=32.2267, format="%.4f")
        lon_A = st.number_input("经度 A", value=118.7255, format="%.4f")
        if st.button("设置 A 点"):
            st.session_state.point_A = [lat_A, lon_A]
            st.success("A 点已设置")

    with col2:
        st.subheader("终点 B")
        lat_B = st.number_input("纬度 B", value=32.2270, format="%.4f")
        lon_B = st.number_input("经度 B", value=118.7260, format="%.4f")
        if st.button("设置 B 点"):
            st.session_state.point_B = [lat_B, lon_B]
            st.success("B 点已设置")

    st.divider()
    st.subheader("飞行参数")
    height = st.slider("飞行高度 (m)", 10, 100, 50)
    st.info(f"当前坐标系：{st.session_state.coord_system}")

    # 显示坐标（转换后）
    a_lat, a_lon = convert_coord(lat_A, lon_A, st.session_state.coord_system, "WGS-84")
    b_lat, b_lon = convert_coord(lat_B, lon_B, st.session_state.coord_system, "WGS-84")
    st.write(f"A 点（WGS-84）：{a_lat:.4f}, {a_lon:.4f}")
    st.write(f"B 点（WGS-84）：{b_lat:.4f}, {b_lon:.4f}")

    st.divider()
    st.subheader("3D 地图（可圈选障碍物）")

    # 3D地图
    m = folium.Map(
        location=[32.2267, 118.7255],
        zoom_start=18,
        tiles="OpenStreetMap"
    )

    # A点标记
    folium.Marker(
        location=st.session_state.point_A,
        popup="起点 A",
        icon=folium.Icon(color="red", icon="plane")
    ).add_to(m)

    # B点标记
    folium.Marker(
        location=st.session_state.point_B,
        popup="终点 B",
        icon=folium.Icon(color="green", icon="flag")
    ).add_to(m)

    # 障碍物圈选工具
    draw = Draw(
        draw_options={
            "polyline": False,
            "rectangle": True,
            "polygon": True,
            "circle": False,
            "marker": False,
            "circlemarker": False
        },
        edit_options={"edit": True, "remove": True}
    )
    draw.add_to(m)

    st_folium(m, width="100%", height=500)

# 页面2：飞行监控（心跳包）
if page == "飞行监控":
    st.title("📡 飞行监控（心跳包）")

    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("无人机状态", st.session_state.drone_status)
    with col2:
        st.metric("心跳次数", len(st.session_state.heartbeat_logs))
    with col3:
        last_time = st.session_state.heartbeat_logs[-1]["time"] if st.session_state.heartbeat_logs else "无"
        st.metric("最后心跳", last_time)

    st.divider()
    st.subheader("心跳日志")
    log_container = st.container(height=350)

    col_a, col_b, col_c = st.columns(3)
    with col_a:
        start = st.button("启动监控", type="primary")
    with col_b:
        stop = st.button("停止监控")
    with col_c:
        clear = st.button("清空日志")

    if start:
        st.session_state.drone_status = "在线"
        st.success("监控已启动")
        while st.session_state.drone_status == "在线":
            t = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            signal = random.randint(70, 100)
            battery = random.randint(30, 100)
            log = {
                "time": t,
