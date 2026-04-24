/**
 * DALENIX — Módulo de Conexión WebSocket + REST
 * Detecta · Analiza · Protege
 * 
 * Uso:
 *   const dalenix = new DALENIXClient({ wsUrl: 'ws://localhost:8765', apiUrl: 'http://localhost:5000' });
 *   dalenix.onSensorData(data => console.log(data));
 *   dalenix.connect();
 */

class DALENIXClient {
  constructor(config = {}) {
    this.wsUrl    = config.wsUrl   || 'ws://localhost:8765';
    this.apiUrl   = config.apiUrl  || 'http://localhost:5000';
    this.ws       = null;
    this.retries  = 0;
    this.maxRetry = 5;
    this.connected = false;

    // Callbacks
    this._onSensorData = null;
    this._onAnomaly    = null;
    this._onStatus     = null;
    this._onConnect    = null;
    this._onDisconnect = null;
  }

  // ── Registro de callbacks ──
  onSensorData(fn)  { this._onSensorData = fn; return this; }
  onAnomaly(fn)     { this._onAnomaly    = fn; return this; }
  onStatus(fn)      { this._onStatus     = fn; return this; }
  onConnect(fn)     { this._onConnect    = fn; return this; }
  onDisconnect(fn)  { this._onDisconnect = fn; return this; }

  // ── Conectar WebSocket ──
  connect() {
    console.log(`[DALENIX] Conectando a ${this.wsUrl}`);
    this.ws = new WebSocket(this.wsUrl);

    this.ws.onopen = () => {
      this.connected = true;
      this.retries   = 0;
      console.log('[DALENIX] WebSocket conectado ✓');
      if (this._onConnect) this._onConnect();
    };

    this.ws.onmessage = (event) => {
      try {
        const data = JSON.parse(event.data);
        this._handleMessage(data);
      } catch (e) {
        console.warn('[DALENIX] JSON inválido:', e);
      }
    };

    this.ws.onerror = (err) => {
      console.warn('[DALENIX] Error WS — usando modo simulado local');
    };

    this.ws.onclose = () => {
      this.connected = false;
      if (this._onDisconnect) this._onDisconnect();
      if (this.retries < this.maxRetry) {
        this.retries++;
        console.log(`[DALENIX] Reconectando en 2s (intento ${this.retries}/${this.maxRetry})`);
        setTimeout(() => this.connect(), 2000);
      }
    };
    return this;
  }

  disconnect() {
    this.maxRetry = 0;
    if (this.ws) this.ws.close();
  }

  // ── Enviar comando al dispositivo ──
  send(action, params = {}) {
    if (!this.connected || this.ws.readyState !== WebSocket.OPEN) {
      console.warn('[DALENIX] No conectado');
      return false;
    }
    this.ws.send(JSON.stringify({ action, ...params }));
    return true;
  }

  startScan(depth = 40) { return this.send('start_scan', { depth }); }
  stopScan()             { return this.send('stop_scan'); }
  setDepth(value)        { return this.send('set_depth', { value }); }
  ping()                 { return this.send('ping'); }

  // ── Manejar mensajes entrantes ──
  _handleMessage(data) {
    if (data.type === 'sensor_data') {
      if (this._onSensorData) this._onSensorData(data);
      // Detectar anomalías y disparar callback
      if (data.anomalies && this._onAnomaly) {
        const { anomalies } = data;
        if (anomalies.water   && anomalies.water_conf   > 70) this._onAnomaly({ type: 'agua',    confidence: anomalies.water_conf,   data });
        if (anomalies.cavity  && anomalies.cavity_conf  > 60) this._onAnomaly({ type: 'cavidad', confidence: anomalies.cavity_conf,  data });
        if (anomalies.mineral && anomalies.mineral_conf > 50) this._onAnomaly({ type: 'mineral', confidence: anomalies.mineral_conf, data });
      }
    } else if (data.type === 'pong') {
      console.log('[DALENIX] Ping OK:', Date.now() - data.ts, 'ms');
    } else if (data.type === 'hello') {
      console.log('[DALENIX] Dispositivo:', data.device, 'v' + data.version);
      if (this._onStatus) this._onStatus(data);
    }
  }

  // ──────────────────────────────────────
  //  REST API helpers
  // ──────────────────────────────────────
  async apiGet(path) {
    const res = await fetch(`${this.apiUrl}${path}`);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  async apiPost(path, body) {
    const res = await fetch(`${this.apiUrl}${path}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body)
    });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return res.json();
  }

  getStatus()              { return this.apiGet('/api/status'); }
  getLiveReading()         { return this.apiGet('/api/sensor/live'); }
  getProjects()            { return this.apiGet('/api/projects'); }
  createProject(name, loc) { return this.apiPost('/api/projects', { name, location: loc }); }
  analyzeData(readings)    { return this.apiPost('/api/analyze', { readings }); }
  exportCSV(projectId)     { window.open(`${this.apiUrl}/api/export/csv/${projectId}`); }

  startScanREST(depth = 40) { return this.apiPost('/api/scan/start', { depth }); }
  stopScanREST()             { return this.apiPost('/api/scan/stop', {}); }
  setMode(mode)              { return this.apiPost('/api/mode', { mode }); }
}

// ──────────────────────────────────────────────
//  SIMULADOR LOCAL (sin backend — para pruebas
//  100% en el navegador, sin servidor)
// ──────────────────────────────────────────────
class DALENIXSimulator {
  constructor() {
    this.phase     = 0;
    this.points    = 0;
    this.scanning  = false;
    this.depth     = 40;
    this._callbacks = {};
    this._interval  = null;
  }

  on(event, fn) { this._callbacks[event] = fn; return this; }
  emit(event, data) { if (this._callbacks[event]) this._callbacks[event](data); }

  start(intervalMs = 500) {
    this._interval = setInterval(() => {
      this.phase += 0.15;
      if (this.scanning) this.points += Math.floor(Math.random() * 10) + 5;
      const data = this._generate();
      this.emit('sensor_data', data);
    }, intervalMs);
    console.log('[DALENIX SIM] Simulador iniciado ✓');
    return this;
  }

  stop() {
    clearInterval(this._interval);
    this.scanning = false;
  }

  startScan(depth = 40) { this.scanning = true; this.points = 0; this.depth = depth; }
  stopScan()             { this.scanning = false; }
  setDepth(v)            { this.depth = v; }

  _generate() {
    const p = this.phase;
    const em_v  = 247 + Math.sin(p*0.7)*35 + Math.sin(p*2.1)*12 + (Math.random()-0.5)*16;
    const em_f  = 10  + Math.sin(p*0.3)*2;
    const gpr_d = Math.max(1, 18.4 + Math.sin(p*0.5)*2 + (Math.random()-0.5)*0.6);
    const gpr_t = gpr_d * 2 * 6.67;
    const ert_r = Math.max(100, 1200 + Math.sin(p*0.4)*350 + Math.cos(p*1.2)*120 + (Math.random()-0.5)*100);
    const batt  = Math.max(0, 87 - p*0.001);

    return {
      type: 'sensor_data', ts: Date.now(), sim: true,
      scanning: this.scanning, depth_target: this.depth,
      em:  { voltage: +em_v.toFixed(1),  frequency: +em_f.toFixed(2) },
      gpr: { depth:   +gpr_d.toFixed(1), time:      +gpr_t.toFixed(1) },
      ert: { resistivity: Math.round(ert_r) },
      battery: +batt.toFixed(1),
      points: this.points,
      anomalies: {
        water:         ert_r < 1000,
        water_conf:    +(Math.random()*7+89).toFixed(1),
        cavity:        em_v > 265,
        cavity_conf:   +(Math.random()*8+65).toFixed(1),
        mineral:       ert_r > 1400,
        mineral_conf:  +(Math.random()*10+50).toFixed(1),
      }
    };
  }
}

// Export para uso en Node.js o como módulo ES
if (typeof module !== 'undefined') {
  module.exports = { DALENIXClient, DALENIXSimulator };
}
