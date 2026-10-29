"""Costruisce index.html (app + motore in un file solo) e sw.js (con una versione che cambia a ogni modifica)."""
import hashlib, os
HERE = os.path.dirname(os.path.abspath(__file__))
a = open(os.path.join(HERE, 'src/app_src.html'), encoding='utf-8').read()
m = open(os.path.join(HERE, 'src/motore.js'), encoding='utf-8').read()
assert '/*@@MOTORE@@*/' in a
html = a.replace('/*@@MOTORE@@*/', m)
open(os.path.join(HERE, 'index.html'), 'w', encoding='utf-8').write(html)
ver = hashlib.sha1(html.encode('utf-8')).hexdigest()[:10]
sw = open(os.path.join(HERE, 'src/sw_src.js'), encoding='utf-8').read().replace('@@VERSIONE@@', ver)
open(os.path.join(HERE, 'sw.js'), 'w', encoding='utf-8').write(sw)
print('index.html', len(html), 'sw', ver)
