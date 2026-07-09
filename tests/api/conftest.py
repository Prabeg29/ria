from collections.abc import Generator

import pytest

from src.deps import get_scraper_registry
from src.main import app
from tests.fixtures.stubs import StubScraperRegistry


@pytest.fixture(scope="module")
def stub_scraper_registry() -> Generator[None, None, None]:
    app.dependency_overrides[get_scraper_registry] = lambda: StubScraperRegistry()
    yield
    app.dependency_overrides.pop(get_scraper_registry, None)
