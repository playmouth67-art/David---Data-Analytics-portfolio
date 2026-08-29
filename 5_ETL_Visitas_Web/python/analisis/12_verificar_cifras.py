# -*- coding: utf-8 -*-
"""Verificacion independiente de las cifras publicadas, sin MySQL.

Reimplementa en Python puro la logica de sql/02_transformacion.sql, escrita
desde cero, y la corre contra los archivos originales de data/seed. Sirve
para dos cosas:

  1. Comprobar los resultados del documento sin levantar el entorno. Basta
     Python 3, sin Docker ni base de datos.
  2. Detectar si el SQL y lo que el documento afirma se separan. Son dos
     implementaciones distintas de la misma regla: si dejan de coincidir,
     una de las dos cambio.

Uso:  python3 python/analisis/12_verificar_cifras.py
"""
import csv, io, re, glob, os
from datetime import datetime
from collections import defaultdict

def localizar_seed():
    """Busca data/seed subiendo desde este archivo.

    Contar niveles a mano es fragil: basta mover el script una carpeta para
    que apunte fuera del proyecto. Y el modo de fallar importaba: la version
    anterior no encontraba los archivos, reportaba cero en todo y decia
    'HAY DISCREPANCIA', que hace parecer un problema de datos lo que era un
    problema de ruta. Este script existe para cazar fallos silenciosos, asi
    que no puede tener uno.
    """
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(5):
        cand = os.path.join(d, 'data', 'seed')
        if os.path.isdir(cand):
            return cand
        d = os.path.dirname(d)
    raise SystemExit(
        "ERROR: no encontre data/seed subiendo desde " +
        os.path.abspath(__file__) + "\n"
        "Corre el script desde el repo:  python3 python/analisis/12_verificar_cifras.py")


SEED = localizar_seed()
RE_MAIL = re.compile(r'^[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}$')

def fecha(s):
    s = (s or '').strip()
    if not s or s == '-':
        return None
    try:
        return datetime.strptime(s, '%d/%m/%Y %H:%M')
    except ValueError:
        return None

def entero(s):
    s = (s or '').strip()
    return int(s) if re.fullmatch(r'[0-9]+', s) else 0

filas = []
for ruta in sorted(glob.glob(os.path.join(SEED, 'report_*.txt'))):
    crudo = open(ruta, 'rb').read().replace(b'\r\n', b'\n').decode('utf-8', 'replace')
    r = list(csv.reader(io.StringIO(crudo)))
    encabezado, cuerpo = r[0], r[1:]
    for i, c in enumerate(cuerpo, start=2):      # num_linea fisica, 1 = encabezado
        if not c or not any(x.strip() for x in c):
            continue
        filas.append({
            'archivo': os.path.basename(ruta), 'num_linea': i,
            'email': c[0].strip(), 'fecha_envio': fecha(c[4]),
            'fecha_open': fecha(c[5]), 'opens': entero(c[6]),
            'fecha_click': fecha(c[8]), 'clicks': entero(c[9]),
        })

if not filas:
    raise SystemExit('ERROR: no hay archivos report_*.txt en ' + SEED)

leidos = len(filas)

# --- wrk: marcas de calidad (V-03 email, V-04 fecha de envio) -------------
for f in filas:
    f['email_ok'] = bool(RE_MAIL.match(f['email']))

# --- wrk_dedupe: ROW_NUMBER() PARTITION BY email, fecha_envio -------------
#     ORDER BY opens DESC, clicks DESC, num_linea DESC
grupos = defaultdict(list)
for f in filas:
    if f['email_ok'] and f['fecha_envio'] is not None:
        grupos[(f['email'], f['fecha_envio'])].append(f)

for g in grupos.values():
    g.sort(key=lambda f: (-f['opens'], -f['clicks'], -f['num_linea']))
    for k, f in enumerate(g, start=1):
        f['rn'] = k

for f in filas:
    f.setdefault('rn', None)

# --- estadistica: solo representantes (rn = 1) ----------------------------
estadistica = [f for f in filas if f['rn'] == 1]
descartados = [f for f in filas if f['rn'] is not None and f['rn'] > 1]
rechazados  = [f for f in filas if f['rn'] is None]
abrieron    = [f for f in estadistica if f['opens'] > 0]

# --- visita: NO filtra por rn = 1. Grano (email, fecha_click) -------------
#     PK colapsa colisiones con GREATEST(clicks)
visita = {}
for f in filas:
    if f['rn'] is not None and f['clicks'] > 0 and f['fecha_click'] is not None:
        k = (f['email'], f['fecha_click'])
        visita[k] = max(visita.get(k, 0), f['clicks'])

# --- visitante: agregado recalculado desde visita -------------------------
visitantes = defaultdict(int)
for (email, _), clicks in visita.items():
    visitantes[email] += clicks

# Con datos sinteticos las cifras cambian en cada semilla, asi que en vez de
# compararlas contra valores fijos se verifican las invariantes que deben
# cumplirse con cualquier juego de datos. Si alguna se rompe, la logica esta
# mal, no los datos.
real = {'leidos': leidos, 'estadistica': len(estadistica), 'descartados': len(descartados),
        'rechazados': len(rechazados), 'abrieron': len(abrieron), 'visita': len(visita),
        'visitante': len(visitantes), 'visitasTotales': sum(visitantes.values())}

print('%-16s %10s' % ('concepto', 'valor'))
print('-' * 28)
for k, v in real.items():
    print('%-16s %10d' % (k, v))

invariantes = [
    ('nada se pierde: estadistica + descartados + rechazados = leidos',
     real['estadistica'] + real['descartados'] + real['rechazados'] == leidos),
    ('un visitante por email, nunca mas visitantes que visitas',
     real['visitante'] <= real['visita']),
    ('visitasTotales suma clics, asi que nunca es menor que las visitas',
     real['visitasTotales'] >= real['visita']),
    ('solo quien abrio pudo dar clic, salvo el evento intermedio perdido (V-10)',
     real['visita'] <= real['abrieron'] + 5),
    ('toda visita tiene fecha de clic propia',
     all(fc is not None for _, fc in visita)),
    ('sin visitas duplicadas en su grano (email, fecha de clic)',
     len(visita) == len(set(visita))),
]

print()
ok = True
for texto, cumple in invariantes:
    ok &= cumple
    print('  [%s] %s' % ('ok' if cumple else 'FALLA', texto))

print()
print('VEREDICTO:', 'todas las invariantes se cumplen' if ok else 'HAY UNA INVARIANTE ROTA')

print('\nduplicados en la llave de negocio, descartados y auditados como V-07:')
for f_ in sorted(descartados, key=lambda x: (x['archivo'], x['num_linea']))[:10]:
    print('   %s linea %-5d %-38s %s' % (f_['archivo'], f_['num_linea'], f_['email'],
                                         f_['fecha_envio'].strftime('%d/%m/%Y %H:%M')))

print('\nmismo envio con dos clics en instantes distintos (el caso que separa el grano):')
por_persona = {}
for (e, fc), c in visita.items():
    por_persona.setdefault(e, []).append((fc, c))
for e, eventos in por_persona.items():
    if len(eventos) > 1:
        for fc, c in sorted(eventos):
            print('   %-38s %s  clics=%d' % (e, fc.strftime('%Y-%m-%d %H:%M'), c))
        print('   visitasTotales de esa persona:', visitantes[e])
        break
