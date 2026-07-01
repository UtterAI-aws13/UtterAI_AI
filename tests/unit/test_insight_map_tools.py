"""Unit tests for the insight map query resolver agent's tool functions."""

from app.agents.insight_map.tools import search_ontology_concepts, search_synonyms


class TestSearchOntologyConcepts:
    def test_finds_concept_by_korean_synonym(self):
        result = search_ontology_concepts("평균 발화 길이")
        assert "MLU" in result

    def test_finds_concept_by_key(self):
        result = search_ontology_concepts("MLU")
        assert "MLU" in result

    def test_returns_not_found_message_for_unrelated_query(self):
        result = search_ontology_concepts("완전히 무관한 검색어 xyz123")
        assert "찾지 못했습니다" in result


class TestSearchSynonyms:
    def test_returns_related_terms_for_known_concept(self):
        result = search_synonyms("MLU")
        assert "평균 발화 길이" in result

    def test_returns_not_found_message_for_unknown_concept(self):
        result = search_synonyms("존재하지_않는_개념")
        assert "찾을 수 없습니다" in result
