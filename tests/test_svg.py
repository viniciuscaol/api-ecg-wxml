from io import BytesIO
import math
from pathlib import Path
import re
from xml.etree import ElementTree as ET
import pytest
from fastapi.testclient import TestClient
import app.main as api
from app.parser import parse_wxml, LEADS
from app.svg import NS, continuous_spec
from app.render import PAGE_HEIGHT, TOP, HEIGHT
from reportlab.lib.units import mm

DATA = Path(__file__).resolve().parents[1].joinpath('examples/synthetic.wxml').read_bytes()
SVG = {'s': NS}


def get_svg(client, query='', data=DATA):
    return client.post('/convert?format=svg'+query, files={'file': ('exam.wxml', data, 'application/xml')})


@pytest.fixture
def client(monkeypatch):
    monkeypatch.delenv('ECG_API_KEY', raising=False)
    with TestClient(api.app) as value:
        yield value


def paths(data):
    return ET.fromstring(data).findall('.//s:path[@class="ecg-trace"]', SVG)


def points(node):
    return [(float(x),float(y)) for x,y in re.findall(r'[ML](-?[\d.]+) (-?[\d.]+)', node.get('d'))]


def test_svg_is_native_without_pdf_or_bitmaps(client, monkeypatch):
    def prohibited(*args, **kwargs):
        raise AssertionError('SVG não deve passar por PDF nem por rasterização')
    monkeypatch.setattr(api, 'render_pdf', prohibited)
    monkeypatch.setattr(api, 'raster_pages', prohibited)
    response = get_svg(client)
    assert response.status_code == 200
    assert response.headers['content-type'].startswith('image/svg+xml')
    assert response.headers['content-disposition'].startswith('inline')
    assert response.headers['cache-control'] == 'no-store'
    assert 'sandbox' in response.headers['content-security-policy']
    root = ET.fromstring(response.content)
    assert root.tag == '{'+NS+'}svg'
    assert root.get('data-pages') == '1'
    assert len(paths(response.content)) == 13
    assert not root.findall('.//s:image', SVG)
    assert not root.findall('.//s:script', SVG)
    assert not root.findall('.//s:foreignObject', SVG)
    assert b'base64' not in response.content
    assert b'PDF-' not in response.content


def test_continuous_preserves_every_sample_and_physical_scale(client):
    response = get_svg(client, '&layout=continuous')
    assert response.status_code == 200
    exam = parse_wxml(DATA)
    leads = paths(response.content)
    assert len(leads) == 12
    assert [p.get('data-lead') for p in leads] == list(LEADS)
    for i, lead in enumerate(leads):
        xy=points(lead)
        assert len(xy) == 4800
        assert lead.get('data-sample-count') == '4800'
        values=exam.records[0].leads[lead.get('data-lead')].samples
        for n,(x,y) in enumerate(xy):
            assert x == pytest.approx((15+n/600*25)*mm, abs=.000001)
            assert y == pytest.approx((PAGE_HEIGHT-(TOP+i*(HEIGHT+1)+HEIGHT/2)+values[n]/200*10)*mm, abs=.000001)
        assert xy[600][0]-xy[0][0] == pytest.approx(25*mm, abs=.000002)


def test_svg_complete_has_all_samples_without_repeated_ids(client):
    response = get_svg(client, '&layout=complete')
    assert response.status_code == 200
    root=ET.fromstring(response.content)
    assert root.get('data-pages') == '4'
    ids=[node.get('id') for node in root.iter() if node.get('id')]
    assert len(ids) == len(set(ids))
    for name in LEADS:
        lead_paths=[p for p in paths(response.content) if p.get('data-lead')==name]
        # DII possui também a faixa longa de cada página.
        if name=='DII':lead_paths=lead_paths[::2]
        assert sum(int(p.get('data-sample-count')) for p in lead_paths)==4800


def test_svg_window_bounds_and_metadata(client):
    response = get_svg(client, '&layout=continuous&offset_seconds=2&duration_seconds=1.5')
    assert response.status_code == 200
    for lead in paths(response.content):
        assert lead.get('data-start-sample') == '1200'
        assert lead.get('data-sample-count') == '900'
        assert len(points(lead)) == 900


@pytest.mark.parametrize('query', ['&layout=continuous&record=2', '&layout=continuous&duration_seconds=0',
    '&layout=continuous&duration_seconds=nan', '&layout=continuous&offset_seconds=8',
    '&duration_seconds=1'])
def test_svg_invalid_options(client, query):
    assert get_svg(client, query).status_code == 422


def test_continuous_not_supported_for_pdf(client):
    assert client.post('/convert?format=pdf&layout=continuous', files={'file':('exam.wxml',DATA)}).status_code==422


def test_svg_escapes_patient_text(client):
    dangerous=DATA.replace('PACIENTE TESTE SINTÉTICO'.encode(), b'&lt;script&gt;alert(1)&lt;/script&gt; &amp; Nome')
    response=get_svg(client, '&layout=continuous', dangerous)
    assert response.status_code==200
    root=ET.fromstring(response.content)
    assert not root.findall('.//s:script',SVG)
    assert '&lt;script&gt;' in response.text
    assert 'alert(1)' in ''.join(root.itertext())
    anonymous=get_svg(client, '&layout=continuous&anonymize=true', dangerous)
    assert 'alert(1)' not in anonymous.text


def test_continuous_limits_large_windows():
    slow=DATA.replace(b'600 amostras por segundo',b'1 amostras por segundo')
    exam=parse_wxml(slow)
    from app.parser import WxmlError
    with pytest.raises(WxmlError):continuous_spec(exam)
    assert continuous_spec(exam,duration_seconds=10).short_samples==10


def test_component_and_openapi(client):
    response=client.get('/assets/ecg-viewer.js')
    assert response.status_code==200
    assert response.headers['content-type'].startswith('text/javascript')
    html=client.get('/').text
    assert 'ecg-viewer' in html
    assert 'value="svg"' in html
    spec=client.get('/openapi.json').json()
    assert 'image/svg+xml' in spec['paths']['/convert']['post']['responses']['200']['content']
