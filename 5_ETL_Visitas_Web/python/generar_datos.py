# -*- coding: utf-8 -*-
"""Genera archivos de origen sintéticos con la misma forma que los reales.

Este proyecto nació de un juego de datos que no puedo publicar: son correos
personales de gente real, con IP, navegador y el registro de cuándo abrió y
cuándo dio clic. Nada de eso va a un repositorio.

Lo que sí se puede reproducir es lo que hacía difícil el problema. Este
generador escribe archivos con el mismo layout de 15 columnas y con las
mismas trampas metidas a propósito, para que el ETL se pueda ejercitar de
punta a punta:

  - Saltos de línea CRLF. Combinados con el punto siguiente, son los que
    hacían que MySQL perdiera filas en silencio.
  - Campos entrecomillados con listas de varias IP separadas por coma. El
    retorno de carro queda después de la comilla de cierre y el motor pierde
    el rastro del delimitador.
  - Duplicados en la llave de negocio (email + fecha de envío) que NO son
    filas idénticas: difieren en aperturas, clics y metadatos. Sirven para
    ejercitar el ranking y la auditoría V-07.
  - El mismo envío repartido en dos archivos con fechas de clic distintas,
    separadas por un minuto. Es el caso que obliga a separar el grano de la
    visita del grano del envío.
  - Fechas de apertura o clic anteriores al envío (V-08) y clics sin
    apertura registrada (V-10).
  - Ausencia de dato en sus tres formas: valor, guion y vacío.
  - Una columna vacía al 100% cuyo encabezado cambia entre archivos (V-09).

Uso:
    python3 python/generar_datos.py                # 3 archivos en data/seed
    python3 python/generar_datos.py --semilla 7    # otra muestra reproducible
"""
import argparse
import os
import random
from datetime import datetime, timedelta

RAIZ = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SALIDA = os.path.join(RAIZ, 'data', 'seed')

COLUMNAS = ['email', '{jyv}', 'Badmail', 'Baja', 'Fecha envio', 'Fecha open',
            'Opens', 'Opens virales', 'Fecha click', 'Clicks', 'Clicks virales',
            'Links', 'IPs', 'Navegadores', 'Plataformas']

# El encabezado de la segunda columna cambia entre archivos. En el juego real
# venia como jk, jyv y fgh. La columna llega vacia al 100%, asi que el proceso
# la conserva por posicion y no por nombre.
ENCABEZADO_2 = ['jk', 'jyv', 'fgh']

NOMBRES = ['ana', 'luis', 'carmen', 'jorge', 'sofia', 'miguel', 'paola',
           'ricardo', 'elena', 'fernando', 'lucia', 'andres', 'marina',
           'diego', 'valeria', 'tomas', 'irene', 'pablo', 'nuria', 'hector']
APELLIDOS = ['ramirez', 'ortega', 'delgado', 'navarro', 'campos', 'ibarra',
             'quiroz', 'salazar', 'mendoza', 'vargas', 'pineda', 'roldan']
DOMINIOS = ['ejemplo.com', 'correo-demo.net', 'demo-mail.org']
NAVEGADORES = ['Chrome', 'Firefox', 'Safari', 'Edge', 'Opera']
PLATAFORMAS = ['Windows', 'Android', 'iOS', 'macOS', 'Linux']
BASE = datetime(2013, 2, 8, 18, 30)


def ip(rnd):
    return '%d.%d.%d.%d' % (rnd.randint(10, 200), rnd.randint(0, 255),
                            rnd.randint(0, 255), rnd.randint(1, 254))


def campo_ips(rnd):
    """Una o varias IP. Cuando son varias van entrecomilladas y con coma dentro.

    Este es el campo que rompia la carga: la comilla de cierre seguida del
    retorno de carro hacia que el motor perdiera el delimitador.
    """
    n = rnd.choices([1, 2, 3], weights=[80, 15, 5])[0]
    valor = ', '.join(ip(rnd) for _ in range(n))
    return '"%s"' % valor if n > 1 else valor


def vacio(rnd):
    """Ausencia de dato en sus tres formas."""
    return rnd.choice(['', '-'])


def fecha(d):
    return d.strftime('%d/%m/%Y %H:%M') if d else ''


def registro(rnd, email, envio, forzar=None):
    forzar = forzar or {}
    abrio = rnd.random() < 0.19
    opens = rnd.randint(1, 4) if abrio else 0
    f_open = envio + timedelta(minutes=rnd.randint(1, 900)) if abrio else None

    hizo_clic = abrio and rnd.random() < 0.12
    clicks = rnd.randint(1, 3) if hizo_clic else 0
    f_click = f_open + timedelta(minutes=rnd.randint(0, 120)) if hizo_clic else None

    # V-08: interaccion anterior al envio. En el juego real era un patron
    # consistente en los tres archivos, probablemente un desfase de zona
    # horaria en el origen.
    if abrio and rnd.random() < 0.12:
        f_open = envio - timedelta(hours=rnd.randint(1, 7))
        if f_click:
            f_click = f_open + timedelta(minutes=rnd.randint(0, 30))

    # V-10: clics sin apertura registrada. Se pierde el evento intermedio.
    if rnd.random() < 0.002:
        clicks, f_click = 1, envio + timedelta(minutes=30)
        opens, f_open = 0, None

    fila = {
        'email': email, 'col2': '', 'badmail': rnd.choice(['NO'] * 24 + ['SI']),
        'baja': rnd.choice(['NO'] * 30 + ['SI']),
        'envio': fecha(envio), 'f_open': fecha(f_open),
        'opens': str(opens), 'opens_virales': str(rnd.randint(0, 1) if opens else 0),
        'f_click': fecha(f_click), 'clicks': str(clicks),
        'clicks_virales': str(rnd.randint(0, 1) if clicks else 0),
        'links': str(rnd.randint(1, 6)) if clicks else vacio(rnd),
        'ips': campo_ips(rnd) if opens else vacio(rnd),
        'navegadores': rnd.choice(NAVEGADORES) if opens else vacio(rnd),
        'plataformas': rnd.choice(PLATAFORMAS) if opens else vacio(rnd),
    }
    fila.update(forzar)
    return fila


def a_linea(f):
    return ','.join([
        f['email'], f['col2'], f['badmail'], f['baja'], f['envio'], f['f_open'],
        f['opens'], f['opens_virales'], f['f_click'], f['clicks'],
        f['clicks_virales'], f['links'], f['ips'], f['navegadores'],
        f['plataformas'],
    ])


def generar(semilla=42, por_archivo=(503, 503, 995)):
    rnd = random.Random(semilla)
    os.makedirs(SALIDA, exist_ok=True)

    # El sufijo numerico garantiza unicidad. Sin el, el catalogo de nombres y
    # apellidos se agota (20 x 12 x 3 = 720 combinaciones) y el muestreo por
    # rechazo nunca termina de juntar los 2,001 correos.
    universo = []
    for i in range(sum(por_archivo)):
        universo.append('%s.%s%d@%s' % (rnd.choice(NOMBRES), rnd.choice(APELLIDOS),
                                        i, rnd.choice(DOMINIOS)))
    rnd.shuffle(universo)

    # Persona que da clic dos veces sobre el mismo envio, en dos archivos
    # distintos y con un minuto de diferencia. Es el caso que obliga a que
    # la tabla de visitas no herede el ranking del envio.
    doble = universo[0]
    archivos = []
    cursor = 0

    for i, n in enumerate(por_archivo):
        filas = []
        for email in universo[cursor:cursor + n]:
            filas.append(registro(rnd, email, BASE))
        cursor += n

        # Duplicado en la llave de negocio dentro del mismo archivo: mismo
        # email y misma fecha de envio, pero materialmente distinto.
        if i < 2:
            gemelo = registro(rnd, filas[rnd.randrange(len(filas))]['email'], BASE)
            gemelo['opens'] = str(int(gemelo['opens'] or 0) + 2)
            filas.insert(rnd.randrange(len(filas)), gemelo)

        # El mismo envio en dos archivos, con clics separados por un minuto.
        if i in (0, 1):
            clic = BASE.replace(hour=11, minute=42 + i)
            filas.append(registro(rnd, doble, BASE, forzar={
                'f_open': fecha(clic - timedelta(minutes=5)),
                'opens': '1', 'f_click': fecha(clic),
                'clicks': '2' if i == 0 else '1', 'links': '1',
            }))

        ruta = os.path.join(SALIDA, 'report_%d.txt' % (7 + i))
        cab = list(COLUMNAS)
        cab[1] = ENCABEZADO_2[i % len(ENCABEZADO_2)]
        cuerpo = [','.join(cab)] + [a_linea(f) for f in filas]
        # CRLF a proposito: es la mitad del bug que este proyecto documenta.
        with open(ruta, 'wb') as fh:
            fh.write(('\r\n'.join(cuerpo) + '\r\n').encode('utf-8'))
        archivos.append((ruta, len(filas)))

    return archivos


if __name__ == '__main__':
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--semilla', type=int, default=42,
                    help='semilla para que la muestra sea reproducible')
    args = ap.parse_args()

    print('Generando archivos sintéticos en data/seed ...')
    total = 0
    for ruta, n in generar(args.semilla):
        print('   %-16s %4d registros' % (os.path.basename(ruta), n))
        total += n
    print('   %-16s %4d registros' % ('total', total))
    print('\nNinguno de estos datos es real. Los archivos llevan CRLF, campos')
    print('entrecomillados con varias IP, duplicados en la llave de negocio y')
    print('el caso del mismo envío con dos clics en archivos distintos.')
    print('\nSiguiente paso:  ./restaurar.sh  &&  python3 python/etl_visitas.py')
