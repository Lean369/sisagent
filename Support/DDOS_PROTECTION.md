# Protección contra Ataques DDoS en el Chatbot de WhatsApp

## 🛡️ Capas de Protección Implementadas

### 1. **Rate Limiting Global**
Limita el número total de mensajes que el sistema puede procesar por minuto, independientemente del número de teléfono.

**Configuración:**
```python
global_max_rpm=100  # Máximo 100 mensajes por minuto en total
```

**Comportamiento:**
- Cuenta todos los requests en los últimos 60 segundos
- Bloquea nuevos requests cuando se alcanza el límite
- Mensaje al usuario: "⚠️ El sistema está experimentando alta demanda. Por favor intenta en unos minutos."

---

### 2. **Detector de Números Nuevos**
Detecta patrones anómalos cuando muchos números desconocidos comienzan a enviar mensajes simultáneamente (típico de ataques con números generados).

**Configuración:**
```python
max_new_numbers_pm=20  # Máximo 20 números nuevos por minuto
suspicious_threshold=10  # Activa modo sospechoso con 10 números nuevos
```

**Modos de Operación:**

1. **Modo Normal:**
   - Permite hasta 20 números nuevos por minuto
   - Los números conocidos no cuentan para el límite

2. **Modo Sospechoso (activado con 10+ números nuevos en 1 minuto):**
   - Bloquea TODOS los números desconocidos por 5 minutos
   - Solo permite mensajes de números ya conocidos
   - Mensaje: "⚠️ Detectamos actividad inusual. Servicio temporalmente restringido."

---

### 3. **Circuit Breaker**
Detiene automáticamente el procesamiento cuando el sistema está bajo estrés extremo, protegiendo los recursos.

**Configuración:**
```python
failure_threshold=10  # 10 fallos consecutivos para abrir el circuito
recovery_timeout=60  # 60 segundos antes de intentar recuperación
```

**Estados:**
- **CLOSED**: Normal, procesando requests
- **OPEN**: Bloqueando todos los requests (sistema sobrecargado)
- **HALF_OPEN**: Intentando recuperación, procesando algunos requests

**Comportamiento:**
- Después de 10 fallos consecutivos, abre el circuito
- Bloquea todos los requests durante 60 segundos
- Intenta recuperación gradual
- Mensaje: "⚠️ Sistema temporalmente no disponible. Intenta en X segundos."

---

### 4. **Blacklist/Whitelist**
Sistema manual y automático para bloquear números maliciosos.

**Funciones:**

```python
# Agregar a blacklist manualmente
ddos_protection.blacklist.add_to_blacklist("5491234567890", "spam")

# Agregar a whitelist (números VIP que nunca se bloquean)
ddos_protection.blacklist.add_to_whitelist("5491234567890")

# Reportar comportamiento sospechoso (auto-blacklist después de 3 reportes)
ddos_protection.reportar_sospechoso("5491234567890")
```

**Auto-Blacklist:**
- El sistema reporta automáticamente números con comportamiento sospechoso
- Después de 3 reportes, el número se agrega automáticamente a la blacklist
- Mensaje: "⚠️ Número bloqueado. Contacta con soporte."

---

## 📊 Monitoreo en Tiempo Real

### Endpoint de Estadísticas
```bash
curl http://localhost:5000/ddos-stats
```

**Respuesta:**
```json
{
  "global_limiter": {
    "requests_last_minute": 45,
    "max_requests": 100,
    "percentage": 45.0
  },
  "new_numbers": {
    "known_numbers": 250,
    "new_numbers_last_minute": 5,
    "suspicious_mode": false,
    "suspicious_until": null
  },
  "circuit_breaker": {
    "state": "CLOSED",
    "failures": 0,
    "failure_threshold": 10
  },
  "blacklist": {
    "blacklist_count": 3,
    "whitelist_count": 5,
    "suspicious_count": 2
  }
}
```

---

## 🔧 Configuración Recomendada por Tipo de Negocio

### Pequeño Negocio (< 1000 mensajes/día)
```python
DDoSProtection(
    global_max_rpm=50,      # 50 mensajes/min
    max_new_numbers_pm=10,  # 10 números nuevos/min
    suspicious_threshold=5  # Modo sospechoso con 5 nuevos
)
```

### Negocio Mediano (1000-5000 mensajes/día)
```python
DDoSProtection(
    global_max_rpm=100,     # 100 mensajes/min
    max_new_numbers_pm=20,  # 20 números nuevos/min
    suspicious_threshold=10 # Modo sospechoso con 10 nuevos
)
```

### Negocio Grande (> 5000 mensajes/día)
```python
DDoSProtection(
    global_max_rpm=200,     # 200 mensajes/min
    max_new_numbers_pm=50,  # 50 números nuevos/min
    suspicious_threshold=25 # Modo sospechoso con 25 nuevos
)
```

---

## 🧪 Testing

### Script de Prueba de Concurrencia
```bash
# Probar con 50 mensajes concurrentes
./venv/bin/python load_test_concurrency.py 50 50

# Probar con 100 mensajes (debería activar protecciones)
./venv/bin/python load_test_concurrency.py 100 100
```

### Simular Ataque DDoS
```python
# Script para simular ataque con múltiples números
import requests
from concurrent.futures import ThreadPoolExecutor

def send_attack_message(i):
    payload = {
        "event": "messages.upsert",
        "instance": "test",
        "data": {
            "key": {
                "remoteJid": f"attacker-{i}@s.whatsapp.net",
                "fromMe": False,
                "id": f"ATTACK-{i}"
            },
            "pushName": "Attacker",
            "message": {"conversation": "spam"}
        }
    }
    return requests.post("http://localhost:5000/webhook", json=payload)

# Enviar 100 mensajes con 100 números diferentes
with ThreadPoolExecutor(max_workers=50) as ex:
    results = list(ex.map(send_attack_message, range(100)))

# Revisar cuántos fueron bloqueados
blocked = sum(1 for r in results if r.status_code == 429)
print(f"Bloqueados: {blocked}/100")
```

---

## 🚨 Alertas y Logs

### Logs a Monitorear
```bash
# Ver activaciones de modo sospechoso
grep "MODO SOSPECHOSO" sisagent_verbose.log

# Ver números bloqueados
grep "DDoS Protection: bloqueando" sisagent_verbose.log

# Ver estado del circuit breaker
grep "CircuitBreaker" sisagent_verbose.log

# Ver estadísticas de rate limiting
grep "GlobalRateLimiter: límite" sisagent_verbose.log
```

### Configurar Alertas (ejemplo con systemd journal)
```bash
# Alerta cuando se activa modo sospechoso
journalctl -u sisagent -f | grep --line-buffered "MODO SOSPECHOSO" | \
  while read line; do
    echo "ALERTA: $line" | mail -s "DDoS detectado" admin@example.com
  done
```

---

## 🔒 Configuración de Variables de Entorno

Agregar al archivo `.env`:
```bash
# Protección DDoS
DDOS_GLOBAL_MAX_RPM=100
DDOS_MAX_NEW_NUMBERS_PM=20
DDOS_SUSPICIOUS_THRESHOLD=10
DDOS_CIRCUIT_BREAKER_THRESHOLD=10
DDOS_CIRCUIT_BREAKER_TIMEOUT=60
```

---

## 📈 Mejores Prácticas

1. **Monitorear Estadísticas Regularmente**
   - Revisar `/ddos-stats` cada hora
   - Configurar alertas para umbrales críticos

2. **Ajustar Límites Gradualmente**
   - Comenzar con límites conservadores
   - Aumentar basándose en métricas reales

3. **Mantener Whitelist Actualizada**
   - Agregar clientes VIP a la whitelist
   - Agregar números de prueba internos

4. **Revisar Blacklist Periódicamente**
   - Auditar números bloqueados automáticamente
   - Remover falsos positivos

5. **Logs y Auditoría**
   - Mantener logs por al menos 30 días
   - Analizar patrones de ataque

---

## 🆘 Respuesta a Incidentes

### Durante un Ataque Activo

1. **Verificar Estado:**
   ```bash
   curl http://localhost:5000/ddos-stats
   ```

2. **Activar Modo Restrictivo Manual:**
   ```python
   # En consola Python del agente
   ddos_protection.new_number_detector.suspicious_mode = True
   ddos_protection.new_number_detector.suspicious_until = time.time() + 3600  # 1 hora
   ```

3. **Bloquear Rangos de Números:**
   ```python
   # Agregar múltiples números a blacklist
   for i in range(1000, 2000):
       ddos_protection.blacklist.add_to_blacklist(f"549123456{i}@s.whatsapp.net", "ataque-ddos")
   ```

4. **Reiniciar con Límites Más Estrictos:**
   - Editar configuración en `ddos_protection.py`
   - Reiniciar: `./agent-manager.sh restart`

---

## 💡 Estrategias Adicionales

### A Nivel de Infraestructura

1. **Cloudflare / CDN:**
   - Rate limiting por IP
   - WAF (Web Application Firewall)

2. **Nginx / Load Balancer:**
   ```nginx
   limit_req_zone $binary_remote_addr zone=webhook:10m rate=10r/s;
   
   location /webhook {
       limit_req zone=webhook burst=20;
       proxy_pass http://localhost:5000;
   }
   ```

3. **Fail2Ban:**
   - Monitorear logs
   - Bloquear IPs automáticamente

### A Nivel de Aplicación

1. **CAPTCHA para Números Nuevos:**
   - Requerir verificación para números desconocidos
   - Usar servicios como Google reCAPTCHA

2. **Verificación por Código SMS:**
   - Enviar código de verificación a números nuevos
   - Validar antes de procesar

3. **Integración con WhatsApp Business API:**
   - Usar plantillas verificadas
   - Limitar mensajes iniciados por usuarios

---

## 📝 Registro de Cambios

- **v1.0.0** - Implementación inicial de todas las capas de protección
- Incluye: Rate limiting global, detector de números nuevos, circuit breaker, blacklist/whitelist

---

## 🤝 Soporte

Para reportar problemas o sugerencias sobre la protección DDoS:
- Revisar logs: `tail -f sisagent_verbose.log`
- Estadísticas: `curl http://localhost:5000/ddos-stats`
- Documentación completa en este archivo
