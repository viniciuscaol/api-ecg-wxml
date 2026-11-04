from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree as ET

import pytest
from fastapi.testclient import TestClient
from app.main import app
from app.parser import WxmlError, parse_sample_rate, parse_sensitivity, parse_wxml

DATA = Path(__file__).resolve().parents[1].joinpath('examples/synthetic.wxml').read_bytes()


def document():
    root = ET.fromstring(DATA)
    return root, root.find('Exame/Registros')


@pytest.mark.parametrize('value', ['600', '600Hz', '600 Hz', '600,0 Hz',
    '600.0 amostras por segundo', '600 amostras/s', '600 samples/s', '600 SPS'])
def test_sample_rate_explicit_variants(value):
    assert parse_sample_rate(value) == 600


@pytest.mark.parametrize('value', ['200/1mV', '200 / 1 mV', '200/mV',
    '200 unidades/mV', '200 counts/mV', '200/1000uV', '5uV', '5 µV/unidade',
    '5 μV/amostra', '5 microvolts', '0,005mV/amostra', '0.005 mV/count'])
def test_sensitivity_equivalent_units(value):
    assert parse_sensitivity(value) == pytest.approx(200)


@pytest.mark.parametrize('value', ['', '200', '0/1mV', '200/0mV', '0uV',
    'NaN', '-5uV', '5V', '200/mV texto', '5uV/mm'])
def test_missing_ambiguous_or_invalid_sensitivity_is_rejected(value):
    with pytest.raises(WxmlError, match='Sensibilidade'):
        parse_sensitivity(value)


@pytest.mark.parametrize('value', ['', 'NaN', '0Hz', '-600', '600kHz', '600foo'])
def test_invalid_sample_rate_is_rejected(value):
    with pytest.raises(WxmlError, match='TaxaAmostragem'):
        parse_sample_rate(value)


@pytest.mark.parametrize('location', ['group_elements', 'record_attributes', 'record_elements'])
def test_metadata_locations_preserve_all_samples_and_calibration(location):
    root, group = document()
    values = {name: group.attrib.pop(name) for name in ('TaxaAmostragem', 'Sensibilidade')}
    target = group if location == 'group_elements' else group.find('Registro')
    for name, value in values.items():
        if location == 'record_attributes':
            target.set(name, value)
        else:
            ET.SubElement(target, name).text = value
    actual = parse_wxml(ET.tostring(root))
    original = parse_wxml(DATA)
    assert actual.sample_rate == original.sample_rate
    assert actual.units_per_mv == original.units_per_mv
    assert actual.records == original.records


@pytest.mark.parametrize('field', ['TaxaAmostragem', 'Sensibilidade'])
def test_absent_metadata_reports_specific_field(field):
    root, group = document()
    del group.attrib[field]
    with pytest.raises(WxmlError, match=field + ' ausente'):
        parse_wxml(ET.tostring(root))


@pytest.mark.parametrize('field,value', [('TaxaAmostragem', '500Hz'), ('Sensibilidade', '10uV')])
def test_conflicting_group_and_record_scales_are_rejected(field, value):
    root, group = document()
    group.find('Registro').set(field, value)
    with pytest.raises(WxmlError, match=field + ' conflitante'):
        parse_wxml(ET.tostring(root))


def test_multiple_records_can_declare_equivalent_units():
    root, group = document()
    second = deepcopy(group.find('Registro'))
    second.set('Numero', '99')
    second.set('TaxaAmostragem', '600Hz')
    second.set('Sensibilidade', '5uV/unidade')
    group.append(second)
    group.set('Quantidade', '2')
    exam = parse_wxml(ET.tostring(root))
    assert len(exam.records) == 2
    assert exam.units_per_mv == 200


def test_each_record_requires_scale_if_group_has_none():
    root, group = document()
    second = deepcopy(group.find('Registro'))
    group.find('Registro').set('TaxaAmostragem', group.attrib.pop('TaxaAmostragem'))
    group.append(second)
    group.set('Quantidade', '2')
    with pytest.raises(WxmlError, match='TaxaAmostragem ausente.*registro 2'):
        parse_wxml(ET.tostring(root))


def test_variant_xml_converts_and_first_record_is_selectable(monkeypatch):
    monkeypatch.delenv('ECG_API_KEY', raising=False)
    root, group = document()
    group.set('TaxaAmostragem', '600 Hz')
    group.set('Sensibilidade', '5 µV/amostra')
    second = deepcopy(group.find('Registro'))
    second.set('Numero', '99')
    group.append(second)
    group.set('Quantidade', '2')
    with TestClient(app) as client:
        response = client.post('/convert?format=svg&layout=continuous&record=1',
            files={'file': ('synthetic.wxml', ET.tostring(root))})
        assert response.status_code == 200
        assert response.headers['X-ECG-Pages'] == '1'
        svg = ET.fromstring(response.content)
        traces = svg.findall('.//{http://www.w3.org/2000/svg}path[@class="ecg-trace"]')
        assert len(traces) == 12
        assert all(path.get('data-sample-count') == '4800' for path in traces)
