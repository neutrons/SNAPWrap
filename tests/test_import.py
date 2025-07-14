import pytest

def test_import():
    import snapwrap.utils
    import snapwrap.io
    import snapwrap.snapStateMgr

def test_import_fail():
    with pytest.raises(ImportError):
        import snapwrap.garbage as foo

