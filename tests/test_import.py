import pytest

def test_import():
    import snapwrap.utils
    import snapwrap.io
    import snapwrap.snapStateMgr
    import snapwrap.wrapConfig
    import snapwrap.SEEMeta

def test_import_fail():
    with pytest.raises(ImportError):
        import snapwrap.garbage as foo

