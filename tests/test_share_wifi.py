from jarvis.core import fastpath
from jarvis.tools.general.share_wifi import wifi_qr_payload


def test_payload_escaping_and_routing():
    assert wifi_qr_payload("My;Net", "wpa-psk", 'p:a"ss') == 'WIFI:T:WPA;S:My\;Net;P:p\\:a\\"ss;;'
    assert wifi_qr_payload("Open", "", "") == "WIFI:T:nopass;S:Open;;"
    assert fastpath.match("share my wifi password").tool == "share_wifi"
    assert fastpath.match("share this file over wifi").tool == "wifi_share"
