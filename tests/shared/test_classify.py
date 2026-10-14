import pytest

from shared.classify import ClassificationError, Classifier


@pytest.fixture
def c():
    return Classifier()


def test_unknown_level_treated_as_client_confidential(c):
    assert c.normalize("不知道") == "客戶機密"
    assert c.normalize(None) == "客戶機密"
    assert not c.is_known("不知道")


def test_rank_order(c):
    assert c.rank("公開") < c.rank("內部一般") < c.rank("內部敏感") < c.rank("客戶機密")


def test_allowed_processing(c):
    assert c.allows("公開", "cloud_llm")
    assert not c.allows("內部一般", "cloud_llm")
    assert c.allows("內部一般", "company_cloud_llm")
    assert not c.allows("內部敏感", "company_cloud_llm")
    assert c.allows("內部敏感", "local_llm")
    assert not c.allows("客戶機密", "cloud_llm")
    with pytest.raises(ClassificationError):
        c.require("內部敏感", "cloud_llm")


def test_highest_level(c):
    assert c.highest(["公開", "內部敏感", "內部一般"]) == "內部敏感"
    assert c.highest(["公開", "亂寫"]) == "客戶機密"
    assert c.highest([]) == "客戶機密"


def test_casebase_allowed(c):
    assert c.casebase_allowed == ["公開", "內部一般"]
