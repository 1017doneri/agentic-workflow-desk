from app.safety.output_guard import desensitize


def test_phone_desensitized():
    """手机号应被脱敏"""
    result = desensitize("我的手机号是13812345678")
    assert "138****5678" in result
    assert "13812345678" not in result


def test_id_card_desensitized():
    """身份证号应被脱敏"""
    result = desensitize("身份证110101199001011234")
    assert "110101********1234" in result
    assert "110101199001011234" not in result


def test_multiple_pii():
    """同时包含手机号和身份证号"""
    text = "手机13812345678，身份证110101199001011234"
    result = desensitize(text)
    assert "138****5678" in result
    assert "110101********1234" in result


def test_no_pii():
    """没有敏感信息时，文本不变"""
    text = "退款已处理，预计24小时内到账。"
    assert desensitize(text) == text


def test_empty_string():
    """空字符串不崩"""
    assert desensitize("") == ""