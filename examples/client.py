"""Cliente multipart sem dependências externas; mantém dados fora dos logs."""
import argparse
import os
from pathlib import Path
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

def main():
    p = argparse.ArgumentParser()
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--url', default='http://localhost:8000')
    p.add_argument('--complete', action='store_true')
    p.add_argument('--continuous', action='store_true', help='12 canais inteiros em SVG')
    args = p.parse_args()
    format = {'jpg': 'jpeg'}.get(args.output.suffix.lower()[1:], args.output.suffix.lower()[1:])
    if format not in ('svg', 'pdf', 'png', 'jpeg', 'zip'):
        p.error('Saída esperada: .svg, .pdf, .png, .jpg ou .zip')
    if args.continuous and (format != 'svg' or args.complete):
        p.error('--continuous exige SVG e não pode ser usado com --complete')
    boundary = 'ecg-' + secrets.token_hex(16)
    # Filename genérico evita problemas com aspas/newlines e informações do paciente.
    prefix = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="exam.wxml"\r\n'
              'Content-Type: application/xml\r\n\r\n').encode()
    data = prefix + args.input.read_bytes() + f'\r\n--{boundary}--\r\n'.encode()
    headers = {'Content-Type': f'multipart/form-data; boundary={boundary}'}
    if os.getenv('ECG_API_KEY'):
        headers['X-API-Key'] = os.environ['ECG_API_KEY']
    query = urlencode({'format': format, 'layout': 'continuous' if args.continuous else ('complete' if args.complete else 'reference')})
    req = Request(args.url.rstrip('/')+'/convert?'+query, data=data, headers=headers, method='POST')
    try:
        with urlopen(req, timeout=120) as response:
            output = response.read()
    except HTTPError as e:
        p.error(f'HTTP {e.code}: {e.read().decode("utf-8", errors="replace")}')
    except URLError as e:
        p.error(f'Não foi possível conectar à API: {e.reason}')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(output)
    print(f'Gerado: {args.output}')

if __name__ == '__main__':
    main()
