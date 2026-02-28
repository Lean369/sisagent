import psycopg2
from datetime import datetime, timedelta

def limpiar_datos_antiguos():
    try:
        # 1. Conexión a tu base de datos Postgres
        conn = psycopg2.connect(
            dbname="tu_db",
            user="tu_usuario",
            password="tu_password",
            host="localhost"
        )
        cur = conn.cursor()

        # 2. Definimos el límite (ejemplo: borrar lo anterior a 30 días)
        limite = datetime.now() - timedelta(days=30)
        
        # 3. Ejecutamos el borrado
        # Cambia 'logs' y 'fecha_registro' por tus nombres reales
        query = "DELETE FROM logs WHERE fecha_registro < %s"
        cur.execute(query, (limite,))
        
        filas_borradas = cur.rowcount
        conn.commit()

        # 4. OPCIONAL: Correr un VACUUM sencillo (no bloquea la tabla)
        # Esto ayuda a que Postgres marque el espacio como reusable internamente
        conn.set_isolation_level(0) # VACUUM no puede correr dentro de una transacción
        cur.execute("VACUUM ANALYZE logs")
        
        print(f"[{datetime.now()}] Limpieza exitosa: {filas_borradas} filas eliminadas.")

    except Exception as e:
        print(f"Error en la limpieza: {e}")
    finally:
        if conn:
            cur.close()
            conn.close()

if __name__ == "__main__":
    limpiar_datos_antiguos()