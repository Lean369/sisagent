# Sistema de Métricas con PostgreSQL (Implementación lista para usar)

import psycopg2
from psycopg2 import sql
from psycopg2.extras import execute_batch
from psycopg2 import pool
from datetime import datetime, timedelta
from dataclasses import dataclass, asdict
from typing import List, Dict, Optional
import os
from threading import Lock
import time
import logging

# Usar el logger principal configurado en agent.py
logger = logging.getLogger(os.getenv('LOGGER_NAME', 'agent'))

# Configuración de PostgresSQL
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'database': os.getenv('DB_NAME_METRICS', 'metrics_db'),
    'user': os.getenv('DB_USER', 'sisbot_user'),
    'password': os.getenv('DB_PASSWORD', 'postgres_password'),
    'port': os.getenv('DB_PORT', '5432')
}

# Pool de conexiones (inicialización lazy para evitar errores al importar)
connection_pool = None

def _get_connection_pool():
    """Obtiene o crea el pool de conexiones (lazy initialization)"""
    global connection_pool
    if connection_pool is None:
        try:
            connection_pool = psycopg2.pool.ThreadedConnectionPool(
                minconn=1,
                maxconn=10,
                **DB_CONFIG
            )
            logger.info("✅ Pool de conexiones PostgreSQL inicializado")
        except Exception as e:
            msg = str(e).lower()
            logger.error(f"❌ Error conectando a PostgreSQL: {e}")
            # Si la causa es que la base de datos no existe, intentar crearla
            if 'does not exist' in msg or 'database "' in msg and 'does not exist' in msg:
                dbname = DB_CONFIG.get('database')
                logger.warning(f"🛠️  Intentando crear la base de datos '{dbname}' porque no existe")
                try:
                    # Intentar conectar a la base 'postgres' para crear la base objetivo
                    tmp_conf = DB_CONFIG.copy()
                    tmp_conf['database'] = 'postgres'
                    conn = psycopg2.connect(**tmp_conf)
                    conn.autocommit = True
                    cur = conn.cursor()
                    # Verificar existencia por si otro proceso la creó
                    cur.execute("SELECT 1 FROM pg_database WHERE datname = %s", (dbname,))
                    if cur.fetchone() is None:
                        cur.execute(sql.SQL("CREATE DATABASE {} OWNER {};").format(
                            sql.Identifier(dbname), sql.Identifier(DB_CONFIG.get('user'))
                        ))
                        logger.info(f"✅ Base de datos '{dbname}' creada correctamente")
                    cur.close()
                    conn.close()
                    # Reintentar crear el pool
                    connection_pool = psycopg2.pool.ThreadedConnectionPool(
                        minconn=1,
                        maxconn=10,
                        **DB_CONFIG
                    )
                    logger.info("✅ Pool de conexiones PostgreSQL inicializado tras crear la DB")
                except Exception as e2:
                    logger.error(f"❌ No fue posible crear la base de datos '{dbname}': {e2}")
                    raise
            else:
                raise
    return connection_pool

@dataclass
class MetricaMensaje:
    timestamp: float
    user_id: str
    tiempo_procesamiento: float
    tokens_usados: int
    fue_cache: bool
    error: bool
    mensaje_length: int = 0
    intencion: Optional[str] = None

class SistemaMetricasDB:
    """Sistema de métricas con persistencia en PostgreSQL"""
    
    def __init__(self):
        self.buffer: List[MetricaMensaje] = []
        # Buffer size configurable via env var for testing/production
        try:
            self.buffer_size = int(os.getenv('METRICS_BUFFER_SIZE', '1'))  # default=1 for immediate inserts
        except Exception:
            self.buffer_size = 1
        self.lock = Lock()
        self._crear_tablas()
    
    def _get_connection(self):
        """Obtiene conexión del pool"""
        pool = _get_connection_pool()
        return pool.getconn()
    
    def _return_connection(self, conn):
        """Devuelve conexión al pool"""
        pool = _get_connection_pool()
        pool.putconn(conn)
    
    def _crear_tablas(self):
        """Crea tablas necesarias si no existen"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            # Tabla principal de métricas
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metricas_mensajes (
                    id SERIAL PRIMARY KEY,
                    timestamp TIMESTAMP NOT NULL,
                    user_id VARCHAR(100) NOT NULL,
                    tiempo_procesamiento REAL NOT NULL,
                    tokens_usados INTEGER DEFAULT 0,
                    fue_cache BOOLEAN DEFAULT FALSE,
                    error BOOLEAN DEFAULT FALSE,
                    mensaje_length INTEGER DEFAULT 0,
                    intencion VARCHAR(50),
                    created_at TIMESTAMP DEFAULT NOW()
                );
                
                CREATE INDEX IF NOT EXISTS idx_metricas_timestamp 
                ON metricas_mensajes(timestamp);
                
                CREATE INDEX IF NOT EXISTS idx_metricas_user_id 
                ON metricas_mensajes(user_id);
                
                CREATE INDEX IF NOT EXISTS idx_metricas_error 
                ON metricas_mensajes(error);
            """)
            
            # Tabla de métricas agregadas por hora
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metricas_hora (
                    id SERIAL PRIMARY KEY,
                    hora TIMESTAMP NOT NULL,
                    total_mensajes INTEGER DEFAULT 0,
                    mensajes_exitosos INTEGER DEFAULT 0,
                    mensajes_error INTEGER DEFAULT 0,
                    mensajes_cache INTEGER DEFAULT 0,
                    tiempo_promedio REAL DEFAULT 0,
                    tokens_totales INTEGER DEFAULT 0,
                    usuarios_unicos INTEGER DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(hora)
                );
                
                CREATE INDEX IF NOT EXISTS idx_metricas_hora_hora 
                ON metricas_hora(hora);
            """)
            
            # Tabla de estadísticas por usuario
            cur.execute("""
                CREATE TABLE IF NOT EXISTS metricas_usuarios (
                    id SERIAL PRIMARY KEY,
                    user_id VARCHAR(100) NOT NULL,
                    total_mensajes INTEGER DEFAULT 0,
                    ultimo_mensaje TIMESTAMP,
                    primer_mensaje TIMESTAMP,
                    tiempo_promedio REAL DEFAULT 0,
                    tasa_error REAL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT NOW(),
                    updated_at TIMESTAMP DEFAULT NOW(),
                    UNIQUE(user_id)
                );
                
                CREATE INDEX IF NOT EXISTS idx_metricas_usuarios_user_id 
                ON metricas_usuarios(user_id);
            """)
            
            conn.commit()
            cur.close()
            logger.info("✅ Tablas de métricas creadas/verificadas")
            
        except Exception as e:
            logger.error(f"❌ Error creando tablas: {e}")
            conn.rollback()
        finally:
            self._return_connection(conn)
    
    def registrar_metrica(self, metrica: MetricaMensaje):
        """Registra una métrica (con buffering)"""
        with self.lock:
            self.buffer.append(metrica)
            try:
                logger.debug(f"🔸 Buffer metrics: {len(self.buffer)}/{self.buffer_size}")
            except Exception:
                pass
            
            # Si buffer está lleno, guardar en DB
            if len(self.buffer) >= self.buffer_size:
                self._flush_buffer()
    
    def _flush_buffer(self):
        """Guarda buffer en base de datos"""
        if not self.buffer:
            return
        
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            # Preparar datos para batch insert
            datos = []
            for m in self.buffer:
                datos.append((
                    datetime.fromtimestamp(m.timestamp),
                    m.user_id,
                    m.tiempo_procesamiento,
                    m.tokens_usados,
                    m.fue_cache,
                    m.error,
                    m.mensaje_length,
                    m.intencion
                ))
            
            # Batch insert (mucho más rápido)
            execute_batch(cur, """
                INSERT INTO metricas_mensajes 
                (timestamp, user_id, tiempo_procesamiento, tokens_usados, 
                 fue_cache, error, mensaje_length, intencion)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            """, datos)
            
            conn.commit()
            cur.close()
            
            # Actualizar métricas agregadas
            self._actualizar_metricas_agregadas()
            
            # Limpiar buffer
            self.buffer.clear()
            
            logger.info(f"💾 Guardadas {len(datos)} métricas en DB")
            return len(datos)
            
        except Exception as e:
            logger.error(f"❌ Error guardando métricas: {e}")
            conn.rollback()
        finally:
            self._return_connection(conn)

    def forzar_flush(self):
        """Forzar el vaciado del buffer de métricas y retornar cuántas métricas se insertaron."""
        with self.lock:
            cantidad = len(self.buffer)
            try:
                inserted = self._flush_buffer() or 0
                return {"buffer_before": cantidad, "inserted": inserted}
            except Exception as e:
                print(f"❌ Error forzando flush: {e}")
                return {"error": str(e)}
    
    def _actualizar_metricas_agregadas(self):
        """Actualiza tablas de métricas agregadas"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            # Actualizar métricas por hora (última hora)
            cur.execute("""
                INSERT INTO metricas_hora (
                    hora, total_mensajes, mensajes_exitosos, mensajes_error,
                    mensajes_cache, tiempo_promedio, tokens_totales, usuarios_unicos
                )
                SELECT 
                    DATE_TRUNC('hour', timestamp) as hora,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE NOT error) as exitosos,
                    COUNT(*) FILTER (WHERE error) as errores,
                    COUNT(*) FILTER (WHERE fue_cache) as cache,
                    AVG(tiempo_procesamiento) as tiempo_prom,
                    SUM(tokens_usados) as tokens_tot,
                    COUNT(DISTINCT user_id) as usuarios
                FROM metricas_mensajes
                WHERE timestamp >= NOW() - INTERVAL '1 hour'
                GROUP BY DATE_TRUNC('hour', timestamp)
                ON CONFLICT (hora) DO UPDATE SET
                    total_mensajes = EXCLUDED.total_mensajes,
                    mensajes_exitosos = EXCLUDED.mensajes_exitosos,
                    mensajes_error = EXCLUDED.mensajes_error,
                    mensajes_cache = EXCLUDED.mensajes_cache,
                    tiempo_promedio = EXCLUDED.tiempo_promedio,
                    tokens_totales = EXCLUDED.tokens_totales,
                    usuarios_unicos = EXCLUDED.usuarios_unicos;
            """)
            
            # Actualizar estadísticas por usuario
            cur.execute("""
                INSERT INTO metricas_usuarios (
                    user_id, total_mensajes, ultimo_mensaje, primer_mensaje,
                    tiempo_promedio, tasa_error
                )
                SELECT 
                    user_id,
                    COUNT(*) as total,
                    MAX(timestamp) as ultimo,
                    MIN(timestamp) as primero,
                    AVG(tiempo_procesamiento) as tiempo_prom,
                    (COUNT(*) FILTER (WHERE error)::FLOAT / COUNT(*)) * 100 as tasa_err
                FROM metricas_mensajes
                WHERE timestamp >= NOW() - INTERVAL '24 hours'
                GROUP BY user_id
                ON CONFLICT (user_id) DO UPDATE SET
                    total_mensajes = EXCLUDED.total_mensajes,
                    ultimo_mensaje = EXCLUDED.ultimo_mensaje,
                    tiempo_promedio = EXCLUDED.tiempo_promedio,
                    tasa_error = EXCLUDED.tasa_error,
                    updated_at = NOW();
            """)
            
            conn.commit()
            cur.close()
            
        except Exception as e:
            logger.error(f"❌ Error actualizando agregados: {e}")
            conn.rollback()
        finally:
            self._return_connection(conn)
    
    def obtener_estadisticas_generales(self, horas: int = 24) -> Dict:
        """Obtiene estadísticas generales del sistema"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            # Estadísticas últimas N horas
            cur.execute("""
                SELECT 
                    COUNT(*) as total_mensajes,
                    COUNT(*) FILTER (WHERE NOT error) as exitosos,
                    COUNT(*) FILTER (WHERE error) as errores,
                    COUNT(*) FILTER (WHERE fue_cache) as cache,
                    AVG(tiempo_procesamiento) as tiempo_promedio,
                    MIN(tiempo_procesamiento) as tiempo_min,
                    MAX(tiempo_procesamiento) as tiempo_max,
                    SUM(tokens_usados) as tokens_totales,
                    COUNT(DISTINCT user_id) as usuarios_unicos
                FROM metricas_mensajes
                WHERE timestamp >= NOW() - INTERVAL '%s hours'
            """, (horas,))
            
            resultado = cur.fetchone()
            cur.close()
            
            if not resultado or resultado[0] == 0:
                return {"error": "Sin datos en el período especificado"}
            
            total = resultado[0]
            exitosos = resultado[1] or 0
            errores = resultado[2] or 0
            cache = resultado[3] or 0
            
            return {
                "periodo_horas": horas,
                "total_mensajes": total,
                "mensajes_exitosos": exitosos,
                "mensajes_error": errores,
                "mensajes_cache": cache,
                "tasa_exito_porcentaje": round((exitosos / total) * 100, 2) if total > 0 else 0,
                "tasa_error_porcentaje": round((errores / total) * 100, 2) if total > 0 else 0,
                "tasa_cache_porcentaje": round((cache / total) * 100, 2) if total > 0 else 0,
                "tiempo_promedio_segundos": round(resultado[4] or 0, 2),
                "tiempo_minimo_segundos": round(resultado[5] or 0, 2),
                "tiempo_maximo_segundos": round(resultado[6] or 0, 2),
                "tokens_totales": resultado[7] or 0,
                "usuarios_unicos": resultado[8] or 0,
                "mensajes_por_usuario": round(total / (resultado[8] or 1), 2)
            }
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo estadísticas: {e}")
            return {"error": str(e)}
        finally:
            self._return_connection(conn)
    
    def obtener_metricas_por_hora(self, ultimas_horas: int = 24) -> List[Dict]:
        """Obtiene métricas agregadas por hora"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    hora,
                    total_mensajes,
                    mensajes_exitosos,
                    mensajes_error,
                    mensajes_cache,
                    tiempo_promedio,
                    tokens_totales,
                    usuarios_unicos
                FROM metricas_hora
                WHERE hora >= NOW() - INTERVAL '%s hours'
                ORDER BY hora DESC
            """, (ultimas_horas,))
            
            resultados = []
            for row in cur.fetchall():
                resultados.append({
                    "hora": row[0].isoformat(),
                    "total_mensajes": row[1],
                    "exitosos": row[2],
                    "errores": row[3],
                    "cache": row[4],
                    "tiempo_promedio": round(row[5], 2),
                    "tokens": row[6],
                    "usuarios": row[7]
                })
            
            cur.close()
            return resultados
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo métricas por hora: {e}")
            return []
        finally:
            self._return_connection(conn)

    def obtener_metricas_por_hora_rango(self, start_iso: str, end_iso: str) -> List[Dict]:
        """Obtiene métricas agregadas por hora en un rango de fechas (ISO strings)."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()

            cur.execute("""
                SELECT 
                    hora,
                    total_mensajes,
                    mensajes_exitosos,
                    mensajes_error,
                    mensajes_cache,
                    tiempo_promedio,
                    tokens_totales,
                    usuarios_unicos
                FROM metricas_hora
                WHERE hora >= %s AND hora <= %s
                ORDER BY hora DESC
            """, (start_iso, end_iso))

            resultados = []
            for row in cur.fetchall():
                resultados.append({
                    "hora": row[0].isoformat(),
                    "total_mensajes": row[1],
                    "exitosos": row[2],
                    "errores": row[3],
                    "cache": row[4],
                    "tiempo_promedio": round(row[5], 2) if row[5] is not None else 0,
                    "tokens": row[6],
                    "usuarios": row[7]
                })

            cur.close()
            return resultados

        except Exception as e:
            logger.error(f"❌ Error obteniendo métricas por hora (rango): {e}")
            return []
        finally:
            self._return_connection(conn)

    def obtener_estadisticas_por_rango(self, start_iso: str, end_iso: str) -> Dict:
        """Obtiene estadísticas generales entre dos timestamps ISO."""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            cur.execute("""
                SELECT 
                    COUNT(*) as total_mensajes,
                    COUNT(*) FILTER (WHERE NOT error) as exitosos,
                    COUNT(*) FILTER (WHERE error) as errores,
                    COUNT(*) FILTER (WHERE fue_cache) as cache,
                    AVG(tiempo_procesamiento) as tiempo_promedio,
                    MIN(tiempo_procesamiento) as tiempo_min,
                    MAX(tiempo_procesamiento) as tiempo_max,
                    SUM(tokens_usados) as tokens_totales,
                    COUNT(DISTINCT user_id) as usuarios_unicos
                FROM metricas_mensajes
                WHERE timestamp >= %s AND timestamp <= %s
            """, (start_iso, end_iso))

            resultado = cur.fetchone()
            cur.close()

            if not resultado or resultado[0] == 0:
                return {"error": "Sin datos en el período especificado"}

            total = resultado[0]
            exitosos = resultado[1] or 0
            errores = resultado[2] or 0
            cache = resultado[3] or 0

            return {
                "periodo_start": start_iso,
                "periodo_end": end_iso,
                "total_mensajes": total,
                "mensajes_exitosos": exitosos,
                "mensajes_error": errores,
                "mensajes_cache": cache,
                "tasa_exito_porcentaje": round((exitosos / total) * 100, 2) if total > 0 else 0,
                "tasa_error_porcentaje": round((errores / total) * 100, 2) if total > 0 else 0,
                "tasa_cache_porcentaje": round((cache / total) * 100, 2) if total > 0 else 0,
                "tiempo_promedio_segundos": round(resultado[4] or 0, 2),
                "tiempo_minimo_segundos": round(resultado[5] or 0, 2),
                "tiempo_maximo_segundos": round(resultado[6] or 0, 2),
                "tokens_totales": resultado[7] or 0,
                "usuarios_unicos": resultado[8] or 0,
                "mensajes_por_usuario": round(total / (resultado[8] or 1), 2)
            }

        except Exception as e:
            logger.error(f"❌ Error obteniendo estadísticas por rango: {e}")
            return {"error": str(e)}
        finally:
            self._return_connection(conn)
    
    def obtener_top_usuarios(self, limit: int = 10) -> List[Dict]:
        """Obtiene usuarios más activos"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            cur.execute("""
                SELECT 
                    user_id,
                    total_mensajes,
                    ultimo_mensaje,
                    tiempo_promedio,
                    tasa_error
                FROM metricas_usuarios
                ORDER BY total_mensajes DESC
                LIMIT %s
            """, (limit,))
            
            resultados = []
            for row in cur.fetchall():
                resultados.append({
                    "user_id": row[0],
                    "total_mensajes": row[1],
                    "ultimo_mensaje": row[2].isoformat() if row[2] else None,
                    "tiempo_promedio": round(row[3], 2),
                    "tasa_error": round(row[4], 2)
                })
            
            cur.close()
            return resultados
            
        except Exception as e:
            logger.error(f"❌ Error obteniendo top usuarios: {e}")
            return []
        finally:
            self._return_connection(conn)
    
    def limpiar_datos_antiguos(self, dias: int = 30):
        """Elimina métricas detalladas antiguas (mantiene agregados)"""
        conn = self._get_connection()
        try:
            cur = conn.cursor()
            
            cur.execute("""
                DELETE FROM metricas_mensajes
                WHERE timestamp < NOW() - INTERVAL '%s days'
            """, (dias,))
            
            eliminados = cur.rowcount
            conn.commit()
            cur.close()
            
            logger.info(f"🧹 Eliminadas {eliminados} métricas antiguas (>{dias} días)")
            return eliminados
            
        except Exception as e:
            logger.error(f"❌ Error limpiando datos: {e}")
            conn.rollback()
            return 0
        finally:
            self._return_connection(conn)

    def borrar_todas_metricas(self):
        """Borra todas las tablas de métricas y reinicia los contadores.

        Devuelve un dict con los conteos eliminados por tabla antes del borrado.
        """
        conn = self._get_connection()
        try:
            cur = conn.cursor()

            # Contar filas actuales para reporte
            cur.execute("SELECT COUNT(*) FROM metricas_mensajes")
            c_mensajes = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM metricas_hora")
            c_hora = cur.fetchone()[0] or 0
            cur.execute("SELECT COUNT(*) FROM metricas_usuarios")
            c_usuarios = cur.fetchone()[0] or 0

            # Truncar las tablas y reiniciar identities
            cur.execute("TRUNCATE metricas_mensajes, metricas_hora, metricas_usuarios RESTART IDENTITY CASCADE;")
            conn.commit()
            cur.close()

            logger.info(f"🧹 Truncadas tablas de métricas: mensajes={c_mensajes}, hora={c_hora}, usuarios={c_usuarios}")
            return {
                "metricas_mensajes": c_mensajes,
                "metricas_hora": c_hora,
                "metricas_usuarios": c_usuarios,
                "total": int(c_mensajes + c_hora + c_usuarios)
            }

        except Exception as e:
            logger.error(f"❌ Error borrando todas las métricas: {e}")
            conn.rollback()
            return {"error": str(e)}
        finally:
            self._return_connection(conn)
    
    def __del__(self):
        """Asegura que el buffer se guarde al destruir el objeto"""
        self._flush_buffer()

# Instancia global
metricas_db = SistemaMetricasDB()

# Alias para compatibilidad
MetricsDB = SistemaMetricasDB