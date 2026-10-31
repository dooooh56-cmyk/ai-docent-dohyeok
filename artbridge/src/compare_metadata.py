"""Present confirmed metadata side by side without changing search ranking."""


def compare_metadata(query_record, candidate_record, fields):
    comparisons = []
    for field in fields:
        original_key = f"{field}_original"
        normalized_key = f"{field}_normalized"
        query_original = query_record.get(original_key) or query_record.get(field) or ""
        candidate_original = candidate_record.get(original_key) or candidate_record.get(field) or ""
        query_normalized = query_record.get(normalized_key) or ""
        candidate_normalized = candidate_record.get(normalized_key) or ""
        if not (query_original or query_normalized) or not (candidate_original or candidate_normalized):
            status = "미기재"
        elif query_normalized and candidate_normalized:
            status = "정규화 값 일치" if query_normalized == candidate_normalized else "정규화 값 상이"
        else:
            status = "원문 표기 일치" if query_original == candidate_original else "원문 표기 상이"
        comparisons.append({"field": field, "query_original": query_original, "candidate_original": candidate_original, "query_normalized": query_normalized, "candidate_normalized": candidate_normalized, "status": status})
    return comparisons
