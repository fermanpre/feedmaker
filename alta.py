"""Alta de una web desde una incidencia de GitHub (título «alta: <url>»), pensada para el workflow alta.yml.

Uso:
  python alta.py registrar feeds.json      # lee ISSUE_TITLE, añade la web a feeds.json y escribe GITHUB_OUTPUT
  python alta.py comentario <id> docs/estado.json   # imprime el comentario (Markdown) para la incidencia

El título de la incidencia es una entrada no fiable: solo se acepta una URL https válida (extractor.validar_url)
y nunca se interpola en comandos de shell; llega por variable de entorno.
"""

import json
import os
import re
import sys
import urllib.parse

import extractor

URL_FEEDLY = "https://feedly.com/i/subscription/feed/"

# Combinados: límites pensados para uso personal; el servidor los aplica aunque la página ya los compruebe.
MINIMO_DE_FEEDS_POR_COMBINADO = 2
MAXIMO_DE_FEEDS_POR_COMBINADO = 5
MAXIMO_DE_COMBINADOS = 20
MAXIMO_DE_PALABRAS_DE_FILTRO = 5
MAXIMA_LONGITUD_DE_PALABRA = 40
MAXIMA_LONGITUD_DEL_NOMBRE = 80
MAXIMA_LONGITUD_DE_URL = 2000
PATRON_DE_IDENTIFICADOR = re.compile(r"^[a-z0-9][a-z0-9-]{0,79}$")


def extraer_url(titulo):
    coincidencia = re.match(r"^\s*alta:\s*(\S+)\s*$", titulo or "", re.IGNORECASE)
    return coincidencia.group(1) if coincidencia else ""


def texto_completo_pedido():
    """True o False si el alta lo dice expresamente (parámetro TEXTO_COMPLETO del workflow o línea «texto_completo: true»
    / «texto_completo: false» en el cuerpo de la incidencia); None si no dice nada: entonces vale el valor por defecto
    de generar.py (texto completo). Solo se aceptan esos valores exactos; el resto de la entrada no se interpreta."""
    parametro = os.environ.get("TEXTO_COMPLETO", "").strip().lower()
    if parametro in ("true", "false"):
        return parametro == "true"
    cuerpo = os.environ.get("ISSUE_BODY", "")
    coincidencia = re.search(r"^\s*texto_completo:\s*(true|false)\s*$", cuerpo, re.IGNORECASE | re.MULTILINE)
    return coincidencia.group(1).lower() == "true" if coincidencia else None


def normalizar_url(url):
    """Forma canónica para detectar duplicados: sin «www.», sin barra final, sin fragmento ni parámetros de seguimiento.

    No sirve para descargar: la URL guardada en feeds.json es la que escribió el usuario."""
    partes = urllib.parse.urlsplit(url.strip())
    host = (partes.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    ruta = re.sub(r"/+$", "", partes.path) or ""
    parametros = [
        (clave, valor) for clave, valor in urllib.parse.parse_qsl(partes.query, keep_blank_values=True)
        if not clave.lower().startswith("utm_") and clave.lower() not in {"fbclid", "gclid", "mc_cid", "mc_eid"}
    ]
    consulta = urllib.parse.urlencode(sorted(parametros))
    return f"{host}{ruta}" + (f"?{consulta}" if consulta else "")


def crear_identificador(url, identificadores_en_uso):
    partes = urllib.parse.urlsplit(url)
    texto = (partes.netloc + partes.path).lower()
    texto = re.sub(r"^www\.", "", texto)
    base = re.sub(r"[^a-z0-9]+", "-", texto).strip("-")[:50].strip("-") or "web"
    candidato = base
    contador = 2
    while candidato in identificadores_en_uso:
        candidato = f"{base}-{contador}"
        contador += 1
    return candidato


def escribir_salida(**valores):
    ruta = os.environ.get("GITHUB_OUTPUT")
    lineas = [f"{clave}={valor}" for clave, valor in valores.items()]
    if ruta:
        with open(ruta, "a", encoding="utf-8") as fichero:
            fichero.write("\n".join(lineas) + "\n")
    print("\n".join(lineas))


def limpiar_texto_libre(texto, maximo):
    """Texto de una sola línea, sin caracteres de control, con los espacios normalizados y recortado."""
    sin_control = re.sub(r"[\x00-\x1f\x7f]", " ", texto or "")
    return " ".join(sin_control.split())[:maximo]


def separar_por_comas(texto):
    """Lista sin vacíos ni repetidos (sin distinguir mayúsculas), en el orden en que aparecen."""
    vistos = set()
    elementos = []
    for trozo in (texto or "").split(","):
        elemento = " ".join(trozo.split())
        if elemento and elemento.lower() not in vistos:
            vistos.add(elemento.lower())
            elementos.append(elemento)
    return elementos


def leer_peticion_de_combinado():
    """(identificadores, direcciones, nombre, filtro) si el alta pide un combinado, o None si pide una web.

    Llega por los parámetros del workflow (COMBINA, URLS_COMBINADO, NOMBRE_COMBINADO, FILTRO_COMBINADO) o por una
    incidencia con el título «combinar: id1, id2» (puede ir vacío tras los dos puntos) y, en el cuerpo, líneas
    opcionales «web: <dirección>» (una por web nueva), «nombre: …» y «filtro: palabra1, palabra2».
    `identificadores` son feeds que ya existen; `direcciones`, webs que se dan de alta como fuentes ocultas."""
    combina = os.environ.get("COMBINA", "").strip()
    direcciones = os.environ.get("URLS_COMBINADO", "").strip()
    nombre = os.environ.get("NOMBRE_COMBINADO", "")
    filtro = os.environ.get("FILTRO_COMBINADO", "")
    if not combina and not direcciones:
        coincidencia = re.match(r"^\s*combinar:\s*(.*?)\s*$", os.environ.get("ISSUE_TITLE", ""), re.IGNORECASE)
        if not coincidencia:
            return None
        combina = coincidencia.group(1)
        cuerpo = os.environ.get("ISSUE_BODY", "")
        linea_nombre = re.search(r"^\s*nombre:\s*(.*?)\s*$", cuerpo, re.IGNORECASE | re.MULTILINE)
        linea_filtro = re.search(r"^\s*filtro:\s*(.*?)\s*$", cuerpo, re.IGNORECASE | re.MULTILINE)
        lineas_web = re.findall(r"^\s*web:\s*(\S+)\s*$", cuerpo, re.IGNORECASE | re.MULTILINE)
        nombre = linea_nombre.group(1) if linea_nombre else ""
        filtro = linea_filtro.group(1) if linea_filtro else ""
        direcciones = " ".join(lineas_web)
    return (separar_por_comas(combina), direcciones.split(), limpiar_texto_libre(nombre, MAXIMA_LONGITUD_DEL_NOMBRE),
            separar_por_comas(filtro))


def etiqueta_de_la_web(url):
    """Nombre corto de una web para anteponerlo a los títulos de un combinado: su dominio sin «www.» (abc.es)."""
    anfitrion = (urllib.parse.urlsplit(url).hostname or "").lower()
    return anfitrion[4:] if anfitrion.startswith("www.") else anfitrion


def etiqueta_del_miembro(miembro):
    if miembro.get("etiqueta"):
        return miembro["etiqueta"]
    return etiqueta_de_la_web(miembro["url"]) if miembro.get("url") else miembro["nombre"]


def nombre_por_defecto(miembros, filtro):
    """«caja, caja87: abc.es + diariodesevilla.es» (con filtro) o «Combinado: abc.es + …» (sin él), de 80 caracteres como
    máximo: si no cabe, se quitan webs enteras del final y se pone «…», sin cortar el nombre de una web por la mitad."""
    etiquetas = []
    for miembro in miembros:
        etiqueta = etiqueta_del_miembro(miembro)
        if etiqueta not in etiquetas:
            etiquetas.append(etiqueta)
    prefijo = ", ".join(filtro) + ": " if filtro else "Combinado: "
    completo = limpiar_texto_libre(prefijo + " + ".join(etiquetas), 10000)
    if len(completo) <= MAXIMA_LONGITUD_DEL_NOMBRE:
        return completo
    elegidas = []
    for etiqueta in etiquetas:
        con_esta = limpiar_texto_libre(prefijo + " + ".join(elegidas + [etiqueta]) + " + …", 10000)
        if len(con_esta) > MAXIMA_LONGITUD_DEL_NOMBRE:
            break
        elegidas.append(etiqueta)
    if not elegidas:
        return limpiar_texto_libre(completo, MAXIMA_LONGITUD_DEL_NOMBRE)
    return limpiar_texto_libre(prefijo + " + ".join(elegidas) + " + …", MAXIMA_LONGITUD_DEL_NOMBRE)


def validar_combinado(identificadores, filtro, sitios):
    """Motivo de rechazo, o '' si el combinado es aceptable."""
    if not MINIMO_DE_FEEDS_POR_COMBINADO <= len(identificadores) <= MAXIMO_DE_FEEDS_POR_COMBINADO:
        return (f"un combinado lleva de {MINIMO_DE_FEEDS_POR_COMBINADO} a {MAXIMO_DE_FEEDS_POR_COMBINADO} feeds "
                f"(se han indicado {len(identificadores)})")
    por_identificador = {sitio["id"]: sitio for sitio in sitios}
    for identificador in identificadores:
        if not PATRON_DE_IDENTIFICADOR.match(identificador):
            return "identificador de feed no válido"
        miembro = por_identificador.get(identificador)
        if miembro is None:
            return f"el feed «{identificador}» no existe"
        if "combina" in miembro:
            return f"«{identificador}» es un combinado: no se pueden anidar"
    if len(filtro) > MAXIMO_DE_PALABRAS_DE_FILTRO:
        return f"el filtro admite hasta {MAXIMO_DE_PALABRAS_DE_FILTRO} palabras"
    if any(len(palabra) > MAXIMA_LONGITUD_DE_PALABRA or re.search(r"[\x00-\x1f\x7f]", palabra) for palabra in filtro):
        return f"cada palabra del filtro admite hasta {MAXIMA_LONGITUD_DE_PALABRA} caracteres"
    return ""


def dar_de_alta_fuentes_ocultas(direcciones, sitios):
    """(identificadores, webs nuevas, motivo de rechazo) para esas direcciones.

    Una dirección que ya está dada de alta (con o sin «www.», con o sin barra final) reutiliza esa web tal como está. Las
    demás se crean como fuentes ocultas: solo son ingredientes del combinado y no salen en «Mis feeds»."""
    identificadores = []
    nuevas = []
    en_uso = {sitio["id"] for sitio in sitios}
    for direccion in direcciones:
        if len(direccion) > MAXIMA_LONGITUD_DE_URL:
            return [], [], "una dirección es demasiado larga"
        motivo_url = extractor.validar_url(direccion)
        if motivo_url:
            return [], [], f"la dirección «{direccion[:80]}» no es válida: {motivo_url}"
        buscada = normalizar_url(direccion)
        existente = next((sitio for sitio in sitios + nuevas
                          if "combina" not in sitio and normalizar_url(sitio.get("url", "")) == buscada), None)
        if existente is None:
            partes = urllib.parse.urlsplit(direccion)
            existente = {"id": crear_identificador(direccion, en_uso), "nombre": partes.netloc + partes.path.rstrip("/"),
                         "url": direccion, "etiqueta": etiqueta_de_la_web(direccion), "oculto": True}
            en_uso.add(existente["id"])
            nuevas.append(existente)
        identificadores.append(existente["id"])
    return identificadores, nuevas, ""


def registrar_combinado(ruta_feeds, identificadores, direcciones, nombre, filtro):
    with open(ruta_feeds, encoding="utf-8") as fichero:
        sitios = json.load(fichero)
    if len(identificadores) + len(direcciones) > MAXIMO_DE_FEEDS_POR_COMBINADO:
        escribir_salida(valida="false", id="", motivo=(
            f"un combinado lleva de {MINIMO_DE_FEEDS_POR_COMBINADO} a {MAXIMO_DE_FEEDS_POR_COMBINADO} feeds "
            f"(se han indicado {len(identificadores) + len(direcciones)})"))
        return
    de_las_direcciones, nuevas, motivo = dar_de_alta_fuentes_ocultas(direcciones, sitios)
    if motivo:
        escribir_salida(valida="false", motivo=motivo.replace("\n", " "), id="")
        return
    todos = []
    for identificador in identificadores + de_las_direcciones:
        if identificador not in todos:
            todos.append(identificador)
    candidatos = sitios + nuevas
    motivo = validar_combinado(todos, filtro, candidatos)
    if motivo:
        escribir_salida(valida="false", motivo=motivo.replace("\n", " "), id="")
        return
    claves = (frozenset(todos), tuple(sorted(palabra.lower() for palabra in filtro)))
    existente = next((sitio for sitio in sitios if "combina" in sitio and (
        frozenset(sitio["combina"]), tuple(sorted(palabra.lower() for palabra in sitio.get("filtro", [])))) == claves), None)
    if existente is not None:
        escribir_salida(valida="true", motivo="", id=existente["id"])
        return
    if sum(1 for sitio in sitios if "combina" in sitio) >= MAXIMO_DE_COMBINADOS:
        escribir_salida(valida="false", motivo=f"ya hay {MAXIMO_DE_COMBINADOS} combinados: borra alguno antes", id="")
        return
    por_identificador = {sitio["id"]: sitio for sitio in candidatos}
    if not nombre:
        nombre = nombre_por_defecto([por_identificador[identificador] for identificador in todos], filtro)
    base = "comb-" + (re.sub(r"[^a-z0-9]+", "-", nombre.lower()).strip("-")[:40].strip("-") or "feeds")
    en_uso = {sitio["id"] for sitio in candidatos}
    nuevo_id, contador = base, 2
    while nuevo_id in en_uso:
        nuevo_id = f"{base}-{contador}"
        contador += 1
    combinado = {"id": nuevo_id, "nombre": nombre, "combina": todos}
    if filtro:
        combinado["filtro"] = filtro
    pedido = texto_completo_pedido()
    if pedido is not None:
        combinado["texto_completo"] = pedido
    sitios.extend(nuevas)
    sitios.append(combinado)
    with open(ruta_feeds, "w", encoding="utf-8", newline="\n") as fichero:
        json.dump(sitios, fichero, ensure_ascii=False, indent=2)
        fichero.write("\n")
    escribir_salida(valida="true", motivo="", id=nuevo_id)


def registrar(ruta_feeds):
    peticion_de_combinado = leer_peticion_de_combinado()
    if peticion_de_combinado is not None:
        registrar_combinado(ruta_feeds, *peticion_de_combinado)
        return
    # La URL llega por el parámetro del workflow (URL_ALTA) o por el título de una incidencia.
    url = os.environ.get("URL_ALTA", "").strip() or extraer_url(os.environ.get("ISSUE_TITLE", ""))
    motivo = "no se ha recibido ninguna URL (el título debe ser «alta: <url>»)" if not url else extractor.validar_url(url)
    if motivo:
        escribir_salida(valida="false", motivo=motivo.replace("\n", " "), id="")
        return

    with open(ruta_feeds, encoding="utf-8") as fichero:
        sitios = json.load(fichero)
    existente = next((sitio for sitio in sitios if normalizar_url(sitio.get("url", "")) == normalizar_url(url)), None)
    if existente is None:
        identificador = crear_identificador(url, {sitio["id"] for sitio in sitios})
        partes = urllib.parse.urlsplit(url)
        sitio_nuevo = {"id": identificador, "nombre": partes.netloc + partes.path.rstrip("/"), "url": url}
        pedido = texto_completo_pedido()
        if pedido is not None:
            sitio_nuevo["texto_completo"] = pedido
        sitios.append(sitio_nuevo)
        with open(ruta_feeds, "w", encoding="utf-8", newline="\n") as fichero:
            json.dump(sitios, fichero, ensure_ascii=False, indent=2)
            fichero.write("\n")
    else:
        identificador = existente["id"]
    escribir_salida(valida="true", motivo="", id=identificador)


def enlace_feedly(url_del_feed):
    return URL_FEEDLY + urllib.parse.quote(url_del_feed, safe="")


def comentario(identificador, ruta_estado):
    repositorio = os.environ.get("GITHUB_REPOSITORY", "usuario/repositorio")
    propietario, nombre = repositorio.split("/", 1)
    base = f"https://{propietario}.github.io/{nombre}/"
    with open(ruta_estado, encoding="utf-8") as fichero:
        sitios = json.load(fichero)["sitios"]
    sitio = next((s for s in sitios if s["id"] == identificador), None)
    if sitio is None:
        return "No se ha encontrado la web en el estado. Revisa el workflow."
    if sitio["estado"] == "ok":
        feed = f"{base}feeds/{identificador}.xml"
        return (f"Listo: {sitio['entradas']} entradas.\n\n"
                f"- Feed: {feed}\n- Añadir a Feedly: {enlace_feedly(feed)}\n\n"
                "Pages puede tardar 1-2 minutos en servir el fichero nuevo.")
    if sitio["estado"] == "feed_propio":
        return (f"Esta web ya tiene feed propio: {sitio['feed_propio']}\n\n"
                f"Añadir a Feedly: {enlace_feedly(sitio['feed_propio'])}")
    mensaje = f"No se ha podido generar el feed: {sitio['detalle']}"
    if sitio.get("sugerencias"):
        mensaje += "\n\nPrueba con alguna de estas direcciones, que parecen listados:\n" + "\n".join(
            f"- {direccion}" for direccion in sitio["sugerencias"])
    return mensaje


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "registrar":
        registrar(sys.argv[2])
    elif len(sys.argv) == 4 and sys.argv[1] == "comentario":
        print(comentario(sys.argv[2], sys.argv[3]))
    else:
        raise SystemExit(__doc__)
