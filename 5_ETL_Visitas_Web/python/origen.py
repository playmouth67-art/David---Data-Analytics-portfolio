"""
Capa de acceso al origen de archivos.

Por qué existe esta abstracción
-------------------------------
El requerimiento indica que los archivos viven en un servidor remoto
accesible por SFTP, en /home/etl/archivosVisitas. El resto
del ETL no debe saber nada de eso: solo necesita poder listar, descargar
y eliminar archivos.

Aislar el origen detrás de una interfaz da tres cosas:

1. El ETL se puede probar de punta a punta sin un servidor SFTP, usando
   un directorio local con los mismos archivos.
2. Si mañana el origen cambia a S3, FTPS o un montaje de red, solo se
   agrega una implementación; el orquestador no se toca.
3. Las credenciales quedan confinadas a una sola clase, no dispersas.

La implementación activa se elige por configuración (ETL_ORIGEN), no por
código: 'local' para desarrollo y pruebas, 'sftp' para productivo.
"""

import os
import re
import shutil
from datetime import datetime

# Solo se procesan archivos que cumplan el patrón del requerimiento:
# "report_" + consecutivo + ".txt". Cualquier otro archivo del directorio
# se ignora sin marcarlo como error: puede ser de otro proceso.
PATRON_ARCHIVO = re.compile(r'^report_\d+\.txt$')


class ArchivoRemoto:
    """Metadatos de un archivo en el origen, independientes del protocolo."""

    __slots__ = ('nombre', 'bytes', 'mtime')

    def __init__(self, nombre, bytes_, mtime):
        self.nombre = nombre
        self.bytes = bytes_
        self.mtime = mtime

    def __repr__(self):
        return f"<ArchivoRemoto {self.nombre} {self.bytes}B {self.mtime}>"


class OrigenArchivos:
    """Contrato que debe cumplir cualquier origen."""

    def listar(self):
        """Devuelve la lista de ArchivoRemoto que cumplen el patrón, ordenada."""
        raise NotImplementedError

    def descargar(self, nombre, destino_local):
        """Trae el archivo al path local indicado, preservando los bytes."""
        raise NotImplementedError

    def eliminar(self, nombre):
        """Borra el archivo del origen. Solo se invoca tras respaldar."""
        raise NotImplementedError

    def cerrar(self):
        """Libera recursos. Idempotente."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.cerrar()


class OrigenLocal(OrigenArchivos):
    """Directorio local. Se usa en desarrollo y en las pruebas del ETL.

    Permite ejercitar todo el flujo (incluido el borrado en origen) sin
    depender de un servidor SFTP disponible.
    """

    def __init__(self, directorio):
        self.directorio = directorio
        os.makedirs(directorio, exist_ok=True)

    def listar(self):
        encontrados = []
        for nombre in sorted(os.listdir(self.directorio)):
            if not PATRON_ARCHIVO.match(nombre):
                continue
            ruta = os.path.join(self.directorio, nombre)
            if not os.path.isfile(ruta):
                continue
            st = os.stat(ruta)
            encontrados.append(ArchivoRemoto(
                nombre, st.st_size, datetime.fromtimestamp(st.st_mtime)))
        return encontrados

    def descargar(self, nombre, destino_local):
        shutil.copy2(os.path.join(self.directorio, nombre), destino_local)

    def eliminar(self, nombre):
        os.remove(os.path.join(self.directorio, nombre))

    def __repr__(self):
        return f"OrigenLocal({self.directorio})"


class OrigenSFTP(OrigenArchivos):
    """Servidor remoto por SFTP. Es el origen productivo del requerimiento.

    paramiko se importa aquí adentro a propósito: el modo local no debe
    exigir la dependencia instalada.

    Sobre credenciales: se leen de variables de entorno, nunca del código
    ni del repositorio. Se prefiere llave privada sobre contraseña; la
    contraseña queda como alternativa para entornos que aún no migran.
    """

    def __init__(self, host, directorio, usuario, password=None,
                 llave_privada=None, puerto=22, timeout=30):
        import paramiko  # dependencia opcional

        self.host = host
        self.directorio = directorio

        self._transport = paramiko.Transport((host, puerto))
        self._transport.banner_timeout = timeout

        if llave_privada:
            clave = paramiko.RSAKey.from_private_key_file(llave_privada)
            self._transport.connect(username=usuario, pkey=clave)
        else:
            self._transport.connect(username=usuario, password=password)

        self._sftp = paramiko.SFTPClient.from_transport(self._transport)
        self._sftp.chdir(directorio)

    def listar(self):
        encontrados = []
        for attr in self._sftp.listdir_attr('.'):
            if not PATRON_ARCHIVO.match(attr.filename):
                continue
            encontrados.append(ArchivoRemoto(
                attr.filename, attr.st_size,
                datetime.fromtimestamp(attr.st_mtime)))
        return sorted(encontrados, key=lambda a: a.nombre)

    def descargar(self, nombre, destino_local):
        self._sftp.get(nombre, destino_local)

    def eliminar(self, nombre):
        self._sftp.remove(nombre)

    def cerrar(self):
        try:
            if self._sftp:
                self._sftp.close()
            if self._transport:
                self._transport.close()
        except Exception:
            pass

    def __repr__(self):
        return f"OrigenSFTP({self.host}:{self.directorio})"


def crear_origen(base_dir):
    """Fábrica: construye el origen según configuración de entorno.

    ETL_ORIGEN = local | sftp   (default: local)

    Modo local:
        ETL_ORIGEN_DIR        default <base_dir>/data/source

    Modo sftp:
        ETL_SFTP_HOST         default 8.8.8.8
        ETL_SFTP_PUERTO       default 22
        ETL_SFTP_DIR          default /home/etl/archivosVisitas
        ETL_SFTP_USUARIO      requerido
        ETL_SFTP_LLAVE        ruta a llave privada (preferido)
        ETL_SFTP_PASSWORD     alternativa a la llave
    """
    modo = os.environ.get('ETL_ORIGEN', 'local').strip().lower()

    if modo == 'local':
        return OrigenLocal(os.environ.get(
            'ETL_ORIGEN_DIR', os.path.join(base_dir, 'data/source')))

    if modo == 'sftp':
        usuario = os.environ.get('ETL_SFTP_USUARIO')
        if not usuario:
            raise ValueError("ETL_ORIGEN=sftp requiere ETL_SFTP_USUARIO.")
        return OrigenSFTP(
            host=os.environ.get('ETL_SFTP_HOST', '8.8.8.8'),
            puerto=int(os.environ.get('ETL_SFTP_PUERTO', '22')),
            directorio=os.environ.get('ETL_SFTP_DIR', '/home/etl/archivosVisitas'),
            usuario=usuario,
            llave_privada=os.environ.get('ETL_SFTP_LLAVE'),
            password=os.environ.get('ETL_SFTP_PASSWORD'),
        )

    raise ValueError(f"ETL_ORIGEN desconocido: '{modo}'. Use 'local' o 'sftp'.")
