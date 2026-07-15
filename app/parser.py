# parser.py
import pdfplumber
import io
import re
from typing import List

def is_actual_transaction_table(table_rows: List[List[str]]) -> bool:
    """
    테이블의 형태와 헤더를 분석해 거래 데이터가 맞는지 필터링합니다.
    """
    if not table_rows or len(table_rows) < 2:
        return False
    header_keywords = ["일자", "일시", "시간", "구분", "출금", "입금", "잔액", "적요", "내용", "기록", "거래점", "수수료"]
    header_text = "".join(table_rows[0]).replace(" ", "")
    header_score = sum(1 for kw in header_keywords if kw in header_text)
    
    data_score = 0
    sample_rows = table_rows[1:6]
    for row in sample_rows:
        if not row:
            continue
        first_cell = row[0].strip().replace(" ", "")
        is_date = bool(re.search(r'^\d{2,4}[-./]?\d{2}[-./]?\d{2}', first_cell))
        is_no = bool(re.match(r'^\d+$', first_cell))
        is_summary_word = any(kw in first_cell for kw in ["계좌", "조회", "성명", "고객", "잔액", "금액", "한도", "통화"])
        
        if (is_date or is_no) and not is_summary_word:
            data_score += 1

    if header_score >= 3 or (len(sample_rows) > 0 and (data_score / len(sample_rows)) >= 0.5):
        return True
    return False


def extract_raw_tables_from_pdf(pdf_bytes: bytes, password: str = None) -> List[List[List[str]]]:
    """
    메모리 내부의 PDF 바이너리를 읽어, 누락 행 방어 로직을 가동하여 
    거래내역 후보 2차원 리스트들을 돌려줍니다.
    """
    all_transaction_tables = []
    pdf_file_like = io.BytesIO(pdf_bytes)

    try:
        with pdfplumber.open(pdf_file_like) as pdf:
            for page in pdf.pages:
                table_settings = {
                    "vertical_strategy": "lines",
                    "horizontal_strategy": "lines",
                    "snap_tolerance": 4,          
                    "join_tolerance": 4,          
                    "intersection_tolerance": 4,
                }
                
                tables = page.find_tables(table_settings=table_settings)
                if not tables:
                    continue

                for table in tables:
                    raw_table_data = table.extract()
                    cleaned_table = []
                    for row in raw_table_data:
                        clean_row = [cell.replace('\n', ' ').strip() if cell else "" for cell in row]
                        if any(clean_row):
                            cleaned_table.append(clean_row)

                    if not cleaned_table:
                        continue

                    num_columns = len(cleaned_table[0])

                    # 열 경계선 및 바운딩 박스
                    x_coords = sorted(list(set([cell[0] if isinstance(cell, (list, tuple)) else cell[0] for cell in table.cells])))
                    x_coords.append(table.bbox[2])
                    table_left, table_right, table_bottom = table.bbox[0], table.bbox[2], table.bbox[3]
                    
                    # 유실 데이터 구출
                    lost_words = [
                        w for w in page.extract_words()
                        if table_bottom <= w['top'] <= (table_bottom + 32)
                        and table_left <= (w['x0'] + w['x1'])/2 <= table_right
                    ]

                    if lost_words:
                        col_words = {i: [] for i in range(num_columns)}
                        for word in lost_words:
                            word_center = (word['x0'] + word['x1']) / 2
                            for c_idx in range(num_columns):
                                if c_idx < len(x_coords) - 1:
                                    if x_coords[c_idx] <= word_center <= x_coords[c_idx + 1]:
                                        col_words[c_idx].append(word)
                                        break
                        
                        lost_row = [""] * num_columns
                        for c_idx, words in col_words.items():
                            if not words:
                                continue
                            words.sort(key=lambda w: (round(w['top'], 1), w['x0']))
                            cell_text = ""
                            prev_top = None
                            for w in words:
                                if prev_top is not None and abs(w['top'] - prev_top) > 5:
                                    cell_text += " " + w['text']
                                else:
                                    cell_text += (" " if cell_text else "") + w['text']
                                prev_top = w['top']
                            lost_row[c_idx] = cell_text.strip()
                        
                        # 구출 데이터 유효성 검증 (노이즈, 날짜, 순번 검사)
                        combined_row_text = "".join(lost_row).replace(" ", "")
                        noise_keywords = [
                            "file:/", "본명세는", "참고용", "증명서", "ⓒ", "copyright", 
                            "allrightsreserved", "shinhankbank", "nhbank", "고객행복센터",
                            "정보통신망", "이용촉진", "정보보호", "법률에", "발신기준", "대상으로"
                        ]
                        is_noise_text = any(kw in combined_row_text.lower() for kw in noise_keywords)
                        
                        first_cell = lost_row[0].strip().replace(" ", "")
                        has_valid_date = bool(re.search(r'^\d{2,4}[-./]?\d{2}[-./]?\d{2}', first_cell))
                        has_valid_no = bool(re.match(r'^\d+$', first_cell))
                        is_header_text = any(kw in first_cell for kw in ["일자", "일시", "시간", "구분", "순번", "No", "계좌", "조회"])

                        if any(lost_row) and not is_noise_text and (has_valid_date or has_valid_no) and not is_header_text:
                            cleaned_table.append(lost_row)

                    # 유령 열(Empty Column) 트리밍
                    if cleaned_table:
                        first_col_empty = all(row[0] == "" for row in cleaned_table)
                        last_col_empty = all(row[-1] == "" for row in cleaned_table)
                        start_idx = 1 if first_col_empty else 0
                        end_idx = -1 if last_col_empty else None
                        
                        if start_idx == 1 or end_idx == -1:
                            trimmed_table = []
                            for row in cleaned_table:
                                if end_idx == -1:
                                    trimmed_table.append(row[start_idx:-1])
                                else:
                                    trimmed_table.append(row[start_idx:])
                            cleaned_table = trimmed_table

                    # 진짜 거래내역 테이블인 경우만 반환 리스트에 누적
                    if is_actual_transaction_table(cleaned_table):
                        all_transaction_tables.append(cleaned_table)
    except Exception as e:
        # pdfplumber에서 패스워드가 올바르지 않거나 없을 때 발생하는 예외를 캐치하여 상위로 전달
        raise e

    return all_transaction_tables