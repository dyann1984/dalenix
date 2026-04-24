// ============================================================
//  DALENIX — Firmware ESP32
//  Detecta · Analiza · Protege
//  v1.0 — Modo: Simulado + Real (switchable)
// ============================================================

#include <Arduino.h>
#include <WiFi.h>
#include <WebSocketsServer.h>
#include <ArduinoJson.h>

// ── CONFIGURACIÓN WiFi ──
const char* WIFI_SSID     = "DALENIX_HOTSPOT";  // Cambia por tu red
const char* WIFI_PASSWORD = "dalenix2024";

// ── MODO DE OPERACIÓN ──
// true  = datos simulados (para pruebas sin hardware)
// false = lectura real de sensores
bool SIM_MODE = true;

// ── PINES HARDWARE REAL ──
#define PIN_EM_ANALOG     34   // ADC sensor EM (entrada analógica)
#define PIN_EM_FREQ       35   // Señal de frecuencia EM
#define PIN_GPR_TRIG      26   // Trigger GPR
#define PIN_GPR_ECHO      27   // Echo GPR
#define PIN_ERT_A         32   // Electrodo A (ERT)
#define PIN_ERT_B         33   // Electrodo B (ERT)
#define PIN_ERT_M         25   // Electrodo M (ERT)
#define PIN_ERT_N         14   // Electrodo N (ERT)
#define PIN_BATT          39   // Monitor batería (ADC)
#define PIN_LED_STATUS     2   // LED de estado integrado

// ── WebSocket Server (puerto 81) ──
WebSocketsServer wsServer(81);

// ── Variables globales ──
unsigned long lastSend    = 0;
unsigned long sendInterval = 500; // ms entre envíos
int scanDepth = 40;         // profundidad objetivo en metros
bool scanning = false;
float simPhase = 0.0;

// ── Struct de datos del sensor ──
struct SensorData {
  float em_voltage;       // mV
  float em_frequency;     // kHz
  float gpr_depth;        // metros
  float gpr_time;         // nanosegundos
  float ert_resistivity;  // Ohm·m
  float battery;          // %
  int   points;           // puntos acumulados
  bool  anomaly_water;
  bool  anomaly_cavity;
  bool  anomaly_mineral;
  float confidence_water;
  float confidence_cavity;
  float confidence_mineral;
};

SensorData currentData;

// ──────────────────────────────────────
//  SETUP
// ──────────────────────────────────────
void setup() {
  Serial.begin(115200);
  Serial.println("\n[DALENIX] Iniciando sistema...");

  pinMode(PIN_LED_STATUS, OUTPUT);
  pinMode(PIN_GPR_TRIG, OUTPUT);
  pinMode(PIN_GPR_ECHO, INPUT);

  // Parpadeo de inicio
  for (int i = 0; i < 3; i++) {
    digitalWrite(PIN_LED_STATUS, HIGH); delay(200);
    digitalWrite(PIN_LED_STATUS, LOW);  delay(200);
  }

  connectWiFi();

  wsServer.begin();
  wsServer.onEvent(wsEvent);
  Serial.println("[DALENIX] WebSocket activo en puerto 81");
  Serial.print("[DALENIX] IP: ");
  Serial.println(WiFi.localIP());
  Serial.println("[DALENIX] Sistema listo ✓");
  digitalWrite(PIN_LED_STATUS, HIGH);
}

// ──────────────────────────────────────
//  LOOP PRINCIPAL
// ──────────────────────────────────────
void loop() {
  wsServer.loop();

  unsigned long now = millis();
  if (now - lastSend >= sendInterval) {
    lastSend = now;

    if (SIM_MODE) {
      readSimulated();
    } else {
      readRealSensors();
    }

    if (scanning) {
      currentData.points += random(5, 15);
    }

    sendData();
    simPhase += 0.15;
  }
}

// ──────────────────────────────────────
//  CONECTAR WiFi
// ──────────────────────────────────────
void connectWiFi() {
  Serial.print("[WiFi] Conectando a ");
  Serial.print(WIFI_SSID);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int attempts = 0;
  while (WiFi.status() != WL_CONNECTED && attempts < 20) {
    delay(500);
    Serial.print(".");
    digitalWrite(PIN_LED_STATUS, !digitalRead(PIN_LED_STATUS));
    attempts++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.println("\n[WiFi] Conectado ✓");
  } else {
    Serial.println("\n[WiFi] Fallo — modo AP");
    WiFi.softAP("DALENIX_AP", "dalenix2024");
    Serial.print("[WiFi] AP IP: ");
    Serial.println(WiFi.softAPIP());
  }
}

// ──────────────────────────────────────
//  LECTURA SIMULADA (Fase 4 / Demo)
// ──────────────────────────────────────
void readSimulated() {
  // EM — fluctuación sinusoidal con ruido
  currentData.em_voltage   = 247.0 + sin(simPhase * 0.7) * 35.0
                             + sin(simPhase * 2.1) * 12.0
                             + random(-8, 8);
  currentData.em_frequency = 10.0 + sin(simPhase * 0.3) * 2.0;

  // GPR — simula reflección a ~18m (acuífero)
  float gprBase = 18.4 + sin(simPhase * 0.5) * 2.0 + random(-3, 3) * 0.1;
  currentData.gpr_depth    = max(1.0f, gprBase);
  currentData.gpr_time     = currentData.gpr_depth * 2.0 * 6.67; // ns (v=0.1c en suelo húmedo)

  // ERT — resistividad varía por zona
  float ertBase = 1200.0 + sin(simPhase * 0.4) * 350.0
                 + cos(simPhase * 1.2) * 120.0
                 + random(-50, 50);
  currentData.ert_resistivity = max(100.0f, ertBase);

  // Batería simulada
  currentData.battery = 87.0 - (simPhase * 0.001);

  // Detección de anomalías simuladas
  currentData.anomaly_water   = (currentData.ert_resistivity < 1000.0);
  currentData.anomaly_cavity  = (currentData.em_voltage > 265.0);
  currentData.anomaly_mineral = (currentData.ert_resistivity > 1400.0);

  currentData.confidence_water   = constrain(94.0 - random(0,5), 0, 100);
  currentData.confidence_cavity  = constrain(71.0 - random(0,8), 0, 100);
  currentData.confidence_mineral = constrain(55.0 - random(0,10), 0, 100);
}

// ──────────────────────────────────────
//  LECTURA REAL DE SENSORES
// ──────────────────────────────────────
void readRealSensors() {
  // ── SENSOR EM (ADC) ──
  int rawEM = analogRead(PIN_EM_ANALOG);
  currentData.em_voltage = (rawEM / 4095.0) * 3300.0; // mV (3.3V ref)
  currentData.em_frequency = readEMFrequency();

  // ── GPR (Ultrasonido de prueba o módulo real) ──
  currentData.gpr_depth = readGPR();
  currentData.gpr_time = currentData.gpr_depth * 2.0 * 6.67;

  // ── ERT (Lectura diferencial de pines) ──
  currentData.ert_resistivity = readERT();

  // ── BATERÍA ──
  int rawBatt = analogRead(PIN_BATT);
  currentData.battery = (rawBatt / 4095.0) * 100.0;

  // ── DETECCIÓN DE ANOMALÍAS por umbrales ──
  detectAnomalies();
}

// ── Frecuencia EM por conteo de pulsos ──
float readEMFrequency() {
  unsigned long t0 = millis();
  int count = 0;
  while (millis() - t0 < 50) {
    if (digitalRead(PIN_EM_FREQ)) {
      count++;
      while (digitalRead(PIN_EM_FREQ)); // espera flanco bajo
    }
  }
  return count * 20.0 / 1000.0; // kHz
}

// ── GPR via ultrasonido HC-SR04 (prueba) o módulo real ──
float readGPR() {
  digitalWrite(PIN_GPR_TRIG, LOW);  delayMicroseconds(2);
  digitalWrite(PIN_GPR_TRIG, HIGH); delayMicroseconds(10);
  digitalWrite(PIN_GPR_TRIG, LOW);
  long duration = pulseIn(PIN_GPR_ECHO, HIGH, 30000);
  float distCm = duration * 0.034 / 2.0;
  // Escalar a metros subterráneos (factor de calibración)
  return distCm * 0.12; // ajustar según calibración de campo
}

// ── ERT — Tomografía de Resistividad Eléctrica ──
float readERT() {
  // Configuración Wenner: A-M-N-B equidistantes
  // Inyectar corriente en A-B, medir voltaje en M-N
  digitalWrite(PIN_ERT_A, HIGH);
  digitalWrite(PIN_ERT_B, LOW);
  delayMicroseconds(100);
  int vm = analogRead(PIN_ERT_M);
  int vn = analogRead(PIN_ERT_N);
  digitalWrite(PIN_ERT_A, LOW);
  float deltaV = (vm - vn) * (3.3 / 4095.0); // V
  float current = 0.01; // 10mA inyectados (ajustar con shunt)
  float a = 0.5; // separación electrodos en metros
  if (abs(deltaV) < 0.001) return 9999.0;
  return 2.0 * PI * a * (deltaV / current); // Ohm·m
}

// ── Detección de anomalías por umbrales calibrados ──
void detectAnomalies() {
  // Agua: baja resistividad + alta conductividad EM
  currentData.anomaly_water = (currentData.ert_resistivity < 800.0
                                && currentData.em_voltage > 200.0);
  currentData.confidence_water = currentData.anomaly_water
    ? constrain(100.0 - currentData.ert_resistivity / 80.0, 40, 98)
    : 0;

  // Cavidad: alta resistividad + anomalía GPR
  currentData.anomaly_cavity = (currentData.ert_resistivity > 2000.0
                                 && currentData.gpr_depth < 15.0);
  currentData.confidence_cavity = currentData.anomaly_cavity ? 68.0 : 0;

  // Mineral: resistividad intermedia + EM elevado
  currentData.anomaly_mineral = (currentData.ert_resistivity > 1200.0
                                  && currentData.ert_resistivity < 2000.0
                                  && currentData.em_voltage < 180.0);
  currentData.confidence_mineral = currentData.anomaly_mineral ? 55.0 : 0;
}

// ──────────────────────────────────────
//  ENVIAR DATOS POR WebSocket (JSON)
// ──────────────────────────────────────
void sendData() {
  StaticJsonDocument<512> doc;
  doc["type"]           = "sensor_data";
  doc["ts"]             = millis();
  doc["sim"]            = SIM_MODE;
  doc["scanning"]       = scanning;
  doc["depth_target"]   = scanDepth;

  JsonObject em = doc.createNestedObject("em");
  em["voltage"]   = round(currentData.em_voltage * 10) / 10.0;
  em["frequency"] = round(currentData.em_frequency * 10) / 10.0;

  JsonObject gpr = doc.createNestedObject("gpr");
  gpr["depth"] = round(currentData.gpr_depth * 10) / 10.0;
  gpr["time"]  = round(currentData.gpr_time * 10) / 10.0;

  JsonObject ert = doc.createNestedObject("ert");
  ert["resistivity"] = round(currentData.ert_resistivity);

  doc["battery"] = round(currentData.battery * 10) / 10.0;
  doc["points"]  = currentData.points;

  JsonObject anom = doc.createNestedObject("anomalies");
  anom["water"]            = currentData.anomaly_water;
  anom["water_conf"]       = currentData.confidence_water;
  anom["cavity"]           = currentData.anomaly_cavity;
  anom["cavity_conf"]      = currentData.confidence_cavity;
  anom["mineral"]          = currentData.anomaly_mineral;
  anom["mineral_conf"]     = currentData.confidence_mineral;

  String json;
  serializeJson(doc, json);
  wsServer.broadcastTXT(json);
}

// ──────────────────────────────────────
//  EVENTOS WebSocket (comandos desde app)
// ──────────────────────────────────────
void wsEvent(uint8_t num, WStype_t type, uint8_t* payload, size_t length) {
  switch (type) {
    case WStype_CONNECTED:
      Serial.printf("[WS] Cliente #%u conectado\n", num);
      wsServer.sendTXT(num, "{\"type\":\"hello\",\"device\":\"DALENIX\",\"version\":\"1.0\"}");
      break;

    case WStype_DISCONNECTED:
      Serial.printf("[WS] Cliente #%u desconectado\n", num);
      break;

    case WStype_TEXT: {
      StaticJsonDocument<256> cmd;
      DeserializationError err = deserializeJson(cmd, payload, length);
      if (err) break;
      handleCommand(cmd);
      break;
    }
    default: break;
  }
}

// ──────────────────────────────────────
//  MANEJAR COMANDOS DESDE LA APP
// ──────────────────────────────────────
void handleCommand(JsonDocument& cmd) {
  const char* action = cmd["action"];
  if (!action) return;

  if (strcmp(action, "start_scan") == 0) {
    scanning = true;
    currentData.points = 0;
    Serial.println("[CMD] Escaneo iniciado");
  }
  else if (strcmp(action, "stop_scan") == 0) {
    scanning = false;
    Serial.println("[CMD] Escaneo detenido");
  }
  else if (strcmp(action, "set_depth") == 0) {
    scanDepth = cmd["value"] | 40;
    Serial.printf("[CMD] Profundidad: %dm\n", scanDepth);
  }
  else if (strcmp(action, "set_mode") == 0) {
    SIM_MODE = strcmp(cmd["mode"], "real") != 0;
    Serial.printf("[CMD] Modo: %s\n", SIM_MODE ? "SIM" : "REAL");
  }
  else if (strcmp(action, "ping") == 0) {
    wsServer.broadcastTXT("{\"type\":\"pong\",\"ts\":" + String(millis()) + "}");
  }
}
