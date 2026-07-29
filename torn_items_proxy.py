import json
import os
import re
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import requests

# Définition dynamique du dossier racine du projet
ROOT = Path(__file__).parent.resolve()

TORN_API_URL = 'https://api.torn.com/torn/?selections=items&key=b9nBVUJ2Dv0XJihv'
TORNSTATS_URL = 'https://www.tornstats.com/items'
CACHE = None
CACHE_TIME = None
CACHE_TTL = 30


def clean_number(value):
    if value is None:
        return 0
    text = str(value).strip()
    text = text.replace(',', '').replace('$', '')
    text = re.sub(r'<[^>]+>', '', text)
    text = text.split()[0] if text else '0'
    try:
        return int(float(text))
    except ValueError:
        return 0


def parse_tornstats_items(html):
    items = []
    rows = re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S)
    for row in rows:
        cells = re.findall(r'<td[^>]*>(.*?)</td>', row, re.S)
        if len(cells) < 7:
            continue
        name_html = re.sub(r'<[^>]+>', '', cells[1]).strip()
        m = re.search(r'\[(\d+)\]\s*$', name_html)
        if not m:
            continue
        item_id = int(m.group(1))
        name = re.sub(r'\s*\[\d+\]\s*$', '', name_html).strip()
        image_match = re.search(r'https?://[^"\']+', cells[0])
        image = image_match.group(0) if image_match else ''
        entry = {
            'id': item_id,
            'name': name,
            'type': re.sub(r'<[^>]+>', '', cells[3]).strip(),
            'buy_price': clean_number(cells[4]),
            'sell_price': clean_number(cells[5]),
            'market_value': clean_number(cells[6]),
            'image': image,
        }
        items.append(entry)
    return items


def load_items():
    global CACHE, CACHE_TIME
    now = time.time()
    if CACHE and CACHE_TIME and (now - CACHE_TIME) < CACHE_TTL:
        return CACHE

    torn_response = requests.get(TORN_API_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
    torn_response.raise_for_status()
    torn_data = torn_response.json().get('items', {})

    stats_response = requests.get(TORNSTATS_URL, headers={'User-Agent': 'Mozilla/5.0'}, timeout=25)
    stats_response.raise_for_status()
    stats_items = parse_tornstats_items(stats_response.text)

    merged = []
    for entry in stats_items:
        api_item = torn_data.get(str(entry['id']), {}) or {}
        merged.append({
            'id': entry['id'],
            'name': entry['name'] or api_item.get('name', ''),
            'type': (api_item.get('type') or entry.get('type') or 'Item').strip(),
            'buy_price': entry.get('buy_price') or int(api_item.get('buy_price') or 0),
            'sell_price': entry.get('sell_price') or int(api_item.get('sell_price') or 0),
            'market_value': entry.get('market_value') or int(api_item.get('market_value') or 0),
            'image': api_item.get('image') or entry.get('image') or '',
        })

    CACHE = {'items': merged}
    CACHE_TIME = now
    return CACHE


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        parsed = urlparse(self.path)
        
        # Route pour l'API JSON
        if parsed.path == '/api/items-data':
            try:
                data = load_items()
                payload = json.dumps(data).encode('utf-8')
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Cache-Control', 'no-store')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except Exception as exc:
                payload = json.dumps({'error': str(exc)}).encode('utf-8')
                self.send_response(500)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.send_header('Content-Length', str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            return

        # Route pour les fichiers statiques (HTML, JS, CSS, etc.)
        if parsed.path == '/' or parsed.path == '':
            target = ROOT / 'torn_buy_list.html'
        else:
            target = ROOT / parsed.path.lstrip('/')

        if target.exists() and target.is_file():
            self.send_response(200)
            if target.suffix == '.html':
                self.send_header('Content-Type', 'text/html; charset=utf-8')
            elif target.suffix == '.js':
                self.send_header('Content-Type', 'application/javascript; charset=utf-8')
            elif target.suffix == '.css':
                self.send_header('Content-Type', 'text/css; charset=utf-8')
            else:
                self.send_header('Content-Type', 'application/octet-stream')

            self.send_header('Content-Length', str(target.stat().st_size))
            self.end_headers()

            with open(target, 'rb') as f:
                self.wfile.write(f.read())
        else:
            self.send_error(404, "File Not Found")

    def log_message(self, format, *args):
        return


def main():
    port = int(os.environ.get('PORT', 8000))
    server = ThreadingHTTPServer(('0.0.0.0', port), Handler)
    print(f'Serving on http://0.0.0.0:{port}')
    server.serve_forever()


if __name__ == '__main__':
    main()
