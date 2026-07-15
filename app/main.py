# main.py
from fastapi import FastAPI, UploadFile, File, HTTPException, Form
from fastapi.middleware.cors import CORSMiddleware  # ⭐️ CORS 미들웨어 임포트
from app.parser import extract_raw_tables_from_pdf
from app.transformer import parse_table_to_json
from pdfminer.pdfdocument import PDFPasswordIncorrect
from pdfplumber.utils.exceptions import PdfminerException

app = FastAPI(
    title="은행 거래내역서 PDF 파서 API",
    description="업로드된 은행 거래내역 PDF에서 순수 거래 데이터만 추출하여 정제된 JSON으로 반환합니다.",
    version="1.2.2"
)

# ⭐️ 허용할 오리진(Origin) 목록 설정
origins = [
    "http://localhost:5173",    # 로컬 개발용 프론트엔드 (Vite, React 등)
    "http://127.0.0.1:5173",
    "https://profit-track-two.vercel.app/"
    # 추후 실제 배포될 프론트엔드 도메인이 생기면 여기에 추가합니다.
    # 예: "https://your-frontend-app.vercel.app"
]

# ⭐️ CORS 미들웨어 등록
app.add_middleware(
    CORSMiddleware,
    allow_origins=origins,            # 특정 도메인만 허용 (보안상 "*" 대신 직접 명시하는 것을 권장합니다)
    allow_credentials=True,
    allow_methods=["*"],              # GET, POST, OPTIONS 등 모든 HTTP 메서드 허용
    allow_headers=["*"],              # 모든 HTTP 헤더 허용
)

@app.post("/parse-bank-pdf", summary="은행 거래내역서 PDF 파싱 및 정제")
async def parse_bank_pdf(file: UploadFile = File(...),
                         password: str = Form(None)
                         ):
    """
    은행 거래내역서 PDF 파일을 업로드하면 데이터를 추출하고
    구조화된 정제 JSON으로 변환하여 반환합니다.
    """
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="PDF 파일만 업로드할 수 있습니다.")

    try:
        # 1. 파일 이진 데이터를 메모리 상에서 읽어들임
        pdf_bytes = await file.read()

        pdf_password = password if password else None
        
        # 2. PDF 파서 모듈 호출 (순수 거래 데이터 리스트만 가져옴)
        raw_tables = extract_raw_tables_from_pdf(pdf_bytes, password=pdf_password)
        
        # 3. 데이터 변환 모듈 호출 (최종 규격 JSON 리스트로 맵핑)
        final_results = []
        for table in raw_tables:
            json_records = parse_table_to_json(table)
            final_results.extend(json_records)

        return {
            "filename": file.filename,
            "total_records": len(final_results),
            "transactions": final_results
        }

    # ⭐️ 3. 비밀번호 틀림 / 누락 관련 구체적인 예외를 먼저 낚아챕니다.
    except (PDFPasswordIncorrect, PdfminerException) as auth_error:
        # pdfplumber가 던지는 PdfminerException 내부의 진짜 에러가 password 관련인지 한 번 더 체크합니다.
        err_str = repr(auth_error).lower()
        
        # 'pdfpasswordincorrect' 혹은 'password' 관련 단어가 감지되면 401을 반환합니다.
        if "password" in err_str or "authenticate" in err_str:
            raise HTTPException(
                status_code=401, 
                detail=f"PDF 비밀번호가 올바르지 않습니다."
            )
        
        # 비밀번호 에러가 아닌 다른 pdfminer 관련 에러인 경우 500 반환
        raise HTTPException(
            status_code=500, 
            detail=f"PDF 문서 구조를 읽는 중 오류 발생: {str(auth_error)}"
        )

    # 4. 그 외의 예측하지 못한 런타임 예외 처리
    except Exception as e:
        raise HTTPException(
            status_code=500, 
            detail=f"파싱 진행 중 일반 오류 발생: {str(e)}"
        )


if __name__ == "__main__":
    import uvicorn
    import os
    
    # 구글 클라우드가 제공하는 PORT 환경변수가 있으면 쓰고, 없으면 로컬용 8000을 씁니다.
    port = int(os.environ.get("PORT", 8000))
    
    uvicorn.run("main:app", host="0.0.0.0", port=port, reload=True)