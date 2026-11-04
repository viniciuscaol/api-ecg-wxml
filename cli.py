"""Conversão local com o mesmo parser e renderizador da API."""
import argparse
from pathlib import Path
from app.parser import parse_wxml, WxmlError
from app.render import page_specs
from app.svg import continuous_spec
from app.main import convert_bytes

def main():
    p = argparse.ArgumentParser(description='Converte ECG WinCardio WXML')
    p.add_argument('input', type=Path)
    p.add_argument('output', type=Path)
    p.add_argument('--layout', choices=['reference', 'complete', 'continuous'], default='reference')
    p.add_argument('--record', type=int)
    p.add_argument('--offset-seconds', type=float, default=0)
    p.add_argument('--duration-seconds', type=float)
    p.add_argument('--dpi', type=int, default=200)
    p.add_argument('--grid', choices=['gray', 'red'], default='gray')
    p.add_argument('--rhythm', choices=['DI','DII','DIII','aVR','aVL','aVF','V1','V2','V3','V4','V5','V6'], default='DII')
    p.add_argument('--anonymize', action='store_true')
    args = p.parse_args()
    fmt = {'svg':'svg','pdf':'pdf','png':'png','jpg':'jpeg','jpeg':'jpeg','zip':'zip'}.get(args.output.suffix.lower()[1:])
    if not fmt:
        p.error('Saída deve ser .svg, .pdf, .png, .jpg ou .zip')
    try:
        with args.input.open('rb') as f:
            exam = parse_wxml(f.read(10*1024*1024+1))
        if args.layout == 'continuous':
            if fmt != 'svg':
                raise WxmlError('continuous exige saída SVG.')
            specs = [continuous_spec(exam, args.record, args.offset_seconds, args.duration_seconds)]
        else:
            if args.duration_seconds is not None:
                raise WxmlError('--duration-seconds exige --layout continuous.')
            specs = page_specs(exam, args.layout, args.record, args.offset_seconds)
        if fmt in ('png', 'jpeg') and len(specs) != 1:
            raise WxmlError('Use PDF ou ZIP para múltiplas páginas.')
        if fmt == 'zip' and len(specs)*(210/25.4*args.dpi)*(297/25.4*args.dpi)>60_000_000:
            raise WxmlError('ZIP excede orçamento de 60 megapixels; reduza DPI ou use PDF.')
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_bytes(convert_bytes(exam, specs, fmt, args.dpi, args.grid, args.rhythm, args.anonymize, args.layout))
    except (WxmlError, OSError) as e:
        p.error(str(e))
    print(f'Gerado: {args.output} ({len(specs)} página(s))')

if __name__ == '__main__':
    main()
