import pytest

def test_import():
    import snapblue.blueUtils
    import snapblue.blueIO
    import snapblue.SNAPStateMgr

def test_import_fail():
    with pytest.raises(ImportError):
        import snapblue.garbage as foo

