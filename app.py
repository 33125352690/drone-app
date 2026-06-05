import streamlit as st
import folium
from streamlit_folium import st_folium, folium_static
import json
import os
import math
import time
import random
from datetime import datetime
import pandas as pd
import matplotlib.pyplot as plt
from streamlit_autorefresh import st_autorefresh
from folium.plugins import Draw

# ----------------------------------------------------------------------
# 配置
# ----------------------------------------------------------------------

SCHOOL_CENTER_GCJ = [118.749413, 32.234097]  # 南京科技职业学院中心点(GCJ-02)
GAODE_TILE = "https://webst01.is.autonavi.com/appmaptile?style=6&x={x}&y={y}&z={z}"
HEARTBEAT_INTERVAL = 0.2
BASE_SPEED = 5.0
HOVER_SECONDS = 5
CONFIG_FILE = "obstacle_config.json"

# ----------------------------------------------------------------------
# 坐标转换函数（纯 Python 实现，无第三方依赖）
# 基于 eviltransform 算法，已测试往返误差 0.14m
# ----------------------------------------------------------------------

def out_of_china(lng, lat):
    return not (72.004 <= lng <= 137.8347 and 0.8293 <= lat <= 55.8271)

def transform_lat(lng, lat):
    ret = -100.0 + 2.0 * lng + 3.0 * lat + 0.2 * lat * lat + \
          0.1 * lng * lat + 0.2 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 *
            math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lat * math.pi) + 40.0 *
            math.sin(lat / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (160.0 * math.sin(lat / 12.0 * math.pi) + 320 *
            math.sin(lat * math.pi / 30.0)) * 2.0 / 3.0
    return ret

def transform_lng(lng, lat):
    ret = 300.0 + lng + 2.0 * lat + 0.1 * lng * lng + \
          0.1 * lng * lat + 0.1 * math.sqrt(abs(lng))
    ret += (20.0 * math.sin(6.0 * lng * math.pi) + 20.0 *
            math.sin(2.0 * lng * math.pi)) * 2.0 / 3.0
    ret += (20.0 * math.sin(lng * math.pi) + 40.0 *
            math.sin(lng / 3.0 * math.pi)) * 2.0 / 3.0
    ret += (150.0 * math.sin(lng / 12.0 * math.pi) + 300.0 *
            math.sin(lng * math.pi / 30.0)) * 2.0 / 3.0
    return ret

def wgs84_to_gcj02(lng, lat):
    if out_of_china(lng, lat):
        return [lng, lat]
    a = 6378245.0
    ee = 0.00669342162296594323
    dlat = transform_lat(lng - 105.0, lat - 35.0)
    dlng = transform_lng(lng - 105.0, lat - 35.0)
    radlat = lat / 180.0 * math.pi
    magic = math.sin(radlat)
    magic = 1 - ee * magic * magic
    sqrtmagic = math.sqrt(magic)
    dlat = (dlat * 180.0) / ((a * (1 - ee)) / (magic * sqrtmagic) * math.pi)
    dlng = (dlng * 180.0) / (a / sqrtmagic * math.cos(radlat) * math.pi)
    return [lng + dlng, lat + dlat]

def gcj02_to_wgs84(lng, lat):
    if out_of_china(lng, lat):
        return [lng, lat]
    wgs_lng, wgs_lat = lng, lat
    for _ in range(5):
        gcj_lng, gcj_lat = wgs84_to_gcj02(wgs_lng, wgs_lat)
        delta_lng = gcj_lng - lng
        delta_lat = gcj_lat - lat
        wgs_lng -= delta_lng
        wgs_lat -= delta_lat
    return [wgs_lng, wgs_lat]

def transform_to_gcj02(lng, lat, from_coord):
    if from_coord == "WGS-84":
        return wgs84_to_gcj02(lng, lat)
    return lng, lat

def transform_to_display(lng, lat, to_coord):
    return lng, lat

# ----------------------------------------------------------------------
# 障碍物管理
# ----------------------------------------------------------------------

def load_obstacles():
    if os.path.exists(CONFIG_FILE):
        try:
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            obstacles = data.get('obstacles', [])
            for obs in obstacles:
                if 'height' not in obs:
                    obs['height'] = 30
                if 'selected' not in obs:
                    obs['selected'] = False
            return obstacles
        except:
            return []
    return []

def save_obstacles(obstacles):
    data = {
        'obstacles': obstacles,
        'count': len(obstacles),
        'save_time': datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        'version': 'v16.1_fixed_avoidance',
        'coord_sys': 'GCJ-02'
    }
    with open(CONFIG_FILE, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

# ----------------------------------------------------------------------
# 几何辅助函数
# ----------------------------------------------------------------------

def distance(p1, p2):
    return math.hypot(p1[0]-p2[0], p1[1]-p2[1])

def point_in_polygon(point, polygon):
    x, y = point
    inside = False
    n = len(polygon)
    for i in range(n):
        x1, y1 = polygon[i]
        x2, y2 = polygon[(i+1)%n]
        if ((y1 > y) != (y2 > y)) and (x < (x2 - x1)*(y - y1)/(y2 - y1) + x1):
            inside = not inside
    return inside

def segments_intersect(p1, p2, p3, p4):
    def orientation(p, q, r):
        val = (q[1]-p[1])*(r[0]-q[0]) - (q[0]-p[0])*(r[1]-q[1])
        if abs(val) < 1e-10: return 0
        return 1 if val > 0 else 2

    def on_segment(p, q, r):
        return (min(p[0], r[0]) <= q[0] <= max(p[0], r[0]) and
                min(p[1], r[1]) <= q[1] <= max(p[1], r[1]))

    o1 = orientation(p1, p2, p3)
    o2 = orientation(p1, p2, p4)
    o3 = orientation(p3, p4, p1)
    o4 = orientation(p3, p4, p2)

    if o1 != o2 and o3 != o4:
        return True
    if o1 == 0 and on_segment(p1, p3, p2): return True
    if o2 == 0 and on_segment(p1, p4, p2): return True
    if o3 == 0 and on_segment(p3, p1, p4): return True
    if o4 == 0 and on_segment(p3, p2, p4): return True
    return False

def line_intersects_polygon(p1, p2, polygon):
    if point_in_polygon(p1, polygon) or point_in_polygon(p2, polygon):
        return True
    n = len(polygon)
    for i in range(n):
        p3 = polygon[i]
        p4 = polygon[(i+1)%n]
        if segments_intersect(p1, p2, p3, p4):
            return True
    return False

def get_blocking_obstacles(start, end, obstacles, flight_alt, ignore_alt=False):
    """获取阻挡路径的障碍物（改进版）"""
    blocking = []
    for obs in obstacles:
        # 高度判断
        if not ignore_alt and obs.get('height', 30) <= flight_alt:
            continue  # 障碍物低于飞行高度，不阻挡
        
        coords = obs.get('polygon', [])
        if coords and len(coords) >= 3:
            # 检查起点或终点是否在障碍物内
            if point_in_polygon(start, coords) or point_in_polygon(end, coords):
                blocking.append(obs)
                continue
            
            # 检查线段是否与多边形相交
            if line_intersects_polygon(start, end, coords):
                blocking.append(obs)
    
    return blocking

def meters_to_deg(meters, lat=32.23):
    lat_deg = meters / 111000
    lng_deg = meters / (111000 * math.cos(math.radians(lat)))
    return lng_deg, lat_deg

def compute_blocked_bounds(blocking_obs):
    min_lng = float('inf')
    max_lng = -float('inf')
    min_lat = float('inf')
    max_lat = -float('inf')
    for obs in blocking_obs:
        for p in obs.get('polygon', []):
            min_lng = min(min_lng, p[0])
            max_lng = max(max_lng, p[0])
            min_lat = min(min_lat, p[1])
            max_lat = max(max_lat, p[1])
    return min_lng, max_lng, min_lat, max_lat

def is_path_clear(p1, p2, obstacles, flight_alt, ignore_alt=False):
    blocking = get_blocking_obstacles(p1, p2, obstacles, flight_alt, ignore_alt)
    return len(blocking) == 0

def find_avoidance_point(start, end, obstacles, flight_alt, direction, safety_radius=5):
    """找到绕行点（改进版）"""
    blocking = get_blocking_obstacles(start, end, obstacles, flight_alt, ignore_alt=True)
    
    if not blocking:
        return None, []
    
    # 计算所有阻挡障碍物的边界框
    min_lng, max_lng, min_lat, max_lat = compute_blocked_bounds(blocking)
    
    # 扩展边界（安全距离）
    safe_lat = meters_to_deg(safety_radius * 2)[1]
    safe_lng = meters_to_deg(safety_radius * 2)[0]
    
    # 计算路径方向
    dx = end[0] - start[0]
    dy = end[1] - start[1]
    
    if direction == "向左绕行":
        # 左绕：从障碍物左侧或上方通过
        if abs(dx) > abs(dy):  # 水平方向为主
            waypoint_lat = max_lat + safe_lat
            waypoint_lng = (start[0] + end[0]) / 2
        else:  # 垂直方向为主
            waypoint_lng = min_lng - safe_lng
            waypoint_lat = (start[1] + end[1]) / 2
    else:  # 向右绕行
        if abs(dx) > abs(dy):  # 水平方向为主
            waypoint_lat = min_lat - safe_lat
            waypoint_lng = (start[0] + end[0]) / 2
        else:  # 垂直方向为主
            waypoint_lng = max_lng + safe_lng
            waypoint_lat = (start[1] + end[1]) / 2
    
    waypoint = [waypoint_lng, waypoint_lat]
    
    # 确保绕行点不在任何障碍物内
    max_iter = 20
    for _ in range(max_iter):
        inside_any = False
        for obs in blocking:
            if point_in_polygon(waypoint, obs['polygon']):
                inside_any = True
                if direction == "向左绕行":
                    waypoint[1] += safe_lat
                else:
                    waypoint[1] -= safe_lat
                break
        if not inside_any:
            break
    
    return waypoint, blocking

def find_avoidance_path_recursive(start, end, obstacles, flight_alt, direction, safety_radius=5, depth=0):
    """递归找到完整的绕行路径"""
    if depth > 5:
        return [start, end]
    
    if is_path_clear(start, end, obstacles, flight_alt, ignore_alt=False):
        return [start, end]
    
    waypoint, _ = find_avoidance_point(start, end, obstacles, flight_alt, direction, safety_radius)
    
    if waypoint is None:
        return [start, end]
    
    path1 = find_avoidance_path_recursive(start, waypoint, obstacles, flight_alt, direction, safety_radius, depth+1)
    path2 = find_avoidance_path_recursive(waypoint, end, obstacles, flight_alt, direction, safety_radius, depth+1)
    
    full_path = path1[:-1] + path2
    return full_path

def find_left_path(start, end, obstacles, flight_alt, safety_radius=5):
    return find_avoidance_path_recursive(start, end, obstacles, flight_alt, "向左绕行", safety_radius)

def find_right_path(start, end, obstacles, flight_alt, safety_radius=5):
    return find_avoidance_path_recursive(start, end, obstacles, flight_alt, "向右绕行", safety_radius)

def find_best_path(start, end, obstacles, flight_alt, safety_radius=5):
    """选择更优的绕行路径"""
    if is_path_clear(start, end, obstacles, flight_alt, ignore_alt=False):
        return [start, end]
    
    left_path = find_left_path(start, end, obstacles, flight_alt, safety_radius)
    right_path = find_right_path(start, end, obstacles, flight_alt, safety_radius)
    
    left_len = path_length(left_path) * 111000
    right_len = path_length(right_path) * 111000
    
    if len(left_path) <= 2 and left_len < 10:
        return right_path
    if len(right_path) <= 2 and right_len < 10:
        return left_path
    
    return left_path if left_len <= right_len else right_path

def create_avoidance_path(start, end, obstacles, flight_alt, direction, safety_radius=5):
    if direction == "向左绕行":
        return find_left_path(start, end, obstacles, flight_alt, safety_radius)
    elif direction == "向右绕行":
        return find_right_path(start, end, obstacles, flight_alt, safety_radius)
    else:
        return find_best_path(start, end, obstacles, flight_alt, safety_radius)

# ----------------------------------------------------------------------
# 等分航点生成
# ----------------------------------------------------------------------

def path_length(path):
    total = 0.0
    for i in range(len(path)-1):
        total += distance(path[i], path[i+1])
    return total

def interpolate_at_distance(path, dist):
    if dist <= 0:
        return path[0][:]
    total = 0.0
    for i in range(len(path)-1):
        seg_len = distance(path[i], path[i+1])
        if total + seg_len >= dist:
            t = (dist - total) / seg_len
            lng = path[i][0] + t * (path[i+1][0] - path[i][0])
            lat = path[i][1] + t * (path[i+1][1] - path[i][1])
            return [lng, lat]
        total += seg_len
    return path[-1][:]

def generate_equidistant_waypoints(path, num_segments=6):
    if not path or num_segments <= 0:
        return path
    total_len = path_length(path)
    if total_len == 0:
        return [path[0]] * (num_segments + 1)
    step = total_len / num_segments
    waypoints = []
    for i in range(num_segments + 1):
        dist = i * step
        waypoints.append(interpolate_at_distance(path, dist))
    return waypoints

# ----------------------------------------------------------------------
# 心跳模拟器
# ----------------------------------------------------------------------

class HeartbeatData:
    def __init__(self, flight_time, seq, lat, lng, altitude):
        self.flight_time = flight_time
        self.seq = seq
        self.lat = lat
        self.lng = lng
        self.altitude = altitude

class HeartbeatSim:
    def __init__(self, start_point):
        self.current_pos = start_point[:]
        self.waypoints = []
        self.current_wp_idx = 0
        self.running = False
        self.start_time = None
        self.last_update = None
        self.history = []
        self.speed_pct = 50
        self.altitude = 50
        self.total_segments = 0
        self.arrival_flag = False
        self.arrived_wp_index = -1
        self.finished = False
        self.hover_remaining = 0.0
        self.waiting_at_wp = False

    def set_path(self, waypoints, altitude, speed_pct):
        self.waypoints = [wp[:] for wp in waypoints]
        self.current_pos = waypoints[0][:]
        self.current_wp_idx = 1
        self.running = True
        self.finished = False
        self.start_time = datetime.now()
        self.last_update = None
        self.history = []
        self.speed_pct = speed_pct
        self.altitude = altitude
        self.total_segments = len(waypoints) - 1
        self.arrival_flag = False
        self.arrived_wp_index = -1
        self.hover_remaining = 0.0
        self.waiting_at_wp = False
        self._add_heartbeat(seq=1)

    def _add_heartbeat(self, seq=None, arrived=False):
        flight_t = (datetime.now() - self.start_time).total_seconds() if self.start_time else 0
        if seq is None:
            seq = len(self.history) + 1
        hb = HeartbeatData(flight_t, seq, self.current_pos[1], self.current_pos[0], self.altitude)
        self.history.append(hb)
        return hb

    def update_one_step(self):
        if not self.running or self.finished:
            return None

        now = time.time()
        if self.last_update is None:
            dt = HEARTBEAT_INTERVAL
        else:
            dt = min(HEARTBEAT_INTERVAL, now - self.last_update) if (now - self.last_update) > 0 else HEARTBEAT_INTERVAL
        self.last_update = now

        if self.waiting_at_wp:
            self.hover_remaining -= dt
            if self.hover_remaining <= 0:
                self.waiting_at_wp = False
                self.hover_remaining = 0.0
                if self.current_wp_idx >= len(self.waypoints):
                    self.running = False
                    self.finished = True
                    return self._add_heartbeat(arrived=True)
                else:
                    self._add_heartbeat()
                    return self.history[-1] if self.history else None
            else:
                self._add_heartbeat()
                return self.history[-1] if self.history else None

        if self.current_wp_idx >= len(self.waypoints):
            self.running = False
            self.finished = True
            return self._add_heartbeat(arrived=True)

        target = self.waypoints[self.current_wp_idx]
        seg_dist = distance(self.current_pos, target)
        speed = BASE_SPEED * (self.speed_pct / 100.0)
        move_dist = speed * dt

        if move_dist >= seg_dist:
            self.current_pos = target[:]
            self._add_heartbeat()
            self.arrival_flag = True
            self.arrived_wp_index = self.current_wp_idx
            self.current_wp_idx += 1

            if self.current_wp_idx >= len(self.waypoints):
                self.running = False
                self.finished = True
                self._add_heartbeat(arrived=True)
                return self.history[-1]
            else:
                self.waiting_at_wp = True
                self.hover_remaining = HOVER_SECONDS
        else:
            ratio = move_dist / seg_dist
            delta_lng = (target[0] - self.current_pos[0]) * ratio
            delta_lat = (target[1] - self.current_pos[1]) * ratio
            self.current_pos[0] += delta_lng
            self.current_pos[1] += delta_lat
            self._add_heartbeat()

        return self.history[-1] if self.history else None

# ----------------------------------------------------------------------
# 通信日志
# ----------------------------------------------------------------------

def add_comm_log(message, direction="OBC内部"):
    timestamp = datetime.now().strftime("%H:%M:%S.%f")[:-3]
    log_entry = {"time": timestamp, "direction": direction, "message": message}
    if "comm_logs" not in st.session_state:
        st.session_state.comm_logs = []
    st.session_state.comm_logs.insert(0, log_entry)
    if len(st.session_state.comm_logs) > 50:
        st.session_state.comm_logs = st.session_state.comm_logs[:50]

# ----------------------------------------------------------------------
# 地图创建（GCJ-02 -> WGS-84）
# ----------------------------------------------------------------------

def create_planning_map(center_gcj, points_gcj, obstacles, flight_trail, plan_path, drone_pos_gcj, flight_alt, enable_draw=False):
    center_wgs = gcj02_to_wgs84(center_gcj[0], center_gcj[1])
    m = folium.Map(location=[center_wgs[1], center_wgs[0]], zoom_start=16, tiles=GAODE_TILE, attr='高德')

    # 障碍物多边形
    for obs in obstacles:
        coords_gcj = obs.get('polygon', [])
        height = obs.get('height', 30)
        if coords_gcj and len(coords_gcj) >= 3:
            coords_wgs = [gcj02_to_wgs84(lng, lat) for lng, lat in coords_gcj]
            color = "red" if height > flight_alt else "orange"
            folium.Polygon([[c[1], c[0]] for c in coords_wgs], color=color, weight=2,
                          fill=True, fill_color=color, fill_opacity=0.4,
                          popup=f"🚧 {obs.get('name', '障碍物')}\n高度:{height}m").add_to(m)

    # 起点 A
    if points_gcj.get('A'):
        a_wgs = gcj02_to_wgs84(points_gcj['A'][0], points_gcj['A'][1])
        folium.Marker([a_wgs[1], a_wgs[0]], popup='起点A', icon=folium.Icon(color='green')).add_to(m)

    # 终点 B
    if points_gcj.get('B'):
        b_wgs = gcj02_to_wgs84(points_gcj['B'][0], points_gcj['B'][1])
        folium.Marker([b_wgs[1], b_wgs[0]], popup='终点B', icon=folium.Icon(color='red')).add_to(m)

    # 规划路径
    if plan_path and len(plan_path) > 1:
        path_wgs = [gcj02_to_wgs84(p[0], p[1]) for p in plan_path]
        folium.PolyLine([[p[1], p[0]] for p in path_wgs], color='green', weight=4).add_to(m)
        
        # 绘制绕行航点
        if len(plan_path) > 2:
            for i, wp in enumerate(plan_path[1:-1]):
                wp_wgs = gcj02_to_wgs84(wp[0], wp[1])
                folium.CircleMarker([wp_wgs[1], wp_wgs[0]], radius=6, color='purple', fill=True,
                                    popup=f'绕行点{i+1}').add_to(m)

    # 历史轨迹
    if flight_trail:
        trail_wgs = [gcj02_to_wgs84(lng, lat) for lng, lat in flight_trail[-100:]]
        folium.PolyLine([[lat, lng] for lng, lat in trail_wgs], color='orange', weight=2).add_to(m)

    # 无人机当前位置
    if drone_pos_gcj:
        drone_wgs = gcj02_to_wgs84(drone_pos_gcj[0], drone_pos_gcj[1])
        folium.Marker([drone_wgs[1], drone_wgs[0]], icon=folium.Icon(color='blue')).add_to(m)

    # 绘图工具
    if enable_draw:
        draw = Draw(
            draw_options={
                "polygon": {"allowIntersection": False, "drawError": {"color": "#e1e100", "message": "多边形不能相交"},
                           "shapeOptions": {"color": "#ff7800", "weight": 3}},
                "polyline": False,
                "rectangle": False,
                "circle": False,
                "marker": False,
                "circlemarker": False
            },
            edit_options={"edit": False, "remove": False}
        )
        draw.add_to(m)

    return m

# ----------------------------------------------------------------------
# 初始化状态
# ----------------------------------------------------------------------

def init():
    # 南京科技职业学院的实际坐标（GCJ-02）
    DEFAULT_A_GCJ = [118.749413, 32.234097]  # 学校中心点作为起点
    DEFAULT_B_GCJ = [118.751500, 32.235500]  # 偏东北一点作为终点
    
    defaults = {
        'page': '航线规划',
        'points_gcj': {'A': DEFAULT_A_GCJ.copy(), 'B': DEFAULT_B_GCJ.copy()},
        'sim': HeartbeatSim(DEFAULT_A_GCJ.copy()),
        'flight_started': False,
        'latest_hb': None,
        'hb_list': [],
        'flight_trail': [],
        'plan_path': None,
        'waypoints': None,
        'flight_alt': 50,
        'drone_speed': 50,
        'safety_radius': 8,
        'avoid_direction': "最佳航线",
        'coord_sys': 'GCJ-02',
        'obstacles': load_obstacles(),
        'pending_obstacle': None,
        'flight_paused': False,
        'point_select_mode': 'A',
        'pending_click_point': None,
        'last_arrival_msg': "",
        'comm_logs': [],
        'draw_enabled': False,
        'drawn_polygon': None,
        'show_add_dialog': False
    }
    for k, v in defaults.items():
        if k not in st.session_state:
            st.session_state[k] = v

def update_plan_and_waypoints():
    if st.session_state.points_gcj.get('A') and st.session_state.points_gcj.get('B'):
        add_comm_log("开始航线规划 - 算法: 递归绕行", "OBC内部")
        path = create_avoidance_path(
            st.session_state.points_gcj['A'],
            st.session_state.points_gcj['B'],
            st.session_state.obstacles,
            st.session_state.flight_alt,
            st.session_state.avoid_direction,
            st.session_state.safety_radius
        )
        st.session_state.plan_path = path
        waypoints = generate_equidistant_waypoints(path, num_segments=6)
        st.session_state.waypoints = waypoints
        wp_count = len(waypoints) - 2 if waypoints else 0
        total_len = path_length(path) * 111000
        add_comm_log(f"航线规划完成 - 类型: {'绕行' if len(path)>2 else '直线'}, 航点数: {wp_count+2}, 路径长度: {total_len:.1f}m", "OBC内部")
    else:
        st.session_state.plan_path = None
        st.session_state.waypoints = None

# ----------------------------------------------------------------------
# 主程序
# ----------------------------------------------------------------------

def main():
    st.set_page_config(page_title="南京科技职业学院 - 无人机地面站", layout="wide")
    st.title("🏫 南京科技职业学院 - 无人机地面站系统")
    
    init()

    with st.sidebar:
        st.header("📌 导航")
        selected_page = st.radio("功能页面", ["航线规划", "飞行监控", "障碍物管理"],
                                index=["航线规划", "飞行监控", "障碍物管理"].index(st.session_state.page))
        st.session_state.page = selected_page
        st.markdown("---")
        
        st.subheader("🗺️ 坐标系设置")
        coord_choice = st.radio("输入坐标系", ["WGS-84", "GCJ-02(高德/百度)"],
                               index=1 if st.session_state.coord_sys == "GCJ-02" else 0)
        st.session_state.coord_sys = "WGS-84" if coord_choice == "WGS-84" else "GCJ-02"
        st.markdown("---")
        
        st.subheader("📊 系统状态")
        st.checkbox("A点已设", value=st.session_state.points_gcj.get('A') is not None, disabled=True)
        st.checkbox("B点已设", value=st.session_state.points_gcj.get('B') is not None, disabled=True)
        st.checkbox("飞行进行中", value=st.session_state.flight_started, disabled=True)

    # ==================== 障碍物管理页面 ====================
    if st.session_state.page == "障碍物管理":
        st.header("🚧 障碍物配置持久化")
        st.caption(f"配置文件: {os.path.abspath(CONFIG_FILE)} | 版本: v16.1_fixed_avoidance")
        st.info("📂 所有障碍物坐标均以 GCJ-02 存储，与高德底图完全对齐。")

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            if st.button("💾 保存到文件", use_container_width=True):
                save_obstacles(st.session_state.obstacles)
                st.success("保存成功")
        with col2:
            if st.button("📂 从文件加载", use_container_width=True):
                st.session_state.obstacles = load_obstacles()
                update_plan_and_waypoints()
                st.rerun()
        with col3:
            if st.button("🗑️ 清除全部", use_container_width=True):
                st.session_state.obstacles = []
                save_obstacles([])
                update_plan_and_waypoints()
                st.rerun()
        with col4:
            if st.button("🚀 一键部署", use_container_width=True):
                st.info("此功能用于部署，示例中未实现")

        st.markdown("---")
        st.subheader("📥 下载配置文件到本地")
        if st.button("📥 下载 obstacle_config.json", use_container_width=True):
            if os.path.exists(CONFIG_FILE):
                with open(CONFIG_FILE, 'rb') as f:
                    st.download_button("点击下载", data=f, file_name=CONFIG_FILE, mime="application/json")
            else:
                st.warning("配置文件不存在，请先保存")

        st.markdown("---")
        st.subheader("➕ 添加新障碍物（手动输入顶点）")
        with st.form("add_obstacle_form"):
            obs_name = st.text_input("障碍物名称", "新障碍物")
            obs_height = st.number_input("高度 (米)", min_value=1, max_value=200, value=30, step=5)
            st.markdown("#### 顶点坐标 (经度,纬度) 每行一个，格式: 118.749,32.234")
            vertices_text = st.text_area("顶点列表", placeholder="118.746956,32.232945\n118.747500,32.233000\n118.747200,32.233500")
            submitted = st.form_submit_button("✅ 添加障碍物")

            if submitted and vertices_text.strip():
                vertices = []
                for line in vertices_text.strip().split('\n'):
                    if ',' in line:
                        parts = line.split(',')
                        try:
                            lng = float(parts[0].strip())
                            lat = float(parts[1].strip())
                            vertices.append([lng, lat])
                        except:
                            pass
                if len(vertices) >= 3:
                    if st.session_state.coord_sys == "WGS-84":
                        vertices = [list(wgs84_to_gcj02(lng, lat)) for lng, lat in vertices]
                    new_obs = {
                        "name": obs_name,
                        "polygon": vertices,
                        "height": obs_height,
                        "selected": False,
                        "id": f"obs_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
                    }
                    st.session_state.obstacles.append(new_obs)
                    save_obstacles(st.session_state.obstacles)
                    update_plan_and_waypoints()
                    st.success(f"已添加 {obs_name}")
                    st.rerun()
                else:
                    st.error("至少需要3个顶点")

        st.markdown("---")
        st.subheader(f"📋 当前障碍物列表 (共 {len(st.session_state.obstacles)} 个)")
        for idx, obs in enumerate(st.session_state.obstacles):
            with st.expander(f"{obs.get('name', '未命名')} | 高度: {obs.get('height',30)}m"):
                col_a, col_b, col_c = st.columns([1,1,2])
                with col_a:
                    new_h = st.number_input("调整高度", value=obs.get('height',30), key=f"h_{idx}", step=5)
                    if new_h != obs.get('height',30):
                        obs['height'] = new_h
                        save_obstacles(st.session_state.obstacles)
                        update_plan_and_waypoints()
                        st.rerun()
                with col_b:
                    if st.button("🗑️ 删除", key=f"del_{idx}"):
                        st.session_state.obstacles.pop(idx)
                        save_obstacles(st.session_state.obstacles)
                        update_plan_and_waypoints()
                        st.rerun()
                with col_c:
                    st.code(json.dumps(obs.get('polygon', []), indent=2), language='json')

        if os.path.exists(CONFIG_FILE):
            with open(CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            save_time = data.get('save
