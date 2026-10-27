from jarvis.core import charts, config, expenses as ex, fastpath, llm


def test_tables_from_csv_html_json_and_columns(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    monkeypatch.setattr(llm, "chat", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no LLM")))
    csv = b"S.N,District,Population 2021,Area km2\n1,Kathmandu,\"2,041,587\",395\n2,Lalitpur,551667,385\n3,Kaski,600051,2017\n"
    h, r = charts.parse_bytes(csv, "pop.csv")
    assert charts.pick(h, r, "population by district") == (1, [2])
    paths, what = charts.from_table(h, r, "population by district", "census")
    assert [p.name.split("-")[-1] for p in paths] == ["bar.png", "pie.png"] and "Population 2021 by District" in what
    html = (b"<table><tr><td>menu</td></tr></table><table><tr><th>Year</th><th>GDP growth</th></tr>"
            b"<tr><td>2019</td><td>6.7</td></tr><tr><td>2020</td><td>-2.4</td></tr><tr><td>2021</td><td>4.8%</td></tr></table>")
    h, r = charts.parse_bytes(html, "", "text/html")
    paths, _ = charts.from_table(h, r, "", "gov")
    assert [p.name.split("-")[-1] for p in paths] == ["line.png", "bar.png"]  # years: line first, no pie (negative)
    h, r = charts.parse_bytes(b'{"data": [{"name": "a", "v": 1}, {"name": "b", "v": 3}]}', "x.json")
    assert h == ["name", "v"] and r == [["a", 1], ["b", 3]]
    assert charts.from_table([], [], "", "x")[0] == []


def test_money_charts_and_routes(monkeypatch, tmp_path):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    assert charts.chart_money("month")[0] == []
    ex.add("spent 500 on momo")
    ex.add("spent 1200 on a shirt")
    paths, what = charts.chart_money("month")
    assert len(paths) >= 2 and what == "your spending this month" and all(p.stat().st_size > 1000 for p in paths)
    m = fastpath.match
    assert m("pie chart of my spending this week").args == {"source": "money", "kind": "pie", "period": "week"}
    i = m("draw a graph of population by district from https://example.com/data.csv")
    assert i.tool == "make_chart" and i.args["source"] == "https://example.com/data.csv"
    assert m("what is a pie chart") is None
