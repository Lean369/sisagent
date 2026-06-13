import requests
from langchain_core.tools import tool
import os
from loguru import logger
from dotenv import load_dotenv

load_dotenv(override=True)

TIENDANUBE_API_URL = os.getenv("TIENDANUBE_API_URL", "https://tiendanube.sisnova.org/api")
TIENDANUBE_STORE_ID = os.getenv("TIENDANUBE_STORE_ID", "")
TIENDANUBE_API_TOKEN = os.getenv("TIENDANUBE_API_TOKEN", "")


def _get_headers() -> dict:
    headers = {
        "Content-Type": "application/json",
        "X-Store-ID": TIENDANUBE_STORE_ID,
    }
    if TIENDANUBE_API_TOKEN:
        headers["Authorization"] = f"Bearer {TIENDANUBE_API_TOKEN}"
    return headers


@tool("consultar_orden_tiendanube")
def consultar_orden_tiendanube(numero_orden: str) -> str:
    """
    Consulta el estado y los detalles de una orden de compra en Tienda Nube.
    Usa esta herramienta cuando el cliente pregunte por el estado de su pedido,
    envío o compra. Recibe el número o ID de la orden.
    """
    logger.info(f"[TIENDANUBE] Consultando orden: {numero_orden}")
    try:
        headers = _get_headers()
        # Usar el endpoint general /orders?q= para obtener todos los campos sin restricciones.
        # El endpoint /orders/:id del proxy limita los campos a id,number,shipping_address,shipping_status.
        url = f"{TIENDANUBE_API_URL}/orders"
        params = {"q": numero_orden}
        logger.debug(f"[TIENDANUBE] GET {url} | params: {params}")
        response = requests.get(url, headers=headers, params=params, timeout=10)
        logger.debug(f"[TIENDANUBE] Respuesta orden {numero_orden}: HTTP {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            ordenes = data.get("data", data)

            if not isinstance(ordenes, list):
                ordenes = [ordenes]

            if not ordenes:
                logger.warning(f"[TIENDANUBE] Orden {numero_orden} no encontrada (lista vacía)")
                return f"No se encontró ninguna orden con el número {numero_orden}."

            orden = ordenes[0]

            numero = orden.get("number", orden.get("id", "N/D"))
            estado_pago = orden.get("payment_status", "N/D")
            estado_envio = orden.get("shipping_status", "N/D")
            estado_orden = orden.get("status", "N/D")
            total = orden.get("total", "N/D")
            moneda = orden.get("currency", "")
            cliente = orden.get("customer", {})
            nombre_cliente = cliente.get("name", "") if isinstance(cliente, dict) else ""
            tracking = orden.get("shipping_tracking_number", "") or ""
            carrier = orden.get("shipping_carrier_name", "") or ""

            logger.info(f"[TIENDANUBE] Orden #{numero} - Estado: {estado_orden} | Pago: {estado_pago} | Envío: {estado_envio}")

            resumen = (
                f"📦 Orden #{numero}\n"
                f"Estado: {estado_orden}\n"
                f"Pago: {estado_pago}\n"
                f"Envío: {estado_envio}\n"
                f"Total: {total} {moneda}"
            )
            if nombre_cliente:
                resumen += f"\nCliente: {nombre_cliente}"
            if tracking:
                resumen += f"\nNúmero de seguimiento: {tracking}"
                if carrier:
                    resumen += f" ({carrier})"

            # Incluir productos de la orden
            productos = orden.get("products", [])
            if productos:
                resumen += "\nProductos:"
                for p in productos:
                    p_nombre = p.get("name", "Producto")
                    p_qty = p.get("quantity", 1)
                    p_precio = p.get("price", "")
                    resumen += f"\n  - {p_nombre} x{p_qty}"
                    if p_precio:
                        resumen += f" ({p_precio} {moneda})"

            return resumen

        if response.status_code == 404:
            logger.warning(f"[TIENDANUBE] Orden {numero_orden} no encontrada (404)")
            return f"No se encontró ninguna orden con el número {numero_orden}."

        logger.error(f"[TIENDANUBE] Error consultando orden {numero_orden}: HTTP {response.status_code} - {response.text[:200]}")
        return f"Error al consultar la orden: {response.status_code} - {response.text[:200]}"

    except requests.Timeout:
        logger.error(f"[TIENDANUBE] Timeout consultando orden {numero_orden}")
        return "La consulta tardó demasiado. Por favor, intenta nuevamente en unos momentos."
    except Exception as e:
        logger.exception(f"[TIENDANUBE] Excepción consultando orden {numero_orden}: {e}")
        return f"Error al conectar con Tienda Nube: {e}"


@tool("consultar_productos_tiendanube")
def consultar_productos_tiendanube(nombre_producto: str) -> str:
    """
    Busca productos en la tienda y devuelve su disponibilidad, precio y detalles.
    Usa esta herramienta cuando el cliente pregunte por un producto específico,
    su precio, stock, o características. Recibe el nombre o descripción del producto.
    Pasa una cadena vacía para listar los productos disponibles.
    """
    logger.info(f"[TIENDANUBE] Buscando productos: '{nombre_producto or '(todos)'}'")
    try:
        headers = _get_headers()
        params = {"q": nombre_producto} if nombre_producto.strip() else {}
        url = f"{TIENDANUBE_API_URL}/products/available"
        logger.debug(f"[TIENDANUBE] GET {url} | params: {params}")
        response = requests.get(url, headers=headers, params=params, timeout=10)
        logger.debug(f"[TIENDANUBE] Respuesta productos: HTTP {response.status_code}")

        if response.status_code == 200:
            data = response.json()
            productos = data.get("data", data)

            if not isinstance(productos, list):
                productos = [productos]

            if not productos:
                logger.warning(f"[TIENDANUBE] Sin resultados para '{nombre_producto}'")
                return f"No se encontraron productos disponibles con '{nombre_producto}'."

            logger.info(f"[TIENDANUBE] {len(productos)} producto(s) encontrado(s) para '{nombre_producto or '(todos)'}'")

            lineas = [f"Se encontraron {len(productos)} producto(s):\n"]
            for p in productos[:5]:  # Limitar a 5 resultados para no saturar
                nombre = p.get("name", {})
                if isinstance(nombre, dict):
                    nombre = nombre.get("es", next(iter(nombre.values()), "Sin nombre"))
                precio = p.get("variants", [{}])[0].get("price", "N/D") if p.get("variants") else "N/D"
                stock = p.get("variants", [{}])[0].get("stock", "N/D") if p.get("variants") else "N/D"
                publicado = p.get("published", False)
                url_producto = p.get("canonical_url", "")

                logger.debug(f"[TIENDANUBE] Producto: {nombre} | Precio: {precio} | Stock: {stock}")
                linea = f"• {nombre} | Precio: {precio} | Stock: {stock} | Publicado: {'Sí' if publicado else 'No'}"
                if url_producto:
                    linea += f"\n  {url_producto}"
                lineas.append(linea)

            if len(productos) > 5:
                lineas.append(f"\n... y {len(productos) - 5} productos más.")

            return "\n".join(lineas)

        if response.status_code == 404:
            logger.warning(f"[TIENDANUBE] Productos no encontrados para '{nombre_producto}' (404)")
            return f"No se encontraron productos con '{nombre_producto}'."

        logger.error(f"[TIENDANUBE] Error consultando productos: HTTP {response.status_code} - {response.text[:200]}")
        return f"Error al consultar productos: {response.status_code} - {response.text[:200]}"

    except requests.Timeout:
        logger.error(f"[TIENDANUBE] Timeout buscando productos '{nombre_producto}'")
        return "La consulta tardó demasiado. Por favor, intenta nuevamente en unos momentos."
    except Exception as e:
        logger.exception(f"[TIENDANUBE] Excepción buscando productos '{nombre_producto}': {e}")
        return f"Error al conectar con Tienda Nube: {e}"
