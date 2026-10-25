from jarvis.core import contacts, fastpath


def test_sheet_add_find_update_delete(tmp_path, monkeypatch):
    monkeypatch.setattr(contacts.config, "CONTACTS_FILE", str(tmp_path / "c.xlsx"))
    assert "Saved Ram Bahadur" in contacts.add("ram bahadur", "98-0000-0001")
    assert "already saved" in contacts.add("Ram Bahadur", "9800000001")
    contacts.add("Sita Sharma", "+977 9811111111", "college")
    assert "9800000001" in contacts.find("ram")
    assert "Sita Sharma: +9779811111111 (college)" == contacts.find("sitta sharma")  # typo tolerated
    assert "Sita" in contacts.find("98111")  # by part of the number
    assert "No contact" in contacts.find("nobody")
    assert "Updated Ram Bahadur" in contacts.update("ram", "9822222222")
    from jarvis.core import safety
    monkeypatch.setattr(safety, "ask", lambda p: True)
    assert "Deleted Sita Sharma" in contacts.delete("sita")
    assert contacts.list_all().startswith("1 contacts")
    from openpyxl import load_workbook
    ws = load_workbook(tmp_path / "c.xlsx").active
    assert [c.value for c in ws[1]] == contacts.HEAD and ws["B2"].value == "9822222222"


def test_intents():
    assert fastpath.match("save Ram's number 9800000000").args["action"] == "add"
    assert fastpath.match("what is Ram's number").args == {"action": "find", "name": "Ram"}
    assert fastpath.match("phone number of Hari").args["name"] == "Hari"
    assert fastpath.match("what is the number of planets") is None
    assert fastpath.match("what is my roll number") is None
