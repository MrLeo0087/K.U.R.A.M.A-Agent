from jarvis.core import config, diagram, fastpath

README = """# My App
Intro text.
## Install
- pip install -r requirements.txt
- copy .env.example to .env: it holds keys
```
code block - ignored
```
## Usage
1. Run the server
2. Open the page
### Advanced
- Plugins (optional)
| table | ignored |
"""


def test_readme_tree_and_no_readme(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path / "out")
    labels, edges = diagram.readme_tree(README, "x")
    assert labels[0] == "My App" and "Install" in labels and "Advanced" in labels and "Plugins" in labels
    assert "copy .env.example to .env" in labels and not any("ignored" in x for x in labels)
    i = {v: k for k, v in enumerate(labels)}
    assert (i["Usage"], i["Advanced"]) in edges and (i["Install"], i["pip install -r requirements.txt"]) in edges
    proj = tmp_path / "app"
    proj.mkdir()
    assert "has no README" in diagram.project(proj)
    (proj / "README.md").write_text(README)
    assert diagram.project(proj).startswith("I drew app from its README")
    assert len(list((tmp_path / "out" / "diagrams").glob("*.png"))) == 1


def test_flow_and_call_graph(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "OUTPUTS_DIR", tmp_path)
    assert diagram.split_steps("open the app, then log in -> check the password and finally log out") == \
        ["Open the app", "Log in", "Check the password", "Log out"]
    assert "4 steps" in diagram.flow_from_text("open the app, then log in -> check the password and finally log out")
    src = "def a():\n    b()\n\ndef b():\n    c()\n\ndef c():\n    pass\n\ndef lone():\n    pass\n\nif __name__ == '__main__':\n    a()\n"
    labels, edges = diagram.call_graph(src, "m.py")
    assert labels == ["m.py", "a()", "b()", "c()", "lone()"] and set(edges) == {(0, 1), (1, 2), (2, 3), (0, 4)}
    f = tmp_path / "m.py"
    f.write_text(src)
    assert "4 functions" in diagram.code(f)


def test_routes():
    m = fastpath.match
    assert m("make a diagram of this project").args == {"kind": "project", "target": ""}
    assert m("flowchart: login, check password, open the dashboard").args["kind"] == "flow"
    assert m("make a call graph of utils.py").args == {"kind": "code", "target": "utils.py"}
    assert m("what is a flowchart") is None
