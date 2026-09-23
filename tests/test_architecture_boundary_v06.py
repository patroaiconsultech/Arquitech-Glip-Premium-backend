from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]

def test_no_efata_database_or_private_runtime_imports():
    source="\n".join(
        p.read_text(encoding="utf-8",errors="ignore")
        for p in (ROOT/"src/glip").rglob("*.py")
    )
    assert "orkio_v2." not in source
    assert "efata." not in source
    assert "EFATA_DATABASE_URL" not in source

def test_frontend_m2m_secret_not_part_of_backend_public_contract():
    env=(ROOT/".env.example").read_text()
    assert "VITE_" not in env
    assert "GLIP_ORKIO_M2M_TOKEN" in env
