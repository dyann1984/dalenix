# DALENIX — Guía Completa de Instalación y Pruebas
## Detecta · Analiza · Protege — v1.0

---

## 📁 ESTRUCTURA DEL PROYECTO

```
dalenix/
├── firmware/
│   └── dalenix_esp32.ino       ← Código Arduino para ESP32
├── backend/
│   └── dalenix_server.py       ← Servidor Python (REST + WebSocket)
├── frontend/
│   ├── js/
│   │   └── dalenix-client.js   ← Módulo JS de conexión
│   └── DALENIX_App.html        ← App web completa (standalone)
└── README.md                   ← Este archivo
```

---

## 🚀 OPCIÓN 1 — PRUEBA RÁPIDA (Sin hardware, sin servidor)

Solo abre `DALENIX_App.html` en tu navegador.
Todo funciona con simulador local integrado. No necesitas nada más.

✅ Funciona offline  
✅ Todos los módulos activos  
✅ Datos simulados realistas  

---

## 🖥️ OPCIÓN 2 — Con servidor backend Python

### Requisitos
```bash
Python 3.8+
pip install flask flask-cors websockets
```

### Instalar y ejecutar
```bash
cd backend/
pip install flask flask-cors websockets
python dalenix_server.py
```

### Endpoints disponibles
| Método | URL                        | Descripción                  |
|--------|----------------------------|------------------------------|
| GET    | /api/status                | Estado del sistema           |
| GET    | /api/sensor/live           | Lectura actual (REST)        |
| POST   | /api/scan/start            | Iniciar escaneo              |
| POST   | /api/scan/stop             | Detener + análisis IA        |
| GET    | /api/projects              | Lista de proyectos           |
| POST   | /api/projects              | Crear proyecto               |
| POST   | /api/analyze               | Análisis IA de lecturas      |
| GET    | /api/export/csv/:id        | Exportar CSV                 |
| POST   | /api/mode                  | Cambiar sim/real             |

### Probar desde terminal
```bash
# Estado del sistema
curl http://localhost:5000/api/status

# Lectura en tiempo real
curl http://localhost:5000/api/sensor/live

# Iniciar escaneo a 40m
curl -X POST http://localhost:5000/api/scan/start \
     -H "Content-Type: application/json" \
     -d '{"depth": 40}'

# Detener y obtener análisis
curl -X POST http://localhost:5000/api/scan/stop

# Ver proyectos
curl http://localhost:5000/api/projects
```

---

## ⚡ OPCIÓN 3 — Con ESP32 (Hardware real)

### Librerías Arduino necesarias
Instala desde Arduino IDE → Library Manager:
- `WebSockets` by Markus Sattler
- `ArduinoJson` by Benoit Blanchon

### Conexiones de hardware

```
ESP32 GPIO  →  Sensor
─────────────────────────────────────────
GPIO 34     →  Sensor EM (señal analógica)
GPIO 35     →  Frecuencia EM (señal digital)
GPIO 26     →  Trigger GPR (salida digital)
GPIO 27     →  Echo GPR (entrada digital)
GPIO 32     →  Electrodo A — ERT (salida)
GPIO 33     →  Electrodo B — ERT (salida)
GPIO 25     →  Electrodo M — ERT (ADC)
GPIO 14     →  Electrodo N — ERT (ADC)
GPIO 39     →  Monitor batería LiPo (ADC)
GPIO  2     →  LED de estado (integrado)
GND         →  GND común de todos los sensores
3.3V        →  VCC sensores (si son 3.3V)
5V          →  VCC sensores (si son 5V — usar via Vin)
```

### Configurar WiFi
En `dalenix_esp32.ino`, líneas 14–15:
```cpp
const char* WIFI_SSID     = "TU_RED_WIFI";
const char* WIFI_PASSWORD = "TU_PASSWORD";
```

### Subir firmware
1. Conecta ESP32 por USB
2. Selecciona: Board → ESP32 Dev Module
3. Selecciona el puerto COM/ttyUSB correcto
4. Clic en Upload ▶

### Verificar en Monitor Serie (115200 baud)
```
[DALENIX] Iniciando sistema...
[WiFi] Conectando a TU_RED...
[WiFi] Conectado ✓
[DALENIX] WebSocket activo en puerto 81
[DALENIX] IP: 192.168.1.xxx
[DALENIX] Sistema listo ✓
```

---

## 🔌 USAR EL MÓDULO JS EN TU PROPIA PÁGINA

```html
<script src="js/dalenix-client.js"></script>
<script>
  // ── Con hardware real ──
  const dalenix = new DALENIXClient({
    wsUrl:  'ws://192.168.1.100:81',     // IP del ESP32
    apiUrl: 'http://192.168.1.100:5000'  // IP del backend Python
  });

  dalenix
    .onConnect(() => console.log('Conectado al DALENIX'))
    .onSensorData(data => {
      console.log('EM:', data.em.voltage, 'mV');
      console.log('GPR:', data.gpr.depth, 'm');
      console.log('ERT:', data.ert.resistivity, 'Ω·m');
    })
    .onAnomaly(a => {
      console.log(`⚠ Anomalía detectada: ${a.type} (${a.confidence}%)`);
    })
    .connect();

  // Iniciar escaneo a 40m
  document.getElementById('btnScan').onclick = () => {
    dalenix.startScan(40);
  };


  // ── Sin hardware (simulador local) ──
  const sim = new DALENIXSimulator();
  sim
    .on('sensor_data', data => {
      document.getElementById('em').textContent = data.em.voltage.toFixed(1) + ' mV';
      document.getElementById('gpr').textContent = data.gpr.depth.toFixed(1) + ' m';
      document.getElementById('ert').textContent = data.ert.resistivity + ' Ω·m';
    })
    .start(500);

  sim.startScan(40);
</script>
```

---

## 🔬 CALIBRACIÓN DE SENSORES

### Sensor EM
- Alejar de metales y cables eléctricos al calibrar
- Tomar lectura baseline en aire libre (sin suelo)
- Registrar ese valor como `EM_BASELINE` en el firmware
- Ajustar `MINERAL_EM_THRESHOLD` según tipo de suelo local

### GPR / Ultrasonido (prueba)
- El HC-SR04 sirve para pruebas a corta distancia
- Para uso real: módulo GPR SIR-20 / GSSI o similar
- Ajustar el factor de escala `* 0.12` según calibración de campo
- Calibrar con objeto a profundidad conocida

### ERT
- Separación Wenner recomendada: 0.5m entre electrodos
- Suelo húmedo mejora el contacto eléctrico
- Clave: buena inyección de corriente (mínimo 10mA)
- Resistividad típica: agua < 100 Ω·m, roca seca > 2000 Ω·m

---

## 📊 FORMATO DE DATOS JSON (WebSocket)

```json
{
  "type": "sensor_data",
  "ts": 1714000000000,
  "sim": true,
  "scanning": true,
  "depth_target": 40,
  "em": {
    "voltage": 247.3,
    "frequency": 10.2
  },
  "gpr": {
    "depth": 18.4,
    "time": 245.6
  },
  "ert": {
    "resistivity": 1247
  },
  "battery": 87.0,
  "points": 1024,
  "anomalies": {
    "water": true,
    "water_conf": 94.1,
    "cavity": false,
    "cavity_conf": 0,
    "mineral": false,
    "mineral_conf": 0
  }
}
```

---

## 🛣️ ROADMAP

### v1.0 (actual) — Fase 4/5
- [x] App web completa (4 módulos)
- [x] Simulador de sensores
- [x] Servidor REST + WebSocket
- [x] Firmware ESP32 base
- [x] Motor de análisis por reglas

### v1.1 — Fase 6/7
- [ ] Integración GPS para georreferenciación
- [ ] Mapa 3D exportable (.obj / .ply)
- [ ] App Android (Capacitor/PWA)
- [ ] Reportes PDF automáticos
- [ ] Dashboard multi-proyecto

### v2.0 — Fase 8
- [ ] ML entrenado con datos de campo
- [ ] Sincronización en nube
- [ ] App iOS
- [ ] Panel de administración web
- [ ] API pública para integradores

---

## 📞 SOPORTE

Sistema: DALENIX v1.0  
Slogan:  Detecta · Analiza · Protege  
Stack:   ESP32 + Python + JavaScript + Three.js  
