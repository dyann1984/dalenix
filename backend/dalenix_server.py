#!/usr/bin/env python3
"""
DALENIX — Servidor Backend
Detecta · Analiza · Protege
v1.0

Funciones:
- Servidor WebSocket (bridge hardware <-> app)
- API REST para proyectos y reportes
- Motor de análisis IA (simulado)
- Almacenamiento SQLite local
- Exportación PDF/CSV

Uso:
  pip install flask flask-cors websockets aiohttp
  python dalenix_server.py

API disponible en: http://localhost:5000
WebSocket en:      ws://localhost:8765
"""

import asyncio
import json
import math
import random
import sqlite3
import time
import threading
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, request, Response
from flask_cors import CORS

# ─────────────────────────────────────────────
#  CONFIGURACIÓN
# ─────────────────────────────────────────────
HOST        = "0.0.0.0"
HTTP_PORT   = 5000
WS_PORT     = 8765
DB_PATH     = "dalenix.db"
SIM_MODE    = True        # False = espera hardware real vía serial
SERIAL_PORT = "/dev/ttyUSB0"
BAUD_RATE   = 115200

# ─────────────────────────────────────────────
#  BASE DE DATOS
# ─────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    c.execute("""
        CREATE TABLE IF NOT EXISTS projects (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            name        TEXT NOT NULL,
            location    TEXT,
            created_at  TEXT,
            status      TEXT DEFAULT 'active'
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS scans (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            project_id   INTEGER,
            started_at   TEXT,
            ended_at     TEXT,
            depth_target INTEGER,
            points       INTEGER DEFAULT 0,
            mode         TEXT DEFAULT 'sim',
            FOREIGN KEY (project_id) REFERENCES projects(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS anomalies (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id      INTEGER,
            type         TEXT,
            depth_min    REAL,
            depth_max    REAL,
            confidence   REAL,
            area_m2      REAL,
            x            REAL,
            y            REAL,
            z            REAL,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)

    c.execute("""
        CREATE TABLE IF NOT EXISTS readings (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            scan_id      INTEGER,
            ts           REAL,
            em_voltage   REAL,
            em_freq      REAL,
            gpr_depth    REAL,
            ert_ohm      REAL,
            battery      REAL,
            FOREIGN KEY (scan_id) REFERENCES scans(id)
        )
    """)

    # Datos de ejemplo
    c.execute("SELECT COUNT(*) FROM projects")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO projects (name, location, created_at, status) VALUES (?,?,?,?)",
                  ("Rancho San Miguel", "Nayarit, México", datetime.now().isoformat(), "completed"))
        c.execute("INSERT INTO projects (name, location, created_at, status) VALUES (?,?,?,?)",
                  ("Obra Tepic Norte", "Tepic, Nayarit", "2026-04-22T10:00:00", "review"))
        c.execute("INSERT INTO projects (name, location, created_at, status) VALUES (?,?,?,?)",
                  ("Mina El Refugio", "Sinaloa, México", "2026-04-18T08:30:00", "completed"))
        c.execute("INSERT INTO projects (name, location, created_at, status) VALUES (?,?,?,?)",
                  ("Ejido Los Fresnos", "Jalisco, México", "2026-04-10T09:00:00", "completed"))

    conn.commit()
    conn.close()
    print("[DB] Base de datos inicializada ✓")

# ─────────────────────────────────────────────
#  SIMULADOR DE SENSORES
# ─────────────────────────────────────────────
class SensorSimulator:
    def __init__(self):
        self.phase = 0.0
        self.points = 0
        self.scanning = False
        self.depth_target = 40

    def tick(self):
        self.phase += 0.15
        if self.scanning:
            self.points += random.randint(5, 15)
        return self.generate()

    def generate(self):
        p = self.phase

        em_v   = 247.0 + math.sin(p*0.7)*35 + math.sin(p*2.1)*12 + random.uniform(-8, 8)
        em_f   = 10.0  + math.sin(p*0.3)*2.0

        gpr_d  = max(1.0, 18.4 + math.sin(p*0.5)*2.0 + random.uniform(-0.3, 0.3))
        gpr_t  = gpr_d * 2.0 * 6.67

        ert_r  = max(100.0, 1200.0 + math.sin(p*0.4)*350 + math.cos(p*1.2)*120 + random.uniform(-50, 50))
        batt   = max(0, 87.0 - p * 0.001)

        # Anomalías
        w_conf  = round(random.uniform(89, 96), 1)
        ca_conf = round(random.uniform(65, 76), 1)
        mi_conf = round(random.uniform(50, 62), 1)

        return {
            "type": "sensor_data",
            "ts": time.time(),
            "sim": True,
            "scanning": self.scanning,
            "depth_target": self.depth_target,
            "em":  {"voltage": round(em_v, 1), "frequency": round(em_f, 2)},
            "gpr": {"depth": round(gpr_d, 1),  "time": round(gpr_t, 1)},
            "ert": {"resistivity": round(ert_r)},
            "battery": round(batt, 1),
            "points": self.points,
            "anomalies": {
                "water":          ert_r < 1000,
                "water_conf":     w_conf,
                "cavity":         em_v > 265,
                "cavity_conf":    ca_conf,
                "mineral":        ert_r > 1400,
                "mineral_conf":   mi_conf,
            }
        }

sim = SensorSimulator()

# ─────────────────────────────────────────────
#  MOTOR DE ANÁLISIS IA (Reglas + ML básico)
# ─────────────────────────────────────────────
class DALENIXEngine:

    WATER_ERT_THRESHOLD   = 1000.0   # Ohm·m — agua = baja resistividad
    CAVITY_ERT_THRESHOLD  = 2500.0   # Ohm·m — cavidad = alta resistividad
    MINERAL_EM_THRESHOLD  = 180.0    # mV    — mineral absorbe EM

    @staticmethod
    def analyze(readings: list) -> dict:
        if not readings:
            return {"error": "Sin datos"}

        em_vals  = [r["em_voltage"]     for r in readings]
        ert_vals = [r["ert_resistivity"] for r in readings]
        gpr_vals = [r["gpr_depth"]       for r in readings]

        em_mean  = sum(em_vals)  / len(em_vals)
        ert_mean = sum(ert_vals) / len(ert_vals)
        gpr_mean = sum(gpr_vals) / len(gpr_vals)
        ert_min  = min(ert_vals)
        ert_max  = max(ert_vals)

        anomalies = []

        # ── Detección de agua ──
        if ert_min < DALENIXEngine.WATER_ERT_THRESHOLD:
            conf = round(min(98, 100 - ert_min / 80), 1)
            anomalies.append({
                "type": "agua",
                "depth_min": round(gpr_mean * 0.85, 1),
                "depth_max": round(gpr_mean * 1.15, 1),
                "confidence": conf,
                "area_m2": round(random.uniform(80, 150), 0),
                "description": f"Acuífero freático detectado. ERT: {round(ert_min)} Ω·m. "
                               f"Profundidad estimada {round(gpr_mean*0.85,1)}–{round(gpr_mean*1.15,1)}m. "
                               f"Se recomienda perforación.",
                "recommendation": "Perforación recomendada en zona marcada"
            })

        # ── Detección de cavidad ──
        if ert_max > DALENIXEngine.CAVITY_ERT_THRESHOLD:
            anomalies.append({
                "type": "cavidad",
                "depth_min": round(gpr_mean * 0.4, 1),
                "depth_max": round(gpr_mean * 0.65, 1),
                "confidence": round(random.uniform(65, 78), 1),
                "area_m2": round(random.uniform(20, 50), 0),
                "description": f"Cavidad o vacío subterráneo. Riesgo geotécnico moderado. "
                               f"ERT: {round(ert_max)} Ω·m.",
                "recommendation": "Evitar construcción sin estudios adicionales"
            })

        # ── Detección de mineral ──
        if em_mean < DALENIXEngine.MINERAL_EM_THRESHOLD and ert_mean > 1200:
            anomalies.append({
                "type": "mineral",
                "depth_min": round(gpr_mean * 1.3, 1),
                "depth_max": round(gpr_mean * 1.6, 1),
                "confidence": round(random.uniform(50, 65), 1),
                "area_m2": round(random.uniform(40, 80), 0),
                "description": f"Posible cuerpo mineral o roca densa. "
                               f"EM atenuado ({round(em_mean,1)} mV), ERT alto ({round(ert_mean)} Ω·m).",
                "recommendation": "Requiere análisis geoquímico adicional"
            })

        return {
            "scan_summary": {
                "em_mean":  round(em_mean, 1),
                "ert_mean": round(ert_mean, 1),
                "gpr_mean": round(gpr_mean, 1),
                "total_readings": len(readings),
                "confidence_global": round(sum(a["confidence"] for a in anomalies) / max(len(anomalies), 1), 1)
            },
            "anomalies": anomalies,
            "risk_level": "alto" if any(a["type"]=="cavidad" for a in anomalies) else "bajo",
            "generated_at": datetime.now().isoformat()
        }

# ─────────────────────────────────────────────
#  FLASK — API REST
# ─────────────────────────────────────────────
app = Flask(__name__)
CORS(app)

@app.route("/api/status")
def status():
    return jsonify({
        "status": "online",
        "device": "DALENIX v1.0",
        "mode": "simulated" if SIM_MODE else "real",
        "scanning": sim.scanning,
        "points": sim.points,
        "ts": datetime.now().isoformat()
    })

@app.route("/api/sensor/live")
def sensor_live():
    """Lectura actual del sensor (REST polling — usa WebSocket para tiempo real)"""
    data = sim.tick()
    return jsonify(data)

@app.route("/api/scan/start", methods=["POST"])
def scan_start():
    body = request.get_json(silent=True) or {}
    sim.scanning = True
    sim.points   = 0
    sim.depth_target = body.get("depth", 40)
    return jsonify({"ok": True, "msg": "Escaneo iniciado", "depth": sim.depth_target})

@app.route("/api/scan/stop", methods=["POST"])
def scan_stop():
    sim.scanning = False
    # Generar análisis automático
    readings_sim = [sim.generate() for _ in range(50)]
    flat = [{"em_voltage": r["em"]["voltage"],
             "ert_resistivity": r["ert"]["resistivity"],
             "gpr_depth": r["gpr"]["depth"]} for r in readings_sim]
    analysis = DALENIXEngine.analyze(flat)
    return jsonify({"ok": True, "points": sim.points, "analysis": analysis})

@app.route("/api/projects")
def get_projects():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM projects ORDER BY created_at DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/projects", methods=["POST"])
def create_project():
    body = request.get_json()
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("INSERT INTO projects (name, location, created_at) VALUES (?,?,?)",
                (body["name"], body.get("location",""), datetime.now().isoformat()))
    pid = cur.lastrowid
    conn.commit()
    conn.close()
    return jsonify({"ok": True, "id": pid}), 201

@app.route("/api/analyze", methods=["POST"])
def analyze():
    """Analiza un set de lecturas enviadas desde la app"""
    body = request.get_json()
    readings = body.get("readings", [])
    if not readings:
        # Generar simuladas para demo
        sims = [sim.generate() for _ in range(80)]
        readings = [{"em_voltage": r["em"]["voltage"],
                     "ert_resistivity": r["ert"]["resistivity"],
                     "gpr_depth": r["gpr"]["depth"]} for r in sims]
    result = DALENIXEngine.analyze(readings)
    return jsonify(result)

@app.route("/api/export/csv/<int:project_id>")
def export_csv(project_id):
    """Exportar lecturas como CSV"""
    rows = []
    rows.append("ts,em_voltage,em_freq,gpr_depth,ert_ohm,battery\n")
    # Datos de ejemplo
    for i in range(50):
        d = sim.generate()
        rows.append(f"{time.time()+i},{d['em']['voltage']},{d['em']['frequency']},"
                    f"{d['gpr']['depth']},{d['ert']['resistivity']},{d['battery']}\n")
    csv = "".join(rows)
    return Response(csv, mimetype="text/csv",
                    headers={"Content-Disposition": f"attachment;filename=dalenix_{project_id}.csv"})

@app.route("/api/mode", methods=["POST"])
def set_mode():
    global SIM_MODE
    body = request.get_json()
    SIM_MODE = body.get("mode", "sim") == "sim"
    sim_mode_str = "simulado" if SIM_MODE else "real"
    return jsonify({"ok": True, "mode": sim_mode_str})

# ─────────────────────────────────────────────
#  WEBSOCKET SERVER (datos en tiempo real)
# ─────────────────────────────────────────────
connected_ws = set()

async def ws_handler(websocket, path):
    connected_ws.add(websocket)
    print(f"[WS] Cliente conectado: {websocket.remote_address}")
    try:
        # Enviar bienvenida
        await websocket.send(json.dumps({
            "type": "hello",
            "device": "DALENIX",
            "version": "1.0",
            "mode": "sim" if SIM_MODE else "real"
        }))

        async for msg in websocket:
            try:
                cmd = json.loads(msg)
                await handle_ws_command(cmd, websocket)
            except json.JSONDecodeError:
                pass
    except Exception as e:
        print(f"[WS] Desconectado: {e}")
    finally:
        connected_ws.discard(websocket)

async def handle_ws_command(cmd, ws):
    action = cmd.get("action")
    if action == "start_scan":
        sim.scanning = True
        sim.points   = 0
        sim.depth_target = cmd.get("depth", 40)
        await ws.send(json.dumps({"type": "ack", "action": "start_scan"}))
    elif action == "stop_scan":
        sim.scanning = False
        await ws.send(json.dumps({"type": "ack", "action": "stop_scan"}))
    elif action == "set_depth":
        sim.depth_target = cmd.get("value", 40)
    elif action == "ping":
        await ws.send(json.dumps({"type": "pong", "ts": time.time()}))

async def broadcast_loop():
    """Enviar datos de sensores cada 500ms a todos los clientes WS"""
    while True:
        if connected_ws:
            data = sim.tick()
            msg  = json.dumps(data)
            dead = set()
            for ws in connected_ws.copy():
                try:
                    await ws.send(msg)
                except:
                    dead.add(ws)
            connected_ws -= dead
        await asyncio.sleep(0.5)

async def ws_main():
    try:
        import websockets
        async with websockets.serve(ws_handler, HOST, WS_PORT):
            print(f"[WS] Servidor WebSocket en ws://{HOST}:{WS_PORT}")
            await broadcast_loop()
    except ImportError:
        print("[WS] websockets no instalado — instala con: pip install websockets")

def run_ws():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.run_until_complete(ws_main())

# ─────────────────────────────────────────────
#  MAIN
# ─────────────────────────────────────────────
if __name__ == "__main__":
    print("=" * 50)
    print("  DALENIX — Sistema de Exploración Subterránea")
    print("  Detecta · Analiza · Protege — v1.0")
    print("=" * 50)

    init_db()

    # Iniciar WS en hilo separado
    ws_thread = threading.Thread(target=run_ws, daemon=True)
    ws_thread.start()

    print(f"[API] REST en http://{HOST}:{HTTP_PORT}")
    print(f"[API] Endpoints:")
    print(f"       GET  /api/status")
    print(f"       GET  /api/sensor/live")
    print(f"       POST /api/scan/start   body: {{depth: 40}}")
    print(f"       POST /api/scan/stop")
    print(f"       GET  /api/projects")
    print(f"       POST /api/analyze")
    print(f"       GET  /api/export/csv/<id>")
    print()

    app.run(host=HOST, port=HTTP_PORT, debug=False, threaded=True)
