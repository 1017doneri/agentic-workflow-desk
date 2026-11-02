import re


def desensitize(text: str) -> str:
    if not text:
        return text

    # 手机号：13812345678 → 138****5678
    # 前后不能是数字（但可以是中文）
    text = re.sub(r'(?<!\d)(1[3-9]\d)\d{4}(\d{4})(?!\d)', r'\1****\2', text)

    # 身份证号：110101199001011234 → 110101********1234
    text = re.sub(r'(?<!\d)(\d{6})\d{8}(\d{4})(?!\d)', r'\1********\2', text)

    return text