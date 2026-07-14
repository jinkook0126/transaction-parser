import re
from typing import List, Dict, Any

def parse_table_to_json(table_data: List[List[str]]) -> List[Dict[str, Any]]:
    """
    정제된 테이블 데이터를 분석하여 규격화된 JSON으로 변환합니다.
    추가 필드: description(적요/내용), memo(메모/거래처/거래점)
    """
    if not table_data or len(table_data) < 2:
        return []

    header = table_data[0]
    data_rows = table_data[1:]

    # 1. 헤더에서 각 유효 필드가 위치한 인덱스를 동적으로 감지
    col_indices = {
        "date": [],
        "time": [],
        "withdraw_cols": [],  # 출금 관련 열 (출금, 찾으신금액, 지급액 등)
        "deposit_cols": [],   # 입금 관련 열 (입금, 맡기신금액, 수납액 등)
        "amount_cols": [],    # 통합 거래금액 열
        "desc_cols": [],      # description 매핑 (적요, 거래내용)
        "memo_cols": []       # memo 매핑 (내용, 메모, 거래점, 지점)
    }

    for idx, col in enumerate(header):
        col_clean = col.replace(" ", "")
        
        # 날짜/시간 감지
        if any(kw in col_clean for kw in ["일자", "날짜"]):
            col_indices["date"].append(idx)
        elif any(kw in col_clean for kw in ["시간", "일시"]):
            col_indices["time"].append(idx)
            if "일시" in col_clean:
                col_indices["date"].append(idx)
                
        # 금액 관련 열 감지
        if any(kw in col_clean for kw in ["출금", "찾으신", "지급"]):
            col_indices["withdraw_cols"].append(idx)
        elif any(kw in col_clean for kw in ["입금", "맡기신", "수납"]):
            col_indices["deposit_cols"].append(idx)
        elif any(kw in col_clean for kw in ["금액", "거래금액"]):
            col_indices["amount_cols"].append(idx)
            
        # [신규] description(적요, 거래내용) 열 감지
        if any(kw in col_clean for kw in ["적요", "거래내용"]):
            col_indices["desc_cols"].append(idx)
            
        # [신규] memo(내용, 메모, 거래점, 지점) 열 감지
        if any(kw in col_clean for kw in ["내용", "메모", "거래점", "지점", "취급점"]):
            col_indices["memo_cols"].append(idx)

    # 2. 행 데이터 순회 파싱
    parsed_records = []
    
    for row in data_rows:
        if len(row) < len(header):
            continue

        record = {
            "transactionDate": None,
            "transactionTime": None,
            "amount": 0,
            "transactionType": "출금",
            "description": "",
            "memo": ""
        }

        # --- A. 날짜 및 시간 가공 (기존 로직 동일) ---
        raw_date_str = " ".join([row[i] for i in col_indices["date"] if row[i]])
        raw_time_str = " ".join([row[i] for i in col_indices["time"] if row[i]])
        full_text = f"{raw_date_str} {raw_time_str}".strip()
        
        date_match = re.search(r'(\d{4}[-./]?\d{2}[-./]?\d{2})', full_text)
        if date_match:
            date_clean = re.sub(r'[-./]', '', date_match.group(1))
            if len(date_clean) == 8:
                record["transactionDate"] = f"{date_clean[:4]}-{date_clean[4:6]}-{date_clean[6:]}"
            else:
                record["transactionDate"] = date_match.group(1)
        
        time_match = re.search(r'(\d{2}:\d{2}(:\d{2})?)', full_text)
        if time_match:
            record["transactionTime"] = time_match.group(1)
        if not record["transactionTime"] and raw_time_str:
            record["transactionTime"] = raw_time_str

        # 금액 변환 헬퍼
        def clean_to_int(val_str):
            if not val_str: return 0
            cleaned = re.sub(r'[^0-9-]', '', val_str)
            return int(cleaned) if cleaned else 0

        # --- B. 거래금액 및 거래타입(입/출금) 판별 ---
        amt_withdraw = sum(clean_to_int(row[i]) for i in col_indices["withdraw_cols"])
        amt_deposit = sum(clean_to_int(row[i]) for i in col_indices["deposit_cols"])
        amt_single = sum(clean_to_int(row[i]) for i in col_indices["amount_cols"])

        # 1) 텍스트 분석용 병합 문자열 미리 생성 (description과 memo 필드를 합쳐서 분석)
        all_text_cols = list(set(col_indices["desc_cols"] + col_indices["memo_cols"]))
        combined_text = "".join([row[i] for i in all_text_cols if row[i]]).replace(" ", "")

        # 입/출금 키워드 셋
        withdraw_keywords = ["출금", "지급", "대체출", "송금", "이체", "지출", "자동이체", "인출", "모바일뱅킹", "인터넷이체"]
        deposit_keywords = ["입금", "수납", "대체입", "환급", "입동", "급여", "자금이체입", "이자"]

        # 2) 타입 판별 실행
        if amt_withdraw > 0 and amt_deposit == 0:
            record["amount"] = amt_withdraw
            record["transactionType"] = "출금"
        elif amt_deposit > 0 and amt_withdraw == 0:
            record["amount"] = amt_deposit
            record["transactionType"] = "입금"
        else:
            record["amount"] = max(amt_withdraw, amt_deposit, amt_single)
            
            # 애매한 금액 열 구조일 때 텍스트 우선 판별
            if any(kw in combined_text for kw in deposit_keywords):
                record["transactionType"] = "입금"
            elif any(kw in combined_text for kw in withdraw_keywords):
                record["transactionType"] = "출금"
            else:
                # 음수 기호 대응
                if amt_single < 0 or "-" in str(row[col_indices["amount_cols"][0] if col_indices["amount_cols"] else 0]):
                    record["transactionType"] = "출금"
                    record["amount"] = abs(record["amount"])
                else:
                    record["transactionType"] = "출금" # 디폴트

        # --- C. description 및 memo 값 추출 ---
        # 1) description 추출 (적요/거래내용)
        desc_text = " ".join([row[i] for i in col_indices["desc_cols"] if row[i]]).strip()
        record["description"] = desc_text

        # 2) memo 추출 (내용, 메모, 거래점, 지점) - 개행(\n)으로 구분하여 결합
        memo_parts = []
        for idx in col_indices["memo_cols"]:
            cell_value = row[idx].strip()
            if cell_value and cell_value not in memo_parts:
                memo_parts.append(cell_value)
        
        # 각 열에서 온 데이터를 공백 대신 개행 문자('\n')로 결합
        raw_memo = "\n".join(memo_parts).strip()

        # 3) [핵심] description에 포함된 단어가 memo에 있다면 지워주기
        if desc_text and raw_memo:
            # description 단어들을 공백 기준으로 쪼개어 memo에서 제거
            desc_words = desc_text.split()
            cleaned_memo = raw_memo
            
            for word in desc_words:
                if len(word) >= 2: # 최소 2글자 이상인 유효 단어만 매칭해서 제거 (방어코드)
                    # 대소문자나 앞뒤 공백을 고려해 정규식으로 단어 제거
                    cleaned_memo = re.sub(rf'\b{re.escape(word)}\b', '', cleaned_memo)
                    # 혹시 공백 없이 붙어있는 경우를 대비한 일반 replace
                    cleaned_memo = cleaned_memo.replace(word, '')

            # 단어가 빠지면서 생긴 지저분한 줄바꿈이나 공백 정제
            memo_lines = [line.strip() for line in cleaned_memo.split('\n') if line.strip()]
            record["memo"] = "/".join(memo_lines)
        else:
            record["memo"] = raw_memo

        parsed_records.append(record)

    return parsed_records
